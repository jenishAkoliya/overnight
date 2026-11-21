"""Executor: performs AUTO actions (and user-approved ones). Idempotent, retried, DRY_RUN-aware.
Retry/backoff behaviour comes from runtime_config.yaml (patchable)."""
import hashlib
import re
from datetime import datetime, timedelta
import os
import json
from .. import config, runtime
from ..bus import bus, redact
import time as _time
from ..contracts import Action, ActionResult, Decision, Task, TaskStatus
from ..integrations.airbyte_client import get_connector, is_real, RateLimited, AuthExpired
from ..policy import load_rules
from ..standing import standing

SENDING = {"gmail.send", "pay.invoice", "composite.confirm_meeting"}


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def invite_when(text: str):
    """Next occurrence of '<weekday> ... <time>' in an invitation text -> (datetime, recurring?) or None."""
    low = text.lower()
    day = next((i for i, d in enumerate(DAYS) if re.search(rf"\b{d[:3]}\w*", low)), None)
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low) or re.search(r"\b(\d{1,2}):(\d{2})\b", low)
    if day is None or not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    ap = m.group(3) if m.lastindex and m.lastindex >= 3 else None
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    now = config.tonight()
    d = now.date() + timedelta(days=((day - now.weekday()) % 7) or 7)
    return datetime(d.year, d.month, d.day, h, mi, tzinfo=config.TZ), bool(re.search(r"recurring|weekly|every|\w+days\b", low))


class Payments:
    """Payments are ALWAYS simulated (we never move real money in the demo)."""
    def __init__(self): self.paid: list[dict] = []


payments = Payments()


