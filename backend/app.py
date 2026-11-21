"""FastAPI app: REST + SSE + static single-page frontend."""
import asyncio
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config, runtime, scheduler
from .bus import bus
from .contracts import Decision, TaskStatus
from .state import state
from .orchestrator import run_night
from .agents.memory import memory
from .agents.executor import executor
from .agents.sre import sre_agent
from . import service, simlab
from .agents.ingest import IngestAgent
from .integrations.airbyte_client import connectors_status
from .integrations.persona_client import get_persona
from .integrations.sie_client import get_sie

FRONT = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app):
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Overnight", lifespan=lifespan)


class UserTask(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"ok": True, "mock_mode": config.MOCK_MODE, "dry_run": config.DRY_RUN, "connectors": connectors_status(),
            "tonight": config.tonight().isoformat(), "runs": state.run_count, "sie": get_sie().health(), "live_sources": [c["name"] for c in connectors_status() if c["mode"] == "real"],
            "source_errors": IngestAgent.errors,
            "write_policy": "DRY_RUN: every write is simulated, nothing leaves the machine" if config.DRY_RUN else "LIVE WRITES ENABLED",
            "approved_actions_live": os.getenv("APPROVED_ACTIONS_LIVE", "").lower() == "true"}


@app.get("/plan")
def get_plan():
    if not state.plan:
        return {"plan": None, "brief": None, "running": state.running}
    return {"plan": state.plan.model_dump(mode="json"), "brief": state.brief, "running": state.running, "metrics": state.last_summary}


@app.post("/run-night")
def post_run_night(sync: bool = False, pace: float = 0.45, reset: bool = False, chaos: str = ""):
    if state.running:
        return {"status": "already_running"}
    if sync:
        return run_night(pace=0, reset=reset, chaos=chaos or None)
    threading.Thread(target=run_night, kwargs={"pace": pace, "reset": reset, "chaos": chaos or None}, daemon=True).start()
    return {"status": "started"}


@app.post("/user-task")
def user_task(body: UserTask):
    text = " ".join((body.text or "").split())
    if not text:
        raise HTTPException(400, "Please type a task first")
    if len(text) > 300:
        raise HTTPException(400, "Task is too long (max 300 characters)")
    t = memory.remember_user_task(text)
    return {"stored": t, "preferences": t["preferences"], "note": "Saved to memory - will be planned tonight"}


@app.get("/user-tasks")
def user_tasks():
    """User-added tasks with their current status (queued, or planned at HH:MM after a run)."""
    out = []
    for ut in memory.user_tasks:
        row = {**ut, "status": "queued for tonight", "why": "", "planned": None}
        task = next((x for x in state.tasks.values() if x.source_item_id == ut["id"] and x.user_added), None)
        if task and state.plan:
            blk = next((b for b in state.plan.blocks if b.task_id == task.id), None)
            if blk:
                row.update(status=f"planned {blk.start:%-I:%M %p}", why=blk.note, planned=blk.start.isoformat())
            else:
                row.update(status="in plan, no free slot tomorrow", why=task.why)
        out.append(row)
    return {"tasks": out, "preferences": [p for p in memory.preferences]}


def _task(tid):
    t = state.tasks.get(tid)
    if not t:
        raise HTTPException(404, "unknown task")
    return t


class Approval(BaseModel):
    reply_body: str = ""


@app.post("/approve/{tid}")
def approve(tid: str, body: Approval | None = None):
    t = _task(tid)
    try:
        service.approve_task(t, (body.reply_body if body else ""))
    except service.NotAllowed as e:
        raise HTTPException(e.code, e.msg)
    return t.model_dump(mode="json")


@app.post("/reject/{tid}")
def reject(tid: str, reason: str = ""):
    return service.reject_task(_task(tid), reason).model_dump(mode="json")


@app.post("/message")
def user_message(body: UserTask):
    return {"handled": service.handle_user_message(body.text)}


@app.post("/undo/{tid}")
def undo(tid: str):
    t = _task(tid)
    if not executor.undo(t):
        raise HTTPException(400, "nothing to undo")
    memory.record_feedback(tid, False, "undone after auto-action", t.action_type, t.people[0] if t.people else "")
    return t.model_dump(mode="json")


@app.post("/verify/{tid}/start")
def verify_start(tid: str):
    t = _task(tid)
    if t.decision != Decision.VERIFY:
        raise HTTPException(400, "task does not need verification")
    inq = get_persona().start("maya.chen", tid)
    bus.emit("Persona", "step_up", f"Identity check started for: {t.title}", decision="VERIFY", why=f"inquiry {inq['id']} ({inq['mode']})")
    return inq


@app.get("/verify/{iid}/status")
def verify_status(iid: str, tid: str):
    t = _task(tid)
    s = get_persona().status(iid)
    if s == "completed" and not t.verified:
        t.verified = True
        bus.emit("Persona", "verified", f"Identity verified for: {t.title}", decision="VERIFY", why="inquiry completed")
    return {"status": s, "verified": t.verified}


@app.post("/verify/{iid}/simulate")
def verify_simulate(iid: str):
    get_persona().simulate_pass(iid)
    return {"ok": True}


@app.get("/events")
async def events(last: int = 0):
    async def gen():
        cur = last
        while True:
            for ev in bus.since(cur):
                cur = ev.seq
                yield f"id: {ev.seq}\ndata: {ev.model_dump_json()}\n\n"
            yield ": keepalive\n\n" if not bus.since(cur) else ""
            await asyncio.sleep(0.25)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/memory/graph")
def memory_graph():
    return memory.graph()


@app.post("/firedrill/run")
def firedrill_run(label: str = ""):
    return {"started": simlab.start_suite(label)}


