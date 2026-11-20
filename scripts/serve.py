"""Safe server start. Usage: serve.py demo|live
- Port free            -> start uvicorn in the requested mode.
- Healthy Overnight    -> reuse it (never start a duplicate); warn if its mode differs.
- Other process        -> print who owns the port and exit 1. Never kills anything."""
import json
import os
import subprocess
import sys
import urllib.request

mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
port = int(os.getenv("PORT", "8000"))
env = dict(os.environ)
if mode == "demo":
    env["SOURCES_MOCK"] = "1"; env.pop("REAL_CLOCK", None)
else:
    env["REAL_CLOCK"] = "1"; env.pop("SOURCES_MOCK", None)


def owner():
    out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"], capture_output=True, text=True).stdout.split()
    pid = next((x[1:] for x in out if x.startswith("p")), None)
    cmd = next((x[1:] for x in out if x.startswith("c")), "?")
    return pid, cmd


pid, cmd = owner()
if pid:
    try:
        h = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3))
        running = "live" if h.get("live_sources") else "demo"
        print(f"Overnight is ALREADY RUNNING on http://localhost:{port} (pid {pid}, mode: {running}, dry_run={h.get('dry_run')}). Reusing it - not starting a duplicate.")
        if running != mode:
            print(f"NOTE: it is in {running} mode but you asked for {mode}. To switch, stop that exact process yourself: kill {pid}   then re-run make {mode}.")
        sys.exit(0)
    except Exception:
        print(f"Port {port} is in use by pid {pid} ({cmd}) which is not a healthy Overnight server. Not touching it. Free the port or set PORT=8001.")
        sys.exit(1)
print(f"Starting Overnight ({mode} mode) on http://localhost:{port}")
os.execvpe(sys.executable, [sys.executable, "-m", "uvicorn", "backend.app:app", "--port", str(port)], env)
