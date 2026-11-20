import os
os.environ["DISABLE_SCHEDULER"] = "1"
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.orchestrator import run_night
from backend.state import state
from backend.contracts import Decision, TaskStatus
from backend.agents.memory import memory
from backend.integrations.airbyte_client import get_connector, faults

c = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    run_night(reset=True)
    yield


def by(sub):
    return next(t for t in state.tasks.values() if sub.lower() in t.title.lower())


def test_split_has_all_three_decisions():
    ds = {t.decision for t in state.tasks.values()}
    assert ds == {Decision.AUTO, Decision.ASK, Decision.VERIFY}


def test_insurance_is_verify_phishing_and_injection_blocked():
    assert by("insurance").decision == Decision.VERIFY
    assert by("suspicious invoice").status == TaskStatus.blocked
    assert by("forward your inbox").status == TaskStatus.blocked
    assert get_connector("gmail").count("messages.send") == 0  # nothing sent, ever


def test_hard_rules_override_scores():
    t = by("insurance"); assert t.confidence < 0.8
    t.confidence = 0.99
    from backend.policy import PolicyEngine
    assert PolicyEngine().decide(t).decision == Decision.VERIFY


def test_every_decision_has_why():
    assert all(t.why for t in state.tasks.values())


def test_duplicates_merged_and_calendar_deduped():
    titles = [t.title for t in state.tasks.values()]
    assert sum("onboarding PRD" in x for x in titles) == 1
    assert sum("roadmap deck" in x.lower() for x in titles) == 1


def test_timezone_event_converted_to_pt():
    z = next(b for b in state.plan.blocks if "Zurich" in b.title)
    assert z.start.hour == 8 and z.start.utcoffset().total_seconds() == -8 * 3600


def test_idempotent_executor():
    from backend.agents.executor import executor
    t = next(t for t in state.tasks.values() if t.status == TaskStatus.done)
    r = executor.execute(t)
    assert r.status == "duplicate"


def test_retry_then_fail_honestly_and_recovery():
    from backend.agents.executor import executor
    from backend import config
    config.DRY_RUN = False
    run_night(reset=True)
    executor.reset(); faults.configure([{"type": "dependency_unavailable", "service": "gmail"}])
    t = next(t for t in state.tasks.values() if t.action_type == "archive")
    r = executor.execute(t)
    from backend import runtime
    assert not r.ok and "FAILED" in r.why and r.attempts == runtime.load("runtime_config.yaml")["retry"]["max_attempts"]
    faults.reset()
    assert executor.execute(t).ok


def test_verify_requires_persona_then_pays():
    t = by("insurance")
    assert c.post(f"/approve/{t.id}").status_code == 409
    inq = c.post(f"/verify/{t.id}/start").json()
    c.post(f"/verify/{inq['id']}/simulate")
    assert c.get(f"/verify/{inq['id']}/status", params={"tid": t.id}).json()["verified"]
    r = c.post(f"/approve/{t.id}").json()
    assert r["status"] == "done"
    from backend.agents.executor import payments
    assert len(payments.paid) == 1


def test_blocked_cannot_be_approved():
    t = by("suspicious invoice")
    assert c.post(f"/approve/{t.id}").status_code == 403


def test_user_task_remembered_and_morning_pref():
    c.post("/user-task", json={"text": "book dentist, I prefer mornings"})
    run_night()
    b = next(b for b in state.plan.blocks if "dentist" in b.title.lower())
    assert b.start.hour < 12
    assert sum("dentist" in t.title.lower() for t in state.tasks.values()) == 1


def test_rejection_teaches_memory():
    t = next(t for t in state.tasks.values() if t.decision == Decision.AUTO and t.action_type == "archive")
    author = t.people[0]
    c.post(f"/reject/{t.id}")
    run_night()
    again = [x for x in state.tasks.values() if x.action_type == "archive" and x.people and x.people[0] == author]
    assert again and all(x.decision == Decision.ASK for x in again)


def test_metrics_and_endpoints():
    m = state.last_summary
    assert m["auto_done"] > 10 and m["small_model_pct"] > 50
    assert c.get("/health").json()["ok"]
    assert c.get("/plan").json()["plan"]["blocks"]
    assert c.get("/memory/graph").json()["nodes"]
    assert c.get("/firedrill/status").json()["total"] == 0
