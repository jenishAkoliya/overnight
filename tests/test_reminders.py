import os
os.environ["DISABLE_SCHEDULER"] = "1"
from fastapi.testclient import TestClient
from backend.app import app
from backend.orchestrator import run_night
from backend.bus import bus

c = TestClient(app)


def test_reminders_cover_everything_that_needs_the_user():
    run_night(reset=True)
    j = c.get("/reminders").json()
    kinds = {r["kind"] for r in j["reminders"]}
    assert j["count"] > 5 and {"verify", "approve", "work"} <= kinds and j["channel"] == "in-app only"
    assert any("insurance" in r["title"].lower() and r["kind"] == "verify" for r in j["reminders"])
    assert not any("Blocked" in r["title"] for r in j["reminders"])          # blocked items are not to-dos


def test_snooze_and_done_hide_without_executing():
    run_night(reset=True)
    rs = c.get("/reminders").json()["reminders"]
    a, b = rs[0], rs[1]
    c.post(f"/reminders/{a['id']}/snooze?minutes=60"); c.post(f"/reminders/{b['id']}/done")
    ids = {r["id"] for r in c.get("/reminders").json()["reminders"]}
    assert a["id"] not in ids and b["id"] not in ids
    plan = c.get("/plan").json()["plan"]
    assert next(t for t in plan["tasks"] if t["id"] == b["task_id"])["status"] in ("needs_you", "done")   # unchanged


def test_tick_pops_due_reminders_once():
    run_night(reset=True)
    c.post("/reminders/tick"); c.post("/reminders/tick")
    due = [e for e in bus.events if e.step == "reminder_due"]
    assert len(due) == len({e.summary for e in due})
