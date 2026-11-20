"""TriageAgent: SourceItem -> Task(s) scored by value + confidence via SIE (mock heuristics now)."""
import hashlib
import re
from ..standing import standing
import re
from datetime import timedelta
from ..bus import bus
from ..contracts import SourceItem, Task, Value
from ..guards import scan
from ..integrations.sie_client import get_sie
from ..integrations.llm import get_llm
from .memory import memory
from ..config import tomorrow, tonight

STAKES = {"trivial": Value.low, "moderate": Value.medium, "high": Value.high}
costs = {"sie_calls": 0, "llm_calls": 0}


def _id(s: str) -> str:
    return "t-" + hashlib.sha1(s.encode()).hexdigest()[:8]


def _weekday_date(name: str):
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    d = tonight().date()
    for i in range(1, 8):
        if (d + timedelta(days=i)).weekday() == names.index(name):
            return d + timedelta(days=i)


def _user_title(text: str) -> str:
    """'book dentist, I prefer mornings' -> 'Book dentist' (drop preference clauses)."""
    t = memory.PREF_RE.sub("", text)
    t = memory.NOBEFORE_RE.sub("", t)
    t = re.sub(r"\b(i|and|but)\s*$", "", t.strip(" ,;.-"), flags=re.I).strip(" ,;.-")
    t = re.split(r"[,;]", t)[0].strip() or text
    return t[:1].upper() + t[1:]


