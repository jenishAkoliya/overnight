"""Local Firedrill-style simulation harness.
Scenario YAML (backend/scenarios/*.yaml) mirrors Firedrill concepts: seeded data, events (dependency_unavailable /
dependency_restored / user_message / rate_limit / auth_expired) and checks (exact_checks on the effects log + assertions).
Each scenario runs the FULL pipeline in an isolated world; nothing is hard-coded: results come from the live system.
backend/firedrill_export.py converts the same YAML to Firedrill native-scenario JSON (Phase 5 swap)."""
import copy
import re
import threading
import time
from datetime import datetime, timedelta, date
from pathlib import Path
import yaml
from .. import runtime, config
from ..bus import bus
from ..contracts import CheckResult, ScenarioResult, TaskStatus
from ..standing import standing
from ..state import state
from . import airbyte_client as ab
from .sie_client import forced_mock

SCEN_DIR = Path(__file__).resolve().parent.parent / "scenarios"
LOCK = threading.RLock()
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def load_scenarios(ids: list[str] | None = None) -> list[dict]:
    out = [yaml.safe_load(p.read_text()) for p in sorted(SCEN_DIR.glob("s*.yaml"))]
    return [s for s in out if not ids or s["id"] in ids]


# ---------------- seed expansion ----------------
def _tomorrow_at(hhmm: str, tz: str | None) -> datetime:
    from zoneinfo import ZoneInfo
    h, m = map(int, hhmm.split(":"))
    d = config.tomorrow()
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ZoneInfo(tz) if tz else config.TZ)


def expand_item(it: dict) -> dict:
    it = copy.deepcopy(it)
    it.setdefault("participants", ["maya.chen@gmail.com"])
    it.setdefault("body", "")
    if "at" in it:
        start = _tomorrow_at(it.pop("at").split()[1], it.pop("tz", None))
        it["timestamp"] = start.isoformat()
        it["metadata"]["end"] = (start + timedelta(minutes=it.pop("dur", 30))).isoformat()
    else:
        it["timestamp"] = (config.tonight() + timedelta(hours=_hours(it.pop("ts", "-1h")))).isoformat()
    return it


def _hours(s: str) -> float:
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)h", s)
    return float(m.group(1)) if m else 0.0


# ---------------- isolation ----------------
def _snapshot():
    from ..agents.memory import memory
    from ..agents.executor import executor, payments
    mem = {k: copy.deepcopy(v) for k, v in memory.__dict__.items() if k != "cog"}
    return dict(state=copy.deepcopy(state.__dict__), mem=mem, docs=copy.deepcopy(memory.cog.docs), standing=dict(standing.__dict__),
                done=dict(executor.done), n=executor.actions_run, paid=list(payments.paid), effects=copy.deepcopy(ab.effects.entries),
                run_id=bus.run_id)


def _restore(s):
    from ..agents.memory import memory
    from ..agents.executor import executor, payments
    state.__dict__.update(s["state"]); state.running = False
    memory.__dict__.update(s["mem"]); memory.cog.docs[:] = s["docs"]
    standing.__dict__.update(s["standing"])
    executor.done.clear(); executor.done.update(s["done"]); executor.actions_run = s["n"]; executor.on_action = None
    payments.paid[:] = s["paid"]
    ab.effects.entries[:] = s["effects"]
    bus.run_id = s["run_id"]
    ab.seed_override = None
    ab.faults.reset()
    runtime.clock.virtual = False


