"""Google Calendar: no Airbyte connector exists -> google-api-python-client behind the same interface.
Mock reads seed events. Real impl wired in Phase 1."""
from .airbyte_client import MockSource


class MockCalendar(MockSource):
    writable_ops = {"events.accept", "events.insert", "reminders.create", "events.delete"}

    def __init__(self):
        super().__init__("calendar")


_cal: MockCalendar | None = None


def get_calendar():
    global _cal
    if _cal is None:
        from ..config import use_mock_sources
        if use_mock_sources("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
            _cal = MockCalendar()
        else:
            from .real_sources import RealCalendar
            _cal = RealCalendar()
    return _cal


def reset_calendar():
    global _cal
    _cal = None
