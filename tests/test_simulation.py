import os
os.environ["DISABLE_SCHEDULER"] = "1"
import shutil
import tempfile
from pathlib import Path
import pytest
from backend import runtime
from backend.agents import sre as sre_mod
from backend.agents.sre import SREAgent, apply_patch, _copy_config
from backend.integrations.firedrill_client import load_scenarios, run_scenario, run_all
from backend.orchestrator import run_night


def cfg(**retry):
    d = Path(tempfile.mkdtemp())
    _copy_config(runtime.LIVE_DIR, d)
    if retry:
        apply_patch(d, dict(file="runtime_config.yaml", op="set", path=["retry", "max_attempts"], value=retry["max_attempts"]))
    return d


def sc(i):
    return next(s for s in load_scenarios() if s["id"] == i)


def test_fifteen_scenarios_with_checks():
    ss = load_scenarios()
    assert len(ss) == 15 and all(s["checks"] and s["description"] for s in ss)


def test_outage_scenario_fails_without_retries_and_passes_with_them():
    one = run_scenario(sc("s05"), cfg(max_attempts=1), quiet=True)
    assert not one.passed and any(c.category == "retry_config" and not c.passed for c in one.check_results)
    many = run_scenario(sc("s05"), cfg(max_attempts=5), quiet=True)
    assert many.passed
    assert len([e for e in many.evidence["effects"] if e["ok"]]) == 1   # exactly one accept, no duplicates


def test_isolation_does_not_clobber_live_state():
    run_night(reset=True)
    from backend.state import state
    before = (len(state.tasks), state.plan.date)
    run_scenario(sc("s07"), quiet=True)
    assert (len(state.tasks), state.plan.date) == before
    assert not runtime.clock.virtual


def test_phishing_scenario_really_blocks():
    r = run_scenario(sc("s07"), quiet=True)
    assert r.passed and not [e for e in r.evidence["effects"] if e["op"] == "messages.send"]


def test_sre_keeps_good_patch_and_rejects_regressing_patch(monkeypatch):
    live_before = (runtime.LIVE_DIR / "runtime_config.yaml").read_text()
    good = dict(file="runtime_config.yaml", op="set", path=["retry", "max_attempts"], value=4, rationale="more retries")
    bad = dict(file="policy_rules.yaml", op="set", path=["hard_blocks", "flags"], value=[], rationale="drop all hard blocks")
    monkeypatch.setattr(sre_mod, "diagnose", lambda r, live: [{"scenario_id": r.id, "scenario": r.name, "check": "x", "category": "retry_config", "expected": "", "observed": "",
                                                           "root_cause": "t", "patch": good if r.id == "s05" else (bad if r.id == "s11" else None), "escalate": None}
                                                          for _ in [0] if not r.passed])
    agent = SREAgent()
    out = agent.run()
    assert [k["value"] for k in out["kept"]] == [4]
    assert out["rejected"] and "regression" in out["rejected"][0]["reason"]
    assert out["pass_after"] > out["pass_before"]
    assert (runtime.LIVE_DIR / "runtime_config.yaml").read_text() == live_before   # staged, not applied


def test_sre_real_run_apply_and_revert():
    agent = SREAgent()
    snap = {n: (runtime.LIVE_DIR / n).read_text() for n in runtime.PATCHABLE if (runtime.LIVE_DIR / n).exists()}
    try:
        out = agent.run()
        assert out["pass_after"] >= out["pass_before"] and out["kept"]
        assert all(p["file"] in runtime.PATCHABLE and not p["file"].endswith(".py") for p in out["kept"])
        agent.apply()
        assert sum(r.passed for r in run_all(quiet=True)) == out["pass_after"]
        agent.revert()
        assert {n: (runtime.LIVE_DIR / n).read_text() for n in snap} == snap
    finally:
        for n, t in snap.items():
            (runtime.LIVE_DIR / n).write_text(t)
