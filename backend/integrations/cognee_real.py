"""Real Cognee (v1.6.10) via scripts/cognee_bridge.py in .venv-cognee (isolated deps).
Cognee's LLM + embeddings are hosted Superlinked models (Qwen3.8-27B + bge-m3 1024d). Ingestion is slow (LLM graph
extraction), so it runs in a background thread after each night; the pipeline never waits for it."""
import json
import os
import subprocess
import threading
from pathlib import Path
from ..bus import bus

ROOT = Path(__file__).resolve().parent.parent.parent
PY = ROOT / ".venv-cognee" / "bin" / "python"
BRIDGE = ROOT / "scripts" / "cognee_bridge.py"
status = {"available": PY.exists() and BRIDGE.exists(), "state": "idle", "docs": 0, "last_error": "", "last_batch": 0}
_lock = threading.Lock()


def enabled() -> bool:
    from .sie_client import hosted_available
    return status["available"] and os.getenv("OVERNIGHT_OFFLINE") != "1" and hosted_available() and os.getenv("COGNEE", "1") == "1"


def _run(args, stdin=None, timeout=600):
    return subprocess.run([str(PY), str(BRIDGE), *args], input=stdin, capture_output=True, text=True, timeout=timeout, cwd=ROOT)


def remember_async(docs: list[str], dataset: str):
    if not enabled() or not docs or not _lock.acquire(blocking=False):
        return False

    def work():
        try:
            status.update(state="ingesting", last_batch=len(docs))
            bus.emit("Cognee", "ingest_start", f"Building the knowledge graph from {len(docs)} documents", why="Cognee + Superlinked LLM/embeddings (background)")
            r = _run(["remember", dataset], json.dumps(docs))
            out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
            if r.returncode == 0 and '"ok": true' in out:
                status["docs"] += len(docs); status.update(state="ready", last_error="")
                bus.emit("Cognee", "ingest_done", f"Knowledge graph updated (+{len(docs)} docs)")
            else:
                status.update(state="error", last_error=(r.stderr or out)[-200:])
                bus.emit("Cognee", "ingest_failed", "Cognee ingestion failed; local memory still works", why=status["last_error"][:150])
        except Exception as e:
            status.update(state="error", last_error=str(e)[:200])
        finally:
            _lock.release()
    threading.Thread(target=work, daemon=True).start()
    return True


def ask(question: str) -> dict:
    if not enabled():
        return {"ok": False, "error": "Cognee is not enabled (needs .venv-cognee and hosted Superlinked allowed)."}
    try:
        r = _run(["recall", question[:300]], timeout=120)
        line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "[]"
        return {"ok": r.returncode == 0, "answers": json.loads(line) if line.startswith("[") else [], "via": "Cognee recall (Superlinked LLM + bge-m3)"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
