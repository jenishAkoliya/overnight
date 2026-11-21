"""Cognee bridge (runs in .venv-cognee). Cognee's LLM AND embeddings both point at hosted Superlinked (OpenAI-compatible).
Usage: cognee_bridge.py remember <dataset>  (JSON list of texts on stdin)
       cognee_bridge.py recall "<query>"     (prints JSON list)
Keys are read from .env and never printed."""
import asyncio, json, os, sys
from pathlib import Path
from dotenv import dotenv_values
ROOT = Path(__file__).resolve().parent.parent
env = dotenv_values(ROOT / ".env")
key = env.get("SIE_API_KEY") or ""
os.environ.update({
    "LLM_PROVIDER": "custom", "LLM_MODEL": "openai/" + os.getenv("COGNEE_LLM_MODEL", "Qwen/Qwen3.8-27B-FP8"),
    "LLM_ENDPOINT": "https://api.superlinked.com/v1", "LLM_API_KEY": key,
    "EMBEDDING_PROVIDER": "openai_compatible", "EMBEDDING_MODEL": "BAAI/bge-m3", "EMBEDDING_ENDPOINT": "https://api.superlinked.com/v1",
    "EMBEDDING_API_KEY": key, "EMBEDDING_DIMENSIONS": "1024", "ENABLE_BACKEND_ACCESS_CONTROL": "false",
    "TELEMETRY_DISABLED": "1", "COGNEE_SKIP_CONNECTION_TEST": "true"})
CLOUD_URL = (env.get("COGNEE_SERVICE_URL") or "").strip()
CLOUD_KEY = (env.get("COGNEE_API_KEY") or "").strip()
import cognee  # noqa: E402

cognee.config.system_root_directory(str(ROOT / ".cognee_data" / "system"))
cognee.config.data_root_directory(str(ROOT / ".cognee_data" / "data"))


async def cloud():
    """Cognee Cloud: the tenant runs extraction/embeddings server-side; we only send documents and questions."""
    client = await cognee.serve(url=CLOUD_URL, api_key=CLOUD_KEY)
    cmd = sys.argv[1]
    try:
        if cmd == "remember":
            docs = json.loads(sys.stdin.read(), strict=False)
            await client.remember(docs, dataset_name=sys.argv[2])
            print(json.dumps({"ok": True, "n": len(docs), "mode": "cloud"}))
        elif cmd == "recall":
            res = await client.recall(sys.argv[2], top_k=5)
            out = []
            for r in res or []:
                if isinstance(r, dict):
                    out.append(str(r.get("search_result") or r.get("text") or r)[:400])
                else:
                    out.append(str(getattr(r, "search_result", None) or r)[:400])
            print(json.dumps(out))
        elif cmd == "ping":
            print(json.dumps({"ok": True, "mode": "cloud"}))
    finally:
        await client.close()


async def main():
    if CLOUD_URL and CLOUD_KEY:
        return await cloud()
    cmd = sys.argv[1]
    if cmd == "remember":
        docs = json.loads(sys.stdin.read(), strict=False)
        await cognee.remember(docs, dataset_name=sys.argv[2], self_improvement=False)
        print(json.dumps({"ok": True, "n": len(docs)}))
    elif cmd == "recall":
        res = await cognee.recall(sys.argv[2], top_k=5)
        out = []
        for r in res or []:
            out.append(str(getattr(r, "search_result", None) or getattr(r, "text", None) or r)[:400])
        print(json.dumps(out))
    elif cmd == "reset":
        await cognee.forget(everything=True); print(json.dumps({"ok": True}))

asyncio.run(main())
