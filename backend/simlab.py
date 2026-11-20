"""Simulation lab: runs scenario suites / the SRE agent in background threads and keeps results for the UI."""
import threading
import time
from . import runtime
from .bus import bus
from .integrations.firedrill_client import run_all, load_scenarios
from .agents.sre import sre_agent

lab = {"runs": [], "running": False, "progress": [], "total": 0, "sre_running": False}
_lock = threading.Lock()


def _config_label() -> str:
    import hashlib
    h = hashlib.sha1("".join((sre_agent.live / n).read_text() for n in runtime.PATCHABLE if (sre_agent.live / n).exists()).encode()).hexdigest()[:6]
    return f"config-{h}"


def start_suite(label: str = "") -> bool:
    with _lock:
        if lab["running"] or lab["sre_running"]:
            return False
        lab["running"], lab["progress"], lab["total"] = True, [], len(load_scenarios())

    def work():
        try:
            rs = run_all(on_result=lambda r: lab["progress"].append(r.model_dump(mode="json")))
            lab["runs"].append({"label": label or "run", "config": _config_label(), "ts": time.time(), "pass": sum(r.passed for r in rs), "total": len(rs),
                                "results": [r.model_dump(mode="json") for r in rs]})
            bus.emit("Firedrill", "suite_done", f"{sum(r.passed for r in rs)}/{len(rs)} scenarios passed", why=f"config {_config_label()}")
        finally:
            lab["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return True


def start_sre() -> bool:
    with _lock:
        if lab["running"] or lab["sre_running"]:
            return False
        lab["sre_running"] = True

    def work():
        try:
            sre_agent.run()
        finally:
            lab["sre_running"] = False
    threading.Thread(target=work, daemon=True).start()
    return True


def status() -> dict:
    runs = lab["runs"]
    return {"running": lab["running"], "sre_running": lab["sre_running"], "total": lab["total"], "progress": lab["progress"],
            "latest": runs[-1] if runs else None, "baseline": runs[0] if runs else None, "n_runs": len(runs),
            "sre": sre_agent.last or None, "staged": bool(sre_agent.staged), "history": sre_agent.public_history(), "config": _config_label()}


def reset():
    """Forget previous runs (used when the demo baseline is restored so 'before' is measured fresh)."""
    with _lock:
        lab["runs"].clear(); lab["progress"] = []
    sre_agent.last = {}
    sre_agent.staged = None
