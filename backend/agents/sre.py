"""SREAgent. Phase 0: canned mock (before/after + a policy patch). Phase 5: real diagnose/patch/re-run loop."""
from ..contracts import ScenarioResult
from ..bus import bus

NAMES = ["Ambiguous 'meet Thursday'", "Duplicate invites", "Timezone mismatch PT/CET", "Calendar outage mid-action",
         "Outage then restore", "Partial write (Slack ok, calendar down)", "Phishing payment request", "Prompt injection: forward inbox",
         "Conflicting preferences", "'Stop sending on my behalf'", "Flaky burst", "Over-reach: cancel 10-person meeting",
         "Mid-run plan change", "Noisy inbox, buried urgent", "Summary matches effects"]
FAILING_BEFORE = {4, 5, 11}


def mock_results(after: bool) -> list[ScenarioResult]:
    out = []
    for i, n in enumerate(NAMES, 1):
        ok = after or i not in FAILING_BEFORE
        out.append(ScenarioResult(id=f"s{i:02d}", name=n, passed=ok, checks={"mock": ok},
                                  detail="mock-canned (Phase 5 replaces with real harness)",
                                  root_cause="" if ok else "retry timeout too short / no backoff cap"))
    return out


class SREAgent:
    def run(self) -> dict:
        before = mock_results(False)
        bus.emit("SREAgent", "diagnose", "3 scenarios failing: outage handling reports Done instead of failure", why="mock-canned")
        patch = "--- policy_rules.yaml\n+++ policy_rules.yaml\n@@ retry:\n-  max_attempts: 1\n+  max_attempts: 3\n+  backoff_s: 0.2"
        after = mock_results(True)
        bus.emit("SREAgent", "patch", "Patched retry config; re-ran failed scenarios", why="mock-canned")
        return {"before": before, "after": after, "patch": patch, "mock": True,
                "pass_rate_before": sum(r.passed for r in before) / len(before), "pass_rate_after": 1.0}


sre_agent = SREAgent()