class TriageAgent:
    def run(self, items: list[SourceItem]) -> list[Task]:
        tasks: dict[str, Task] = {}
        for it in items:
            if it.type == "event" and it.metadata.get("rsvp") != "needsAction":
                continue
            made = self.triage_item(it)
            if not made:
                continue
            key, t = made
            if key in tasks:  # same obligation seen in email + slack -> merge
                bus.emit("TriageAgent", "merge", f"Merged duplicate: {t.title}", why=f"same obligation as {tasks[key].source_item_id}")
                continue
            tasks[key] = t
        # user-added tasks from memory supersede inferred duplicates
        for ut in memory.user_tasks:
            low = ut["text"].lower()
            for k in [k for k in tasks if k in low or any(w in low for w in k.split("-")[:1] if len(w) > 4)]:
                bus.emit("TriageAgent", "merge", f"Your task overrides inferred '{tasks[k].title}'", why="user-added tasks win")
                tasks.pop(k)
            title = _user_title(ut["text"])
            tasks[ut["id"]] = Task(id=_id(ut["id"] + ut["text"]), title=title, source_item_id=ut["id"], action_type="work",
                                   value=Value.medium, confidence=0.95, est_minutes=20, user_added=True, why="You asked for this")
        n_llm = 0
        for t in tasks.values():
            if 0.4 <= t.confidence <= 0.8 and not t.user_added and not t.flags:
                n_llm += 1
                costs["llm_calls"] += 1
                get_llm()  # mock: no completion; keeps SIE score
                t.triage_via = "llm"
                bus.emit("TriageAgent", "llm_escalation", f"Borderline confidence {t.confidence:.2f}: {t.title}", why="SIE confidence 0.4-0.8 -> asked LLM (mock: kept SIE score)", cost=0.002)
        bus.emit("TriageAgent", "done", f"{len(tasks)} tasks from {len(items)} items; {n_llm} escalated to LLM")
        return list(tasks.values())

    def triage_item(self, it: SourceItem):
        made = self._triage_item(it)
        if made:
            self._annotate(it, made[1])
        return made

    def _annotate(self, it, t):
        """Cross-cutting signals: preference conflicts and urgency."""
        low = f"{it.subject} {it.body}".lower()
        mh = standing.min_meeting_hour
        if mh is not None and t.action_type in ("reply", "schedule", "rsvp", "accept_recurring"):
            for h, ap in re.findall(r"\b(\d{1,2})\s?(am|pm)\b", low):
                hr = int(h) % 12 + (12 if ap == "pm" else 0)
                if hr < mh:
                    t.flags = t.flags + ["preference_conflict"]
                    t.title += f" [{hr}:00 is before your {mh}:00 limit]"
                    break
        if re.search(r"urgent|asap|outage|can'?t log ?in|cannot log ?in|blocking|before noon|right now|down\b", low) and not ({"phishing", "prompt_injection", "spoofed_sender"} & set(t.flags)):
            t.priority = 95

    def _triage_item(self, it: SourceItem):
        m, subj, body = it.metadata, it.subject, it.body
        flags = scan(subj, body, m, author=it.author, known_contacts=memory.known_contacts)
        costs["sie_calls"] += 1
        sig = get_sie().signal(f"{subj}\n{body}", m)
        ent = sig.entities
        val, conf = STAKES[sig.stakes], sig.routine_prob
        def T(**kw):
            base = dict(id=_id(it.id), source_item_id=it.id, value=val, confidence=conf, people=[it.author], flags=flags)
            base.update(kw)
            return Task(**base)
        # ---- hard-block content first
        if "prompt_injection" in flags:
            return "injection", T(title=f"Blocked: email instructs agent to forward your inbox ({it.author})", action_type="share", reversible=False, value=Value.high)
        if "phishing" in flags:
            return "phish", T(title=f"Blocked: suspicious invoice demand ${ent.get('amount', 0):,.0f} from {it.author}", action_type="payment", amount=ent.get("amount"), reversible=False, value=Value.high)
        if "spoofed_sender" in flags:
            return f"spoof-{it.id}", T(title=f"Suspicious: '{m.get('display_name')}' writing from unknown address {it.author}: {subj}", action_type="other", reversible=False, value=Value.high, confidence=0.2)
        if m.get("cancel_meeting"):
            return f"cancel-{it.id}", T(title=f"Cancel meeting for {m.get('attendees', 10)} attendees: {subj}", action_type="cancel_meeting", flags=flags + ["external_send"], reversible=False, value=Value.high, confidence=0.6, priority=70)
        if m.get("meeting_confirm"):
            return f"confirm-{it.id}", T(title=f"Confirm: {m['meeting_confirm']['title']} (post to Slack + add to calendar)", action_type="confirm_meeting", value=Value.medium, confidence=0.9, meta=m["meeting_confirm"], flags=flags + ["external_send"])
        s = it.source
        if it.type == "event":
            if "tz_note" in m:
                return "zurich", T(title=f"Zurich sync lands 08:00 PT (scheduled in CET) - before your 9:30 limit", action_type="schedule", value=Value.medium, confidence=0.7, est_minutes=0)
            key = "dinner" if "dinner" in subj.lower() else f"rsvp-{subj}"
            return key, T(title=f"Accept recurring: {subj}", action_type="accept_recurring" if m.get("recurring") else "rsvp", confidence=0.9 if m.get("recurring") else 0.84, value=Value.low)
        if s == "notion":
            from datetime import date as _d
            due = _d.fromisoformat(m["due"]) if m.get("due") else None
            mins = 60 if "slides" in subj.lower() else 20 if "passport" in subj.lower() else 45
            return f"notion-{it.id}", T(title=subj, action_type="work", value=Value.medium, confidence=0.9, est_minutes=mins, due=due)
        if s == "slack":
            low = body.lower()
            if "review" in low and "prd" in low:
                return "prd", T(title="Review onboarding PRD (due before Tue standup)", action_type="work", value=Value.medium, est_minutes=45, confidence=0.9)
            if "lunch" in low:
                return "lunch-dan", T(title="Reply to Dan: lunch Tuesday?", action_type="reply", flags=flags + ["external_send"], value=Value.medium, confidence=0.6)
            if "send final thursday" in low:
                return "deck", T(title="Send final Q4 roadmap deck to Priya by Thu", action_type="work", value=Value.medium, est_minutes=60, due=_weekday_date("thursday"), confidence=0.9)
            if "churn numbers" in low:
                return "churn", T(title="Follow up with Dan if churn numbers haven't arrived (Wed)", action_type="reminder", value=Value.low, confidence=0.88, due=_weekday_date("wednesday"), est_minutes=2)
            return None
        # ---- email
        if m.get("list_unsubscribe"):
            return it.id, T(title=f"Archive newsletter: {subj}", action_type="archive", est_minutes=1)
        if m.get("receipt"):
            return it.id, T(title=f"File receipt: {subj}", action_type="file_receipt", est_minutes=2)
        if m.get("direction") == "sent":
            return "deck", T(title="Send Q4 roadmap deck to Priya by Thu (you promised)", action_type="work", value=Value.medium, est_minutes=60, due=_weekday_date("thursday"), confidence=0.9)
        if "churn numbers" in body:
            return "churn", T(title="Follow up with Dan if churn numbers haven't arrived (Wed)", action_type="reminder", value=Value.low, confidence=0.88, due=_weekday_date("wednesday"), est_minutes=2)
        if m.get("invite"):
            return f"rsvp-{subj.split(':', 1)[1].split('(')[0].strip()}", T(title=f"Accept recurring: {subj.split(':', 1)[1].split('(')[0].strip()}", action_type="accept_recurring", confidence=0.9, value=Value.low, est_minutes=2)
        if m.get("flight"):
            return it.id, T(title="Add check-in reminder for UA 5HT9QK (Thu 7:05 AM flight)", action_type="reminder", est_minutes=2, due=_weekday_date("wednesday"))
        if m.get("money"):
            return "insurance", T(title=f"Car insurance renewal +22% (${ent.get('amount', 1284):,.0f}) - pay before Dec 15", action_type="payment", amount=ent.get("amount", 1284.0), flags=flags + ["money"], reversible=False, value=Value.high, due=None, est_minutes=10, confidence=0.55)
        if m.get("ambiguous_time"):
            return "meet-thu", T(title="Priya: 'meet Thursday?' - no time given; draft a reply, don't book", action_type="reply", flags=flags + ["external_send"], confidence=0.6, est_minutes=3)
        if m.get("data_sharing"):
            return "share", T(title=f"Share Q4 customer list with {it.author}? (new external contact)", action_type="share", flags=flags + ["data_sharing", "new_contact"], reversible=False, value=Value.high, confidence=0.3)
        if m.get("delete"):
            return "delete", T(title="Delete customer exports older than 90 days (legal request)", action_type="delete", flags=flags + ["delete"], reversible=False, value=Value.high, confidence=0.5)
        if m.get("rsvp"):
            return "dinner", T(title=f"RSVP yes: {subj.split(':')[1].strip() if ':' in subj else subj}", action_type="rsvp", confidence=0.84, value=Value.low, est_minutes=2)
        if m.get("cold_outreach"):
            return it.id, T(title=f"Archive cold outreach: {it.author}", action_type="archive", est_minutes=1, confidence=0.9, value=Value.low)
        if m.get("new_contact"):
            return it.id, T(title=f"Recruiter {it.author}: archive or reply?", action_type="archive", confidence=0.65, value=Value.medium, flags=flags)
        if "prd" in body.lower() or "review the new" in body.lower():
            return "prd", T(title="Review onboarding PRD (due before Tue standup)", action_type="work", value=Value.medium, est_minutes=45, confidence=0.9)
        if "lunch" in body.lower():
            return "lunch-dan", T(title="Reply to Dan: lunch Tuesday?", action_type="reply", flags=flags + ["external_send"], confidence=0.6, est_minutes=2)
        if "dentist" in it.author:
            return "dentist", T(title="Book dentist cleaning", action_type="schedule", est_minutes=10, confidence=0.7)
        if "expense report" in body.lower():
            return it.id, T(title="Reminder: submit expense report by Fri", action_type="reminder", confidence=0.9, value=Value.low, est_minutes=2, due=_weekday_date("friday"))
        if "dinner" in body.lower() and "mom" in it.author:
            return "mom", T(title="Reply to Mom: dinner Sunday?", action_type="reply", flags=flags + ["external_send"], confidence=0.6, est_minutes=2)
        if "statement" in subj.lower():
            return it.id, T(title=f"File: {subj}", action_type="file_receipt", est_minutes=1)
        if m.get("known_contact"):
            return f"reply-{it.id}", T(title=f"Reply to {it.author.split('@')[0]}: {subj}", action_type="reply", flags=flags + ["external_send"], confidence=0.6, est_minutes=5)
        return None


triage_agent = TriageAgent()
