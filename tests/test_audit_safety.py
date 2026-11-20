import os

os.environ["DISABLE_SCHEDULER"] = "1"
from fastapi.testclient import TestClient
from backend.app import app
from backend.bus import redact, bus
from backend.integrations.airbyte_client import effects


def test_redact_strips_tokens_and_caps_length():
    t = "auth ya29.A0FAKEtokenvalue and Bearer abc.def.ghi and GOCSPX-FAKEFAKEFAKEFAKE1234 " + "x" * 500
    r = redact(t)
    assert "ya29" not in r and "GOCSPX" not in r and "abc.def" not in r and len(r) <= 210


def test_bus_redacts_events():
    e = bus.emit("Test", "x", "token ya29.FAKESECRETFAKESECRET here", why="Bearer zzz.yyy")
    assert "FAKESECRET" not in e.summary and "zzz" not in e.why


def test_effects_log_drops_bodies():
    effects.add("gmail", "drafts.create", {"body": "full private email body", "message_id": "m1", "idempotency_key": "k"}, "k", True)
    last = effects.entries[-1]["args"]
    assert "body" not in last and last["message_id"] == "m1"


def test_health_reports_sources_and_dry_run():
    h = TestClient(app).get("/health").json()
    assert "live_sources" in h and "write_policy" in h and h["dry_run"] is True