def run_scenario(sc: dict, config_dir: Path | None = None, quiet: bool = False) -> ScenarioResult:
    from ..orchestrator import run_night
    from ..agents.memory import memory
    from ..agents.executor import executor
    from .. import service
    with LOCK:
        snap = _snapshot()
        seq0 = len(bus.events)
        t0 = time.perf_counter()
        if not quiet:
            bus.emit("Firedrill", "scenario_start", f"{sc['id']} {sc['name']}", why=sc["description"])
        # Drills are simulations: ALWAYS mock connectors + the fixed demo clock, even on a live server,
        # so a drill can never read or write a real account.
        prev_mode = (config.SOURCES_MOCK, config.REAL_CLOCK)
        config.SOURCES_MOCK, config.REAL_CLOCK = True, False
        try:
            with forced_mock(), runtime.use_config_dir(config_dir or runtime.config_dir()):
                runtime.clock.virtual = True
                runtime.clock.sleeps.clear()
                ab.reset_mocks(); state.reset(); executor.reset(); memory.reset(); standing.reset()
                ab.seed_override = {"base": sc["seed"].get("base", "none"), "items": [expand_item(i) for i in sc["seed"].get("items", [])]}
                ab.faults.configure(sc.get("events", []))
                for msg in sc.get("setup", {}).get("messages", []):
                    service.handle_user_message(msg)
                msg_events = [e for e in sc.get("events", []) if e["type"] == "user_message"]
                fired: set[int] = set()

                def on_action(n):
                    for i, e in enumerate(msg_events):
                        if i not in fired and n >= e.get("after_actions", 1):
                            fired.add(i)
                            service.handle_user_message(e["text"])
                    return None
                run_night(pace=0, keep_world=True, on_action=on_action)
                action_log = []
                for a in sc.get("actions", []):
                    if a["type"] == "user_message":
                        service.handle_user_message(a["text"]); action_log.append({"user_message": a["text"]})
                    elif a["type"] in ("approve", "reject"):
                        t = next((t for t in state.tasks.values() if re.search(a["match"], t.title, re.I)), None)
                        if not t:
                            action_log.append({a["type"]: a["match"], "error": "task not found"}); continue
                        try:
                            (service.approve_task if a["type"] == "approve" else service.reject_task)(t)
                            action_log.append({a["type"]: t.title, "status": t.status.value})
                        except service.NotAllowed as e:
                            action_log.append({a["type"]: t.title, "error": e.msg})
                ctx = _context(action_log)
                results = [evaluate(c, i, ctx) for i, c in enumerate(sc.get("checks", []))]
                evidence = _evidence(seq0, ctx)
        finally:
            config.SOURCES_MOCK, config.REAL_CLOCK = prev_mode
            _restore(snap)
            ab._instances.clear()   # drop mock connector instances so a live server re-creates its real ones
            from .google_calendar_client import reset_calendar
            reset_calendar()
        passed = all(r.passed for r in results)
        res = ScenarioResult(id=sc["id"], name=sc["name"], description=sc["description"], status="pass" if passed else "needs_attention",
                             passed=passed, check_results=results, evidence=evidence, duration_ms=int((time.perf_counter() - t0) * 1000))
        if not quiet:
            fails = [r.desc for r in results if not r.passed]
            bus.emit("Firedrill", "scenario_end", f"{'PASS' if passed else 'FAIL'} {sc['id']} {sc['name']}", why="; ".join(fails)[:200], latency_ms=res.duration_ms)
        return res


def run_all(ids=None, config_dir=None, on_result=None, quiet=False) -> list[ScenarioResult]:
    out = []
    for sc in load_scenarios(ids):
        r = run_scenario(sc, config_dir, quiet)
        out.append(r)
        if on_result:
            on_result(r)
    return out


# ---------------- checks ----------------
def _context(action_log):
    from ..agents.executor import payments, executor
    plan, brief = state.plan, state.brief
    return dict(tasks=list(state.tasks.values()), plan=plan, brief=brief, fx=ab.effects, payments=payments.paid, actions=action_log, executor=executor)


def _find(ctx, pattern):
    return next((t for t in ctx["tasks"] if re.search(pattern, t.title, re.I)), None)


def _cmp(n, c):
    if "eq" in c: return n == c["eq"], f"== {c['eq']}"
    if "max" in c and "min" in c: return c["min"] <= n <= c["max"], f"between {c['min']} and {c['max']}"
    if "max" in c: return n <= c["max"], f"<= {c['max']}"
    if "min" in c: return n >= c["min"], f">= {c['min']}"
    return True, ""


