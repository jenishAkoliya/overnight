"""Orchestrator: runs the nightly pipeline Ingest -> Memory -> Triage -> Plan -> Policy -> Execute -> Notify."""
import time
import uuid
from . import config
from .bus import bus
from .contracts import Decision, TaskStatus
from .policy import PolicyEngine
from .state import state
from .standing import standing
from .agents.ingest import IngestAgent
from .agents.memory import memory
from .agents.triage import triage_agent, costs
from .integrations.sie_client import stats as sie_stats, get_sie
from .agents.planner import planner_agent
from .agents.executor import executor
from .agents.notifier import notifier

SIE_COST, LLM_COST = 0.00002, 0.002
CREDIT_USD = 0.00001   # ASSUMED $ per hosted SIE credit (rate unknown; credits are the real unit)   # est. $ per call (small model vs Claude)
BASELINE_PLANNING_MIN = 25            # manual nightly/morning planning time
MIN_PER_AUTO = {"archive": 1, "file_receipt": 2, "accept_recurring": 3, "rsvp": 2, "reminder": 2, "draft_reply": 4}


def run_night(pace: float = 0.0, reset: bool = False, on_action=None, keep_world: bool = False) -> dict:
    """pace>0 sleeps between steps so the live UI visibly lights up."""
    if state.running:
        return {"status": "already_running"}
    state.running = True
    try:
        if keep_world:
            state.tasks.clear()
        else:
            if reset:
                state.reset(); bus.reset(); executor.reset()
                from .integrations.airbyte_client import reset_mocks
                reset_mocks(); memory.reset(); standing.reset()
            else:
                state.tasks.clear(); executor.reset()
                from .integrations.airbyte_client import reset_mocks
                reset_mocks()
                memory.cog.reset_sources()
        costs["sie_calls"] = costs["llm_calls"] = 0
        get_sie().cache.clear()   # every night recomputes; cached repeats would hide real cost
        s0 = sie_stats.snapshot()
        bus.run_id = f"run-{uuid.uuid4().hex[:6]}"
        t0 = time.perf_counter()
        nap = lambda: time.sleep(pace) if pace else None
        bus.emit("Scheduler", "start", f"Tonight's run started ({config.tonight():%a %b %d %H:%M %Z})", why="21:00 cron / manual 'Simulate tonight'")
        nap()
        items = IngestAgent().run(); nap()
        memory.ingest(items); nap()
        tasks = triage_agent.run(items); nap()
        policy = PolicyEngine()
        for t in tasks:
            t.confidence = _apply_learning(t)
            policy.decide(t)
            bus.emit("PolicyEngine", "decide", t.title, decision=t.decision, why=t.why)
        nap()
        plan = planner_agent.build(items, tasks); nap()
        state.tasks = {t.id: t for t in tasks}
        executor.on_action = on_action
        for t in tasks:
            if t.decision == Decision.AUTO:
                t.result = executor.execute(t)
                t.status = TaskStatus.done if t.result.ok else TaskStatus.failed
                nap() if pace else None
        executor.on_action = None
        if standing.defer_to and standing.defer_to != plan.date:
            plan = planner_agent.build(items, tasks, day=standing.defer_to)
            bus.emit("PlannerAgent", "replan", f"Re-planned for {standing.defer_to:%a %b %d} after your instruction", why="you asked to move work")
        metrics = _metrics(tasks, time.perf_counter() - t0, s0)
        plan.metrics = metrics
        state.plan = plan
        state.brief = notifier.brief(plan, metrics)
        state.run_count += 1
        state.last_summary = metrics
        bus.emit("Scheduler", "run_complete", f"Done: {metrics['auto_done']} auto, {metrics['needs_you']} need you, {metrics['blocked']} blocked",
                 latency_ms=int(metrics["duration_s"] * 1000), cost=metrics["cost_per_night"])
        return {"status": "ok", "run_id": bus.run_id, "metrics": metrics}
    finally:
        state.running = False


def _apply_learning(t):
    """Cognee feedback learning: a rejected AUTO type from the same sender drops confidence so it becomes ASK."""
    author = t.people[0] if t.people else ""
    n = memory.rejections(t.action_type, author)
    if n:
        bus.emit("MemoryAgent", "learned", f"Lowered confidence for {t.action_type} from {author}", why=f"you rejected this {n}x before")
        return max(0.0, t.confidence - 0.3 * n)
    return t.confidence


def _metrics(tasks, dur, s0) -> dict:
    done = [t for t in tasks if t.status == TaskStatus.done]
    saved = sum(MIN_PER_AUTO.get(t.action_type, 2) for t in done)
    s1 = sie_stats.snapshot()
    d = {k: s1["calls"][k] - s0["calls"][k] for k in s1["calls"]}
    sie = sum(d.values())
    gen = s1["gen_calls"] - s0["gen_calls"]
    llm = costs["llm_calls"] + gen            # simulated (mock) escalations + real generation calls
    credits = round(s1["credits"] - s0["credits"], 2)
    total = max(sie + llm, 1)
    cost = d["mock"] * SIE_COST + costs["llm_calls"] * LLM_COST + credits * CREDIT_USD
    return {
        "items": len(set(t.source_item_id for t in tasks if t.source_item_id)),
        "tasks": len(tasks),
        "auto_done": len(done),
        "needs_you": sum(1 for t in tasks if t.status == TaskStatus.needs_you and t.action_type != "work"),
        "blocked": sum(1 for t in tasks if t.status == TaskStatus.blocked),
        "failed": sum(1 for t in tasks if t.status == TaskStatus.failed),
        "verify": sum(1 for t in tasks if t.decision == Decision.VERIFY and t.status != TaskStatus.blocked),
        "minutes_saved": BASELINE_PLANNING_MIN + saved,
        "sie_calls": sie, "llm_calls": llm,
        "sie_hosted_calls": d["hosted"], "sie_local_calls": d["local"], "sie_mock_calls": d["mock"], "gen_calls": gen, "credits_used": credits,
        "sie_tier": get_sie().tier(),
        "small_model_pct": round(100 * sie / total),
        "cost_per_night": round(cost, 4),
        "duration_s": round(dur, 2),
        "mode": "mock" if config.use_mock("ANTHROPIC_API_KEY") else "real",
    }
