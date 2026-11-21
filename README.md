# 🌙 Overnight

> **Plans your tomorrow while you sleep and quietly does the boring stuff — safely.**

Overnight is a privacy-conscious personal operations agent. Every night it reads your Gmail and Calendar, remembers context, lets small models and a four-specialist **council** score every item, auto-prepares only the safe, reversible chores, asks you about everything else, demands an identity check for risky actions, **blocks** unsafe ones, and writes an auditable record. **It is safe by default: DRY RUN means nothing is ever sent, changed or deleted.**

## For judges (30 seconds)
1. `make demo` → open http://localhost:8000 (Maya's synthetic inbox, no keys needed).
2. Press **▶ Simulate tonight**. Overview shows: 25 AUTO (simulated), 10 need you, 3 blocked.
3. **Inbox / Tasks** → filter AUTO / ASK / VERIFY / BLOCKED. Click any row for the why.
4. **Council Decisions** → evidence (Superlinked), four specialists, debate, judge. Try the spoofed “Priya Nair”, the insurance renewal (VERIFY), and “can we do 8am?” (preference conflict).
5. **Evaluations** → *Demo: reset to pre-hardening config* → *Run simulations* (11/15) → *Run SRE agent* → *Apply* → *Re-run* (15/15).
6. Header **⚡ …with calendar outage** shows retry/backoff recovery in the Audit Log.

The strip on every page says **DRY RUN — No external changes will be made.**, **LIVE SOURCES** and **MOCK SOURCES**.