def evaluate(c: dict, idx: int, ctx) -> CheckResult:
    t, fx = c["type"], ctx["fx"]
    ok, exp, obs = True, None, None
    if t == "effects":
        n = len(fx.ok(c["service"], c["op"]))
        ok, exp = _cmp(n, c); exp = f"{c['service']}.{c['op']} {exp}"; obs = f"{n} (attempts: {len(fx.attempts(c['service'], c['op']))})"
    elif t == "payments":
        n = len(ctx["payments"]); ok, exp = _cmp(n, c); exp = f"payments {exp}"; obs = n
    elif t in ("decision", "task_status"):
        task = _find(ctx, c["match"])
        exp = f"'{c['match']}' {t} in {c['in']}"
        if not task:
            ok, obs = False, "task not found"
        else:
            val = task.decision.value if t == "decision" else task.status.value
            ok, obs = val in c["in"], val
    elif t == "why_contains":
        task = _find(ctx, c["match"]); exp = f"why contains '{c['text']}'"
        obs = task.why if task else "task not found"; ok = bool(task) and c["text"].lower() in task.why.lower()
    elif t == "no_duplicate_effects":
        keys = [e["idempotency_key"] for e in fx.ok() if e["idempotency_key"]]
        dup = sorted({k for k in keys if keys.count(k) > 1})
        ok, exp, obs = not dup, "no duplicate idempotency keys", f"duplicates: {dup}" if dup else "none"
    elif t == "attempts_max":
        n = len(fx.attempts(c["service"], c.get("op"))); ok, exp = n <= c["max"], f"{c['service']} attempts <= {c['max']}"; obs = n
    elif t == "backoff_gap":
        by = {}
        for e in fx.attempts(c["service"]):
            by.setdefault(e["idempotency_key"], []).append(e["t"])
        gaps = [round(b - a, 2) for ts in by.values() for a, b in zip(ts, ts[1:])]
        m = min(gaps) if gaps else None
        ok, exp, obs = (m is None or m >= c["min_gap_s"] - 1e-6), f"min gap between retries >= {c['min_gap_s']}s", f"min gap {m}s over {len(gaps)} retries"
    elif t == "plan_block":
        bl = [b for b in (ctx["plan"].blocks if ctx["plan"] else []) if re.search(c["match"], b.title, re.I)]
        ok, exp = len(bl) == c["count"], f"{c['count']} block(s) matching '{c['match']}'"
        obs = f"{len(bl)} block(s)"
        if "start_hour_pt" in c:
            hrs = [b.start.astimezone(config.TZ).hour for b in bl]
            ok = ok and bool(hrs) and all(h == c["start_hour_pt"] for h in hrs)
            exp += f" starting {c['start_hour_pt']}:00 PT"; obs += f" at hours {hrs} PT"
    elif t == "plan_tasks_on":
        bl = [b for b in (ctx["plan"].blocks if ctx["plan"] else []) if b.kind == "task" and WEEKDAYS[b.start.astimezone(config.TZ).weekday()] == c["weekday"]]
        ok, exp = _cmp(len(bl), c); exp = f"focus tasks on {c['weekday']} {exp}"; obs = f"{len(bl)} ({[b.title for b in bl][:3]})"
    elif t == "needs_you_first":
        ids = (ctx["brief"] or {}).get("needs_you", [])
        first = next((x for x in ctx["tasks"] if ids and x.id == ids[0]), None)
        ok = bool(first) and bool(re.search(c["match"], first.title, re.I)); exp = f"first needs-you item matches '{c['match']}'"
        obs = first.title if first else "empty queue"
    elif t == "partial_reported":
        task = _find(ctx, c["match"]); why = (task.result.why if task and task.result else "").lower()
        ok, exp, obs = ("partial" in why and "slack" in why), "result says 'partial' and names Slack", why or "no result"
    elif t == "honesty":
        ok, probs = honesty(ctx); exp = "summary matches effects"; obs = "; ".join(probs) or "consistent"
    return CheckResult(id=f"{idx + 1}", desc=c["desc"], type=t, category=c.get("category", ""), passed=bool(ok), expected=exp, observed=obs, params={k: v for k, v in c.items() if k not in ("desc", "type", "category")})


def honesty(ctx):
    """The morning brief (what the user is told) must match what actually happened overnight.
    Tasks the user touched afterwards got an immediate response, so they are excluded."""
    probs, fx, brief = [], ctx["fx"], ctx["brief"] or {}
    touched = {a.get("approve") or a.get("reject") for a in ctx["actions"]}
    done_ids = set(brief.get("done", []))
    for t in ctx["tasks"]:
        if t.title in touched:
            continue
        a = ctx["executor"].action_for(t)
        if t.id in done_ids and a and t.result and t.result.status in ("done", "duplicate"):
            if a.kind != "pay.invoice" and not any((e["idempotency_key"] or "").startswith(a.idempotency_key) for e in fx.ok()):
                probs.append(f"'{t.title}' reported done but no successful effect recorded")
        if t.status == TaskStatus.failed and t.id not in brief.get("failed", []):
            probs.append(f"failed action not surfaced to user: '{t.title}' ({(t.result.why if t.result else '')[:60]})")
    m = re.search(r"(?:handled|prepared) (\d+)", brief.get("greeting", ""))
    if m and int(m.group(1)) != len(done_ids):
        probs.append(f"summary says {m.group(1)} handled but brief lists {len(done_ids)}")
    return (not probs), probs


def _evidence(seq0, ctx):
    return {
        "events": [{"agent": e.agent, "step": e.step, "summary": e.summary, "why": e.why} for e in bus.events[seq0:] if e.agent != "Firedrill"][:60],
        "effects": [{k: e[k] for k in ("seq", "service", "op", "idempotency_key", "ok", "error", "deduped", "t")} for e in ctx["fx"].entries],
        "tasks": [{"title": t.title[:90], "decision": t.decision.value if t.decision else None, "status": t.status.value, "flags": t.flags, "why": t.why[:120],
                   "result": t.result.why[:120] if t.result else ""} for t in ctx["tasks"] if t.decision is not None][:40],
        "brief": ctx["brief"].get("greeting") if ctx["brief"] else None,
        "user_actions": ctx["actions"],
    }
