"""Notifier: morning brief + 'needs you' queue. In-app; email is only ever a draft.
The brief must match reality: failed and partially-completed actions are listed, never hidden."""
from .. import config
from ..bus import bus
from ..contracts import Plan, TaskStatus


class Notifier:
    def brief(self, plan: Plan, metrics: dict) -> dict:
        done = [t for t in plan.tasks if t.status == TaskStatus.done]
        needs = sorted((t for t in plan.tasks if t.status == TaskStatus.needs_you and t.action_type != "work"), key=lambda t: -t.priority)
        blocked = [t for t in plan.tasks if t.status == TaskStatus.blocked]
        failed = [t for t in plan.tasks if t.status == TaskStatus.failed]
        verb = "prepared" if config.DRY_RUN else "handled"
        from .advisor import profile as _p
        who = _p().get("name", "there") if config.REAL_CLOCK else "Maya"
        greeting = f"Good morning {who} - I {verb} {len(done)} things overnight{' (simulated, dry run)' if config.DRY_RUN else ''}; {len(needs)} need you."
        if failed:
            greeting += f" {len(failed)} action(s) FAILED and were not done."
        b = {"date": plan.date.isoformat(), "greeting": greeting,
             "done": [t.id for t in done], "needs_you": [t.id for t in needs], "blocked": [t.id for t in blocked],
             "failed": [t.id for t in failed],
             "failed_detail": [{"id": t.id, "title": t.title, "why": t.result.why if t.result else ""} for t in failed],
             "email_draft": {"to": "maya.chen@gmail.com", "subject": f"Your plan for {plan.date:%A}", "sent": False,
                             "body": f"Done for you: {len(done)}. Needs you: {len(needs)}. Failed: {len(failed)}. Blocked for safety: {len(blocked)}."}}
        bus.emit("Notifier", "morning_brief", greeting, why="email saved as a draft only, never sent")
        return b


notifier = Notifier()
