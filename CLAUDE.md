# Overnight — project memory (hackathon: Personal Agents, SF, Nov 20 2026; submit 4:30 PM PT, demos 5:00 PM)

## Goal
Near-zero human next-day planning + fewer mundane tasks. Optimize for a reliable, impressive demo over completeness.

## Pitch
"Overnight plans your tomorrow while you sleep and quietly does the boring stuff." Pulls data nightly (Airbyte) -> long-term memory (Cognee) -> small models triage + score value/confidence (Superlinked) -> auto-completes low-value/high-confidence tasks -> notifies only about what needs the user. Risky actions need a Persona identity step-up. Firedrill simulates failures; an SRE agent fixes them.

## Architecture (Python/FastAPI + single-page React)
Scheduler(21:00 plan, 07:00 brief) -> IngestAgent -> MemoryAgent -> TriageAgent -> PlannerAgent -> PolicyEngine -> Executor -> Notifier; Firedrill harness -> SREAgent.
Every step emits AgentEvent on `backend/bus.py` -> `GET /events` (SSE). Every integration = interface + MOCK fallback, auto-selected when env keys are missing (`MOCK_MODE=auto`). Full demo runs offline with zero keys.
Key files: backend/{app,orchestrator,policy,policy_rules.yaml,contracts,bus,guards,state,scheduler}.py, backend/agents/*, backend/integrations/*, backend/seed/{build_seed.py,demo_user.json}, frontend/index.html (React+htm vendored in frontend/vendor, no CDN).
Demo clock: `DEMO_TONIGHT=2026-12-06T21:00-08:00` (Sunday night; tomorrow = Mon Dec 7). Seed is generated relative to it (`make seed`).

## Contracts (backend/contracts.py)
SourceItem, Task{action_type, reversible, value, confidence, flags, decision, why, status}, Decision{AUTO,ASK,VERIFY}, Plan/PlanBlock, Action/ActionResult, AgentEvent, ScenarioResult. Task.status adds `blocked` for hard blocks.

## Policy (backend/policy_rules.yaml — SRE agent may edit)
AUTO only if reversible AND confidence>=0.8 AND value=low AND type in allowed list AND no external send. ASK for medium value / send to a contact / conf<0.8. VERIFY (Persona) for money, irreversible, new external contact, delete, data sharing. Hard blocks (phishing, prompt_injection) override everything, cannot be approved. Every decision records a one-line `why`. Payments are ALWAYS simulated (never moves money). Executor refuses send/pay unless approved (+verified for VERIFY).

## Sponsors + docs
Docs in docs/research/{airbyte,cognee,superlinked,persona_arcee,firedrill}.md (trust over memory).
### Sponsor access & usage (free hackathon access ONLY; never upgrade/pay; on quota/402/429 -> fall back to mock and ask)
| Service | Access type | Free limit | Used so far | Status |
|---|---|---|---|---|
| Airbyte | not yet requested | OSS/local SDK free; Cloud 14-day trial | 0 | MOCK |
| Cognee | OSS (pip), needs LLM key + embeddings | local | 0 | MOCK |
| Superlinked SIE | not yet requested (local docker / hosted key) | local free | 0 | MOCK |
| Persona | not yet requested (sandbox key + template) | sandbox | 0 | MOCK |
| Firedrill | not yet requested (event code TOKENSAND = +500 credits) | 500 credits | 0 | MOCK |
| Arcee | not yet requested (optional LLM) | - | 0 | not used |

## Status per component
| Component | State |
|---|---|
| Ingest / connector registry (gmail, calendar, slack, notion, github, linear) | MOCK (seed) — real in Phase 1 |
| Executor (idempotency, retry/backoff, DRY_RUN, guards, undo) | REAL logic, MOCK connectors |
| MemoryAgent / Cognee | MOCK (local store + keyword search, graph for UI) — real in Phase 2 |
| TriageAgent / SIE | MOCK heuristics (LLM escalation 0.4–0.8 logged, simulated) — real in Phase 3 |
| PlannerAgent | deterministic (tz-aware, respects prefs); Claude in Phase 3 |
| PolicyEngine | REAL |
| Persona | MOCK (passes after 2 s; hidden ⚡ simulate button in modal) |
| Notifier | in-app brief; email only a draft |
| Firedrill / SRE | CANNED mock (`/firedrill/run`, `/sre/run`) — real in Phase 5 |
| UI | working (projector-readable) |
Python 3.12 venv at .venv (system python is 3.15 — outside Cognee's range). Node v26.13.0 (< 26.13.1 required by Firedrill CLI; need to upgrade/nvm before Phase 5). Apple Silicon (arm64): run SIE natively or hosted.

## Decisions log
- Python 3.12 venv; React+htm vendored (offline demo, no build step).
- Seed anchored to a fixed demo clock so output is deterministic; real mode will use the real clock.
- Mock-mode LLM escalations are counted as (simulated) LLM calls so "% small-model calls" is not trivially 100%.
- Email-vs-Slack/calendar duplicates are merged in triage (same obligation); user-added tasks override inferred ones.
- Rejecting/undoing an AUTO action lowers confidence for that (action type, sender) next run -> becomes ASK (feedback learning; Cognee improve() in Phase 2).

## Demo script (3 min)
1 apps connected + memory graph; 2 Simulate tonight (agents light up); 3 Morning brief: plan + Done for you (why) + Needs you; 4 insurance -> Persona -> paid; phishing blocked; 5 add "book dentist, I prefer mornings" -> Simulate again -> morning block; 6 Firedrill pass rate -> SRE patch -> after; 7 cost/night + time saved.

## Pitch numbers (mock run, Phase 0)
25 tasks auto-done; 63 min saved/night (25 baseline planning + per-task); $0.007/night; 95% small-model calls; 2 hard-blocked (phishing, injection); 3 VERIFY. Firedrill before/after: canned 12/15 -> 15/15 (replace in Phase 5).

## Open questions
Google OAuth, Slack token, Anthropic key + model choice, SIE mode, Persona sandbox key+template, Firedrill signup/TOKENSAND, GitHub repo to push.
