"""Process-wide state for the demo (single user, no auth)."""
from .contracts import Plan, Task


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.plan: Plan | None = None
        self.tasks: dict[str, Task] = {}
        self.brief: dict = {}
        self.run_count = 0
        self.running = False
        self.last_summary: dict = {}
        self.pending_user_tasks: list[dict] = []


state = State()