@app.get("/firedrill/status")
def firedrill_status():
    return simlab.status()


@app.post("/sre/run")
def sre_run():
    return {"started": simlab.start_sre()}


@app.post("/sre/apply")
def sre_apply():
    return sre_agent.apply()


@app.post("/sre/baseline")
def sre_baseline():
    out = sre_agent.reset_to_baseline()
    simlab.reset()
    return out


@app.post("/sre/revert")
def sre_revert():
    return sre_agent.revert()


@app.get("/")
def index():
    return FileResponse(FRONT / "index.html")




@app.get("/readiness")
def readiness(sims: bool = False):
    from .readiness import report
    return report(run_sims=sims, cli=False)


@app.get("/audit")
def audit():
    from .integrations.airbyte_client import effects
    from .contracts import AgentEvent
    evs = [{"seq": e.seq, "ts": e.ts.isoformat(), "source": e.agent, "step": e.step, "summary": e.summary, "decision": e.decision, "why": e.why, "run": e.run_id}
           for e in bus.events[-250:]]
    from .integrations.airbyte_client import is_real
    writes = [e for e in effects.entries if e["op"] != "list" and e["ok"] and not e["deduped"]]
    external = [e for e in writes if e["service"] in ("gmail", "calendar", "slack", "notion", "github", "linear") and is_real(e["service"])]
    sandbox = len(writes) - len(external)
    return {"actions": executor.audit[-150:], "events": evs,
            "service_calls": [{k: e[k] for k in ("seq", "service", "op", "ok", "error", "deduped")} for e in effects.entries[-100:]],
            "external_writes": {"count": len(external), "sandbox_writes": sandbox, "dry_run": config.DRY_RUN,
                                "status": (("DRY RUN: nothing left this machine" if config.DRY_RUN else "live writes enabled") +
                                           (f" · {sandbox} simulated writes inside the mock demo sandbox" if sandbox else ""))},
            "note": "Titles truncated; email bodies, tokens and recipients are never stored."}


@app.post("/memory/ask")
def memory_ask(body: UserTask):
    from .integrations import cognee_real
    return cognee_real.ask(body.text)


@app.get("/reminders")
def get_reminders():
    from .agents import reminders
    rs = reminders.build()
    return {"reminders": rs, "count": len(rs), "urgent": sum(r["urgency"] in ("overdue", "soon") for r in rs), "channel": "in-app only"}


@app.post("/reminders/{rid}/snooze")
def snooze_reminder(rid: str, minutes: int = 60):
    from .agents import reminders
    reminders.snooze(rid, minutes)
    return {"ok": True}


@app.post("/reminders/{rid}/done")
def done_reminder(rid: str):
    from .agents import reminders
    reminders.done(rid)
    return {"ok": True, "note": "Hidden from reminders only; nothing was approved or executed."}


@app.post("/reminders/tick")
def reminder_tick():
    from .agents import reminders
    reminders.tick()
    return {"ok": True}


@app.get("/sources")
def sources():
    from .integrations.airbyte_client import REGISTRY
    counts = {}
    for it in memory.items.values():
        counts[it.source] = counts.get(it.source, 0) + 1
    out = []
    for c in connectors_status():
        err = IngestAgent.errors.get(c["name"])
        out.append({**c, "items_last_ingest": counts.get(c["name"], 0), "error": err,
                    "health": "degraded" if err else ("healthy" if c["mode"] == "real" else "mock (demo data)"),
                    "credentials_needed": list(REGISTRY[c["name"]][1])})
    from .integrations import cognee_real
    return {"sources": out, "sie": get_sie().health(), "dry_run": config.DRY_RUN, "cognee": {**cognee_real.status, "enabled": cognee_real.enabled()}}


@app.get("/settings")
def settings():
    import os
    from .policy import load_rules
    r = load_rules()
    present = lambda *k: all(bool(os.getenv(x)) for x in k)
    return {
        "dry_run": config.DRY_RUN,
        "write_policy": "DRY RUN — No external changes will be made." if config.DRY_RUN else "LIVE WRITES ENABLED",
        "hosted_superlinked_for_real_data": os.getenv("ALLOW_HOSTED_FOR_REAL_DATA") == "1",
        "approval_requirements": [
            "AUTO only if reversible, low value, confidence ≥ %.2f and an allowed action type" % r["auto"]["min_confidence"],
            "ASK: you approve before anything runs (medium value, low confidence, sending to a person, preference conflicts)",
            "VERIFY: identity step-up (Persona) required for money, irreversible, deletes, data sharing, new contacts",
            "BLOCKED: hard rules (%s) are never executed and cannot be approved" % ", ".join(r["hard_blocks"]["flags"]),
            "Sending email or paying always needs explicit approval; payments are always simulated"],
        "hard_blocks": r["hard_blocks"]["flags"], "verify_flags": r["verify"]["flags"], "ask_flags": r["ask"].get("flags", []),
        "retry": runtime.load("runtime_config.yaml")["retry"],
        "configuration": {"Google OAuth (Gmail/Calendar)": present("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"),
                          "Superlinked hosted key": present("SIE_API_KEY"), "Anthropic key": present("ANTHROPIC_API_KEY"),
                          "Persona sandbox": present("PERSONA_API_KEY", "PERSONA_TEMPLATE_ID"), "Slack token": present("SLACK_TOKEN"),
                          "Notion token": present("NOTION_TOKEN"), "GitHub token": present("GITHUB_TOKEN"), "Linear key": present("LINEAR_API_KEY")},
        "note": "Only whether a credential is configured is shown; values are never displayed."}


app.mount("/static", StaticFiles(directory=FRONT), name="static")
