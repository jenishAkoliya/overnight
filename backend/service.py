"""User-facing operations shared by the API and the simulation harness."""
import re
from datetime import timedelta
from . import runtime
from .bus import bus
from .contracts import Decision, TaskStatus
from .standing import standing
from .state import state
from .config import tonight
from .agents.memory import memory
from .agents.executor import executor

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class NotAllowed(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def approve_task(t):
    if t.status == TaskStatus.blocked:
        raise NotAllowed(403, "hard-blocked: cannot be approved")
    if t.decision == Decision.VERIFY and not t.verified:
        raise NotAllowed(409, "identity verification required: POST /verify/{id}/start")
    t.status = TaskStatus.approved
    t.result = executor.execute(t)
    t.status = TaskStatus.done if t.result.ok else TaskStatus.failed
    memory.record_feedback(t.id, True, "approved", t.action_type, t.people[0] if t.people else "")
    return t


def reject_task(t, reason: str = ""):
    t.status = TaskStatus.rejected
    memory.record_feedback(t.id, False, reason or "rejected", t.action_type, t.people[0] if t.people else "")
    return t


def handle_user_message(text: str) -> list[str]:
    """Interpret a free-text instruction using the patterns in guards_rules.yaml (user_intents).
    Instructions only come from the user channel, never from email/Slack content."""
    handled = []
    for intent in runtime.load("guards_rules.yaml").get("user_intents", []):
        m = re.search(intent["pattern"], text, re.I)
        if not m:
            continue
        h = intent["handler"]
        if h == "preference.add":
            memory.preferences.append(f"Maya {m.group(0).lower()}")
        elif h == "constraint.min_meeting_hour":
            standing.min_meeting_hour = int(m.group(1))
            memory.preferences.append(f"No meetings before {int(m.group(1))}:00")
        elif h == "standing.no_send":
            standing.no_send = True
        elif h == "plan.defer_work":
            day = next((d for d in WEEKDAYS if d in text.lower()), None)
            if day:
                base = tonight().date()
                standing.defer_to = next(base + timedelta(days=i) for i in range(1, 8) if (base + timedelta(days=i)).weekday() == WEEKDAYS.index(day))
        handled.append(h)
        bus.emit("MemoryAgent", "instruction", f"Understood: {h}", why=f"from you: \"{text}\"")
    if not handled:
        bus.emit("MemoryAgent", "instruction_unrecognized", f"Did not understand instruction: \"{text}\"", why="no matching pattern; stored as a note only")
        memory.cog.remember(text, dataset="user_memory", node_set=["notes"])
    return handled
