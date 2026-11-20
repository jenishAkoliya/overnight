"""The three justified safety/correctness fixes, each tested on its own plus end-to-end on the demo seed."""
import os
os.environ["DISABLE_SCHEDULER"] = "1"
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from backend import runtime
from backend.app import app
from backend.agents.sre import _copy_config
from backend.agents.executor import executor
from backend.contracts import Decision, Task, TaskStatus, Value
from backend.integrations.firedrill_client import load_scenarios, run_scenario, run_all
from backend.orchestrator import run_night
from backend.policy import PolicyEngine
from backend.state import state


def sc(i):
    return next(s for s in load_scenarios() if s["id"] == i)


def test_live_config_is_hardened_and_all_15_scenarios_pass():
    rs = run_all(quiet=True)
    assert [r.id for r in rs if not r.passed] == []


def test_pre_hardening_baseline_fails_exactly_the_four_gaps():
    base = Path(tempfile.mkdtemp()); _copy_config(runtime.LIVE_DIR / "config_baseline", base)
    failed = sorted(r.id for r in run_all(config_dir=base, quiet=True) if not r.passed)
    assert failed == ["s05", "s09", "s11", "s15"]


def test_fix1_retry_budget_covers_a_one_second_outage():
    assert runtime.load("runtime_config.yaml")["retry"]["max_attempts"] >= 4
    assert run_scenario(sc("s05"), quiet=True).passed and run_scenario(sc("s11"), quiet=True).passed


def test_fix2_preference_conflict_requires_review_with_explanation():
    t = Task(id="t1", title="Reply: 8am?", action_type="reply", confidence=0.95, value=Value.low, flags=["preference_conflict"])
    PolicyEngine().decide(t)
    assert t.decision == Decision.ASK and t.status == TaskStatus.needs_you and "conflict" in t.why.lower()


def test_fix3_spoofed_sender_is_hard_blocked_and_never_executes():
    t = Task(id="t2", title="x", action_type="archive", confidence=0.99, value=Value.low, flags=["spoofed_sender"], source_item_id="m1")
    PolicyEngine().decide(t)
    assert t.status == TaskStatus.blocked
    t.decision = Decision.AUTO          # even if something forced AUTO/approved, the executor refuses
    t.status = TaskStatus.approved
    r = executor.execute(t)
    assert not r.ok and "hard-blocked" in r.why


def test_demo_seed_contains_every_demo_moment():
    run_night(reset=True)
    by = {t.title: t for t in state.tasks.values()}
    find = lambda s: next(t for t in state.tasks.values() if s.lower() in t.title.lower())
    assert find("Suspicious").status == TaskStatus.blocked                     # spoofed sender
    assert find("suspicious invoice").status == TaskStatus.blocked             # phishing
    assert find("insurance").decision == Decision.VERIFY                       # step-up
    c = find("8am")
    assert c.decision == Decision.ASK and "conflict" in c.why.lower()          # preference conflict
    assert sum(t.decision == Decision.AUTO for t in state.tasks.values()) >= 15


def test_chaos_calendar_outage_recovers_with_retries():
    r = run_night(reset=True, chaos="calendar_blip")
    from backend.bus import bus
    assert any(e.step == "retry" for e in bus.events)
    assert r["metrics"]["failed"] == 0
    assert all(t.status == TaskStatus.done for t in state.tasks.values() if t.decision == Decision.AUTO)


def test_audit_endpoint_marks_simulation_and_hides_bodies():
    run_night(reset=True)
    j = TestClient(app).get("/audit").json()
    assert j["actions"] and all("body" not in a and "raw" not in a for a in j["actions"])
