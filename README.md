# 🌙 Overnight
> Plans your tomorrow while you sleep and quietly does the boring stuff.

Run: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && make demo` → http://localhost:8000 (zero keys needed; everything has a mock fallback). Tests: `make test`.

Pipeline: Scheduler → Ingest (Airbyte) → Memory (Cognee) → Triage (Superlinked) → Planner (Claude) → Policy (AUTO/ASK/VERIFY) → Executor → Notifier; Persona step-up for risky actions; Firedrill + SRE agent for resilience. See CLAUDE.md for details (full README in Phase 6).
