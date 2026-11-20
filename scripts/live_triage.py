"""Live, READ-ONLY triage of real Gmail/Calendar with DRY_RUN enforced. Prints decisions and verifies no write reached any service.
Run: REAL_CLOCK=1 .venv/bin/python scripts/live_triage.py"""
import os
import sys
sys.path.insert(0, ".")
os.environ["DRY_RUN"] = "true"
os.environ.setdefault("ALLOW_HOSTED_FOR_REAL_DATA", "0")
from backend import config
assert config.DRY_RUN and config.REAL_CLOCK, "needs REAL_CLOCK=1 and DRY_RUN=true"
from backend.orchestrator import run_night
from backend.state import state
from backend.integrations.airbyte_client import effects, connectors_status
from backend.integrations.sie_client import get_sie, stats

print("connectors:", [(c["name"], c["mode"]) for c in connectors_status()])
r = run_night(reset=True)
from backend.agents.ingest import IngestAgent
print("SOURCE ERRORS:", IngestAgent.errors or "none")
m = r["metrics"]
print(f"SIE tier: {get_sie().tier()} | hosted calls: {stats.snapshot()['calls']['hosted']} | planner: {state.plan.planner}")
print(f"tasks={m['tasks']} auto_done(dry-run)={m['auto_done']} needs_you={m['needs_you']} blocked={m['blocked']} verify={m['verify']} failed={m['failed']}")
print(f"{'DEC':6} {'STATUS':9} {'conf':5} {'type':14} item | why")
for t in sorted(state.tasks.values(), key=lambda t: (t.decision.value if t.decision else "", t.title)):
    print(f"{t.decision.value if t.decision else '-':6} {t.status.value:9} {t.confidence:.2f}  {t.action_type:14} {t.title[:60]} | {(t.result.status + ': ' if t.result else '')}{t.why[:70]}")
writes = [e for e in effects.entries if e["op"] not in ("list",)]
print("\nSAFETY: outside-world effects recorded:", len(writes), "(must be 0)")
print("SAFETY: any non dry_run result:", [t.title for t in state.tasks.values() if t.result and t.result.status not in ("dry_run", "skipped")])
sys.exit(1 if writes else 0)
