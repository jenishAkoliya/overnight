"""Notifier: morning brief + 'needs you' queue. In-app; email is only ever a draft."""
from ..bus import bus
from ..contracts import Plan, TaskStatus, Decision


class Notifier:
    def brief(self, plan: Plan, metrics: dict) -> dict:
        done = [t for t in plan.tasks if t.status == TaskStatus.done]
        needs = [t for t in plan.tasks if t.status == TaskStatus.needs_you and t.action_type != "work"]
        blocked = [t for t in plan.tasks if t.status == TaskStatus.blocked]
        b = {"date": plan.date.isoformat(), "greeting": f"Good morning Maya - I handled {len(done)} things overnight; {len(needs)} need you.",
             "done": [t.id for t in done], "needs_you": [t.id for t in needs], "blocked": [t.id for t in blocked],
             "email_draft": {"to": "maya.chen@gmail.com", "subject": f"Your plan for {plan.date:%A}", "sent": False,
                             "body": f"Done for you: {len(done)}. Needs you: {len(needs)}. Blocked for safety: {len(blocked)}."}}
        bus.emit("Notifier", "morning_brief", b["greeting"], why="email saved as a draft only, never sent")
        return b


notifier = Notifier()
