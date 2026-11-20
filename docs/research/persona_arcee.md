# Persona (KYA step-up) + Arcee (planner LLM) - hackathon research (2026-11-20)

## TL;DR
- Persona "Know Your Agent" is a MARKETING FRAMEWORK, not a distinct API. No agent-specific endpoints documented. Build step-up with the normal Inquiries API (sandbox key is instant/self-serve). Pitch it as "KYA = verified human behind the agent, re-verified at payment time".
- Sandbox: sign up -> immediate `persona_sandbox_...` key. No real verification in sandbox; use the Simulate Actions endpoint to force pass/fail, or click through the hosted flow with fake data.
- Arcee: hosted OpenAI-compatible API at https://api.arcee.ai/api/v1. BUT the Trinity models are listed "Not Hosted" in the Arcee platform pricing table (as of docs fetched); hosted models there are GLM/Kimi/DeepSeek. Trinity is reachable via OpenRouter (`arcee-ai/trinity-large-thinking`, also a `:free` variant). Free credits: Trinity Builders Program (apply; rolling review, no timeline - may not land before 4:30pm) and $20 on conductor.arcee.ai signup.

---------------------------------------------------------------
## PART A - PERSONA

### A1. Know Your Agent (KYA)
- Source: https://withpersona.com/lp/know-your-agent/ , https://withpersona.com/solutions/know-your-agent/ , blog https://withpersona.com/blog/building-know-your-agent-the-missing-identity-layer-for-agentic-commerce
- KYA = extend Persona KYC/KYB to verify the people/businesses behind agents: end users, developers, businesses, employees. Lifecycle verification at onboarding, payment execution, access requests, capturing user intent; "dynamic reverification" with method chosen to fit assurance level.
- Page lists NO agent-specific APIs/products; access is "chat with us"/contact sales (no self-serve pricing). Persona is partnered with AstraSync (agent registry) - agents get crypto IDs from AstraSync, not Persona.
- Implication: for the hackathon, KYA step-up == a standard Persona Inquiry (gov ID + selfie, or lighter template) triggered right before a risky action, tied to the user via `reference-id`.

### A2. Integration

