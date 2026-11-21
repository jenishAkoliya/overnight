"""In-app reminders for everything that needs the user: approvals (ASK), identity checks (VERIFY), focus work,
follow-ups and failed actions. Nothing is sent anywhere; reminders live in the app (bell, Overview, live pop-ups).
Snooze/done only hide a reminder; they never approve or execute anything."""
from datetime import datetime, timedelta, time as dtime
from .. import config
from ..bus import bus, redact
from ..state import state

_hidden: dict[str, float] = {}     # reminder id -> hidden until (epoch); inf = done
_notified: set[str] = set()

KIND = {"VERIFY": ("verify", "Verify identity, then approve or reject"), "ASK": ("approve", "Approve or reject")}


def _now() -> datetime:
    return datetime.now(config.TZ) if config.REAL_CLOCK else config.tonight() + timedelta(hours=10)   # demo: the morning after


def build() -> list[dict]:
    plan = state.plan
    if not plan:
        return []
    now = _now()
    blocks = {b.task_id: b for b in plan.blocks if b.task_id}
    morning = datetime.combine(plan.date, dtime(9, 0), config.TZ)
    out = []
    for t in plan.tasks:
        kind = None
        if t.status.value == "failed":
            kind, what = "failed", "Failed overnight - retry or handle it yourself"
        elif t.status.value == "needs_you" and t.action_type == "work":
            kind, what = "work", "Focus task on your plan"
        elif t.status.value == "needs_you":
            kind, what = KIND.get(t.decision.value if t.decision else "ASK", KIND["ASK"])
        elif t.action_type == "reminder" and t.status.value == "done":
            kind, what = "follow-up", "Follow-up reminder"
        if not kind:
            continue
        b = blocks.get(t.id)
        due = b.start if b else (datetime.combine(t.due, dtime(9, 0), config.TZ) if t.due else morning)
        rid = f"r-{t.id}"
        hid = _hidden.get(rid, 0)
        if hid == float("inf") or hid > now.timestamp():
            continue
        mins = (due - now).total_seconds() / 60
        urgency = "overdue" if mins < 0 else "soon" if mins <= 60 else "today" if due.date() == now.date() else "upcoming"
        out.append({"id": rid, "task_id": t.id, "title": redact(t.title, 120), "kind": kind, "what": what, "due": due.isoformat(),
                    "urgency": urgency, "priority": t.priority, "decision": t.decision.value if t.decision else None,
                    "suggestion": t.suggestion, "why": redact(t.why, 140)})
    rank = {"overdue": 0, "soon": 1, "today": 2, "upcoming": 3}
    kr = {"failed": 0, "verify": 1, "approve": 2, "work": 3, "follow-up": 4}
    out.sort(key=lambda r: (rank[r["urgency"]], kr[r["kind"]], -r["priority"], r["due"]))
    return out


def snooze(rid: str, minutes: int = 60):
    _hidden[rid] = _now().timestamp() + minutes * 60


def done(rid: str):
    _hidden[rid] = float("inf")


def reset():
    _hidden.clear(); _notified.clear()


def tick():
    """Called by the scheduler: pop an in-app reminder for anything overdue or due within the hour (once each)."""
    for r in build():
        if r["urgency"] in ("overdue", "soon") and r["id"] not in _notified:
            _notified.add(r["id"])
            bus.emit("Reminder", "reminder_due", f"{r['what']}: {r['title']}", why=f"due {r['due'][11:16]} ({r['urgency']})")


def morning_digest():
    rs = build()
    bus.emit("Reminder", "morning_digest", f"{len(rs)} thing(s) need you today", why="in-app only; nothing was sent")
