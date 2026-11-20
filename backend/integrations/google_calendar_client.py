"""Google Calendar: no Airbyte connector exists -> google-api-python-client behind the same interface.
Mock reads seed events. Real impl wired in Phase 1."""
from .airbyte_client import MockSource


class MockCalendar(MockSource):
    writable_ops = {"events.accept", "events.insert", "reminders.create", "events.delete"}

    def __init__(self):
        super().__init__("calendar")


_cal: MockCalendar | None = None


def get_calendar() -> MockCalendar:
    global _cal
    if _cal is None:
        _cal = MockCalendar()
    return _cal


def reset_calendar():
    global _cal
    _cal = None
