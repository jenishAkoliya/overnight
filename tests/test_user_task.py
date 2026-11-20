import os
os.environ["DISABLE_SCHEDULER"] = "1"
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.orchestrator import run_night
from backend.state import state
from backend.agents.memory import memory

c = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    run_night(reset=True)
    yield


def test_add_task_api_stores_source_timestamp_and_preference():
    r = c.post("/user-task", json={"text": "book dentist, I prefer mornings"})
    assert r.status_code == 200
    j = r.json()
    assert j["stored"]["source"] == "user" and j["stored"]["created"]
    assert j["preferences"] == ["Maya prefers mornings"]
    assert memory.preferences.count("Maya prefers mornings") == 1
    c.post("/user-task", json={"text": "call mom, I prefer mornings"})
    assert memory.preferences.count("Maya prefers mornings") == 1  # no duplicates


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "   "}, {}, {"text": 5}])
def test_add_task_rejects_empty_or_bad(body):
    assert c.post("/user-task", json=body).status_code in (400, 422)


def test_empty_error_message_is_clear():
    assert "type a task" in c.post("/user-task", json={"text": "  "}).json()["detail"].lower()


def test_no_meetings_before_parsed():
    assert memory.parse_preferences("no meetings before 10, ok") == ["No meetings before 10"]
    assert memory.parse_preferences("I prefer afternoons") == ["Maya prefers afternoons"]


def test_list_shows_queued_then_planned():
    c.post("/user-task", json={"text": "book dentist, I prefer mornings"})
    rows = c.get("/user-tasks").json()["tasks"]
    assert len(rows) == 1 and rows[0]["status"] == "queued for tonight"
    run_night()
    row = c.get("/user-tasks").json()["tasks"][0]
    assert row["status"].startswith("planned") and "AM" in row["status"]
    assert "You asked for this" in row["why"] and "prefer mornings" in row["why"]


def test_user_task_in_morning_block_and_dentist_merged():
    c.post("/user-task", json={"text": "book dentist, I prefer mornings"})
    run_night()
    blocks = [b for b in state.plan.blocks if "dentist" in b.title.lower()]
    assert len(blocks) == 1 and blocks[0].start.hour < 12
    assert blocks[0].note == "You asked for this; you prefer mornings"
    assert sum("dentist" in t.title.lower() for t in state.tasks.values()) == 1
    assert next(t for t in state.tasks.values() if "dentist" in t.title.lower()).user_added
    assert not any("dentist" in t.title.lower() for t in state.tasks.values() if not t.user_added)


def test_user_task_survives_second_run():
    c.post("/user-task", json={"text": "book dentist, I prefer mornings"})
    run_night(); run_night()
    assert len(c.get("/user-tasks").json()["tasks"]) == 1
    assert sum("dentist" in b.title.lower() for b in state.plan.blocks) == 1
