"""Google Calendar: no Airbyte connector exists -> google-api-python-client behind the same interface.
Mock reads seed events. Real impl wired in Phase 1."""
from .airbyte_client import MockSource, faults


class MockCalendar(MockSource):
    writable_ops = {"events.accept", "events.insert", "reminders.create", "events.delete"}

    def __init__(self):
        super().__init__("calendar")
        self.events_created: list[dict] = []

    def execute(self, op, params):
        faults.check("calendar")
        if op not in self.writable_ops:
            raise PermissionError(f"calendar: unsupported op {op}")
        key = (op, params.get("title") or params.get("event_id"), params.get("start"))
        if op in ("events.insert", "reminders.create") and key in {(e["op"], e.get("title") or e.get("event_id"), e.get("start")) for e in self.effects}:
            raise ValueError("duplicate event (provider-side dedupe)")  # real calendars allow dupes; harness checks
        return super().execute(op, params)


_cal: MockCalendar | None = None


def get_calendar() -> MockCalendar:
    global _cal
    if _cal is None:
        _cal = MockCalendar()
    return _cal


def reset_calendar():
    global _cal
    _cal = None
