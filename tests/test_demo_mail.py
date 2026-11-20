import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("send_demo", ROOT / "scripts" / "send_demo_emails.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def test_demo_messages_are_tagged_synthetic_and_cover_all_kinds():
    ms = mod.demo_messages()
    assert len(ms) == 8 and all(m["subject"].startswith("[OVERNIGHT DEMO]") for m in ms)
    assert {m["kind"] for m in ms} == {"newsletter", "receipt", "calendar_invitation", "follow_up", "phishing", "spoofed_sender", "preference_conflict", "insurance"}
    assert all(".example" in m["body"] or "Synthetic" in m["body"] or "synthetic" in m["body"] or "fake" in m["body"].lower() or "pretend" in m["body"] for m in ms)


def test_built_message_has_single_recipient_and_marker():
    m = mod.build(mod.demo_messages()[0], "demo@example.test", "demo@example.test")
    assert m["To"] == "demo@example.test" and m["Cc"] is None and m["Bcc"] is None and m["X-Overnight-Demo"] == "synthetic"


def test_mask_hides_address():
    assert mod.mask("someone@gmail.com") == "so***@g***.com"


def test_refuses_without_configured_recipient(tmp_path, monkeypatch):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    # run with .env ignored: a DEMO_RECIPIENT is not set in the environment and the repo .env has none
    out = subprocess.run([sys.executable, "-c", "import os,sys; os.environ.pop('DEMO_RECIPIENT',None); sys.argv=['x','--send']; import runpy; "
                          "mod=runpy.run_path('scripts/send_demo_emails.py'); sys.exit(mod['main']())"], cwd=ROOT, capture_output=True, text=True, env={**env, "DEMO_RECIPIENT": ""})
    assert out.returncode in (2,) or "MISSING" in out.stdout