## Setup
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # all keys optional; with none, everything runs on mocks
make test                       # 47 tests, offline, no network
make demo                       # deterministic demo (SOURCES_MOCK=1)
make live                       # real Gmail/Calendar, read-only, DRY_RUN
make ready                      # readiness + safety report (exit 1 on a safety problem)
make smoke                      # headless-Chrome UI test of all 8 pages
```
`make demo` / `make live` use `scripts/serve.py`: if a healthy Overnight server is already on port 8000 it is **reused** (never duplicated); if another program owns the port it tells you and exits without killing anything (`PORT=8001 make demo` to use another port).

### Credentials (names only — never commit values)
| Variable | Purpose | Required? |
|---|---|---|
| `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN` | Gmail + Calendar (run `make oauth` once). Enable **Gmail API** and **Google Calendar API** in your Cloud project | for live mode |
| `SIE_API_KEY` | Superlinked hosted models (demo data only) | optional |
| `ANTHROPIC_API_KEY`, `PERSONA_API_KEY`+`PERSONA_TEMPLATE_ID` | Claude planner, real Persona step-up | optional (mocked) |
| `SLACK_TOKEN`, `NOTION_TOKEN`, `GITHUB_TOKEN`, `LINEAR_API_KEY` | extra sources | optional (mock) |
| `DEMO_RECIPIENT` | the one address `scripts/send_demo_emails.py` may send synthetic demo mail to | optional |
| `DRY_RUN=true`, `ALLOW_HOSTED_FOR_REAL_DATA=0` | safety switches — keep these values | |

## Demo mode vs live mode
| | `make demo` | `make live` |
|---|---|---|
| Data | Maya Chen's synthetic inbox/calendar/Slack/Notion (deterministic) | **your** Gmail + Calendar (last 2 days), mock sources excluded |
| Clock | fixed demo night | real time |
| Superlinked | hosted models allowed (synthetic data only) | **blocked for real email**; local/mock only |
| Writes | simulated in a mock sandbox | **DRY_RUN: no write call is ever made** |

## Safety guarantees
- **DRY_RUN=true**: for real connectors the executor records “would archive…” and never calls the API; the UI marks every action SIMULATED. Payments are always simulated. Sending/paying needs explicit approval, and VERIFY items need an identity check first.
- **Hard blocks** (phishing, prompt injection, spoofed sender) are never executed and cannot be approved; model scores cannot override them. Instructions found inside emails are data, never commands.
- **Privacy**: real email text never goes to hosted Superlinked (`ALLOW_HOSTED_FOR_REAL_DATA=0`). Evidence panels show subjects/senders only; logs are redacted (tokens stripped, bodies never stored). `make ready` scans git for secrets.
- **The council can only add caution**: it may escalate AUTO → ASK, never relax a rule.
- **Honest reporting**: failed or partial actions are surfaced in the brief, never shown as done.

## How it works (multi-agent workflow)
`Scheduler → IngestAgent (Airbyte SDK / Google APIs) → MemoryAgent (Cognee-style life graph) → TriageAgent (Superlinked) → Council (4 specialists + judge) → PolicyEngine (AUTO/ASK/VERIFY/BLOCK) → PlannerAgent → Executor (idempotent, retry/backoff, DRY_RUN) → Notifier`, with a **Firedrill-style harness + SRE agent** that stress-tests and patches config.

**Superlinked’s role**: hosted `GLiNER2.5-Decide` scores each item (routine? kind? stakes?) → confidence & value; GLiNER extracts amounts/dates; `Qwen3-Reranker` retrieves evidence and ranks urgency; `bge-m3` embeddings are chosen for Cognee; `Qwen3.5-4B` writes summaries and explanations. Falls back hosted → local → mock. Confidence = 0.3·model + 0.7·rule prior (weight fixed a priori).

**Firedrill / SRE**: 15 YAML scenarios (outages, 429 bursts, phishing, injection, spoofing, mid-run instructions…) run the real pipeline in isolated worlds. The SRE agent diagnoses failures, patches **only YAML/prompt files**, validates every patch against all 15 scenarios, and keeps it only if nothing regresses. Real Firedrill (cloud) is an optional final step: `scripts/fd` runs the project-local CLI (Node 24 in `.tools/`); it needs a browser sign-in at app.firedrill.run and event code TOKENSAND, then `python -m backend.firedrill_export` converts the scenarios. Until then the local harness is authoritative.

## Hive (Superlinked expert models)
Each item goes through a pipeline of expert models, each doing one small step and handing its result to the next:
**Understand** (GLiNER) → **Classify** (GLiNER2.5-Decide) → **Risk** (Qwen3.8-27B) → **Safety** (Gemma-4-31B) → **Personal fit** (GLM-5.3-Flash, uses the user's facts) → **Next step** (Qwen3.5-4B, one concrete action).
The steps are visible on the Council page. The hive can only add caution (AUTO→ASK when 3+ experts object); policy remains the authority. This is our orchestration over Superlinked-hosted models.

## User facts and suggestions
`backend/user_profile.yaml` (student, no car, San Jose, VTA/Caltrain/bike, no meetings before 10). The advisor and the Personal-fit expert turn these into suggestions, e.g. "You don't own a car, so this auto-insurance renewal is probably not yours", "No car: take VTA/Caltrain and leave 30 min early".

## Memory: Cognee Cloud
With `COGNEE_SERVICE_URL` + `COGNEE_API_KEY` in `.env`, `scripts/cognee_bridge.py` (in `.venv-cognee`) connects with `cognee.serve()` and sends each night's documents to your Cognee Cloud tenant, which builds the knowledge graph server-side. Ask it from Overview → *Ask memory*. Without those two variables it falls back to the local Cognee engine (LLM Qwen3.8-27B + bge-m3 on Superlinked), and without `.venv-cognee` to the built-in keyword memory.

## Demo mailbox (self-send)
`python scripts/demo_emails.py --set student --send` sends 12 synthetic `[OVERNIGHT DEMO]` emails from the test account to itself (only if it is the approved cortona93 account; refuses to send a set twice). Phishing/spoof examples are inserted with `spf=fail`. `--calendar` adds 3 demo events (`sendUpdates=none`). Requires `DEMO_SELF_SEND=true`.

## Firedrill MCP
`claude mcp add --transport http firedrill https://mcp.firedrill.run` is configured; run `/mcp` in Claude Code to sign in.

## Demo emails (optional)
`make demo-mail` previews 8 synthetic `[OVERNIGHT DEMO]` emails (newsletter, receipt, invitation, follow-up, phishing, spoofed sender, preference conflict, insurance). `make demo-mail-send` sends them **only** to `DEMO_RECIPIENT`; with it unset nothing is sent. Verify delivery with `make ingest`.

## Three-minute demo script
1. **(0:00)** “Overnight reads my apps while I sleep.” Show Overview: DRY RUN strip, LIVE/MOCK labels, KPI cards.
2. **(0:30)** Simulate tonight → watch Recent activity. “25 chores prepared — all simulated, all reversible.”
3. **(1:00)** Inbox: filter BLOCKED → phishing, injection, **spoofed Priya**. Council: show evidence → four votes → debate → judge.
4. **(1:40)** Insurance renewal → Actions → Review → Persona step-up → “paid” (simulated). Open the “8am” task: preference conflict forces ASK.
5. **(2:10)** Header “…with calendar outage” → Audit Log → Retries: outage, backoff, recovery, zero duplicates.
6. **(2:30)** Evaluations: reset to pre-hardening → 11/15 → SRE agent → three validated patches → Apply → 15/15.
7. **(2:50)** Sources/Settings: `make live` proof — real Gmail, zero writes, hosted models blocked for real mail.

See `CLAUDE.md` for architecture notes, decisions and measured numbers.
