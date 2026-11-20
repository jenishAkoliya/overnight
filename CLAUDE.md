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
| Superlinked SIE | hosted hackathon key in .env (SIE_API_KEY) | ~2,000,000 credits (balance via GET /v1/usage); calls cost 1-2 credits | ~360 credits per night run (+~1,400 probing) | LIVE hosted -> local -> mock; self-imposed floor 50k credits |
| Persona | not yet requested (sandbox key + template) | sandbox | 0 | MOCK |
| Firedrill | CLI 3.0.11 installed project-locally (.tools/, Node 24.22.3; use scripts/fd). NOT signed in: needs browser sign-in at app.firedrill.run + event code TOKENSAND applied by the user | 500 credits | 0 | local harness only |
| Arcee | not yet requested (optional LLM) | - | 0 | not used |

## Status per component
| Component | State |
|---|---|
| Ingest / connector registry (gmail, calendar, slack, notion, github, linear) | MOCK (seed) — real in Phase 1 |
| Executor (idempotency, retry/backoff, DRY_RUN, guards, undo) | REAL logic, MOCK connectors |
| MemoryAgent / Cognee | MOCK (local store + keyword search, graph for UI) — real in Phase 2 |
| TriageAgent / SIE | REAL hosted: GLiNER2.5-Decide (/v1/decisions) + GLiNER extract + Qwen3-Reranker-0.6B priority; confidence = 0.3*model + 0.7*rule prior (weight fixed a priori); 0.4-0.8 escalates to Qwen3.5-4B; falls back hosted->local->mock. Scenario harness always uses mock SIE (deterministic, free) |
| Hosted generation | Qwen/Qwen3.5-4B via SIE /v1/chat/completions: planner summary (never moves blocks), triage escalation, SRE explanations. (Qwen3-4B-Instruct-2507 is NOT in the hosted catalog; GLM-5.3-Flash:relay returned empty (reasoning ate tokens)) |
| Embeddings for Cognee | hosted has NO MiniLM: use BAAI/bge-m3 (1024d) at https://api.superlinked.com/v1/embeddings (verified 200, dim 1024). Cognee not wired yet (Phase 2) |
| PlannerAgent | deterministic (tz-aware, respects prefs); Claude in Phase 3 |
| PolicyEngine | REAL |
| Persona | MOCK (passes after 2 s; hidden ⚡ simulate button in modal) |
| Notifier | in-app brief; email only a draft |
| Firedrill local harness | REAL (local): 15 YAML scenarios (backend/scenarios) run the full pipeline in isolated worlds with fault injection (503/429/401, restore, mid-run user messages) and an effects log. Real Firedrill cloud = Phase 5 (`backend/firedrill_export.py` converts YAML -> native scenario JSON; field names inferred, verify then) |
| SREAgent | REAL: diagnoses failed checks (rule-based templates; Claude later), patches ONLY yaml/prompt files, validates on a staging copy (all 15 re-run, keep only if pass count rises and nothing regresses), Apply/Revert + history, lessons -> MemoryAgent |
| Add-a-task | FIXED (UI had no button/feedback; now button+Enter, toast, preference chip, Your tasks list, inline errors) |
| UI | working (projector-readable) |
Python 3.12 venv at .venv (system python is 3.15 — outside Cognee's range). Node v26.13.0 (< 26.13.1 required by Firedrill CLI; need to upgrade/nvm before Phase 5). Apple Silicon (arm64): run SIE natively or hosted.

## Patchable config (SRE may edit these, never .py)
backend/policy_rules.yaml, guards_rules.yaml (phishing/injection patterns, spoofing, user_intents), runtime_config.yaml (retry/backoff/rate-limit), prompts/*.txt. Read through backend/runtime.py (supports a staging dir + virtual clock).

## Simulation results (measured, not scripted)
- First measurement on the Phase-0 system: 8/15. SRE staged 3 config patches -> 12/15 and ESCALATED 3 scenarios that need code (honesty/partial-write reporting, needs-you prioritization).
- Lead then fixed those 3 in code (Notifier lists failed actions + sorts by priority; executor reports partial writes) -> baseline 11/15.
- Current baseline 11/15 (s05 outage-restore, s09 preference conflict, s11 429 burst, s15 spoofed sender fail). SRE: 3 patches kept (retry max_attempts 3->4; policy ask.flags += preference_conflict; hard_blocks += spoofed_sender), 0 rejected, 0 escalated -> 15/15; applying then re-running confirms 15/15. Revert restores baseline.
- Failing scenarios were NOT engineered: policy/retry/intent values are first-cut choices (retry budget 3 attempts; flags not listed in policy). Scenario thresholds (1s outage, 3x 429 burst) were chosen by us.

## Decisions log
- Python 3.12 venv; React+htm vendored (offline demo, no build step).
- Seed anchored to a fixed demo clock so output is deterministic; real mode will use the real clock.
- Mock-mode LLM escalations are counted as (simulated) LLM calls so "% small-model calls" is not trivially 100%.
- Email-vs-Slack/calendar duplicates are merged in triage (same obligation); user-added tasks override inferred ones.
- Rejecting/undoing an AUTO action lowers confidence for that (action type, sender) next run -> becomes ASK (feedback learning; Cognee improve() in Phase 2).

## Demo script (3 min)
1 apps connected + memory graph; 2 Simulate tonight (agents light up); 3 Morning brief: plan + Done for you (why) + Needs you; 4 insurance -> Persona -> paid; phishing blocked; 5 add "book dentist, I prefer mornings" -> Simulate again -> morning block; 6 Firedrill pass rate -> SRE patch -> after; 7 cost/night + time saved.

## Pitch numbers (mock run, Phase 0)
25 tasks auto-done; 63 min saved/night (25 baseline planning + per-task); $0.007/night; 95% small-model calls; 2 hard-blocked (phishing, injection); 3 VERIFY. Firedrill local before/after: 11/15 -> 15/15 after 3 SRE patches (real, measured; see above).

## Open questions
Google OAuth, Slack token, Anthropic key + model choice, SIE mode, Persona sandbox key+template, Firedrill signup/TOKENSAND, GitHub repo to push.

## Live mode (Phase 1) & safety
`make demo` = Maya seed (SOURCES_MOCK=1). `make live` = REAL Gmail+Calendar, real clock, mock sources excluded, DRY_RUN=true, hosted SIE blocked for real data (ALLOW_HOSTED_FOR_REAL_DATA=0). `make ingest` = read-only pull. `scripts/live_triage.py` fails if any write reaches a service. UI shows a DRY RUN banner and SIMULATED tags; audit logs/events are redacted (tokens stripped, bodies never logged). Node: system 26.13.0 is too old for Firedrill; project-local Node 24 in .tools/ (scripts/fd wrapper, .nvmrc=24).

## Final polish (hardening + UI)
- Config HARDENED by default (retry 4 attempts, `preference_conflict` always ASK, `spoofed_sender` hard block); `backend/config_baseline/` keeps the pre-hardening config for the SRE before/after replay (Evaluations -> 'Demo: reset to pre-hardening config'). Local Firedrill: hardened 15/15, baseline 11/15, SRE baseline->15/15 (3 patches).
- Council (backend/agents/council.py): 4 specialists + judge per task; evidence via Superlinked rerank (keyword fallback); can only escalate AUTO->ASK.
- UI: white sidebar app (frontend/index.html + app.css + app.js), 8 hash-routed pages; `make smoke` exercises every page. Endpoints added: /sources /settings /audit /readiness; `make ready` = readiness + secret scan.
- Honest labels: audit separates EXTERNAL writes (real connectors) from sandbox (mock) writes; brief says 'prepared ... (simulated, dry run)'.
- Calendar: real connector reachable but the Google Cloud project has the Calendar API DISABLED (403 accessNotConfigured) -> surfaced as DEGRADED. Manual step: enable it in Cloud Console.
- Demo emails: scripts/send_demo_emails.py needs DEMO_RECIPIENT (not configured -> nothing sent).

## 15:55 update
- Hive = sequential expert pipeline on hosted Superlinked models (agents/swarm.py); 429 backoff; quorum escalation only.
- user_profile.yaml (student, no car, San Jose) + agents/advisor.py suggestions; profile_mismatch flag (ask).
- Real Cognee 1.6.10 in .venv-cognee via scripts/cognee_bridge.py (LLM Qwen3.8-27B + bge-m3 on Superlinked); background ingest; POST /memory/ask. COGNEE_API_KEY present in .env but unused (local Cognee chosen).
- ALLOW_HOSTED_FOR_REAL_DATA=1 by user choice (test mailbox only). DRY_RUN=true.
- Student email set (12) sent to cortona93 (self-send + 2 inserts). Live result 9/12 expected; 3 conservative misses (AUTO->ASK).
- Firedrill MCP added (needs /mcp OAuth).
