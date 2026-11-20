"""FastAPI app: REST + SSE + static single-page frontend."""
import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config, scheduler
from .bus import bus
from .contracts import Decision, TaskStatus
from .state import state
from .orchestrator import run_night
from .agents.memory import memory
from .agents.executor import executor
from .agents.sre import sre_agent
from . import service, simlab
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
            "tonight": config.tonight().isoformat(), "runs": state.run_count, "sie": get_sie().health()}


@app.get("/plan")
def get_plan():
    if not state.plan:
        return {"plan": None, "brief": None, "running": state.running}
    return {"plan": state.plan.model_dump(mode="json"), "brief": state.brief, "running": state.running, "metrics": state.last_summary}


@app.post("/run-night")
def post_run_night(sync: bool = False, pace: float = 0.45, reset: bool = False):
    if state.running:
        return {"status": "already_running"}
    if sync:
        return run_night(pace=0, reset=reset)
    threading.Thread(target=run_night, kwargs={"pace": pace, "reset": reset}, daemon=True).start()
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


@app.post("/approve/{tid}")
def approve(tid: str):
    t = _task(tid)
    try:
        service.approve_task(t)
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


@app.post("/sre/revert")
def sre_revert():
    return sre_agent.revert()


@app.get("/")
def index():
    return FileResponse(FRONT / "index.html")


app.mount("/static", StaticFiles(directory=FRONT), name="static")