**Keys / env** (https://docs.withpersona.com/docs/api-keys)
- Sign up: https://withpersona.com/dashboard/signup -> immediate sandbox key. Dashboard: API > API Keys. Sandbox key prefix `persona_sandbox_...`, production `persona_production_...` (cannot cross environments). Production requires contacting Persona.
- Key scopes (e.g. `inquiry.write`, `inquiry.read`, `account.read`) set under API Keys > Edit > Permissions. Make sure the key can read/write inquiries.
- Auth header: `Authorization: Bearer <key>`.
- Inquiry Template: create in Dashboard (Inquiries > Templates) in the Sandbox environment; ID looks like `itmpl_...`. Environment ID `env_...` is needed for the JS SDK (Dashboard).

**Create inquiry** (https://docs.withpersona.com/api-reference/inquiries/create-an-inquiry)
```
POST https://api.withpersona.com/api/v1/inquiries
Headers: Authorization: Bearer <key>; Content-Type: application/json;
         Persona-Version: 2026-09-29 (docs' current default; optional - omit to use your org's pinned version);
         optional Idempotency-Key, Key-Inflection (camel|kebab|snake)
Body:
{"data":{"attributes":{
   "inquiry-template-id":"itmpl_xxx",
   "reference-id":"user-123",          // your user ID (tutorial uses this attr)
   "fields":{"name-first":"Alex","name-last":"Sample"}   // optional prefill
}}}
Response 201:
{"data":{"id":"inq_...","type":"inquiry",
   "attributes":{"status":"created|pending|completed|failed|needs_review|approved|declined|expired", "reference-id":"user-123", ...},
   "relationships":{"account":{"data":{"id":"act_...","type":"account"}}, ...}},
 "meta":{"session-token":"eyJ...","one-time-link":"https://withpersona.com/verify?code=...","one-time-link-short":"https://go.perso.na/..."}}
```
Note: the 201 response `meta` includes a `one-time-link` -> easiest hosted-flow URL to send/open for the user (no JS SDK needed).

**One-time link (hosted)** (https://docs.withpersona.com/inquiry-one-time-links)
- `POST /api/v1/inquiries/{inq_id}/generate-one-time-link` body `{}` -> `meta.one-time-link`, `meta.one-time-link-short`. Format `https://inquiry.withpersona.com/verify?code=...`. Used to resume/hand off. Default expiry governed by template Session Management settings (dashboard OTLs 24h).
- Alternative hosted URL (no API): `https://inquiry.withpersona.com/verify?inquiry-template-id=itmpl_...&reference-id=...&environment-id=env_...` (hosted flow params: https://docs.withpersona.com/hosted-flow-parameters - not fetched in detail; verify).

**Resume session token**: `POST /api/v1/inquiries/{inq_id}/resume` body `{"meta":{}}` -> `meta["session-token"]` (only for `pending` inquiries). (https://docs.withpersona.com/tutorial-embedded-flow-precreate)

**Embedded flow (JS SDK)** (https://docs.withpersona.com/quickstart-embedded-flow , params https://docs.withpersona.com/embedded-flow-parameters)
```js
import Persona from 'persona';   // npm i persona  (CDN script tag exists too: not confirmed in docs fetched)
const client = new Persona.Client({
  // Option 1: precreated inquiry (recommended; server sets reference-id/fields)
  inquiryId: "inq_...", sessionToken: "..."  /* only if status pending */,
  environmentId: "env_...",
  // Option 2: client-created: templateId:"itmpl_...", referenceId:"user-123"  (do NOT pass templateId when resuming)
  onReady: () => client.open(),
  onComplete: ({inquiryId, status, fields}) => {/* tell backend */},
  onCancel: ({inquiryId, sessionToken}) => {},
  onError: (e) => {},
  onEvent: (name, meta) => {}
});
```

**Status: webhooks vs polling**
- Polling: `GET https://api.withpersona.com/api/v1/inquiries/{inq_id}` -> `data.attributes.status`. List/lookup: `GET /api/v1/inquiries?filter[reference-id]=user-123&filter[status]=created,pending&page[size]=1`. Polling is the simplest for a hackathon (no public URL).
- Webhooks (https://docs.withpersona.com/quickstart-webhooks): Dashboard (Sandbox) > Webhooks; URL must be public HTTPS (use ngrok); events `inquiry.created/started/completed/approved/failed/declined/...` (`inquiry.approved` only if template has a Workflow). Header `persona-signature: t=<ts>,v1=<sig>`; sig = hex HMAC-SHA256(secret, f"{t}.{raw_body}"). Payload: `data.attributes.name` (event), `data.attributes.payload.data.{type,id}`. Retries up to 7 more times with backoff if no 2xx in 5s.

**Reverification of returning user**
- Persona Accounts group inquiries by `reference-id`; a new Inquiry for same reference-id/account is the re-verify (https://help.withpersona.com/articles/4D4JLmYPofDJuYQebxRFJ2.md says same Create Inquiry process is used to "verify or re-verify"; dashboard path All Accounts > Create Inquiry). Practical: reuse the same `reference-id` (your user id) each time and create a fresh inquiry per risky action (use a light template, e.g. selfie-only/ID reuse, for step-up). API attribute for attaching to an account explicitly (`account-id`) is not confirmed in fetched docs - check API reference if needed; reference-id is sufficient. Blog: https://withpersona.com/blog/reverify . Also look into "Reusable Personas" if you want a no-friction returning check (not researched).

**Python (requests) - step-up gate**
```python
import os, time, requests
API = "https://api.withpersona.com/api/v1"
H = {"Authorization": f"Bearer {os.environ['PERSONA_API_KEY']}",   # persona_sandbox_...
     "Persona-Version": "2026-09-29",
     "Content-Type": "application/json"}

def start_stepup(user_id: str, action_summary: str):
    body = {"data": {"attributes": {
        "inquiry-template-id": os.environ["PERSONA_TEMPLATE_ID"],   # itmpl_...
        "reference-id": user_id,
        "note": action_summary,
    }}}
    r = requests.post(f"{API}/inquiries", json=body, headers=H, timeout=20); r.raise_for_status()
    j = r.json()
    return j["data"]["id"], j["meta"]["one-time-link"]   # send/open this link for the user

def get_status(inq_id: str) -> str:
    r = requests.get(f"{API}/inquiries/{inq_id}", headers=H, timeout=20); r.raise_for_status()
    return r.json()["data"]["attributes"]["status"]

def wait_for_approval(inq_id, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = get_status(inq_id)
        if s in ("completed", "approved"): return True
        if s in ("failed", "declined", "expired"): return False
        time.sleep(3)
    return False

def simulate(inq_id, passed=True):   # SANDBOX ONLY - skip the UI in demos/tests
    acts = [{"type": "start_inquiry"}, {"type": "complete_inquiry"}] if passed else [{"type": "start_inquiry"}, {"type": "fail_inquiry"}]
    r = requests.post(f"{API}/inquiries/{inq_id}/perform-simulate-actions",
                      json={"meta": {"simulate-actions": acts}}, headers=H); r.raise_for_status()
```
(`note` attribute shown in response schema; whether it's settable on create is not confirmed - drop it if 400s.)
Treat `completed` as "user finished flow"; `approved` only appears if a Workflow/review marks it. For a gate, accept `completed` (or `approved` if the template has a workflow) and check verification results if you need strictness.

### A3. Sandbox behavior
Sources: https://docs.withpersona.com/docs/integration-testing , https://docs.withpersona.com/environments , https://help.withpersona.com/articles/6I2kGhfPvSuUjYq4z6tpmB.md , https://help.withpersona.com/articles/1snRc3bFMYhykFN6vhLith.md
- Sandbox: free, "Real verifications are not performed"; names forced to "Alexander J Sample"; docs say a toggle in the flow lets you force passes/fails (details/magic values not in fetched docs - you'll see it in the hosted flow UI; in flow, test by using the preview/sandbox flow and its pass/fail toggle).
- Programmatic: `POST /api/v1/inquiries/{id}/perform-simulate-actions` body `{"meta":{"simulate-actions":[...]}}`; action types: `start_inquiry, complete_inquiry, fail_inquiry, expire_inquiry, mark_for_review_inquiry, approve_inquiry, decline_inquiry, create_passed_verification, create_failed_verification` (the latter two need `"data":{"verification-template-id":"vtmpl_..."}`). Each fires the matching webhook events -> good for testing webhook handler.
- Dashboard: switch to Sandbox (top-left), Inquiries > All Inquiries > Create inquiry -> copy link -> complete flow.
- Real ID/selfie extraction testing in sandbox requires contacting Persona.

### A4. Gotchas for 4 hours
1. KYA has no API - don't waste time looking; frame it as Inquiry-based step-up. Production needs sales contact; stay in sandbox and say so in the demo.
2. Create the Inquiry Template in the dashboard FIRST (Sandbox env toggle) and copy `itmpl_` + `env_` IDs. Wrong environment (sandbox key vs prod template) = errors.
3. Use `persona_sandbox_` key; ensure key permissions include inquiry read/write.
4. Webhooks need public HTTPS (ngrok) - polling GET /inquiries/{id} avoids this. Verify HMAC if you do webhooks (raw body, `t.` + body).
5. Pin `Persona-Version` header (docs show 2026-09-29) so JSON shape doesn't shift; keys are kebab-case by default (`inquiry-template-id`, `reference-id`) - or send `Key-Inflection: snake`.
6. Use `one-time-link` from the create response (hosted flow) rather than building embedded JS - least time. If embedding, allow iframe domain (Security page) and don't pass templateId when resuming.
7. Pending inquiries need session token (POST .../resume) when re-opening in the SDK; OTLs expire.
8. `completed` != `approved`; approved requires a workflow. Decide which your gate accepts.
9. For a reliable live demo, have a `simulate()` fallback ready (sandbox only).
10. Rate limit 429 exists; add Idempotency-Key on create to avoid duplicate inquiries.

---------------------------------------------------------------
## PART B - ARCEE

### B1. Models
Sources: https://arcee.ai/trinity , https://docs.arcee.ai/llms-full.txt , https://openrouter.ai/models/arcee-ai/trinity-large-thinking
- Trinity family (open-weight, Hugging Face; Arcee says all share function selection, schema-compliant JSON, multi-turn coherence, parallel tool use, MCP):
  - Trinity Nano: 6B total/1B active, 128K ctx (edge)
  - Trinity Mini: 26B total/3B active, 128K ctx (agent backends) - cheap/fast, good planner candidate
  - Trinity Large Preview: 400B/13B active, 128K served
  - Trinity Large Thinking: 400B/13B active, reasoning + agentic RL, 256K served (BF16), released Apr 1 2026. Best for planning/tool calls; keep reasoning across turns (map `reasoning_content`<->`reasoning`, send `""` not `null` content on tool-call turns).
- Conductor (conductor.arcee.ai): model router with modes `auto`, `auto-reasoning`, `auto-tool` (routes among Caller Large, GPT-4.1, Claude Sonnet 3.7); lists `virtuoso-small/medium/large`, `blitz`, `coder`, `caller-large`. Docs say Blitz/Virtuoso/Maestro/Coder/Caller are "previously released, and now retired" yet Conductor still lists them - status ambiguous; avoid for hackathon. AFM-4.5B exists (small, Ollama/Arm guides), not deprecated per docs.
- Recommendation: Trinity-Large-Thinking (quality planning/tool use) or Trinity-Mini (cheapest/fastest).

### B2. Hosted API
Source: https://docs.arcee.ai/llms-full.txt
- Arcee Platform API: base URL `https://api.arcee.ai/api/v1`, OpenAI-compatible (`/chat/completions`), auth `Authorization: Bearer <key>` (keys prefixed `rcai-`), supports tools/tool_choice, streaming, `response_format json_object`, stateless. 402 on insufficient balance.
- Platform model IDs/pricing per 1M tokens (in/out/cached): zai-org/glm-5.3-flash $0.15/$0.50/$0.03; zai-org/glm-5.3 $1.40/$4.40/$0.26; moonshotai/kimi-k3 $3/$15; moonshotai/kimi-k3.1-pro $2/$10; deepseek/deepseek-v4.1-flash $0.22/$1.20; deepseek/deepseek-v4.1-flash-1017 $0.30/$1.20. Trinity Nano/Mini/Large are marked "Not Hosted" in that table. BUT arcee.ai/trinity says Arcee hosts Trinity on chat.arcee.ai and an OpenAI-compatible API (Builders Program says credits work through that API), and OpenClaw doc uses `arcee/trinity-large-thinking` on the direct route. Docs conflict (multi-turn example even uses `arcee-ai/trinity-mini-thinking`). -> Test `GET https://api.arcee.ai/api/v1/models` with your key to see real IDs; fall back to OpenRouter.
- OpenRouter route: base `https://openrouter.ai/api/v1`, model `arcee-ai/trinity-large-thinking` (also `:free` variant; no limits listed; 262K ctx). Per-token paid price not shown in fetched page. Free variants of trinity-mini / large-preview historically existed on OpenRouter (`arcee-ai/trinity-mini:free`) - verify.
- Credits: Trinity Builders Program https://arcee.ai/trinity-builders-program - free API credits (<50M to >1B tokens requested; 90-day validity), apply online, rolling review with no timeline, not guaranteed. Conductor signup gives $20 credit (docs). No hackathon-specific credits found - ask the Arcee booth/sponsor for a code.

```python
from openai import OpenAI
client = OpenAI(api_key=os.environ["ARCEE_API_KEY"], base_url="https://api.arcee.ai/api/v1")
# print([m.id for m in client.models.list().data])   # discover real IDs first
resp = client.chat.completions.create(
    model="trinity-large-thinking",   # may be "arcee-ai/trinity-large-thinking" or other; check /models
    messages=[{"role":"system","content":"You are a planner. Output JSON steps with risk: low|high."},
              {"role":"user","content":"Book a table and email the host."}],
    tools=[...], tool_choice="auto")
# OpenRouter fallback: base_url="https://openrouter.ai/api/v1", model="arcee-ai/trinity-large-thinking" (or ":free"), key=OPENROUTER_API_KEY
```
Safe fallback if Trinity isn't hosted for you: `zai-org/glm-5.3-flash` ($0.15/$0.50) or `deepseek/deepseek-v4.1-flash` on the Arcee platform (OpenAI-compatible, confirmed hosted).

## Sources
- https://withpersona.com/lp/know-your-agent/
- https://withpersona.com/blog/building-know-your-agent-the-missing-identity-layer-for-agentic-commerce
- https://docs.withpersona.com/api-reference/inquiries/create-an-inquiry
- https://docs.withpersona.com/api-reference/inquiries/generate-a-one-time-link
- https://docs.withpersona.com/api-reference/inquiries/perform-simulate-actions
- https://docs.withpersona.com/docs/api-keys
- https://docs.withpersona.com/quickstart-embedded-flow
- https://docs.withpersona.com/embedded-flow-parameters
- https://docs.withpersona.com/tutorial-embedded-flow-precreate
- https://docs.withpersona.com/quickstart-webhooks
- https://docs.withpersona.com/integration-testing
- https://docs.withpersona.com/environments
- https://help.withpersona.com/articles/6I2kGhfPvSuUjYq4z6tpmB.md
- https://help.withpersona.com/articles/4D4JLmYPofDJuYQebxRFJ2.md
- https://arcee.ai/trinity
- https://arcee.ai/trinity-builders-program
- https://docs.arcee.ai/llms-full.txt
- https://openrouter.ai/models/arcee-ai/trinity-large-thinking
- https://docs.openclaw.ai/providers/arcee