class Executor:
    def __init__(self):
        self.done: dict[str, ActionResult] = {}
        self.audit: list[dict] = []
        self.actions_run = 0
        self.partial_note = ""
        self.on_action = None   # hook(n_actions) used by the simulation harness for mid-run events

    def reset(self):
        self.done.clear(); self.audit.clear(); self.actions_run = 0; payments.paid.clear()

    # ---- task -> action ----
    def action_for(self, t: Task) -> Action | None:
        sid = t.source_item_id or ""
        mp = {
            "archive": ("gmail.archive", {"message_id": sid, "remove_label_ids": ["INBOX"]}),
            "label": ("gmail.label", {"message_id": sid, "add_label_ids": ["Label_Receipts"]}),
            "file_receipt": ("gmail.label", {"message_id": sid, "add_label_ids": ["Label_Receipts"], "remove_label_ids": ["INBOX"]}),
            "accept_recurring": ("calendar.accept", {"event_id": sid or t.title, "series": True}),
            "rsvp": ("calendar.accept", {"event_id": sid or t.title}),
            "reminder": ("calendar.reminder", {"title": t.title, "start": str(t.due or "")}),
            "draft_reply": ("gmail.draft", {"in_reply_to": sid, "body": t.meta.get("reply_body") or "(draft prepared, not sent)"}),
            "reply": ("gmail.send", {"in_reply_to": sid, "body": t.meta.get("reply_body", "")}),
            "payment": ("pay.invoice", {"amount": t.amount, "ref": sid}),
            "confirm_meeting": ("composite.confirm_meeting", {"title": t.title, "meeting": t.meta}),
            "cancel_meeting": ("calendar.cancel", {"event_id": sid}),
        }
        if t.action_type not in mp:
            return None
        kind, params = mp[t.action_type]
        if t.action_type in ("accept_recurring", "rsvp") and sid.startswith("gmail-"):
            # an invitation that only exists as an email: "accepting" = putting the event on the user's calendar
            when = invite_when(f"{(t.item or {}).get('subject', '')} {t.title}")
            kind, params = "calendar.insert", {"title": re.sub(r"^(\[[^\]]+\]\s*)?(Invitation:|RSVP:)\s*", "", (t.item or {}).get("subject", t.title)).split("(")[0].strip() or t.title,
                                               "start": when[0].isoformat() if when else "", "duration_min": 60,
                                               "recurrence": ["RRULE:FREQ=WEEKLY"] if when and when[1] else [], "from_email": sid}
        key = hashlib.sha1(json.dumps([t.id, kind, params], sort_keys=True, default=str).encode()).hexdigest()[:16]
        return Action(id=f"a-{key[:8]}", task_id=t.id, kind=kind, params=params, idempotency_key=key)

    def guard(self, t: Task, a: Action) -> str | None:
        """Return a refusal reason, or None if allowed."""
        if t.status == TaskStatus.blocked or set(load_rules()["hard_blocks"]["flags"]) & set(t.flags):
            return "hard-blocked content (policy hard block: never executed)"
        if standing.no_send and a.kind in ("gmail.send", "composite.confirm_meeting"):
            return "you told me to stop sending on your behalf"
        if a.kind in SENDING:
            if t.status != TaskStatus.approved:
                return "send/pay requires explicit user approval"
            if t.decision == Decision.VERIFY and not t.verified:
                return "send/pay requires identity verification (Persona) first"
        elif t.decision != Decision.AUTO and t.status != TaskStatus.approved:
            return "not an AUTO task and not approved"
        return None

    def execute(self, t: Task) -> ActionResult:
        a = self.action_for(t)
        if a is None:
            return ActionResult(action_id="-", ok=True, status="skipped", why="no executable action (work item for you)")
        refusal = self.guard(t, a)
        if refusal:
            r = ActionResult(action_id=a.id, ok=False, status="skipped", why=refusal)
            bus.emit("Executor", "refused", f"{a.kind}: {t.title}", decision=t.decision, why=refusal)
            self._audit(t, a, r)
            return r
        if a.idempotency_key in self.done:
            prev = self.done[a.idempotency_key]
            bus.emit("Executor", "duplicate", f"Skipped duplicate {a.kind}", why="idempotency key already executed")
            return prev.model_copy(update={"status": "duplicate", "why": "already done (idempotent)"})
        if t.decision == Decision.AUTO and self.actions_run >= load_rules()["guards"]["max_actions_per_night"]:
            return ActionResult(action_id=a.id, ok=False, status="skipped", why="max actions per night reached")
        live_approved = (os.getenv("APPROVED_ACTIONS_LIVE", "").lower() == "true" and t.status == TaskStatus.approved and a.kind != "pay.invoice")
        if config.DRY_RUN and not live_approved and a.kind != "pay.invoice" and is_real(a.kind.split(".")[0] if not a.kind.startswith("composite") else "calendar"):
            r = ActionResult(action_id=a.id, ok=True, status="dry_run", dry_run=True, why=f"DRY_RUN: would {a.kind} ({t.why})",
                             undo={"kind": a.kind})
        else:
            r = self._with_retry(a, t)
        if r.ok:
            self.done[a.idempotency_key] = r
            self.actions_run += 1
        bus.emit("Executor", a.kind, f"{r.status}: {t.title}", decision=t.decision, why=r.why)
        self._audit(t, a, r)
        if self.on_action:
            self.on_action(self.actions_run)
        return r

    def _audit(self, t: Task, a: Action, r: ActionResult):
        """Audit trail: what was proposed/done, simulated or not. Titles are truncated; bodies and tokens are never stored."""
        self.audit.append({"ts": round(_time.time(), 1), "action": a.kind, "task": redact(t.title, 70), "decision": t.decision.value if t.decision else None,
                           "status": r.status, "simulated": bool(r.dry_run or r.status == "dry_run"), "attempts": r.attempts, "why": redact(r.why, 120)})

    def _with_retry(self, a: Action, t: Task) -> ActionResult:
        rc = runtime.load("runtime_config.yaml")
        retry, rl = rc["retry"], rc.get("rate_limit", {})
        last = ""
        self.partial_note = ""
        for attempt in range(1, retry["max_attempts"] + 1):
            try:
                self._call(a)
                return ActionResult(action_id=a.id, ok=True, status="done", attempts=attempt, why=t.why, undo={"kind": a.kind, "params": a.params})
            except AuthExpired as e:   # permanent: retrying cannot help
                return ActionResult(action_id=a.id, ok=False, status="failed", attempts=attempt, why=f"FAILED (not done): {e}; reconnect the account" + (f". {self.partial_note}" if self.partial_note else ""))
            except (TimeoutError, ConnectionError, RateLimited) as e:
                last = str(e)
                delay = min(retry["backoff_s"] * retry.get("backoff_factor", 2) ** (attempt - 1), retry.get("max_backoff_s", 2.0))
                if isinstance(e, RateLimited) and rl.get("respect_retry_after", True):
                    delay = max(delay, e.retry_after)
                bus.emit("Executor", "retry", f"{a.kind} attempt {attempt} failed: {e}", why=f"backoff {delay:.1f}s")
                if attempt < retry["max_attempts"]:
                    runtime.clock.sleep(delay)
            except Exception as e:
                return ActionResult(action_id=a.id, ok=False, status="failed", attempts=attempt, why=f"error: {e}")
        return ActionResult(action_id=a.id, ok=False, status="failed", attempts=retry["max_attempts"], why=f"FAILED after retries (not done): {last}" + (f". {self.partial_note}; check Slack and retry the calendar step" if self.partial_note else ""))

    def _call(self, a: Action):
        sys, op = a.kind.split(".")
        k = a.idempotency_key
        if sys == "pay":
            payments.paid.append({"amount": a.params.get("amount"), "ref": a.params.get("ref"), "simulated": True})
            return
        if sys == "composite":   # confirm_meeting: post to Slack, then create the calendar event
            m = a.params.get("meeting") or {}
            self.partial_note = ""
            get_connector("slack").execute("messages.create", {"channel": m.get("channel", "#general"), "text": f"Confirmed: {a.params['title']}", "idempotency_key": k + "-slack"})
            self.partial_note = "PARTIAL: the Slack message WAS posted, but the calendar event was NOT created"
            get_connector("calendar").execute("events.insert", {"title": m.get("title", a.params["title"]), "start": m.get("start"), "idempotency_key": k + "-cal"})
            self.partial_note = ""
            return
        if a.kind == "calendar.insert" and not a.params.get("start"):
            raise ValueError("could not find a date/time in the invitation - add it to your calendar manually")
        opname = {"insert": "events.insert", "archive": "messages.update", "label": "labels.apply", "draft": "drafts.create", "send": "messages.send",
                  "accept": "events.accept", "reminder": "reminders.create", "cancel": "events.delete"}[op]
        get_connector(sys).execute(opname, {**a.params, "idempotency_key": k})

    def undo(self, t: Task) -> bool:
        if not t.result or not t.result.undo:
            return False
        bus.emit("Executor", "undo", f"Undid: {t.title}", why="user pressed undo")
        t.status = TaskStatus.undone
        return True


executor = Executor()
