import os

os.environ["DISABLE_SCHEDULER"] = "1"
from fastapi.testclient import TestClient
from backend.app import app
from backend.bus import redact, bus
from backend.integrations.airbyte_client import effects


def test_redact_strips_tokens_and_caps_length():
    t = "auth " + "ya" + "29.A0FAKEtokenvalue and Bearer abc.def.ghi and " + "GOC" + "SPX-FAKEFAKEFAKEFAKE1234 " + "x" * 500
    r = redact(t)
    assert "ya29" not in r and "GOCSPX" not in r and "abc.def" not in r and len(r) <= 210


def test_bus_redacts_events():
    e = bus.emit("Test", "x", "token " + "ya" + "29.FAKESECRETFAKESECRET here", why="Bearer zzz.yyy")
    assert "FAKESECRET" not in e.summary and "zzz" not in e.why


def test_effects_log_drops_bodies():
    effects.add("gmail", "drafts.create", {"body": "full private email body", "message_id": "m1", "idempotency_key": "k"}, "k", True)
    last = effects.entries[-1]["args"]
    assert "body" not in last and last["message_id"] == "m1"


def test_health_reports_sources_and_dry_run():
    h = TestClient(app).get("/health").json()
    assert "live_sources" in h and "write_policy" in h and h["dry_run"] is True


def test_calendar_api_not_enabled_gives_actionable_error():
    from backend.integrations.real_sources import _map_error
    e = _map_error(Exception("Google Calendar API has not been used in project 1 before or it is disabled. accessNotConfigured"), "calendar")
    assert "NOT ENABLED" in str(e) and "manual step" in str(e)


def test_ingest_failures_are_surfaced_not_swallowed():
    from backend.agents.ingest import IngestAgent
    from backend.integrations.airbyte_client import faults, reset_mocks
    reset_mocks()
    faults.configure([dict(type="dependency_unavailable", service="gmail", include_reads=True)])
    IngestAgent().run()
    assert "gmail" in IngestAgent.errors
    reset_mocks()
