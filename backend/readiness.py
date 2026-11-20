"""Final health & readiness check (GET /readiness, `make ready`). Never prints secret values."""
import json
import os
import re
import subprocess
import time
from pathlib import Path
from . import config, runtime
from .integrations.airbyte_client import connectors_status
from .integrations.sie_client import get_sie, hosted_available, real_data_active

ROOT = Path(__file__).resolve().parent.parent
SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.I)
SECRET_PATTERNS = [r"GOCSPX-[\w-]{10,}", r"ya29\.[\w-]{20,}", r"1//0[\w-]{30,}", r"xox[abp]-[\w-]{10,}", r"sk-ant-[\w-]{10,}", r"persona_(sandbox|production)_[\w-]{10,}"]


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    return [ROOT / f for f in out if f and (ROOT / f).is_file()]


def secret_scan() -> dict:
    """Search tracked files for (a) known secret patterns and (b) the literal values of secrets in .env. Reports file names only."""
    vals = set()
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if SECRET_NAME.search(k) and len(v.strip()) >= 12:
                    vals.add(v.strip())
    hits = []
    for f in _tracked_files():
        if f.suffix in (".png", ".jpg", ".lock") or f.stat().st_size > 2_000_000:
            continue
        try:
            txt = f.read_text(errors="ignore")
        except Exception:
            continue
        if any(re.search(p, txt) for p in SECRET_PATTERNS) or any(v in txt for v in vals):
            hits.append(str(f.relative_to(ROOT)))
    env_tracked = ".env" in [str(f.relative_to(ROOT)) for f in _tracked_files()]
    return {"clean": not hits and not env_tracked, "files_with_secrets": hits, "env_tracked": env_tracked}


def tests_status() -> dict:
    p = ROOT / ".test_status.json"
    if not p.exists():
        return {"known": False, "note": "run `make test`"}
    j = json.loads(p.read_text())
    return {"known": True, **j, "age_min": round((time.time() - j["ts"]) / 60, 1)}


def firedrill_local() -> dict:
    from .integrations.firedrill_client import run_all
    rs = run_all(quiet=True)
    return {"passed": sum(r.passed for r in rs), "total": len(rs), "failing": [r.id for r in rs if not r.passed]}


def _last_sim() -> dict:
    """Last simulation result already held in memory (never runs scenarios: safe to call while a night is running)."""
    from . import simlab
    st = simlab.status()
    if st["latest"]:
        r = st["latest"]
        return {"passed": r["pass"], "total": r["total"], "failing": [x["id"] for x in r["results"] if not x["passed"]], "from_last_run": True}
    return {"passed": 0, "total": 15, "failing": [], "not_run_yet": True}


def firedrill_cli() -> dict:
    fd = ROOT / "scripts" / "fd"
    if not fd.exists():
        return {"installed": False}
    try:
        out = subprocess.run([str(fd), "status", "--json"], capture_output=True, text=True, timeout=15).stdout
        j = json.loads(out.splitlines()[0])["data"]
        return {"installed": True, "signed_in": bool(j.get("signed_in"))}
    except Exception:
        return {"installed": True, "signed_in": False}


def report(run_sims: bool = True, cli: bool = True) -> dict:
    conns = connectors_status()
    live = [c["name"] for c in conns if c["mode"] == "real"]
    mock = [c["name"] for c in conns if c["mode"] == "mock"]
    sie = get_sie().health()
    optional = {
        "anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "persona_key_and_template": bool(os.getenv("PERSONA_API_KEY") and os.getenv("PERSONA_TEMPLATE_ID")),
        "slack_token": bool(os.getenv("SLACK_TOKEN")), "notion_token": bool(os.getenv("NOTION_TOKEN")),
        "github_token": bool(os.getenv("GITHUB_TOKEN")), "linear_key": bool(os.getenv("LINEAR_API_KEY")),
        "local_sie_running": bool(sie.get("local_up")),
    }
    fd_cli = firedrill_cli() if cli else {"skipped": True}
    optional["firedrill_signed_in"] = bool(fd_cli.get("signed_in"))
    scan = secret_scan()
    rep = {
        "server": "ok",
        "dry_run": config.DRY_RUN,
        "write_policy": "DRY_RUN: every write is simulated" if config.DRY_RUN else "LIVE WRITES ENABLED",
        "mode": "live" if live else "demo",
        "live_sources": live, "mock_sources": mock,
        "hosted_superlinked": {"key_present": sie["hosted_key_present"], "allowed_for_current_data": hosted_available(), "calls_this_process": sie["calls"]["hosted"],
                               "blocked_because_real_data": real_data_active() and os.getenv("ALLOW_HOSTED_FOR_REAL_DATA") != "1"},
        "source_errors": __import__("backend.agents.ingest", fromlist=["IngestAgent"]).IngestAgent.errors,
        "tests": tests_status(),
        "firedrill_local": firedrill_local() if run_sims else _last_sim(),
        "firedrill_cli": fd_cli,
        "secrets_scan": scan,
        "missing_optional_integrations": sorted(k for k, v in optional.items() if not v),
    }
    problems = []
    if not config.DRY_RUN: problems.append("DRY_RUN is off")
    if real_data_active() and os.getenv("ALLOW_HOSTED_FOR_REAL_DATA") == "1": problems.append("hosted SIE allowed for real data")
    if not scan["clean"]: problems.append("secrets found in tracked files")
    rep["degraded"] = sorted(rep["source_errors"])
    rep["safety_problems"] = problems
    rep["ready"] = not problems
    return rep
