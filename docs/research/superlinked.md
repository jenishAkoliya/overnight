# Superlinked Inference Engine (SIE) - research for task-triage agent

Sources: https://github.com/superlinked/sie , https://superlinked.com/docs , https://superlinked.com/docs/reference/sdk , https://superlinked.com/docs/quickstart , https://superlinked.com/docs/extract , https://superlinked.com/docs/extract/relations , https://superlinked.com/docs/score , https://superlinked.com/docs/generate , https://superlinked.com/docs/migrate/openai-decisions , https://superlinked.com/docs/cloud/sie-relay , https://superlinked.com/docs/integrations/langchain , https://superlinked.com/blog/one-inference-stack-for-embeddings-reranking-extraction , https://docs.cognee.ai/setup-configuration/embedding-providers

(Items marked UNVERIFIED were not confirmed in docs I could fetch.)

## 1. What / install / auth
- Apache-2.0, self-hosted inference server: one API for embeddings, reranking, extraction (GLiNER etc.), decisions, OCR, and (separate GPU image) generation. 100+ models, loaded lazily on first request, LRU eviction.
- Run (port 8080):
  - CPU: `docker run -p 8080:8080 -v sie-hf-cache:/app/.cache/huggingface ghcr.io/superlinked/sie-server:latest-cpu-default` (add `--platform linux/amd64` on Apple Silicon; emulated, slow)
  - CPU + Transformers-5 models (GLiNER2.5-Decide etc.): `ghcr.io/superlinked/sie-server:latest-cpu-transformers5`
  - Native: `pip install "sie-server[local]" && sie-server serve` (Python 3.12; macOS Apple Silicon or Linux)
  - GPU: `ghcr.io/superlinked/sie-server:latest-cuda12-default`; generation: `latest-cuda12-sglang`
  - Health: `curl localhost:8080/readyz` -> ok. Mount the HF cache volume or models re-download.
- Python: `pip install sie-sdk` -> `from sie_sdk import SIEClient, SIEAsyncClient; from sie_sdk.types import Item`. TS: `@superlinked/sie-sdk`.
- Auth: local server needs none (decisions endpoint says local server "accepts any key"). Hosted: `SIEClient("https://api.superlinked.com", api_key=os.environ["SIE_API_KEY"])`; HTTP uses `Authorization: Bearer <key>`.
- Primary production target is x86 Linux + NVIDIA GPU; CPU image is "to try everything locally".

## 2. API
```python
from sie_sdk import SIEClient
from sie_sdk.types import Item
client = SIEClient("http://localhost:8080", timeout_s=30.0, api_key=None)  # raise timeout_s for first call!

client.encode(model, items, *, output_types=None, instruction=None, output_dtype=None, is_query=None, options=None, ...)
client.score(model, query, items, *, instruction=None, options=None, ...)       # query is an Item; returns ScoreResult
client.extract(model, items, *, labels=None, output_schema=None, instruction=None, options=None, ...)
client.generate(model, prompt, *, max_new_tokens, temperature, top_p, stop, ...)  # needs sglang image (GPU); early surface
```
All accept `wait_for_capacity=True`, `provision_timeout_s`, `gpu=`. Single Item -> single result; list -> list.

Examples (from README):
```python
r = client.encode("sentence-transformers/all-MiniLM-L6-v2", Item(text="Hello"))
r["dense"].shape            # (384,) numpy array
q = client.encode(model, Item(text="query"), is_query=True)   # for asymmetric models

s = client.score("cross-encoder/ms-marco-MiniLM-L-6-v2",
                 Item(text="What is ML?"),
                 [Item(text="ML learns from data.", id="a"), Item(text="Sunny.", id="b")])
s["scores"][0]   # {'item_id':'a','score':..,'rank':0}  (ms-marco scores are raw logits, can be negative; normalize w/ sigmoid)

e = client.extract("urchade/gliner_multi-v2.1", Item(text="Tim Cook is CEO of Apple."),
                   labels=["person","organization"])
e["entities"][0]  # {'text':'Tim Cook','label':'person','score':0.992,'start':0,'end':8}
```
ExtractResult fields: `entities, relations, classifications, objects, data, error`.
- Classification (GLiClass) via extract: `client.extract("knowledgator/gliclass-base-v1.0", Item(text=...), labels=[...], options={"overflow_policy":"truncate_text"})` -> `result["classifications"]` = list of `{label, score}`. 512-token limit shared by text + labels; ALWAYS set `overflow_policy=truncate_text`.
- GLiNER2 schema mode: `output_schema=` -> structured result in `data` (exact schema format UNVERIFIED; see https://superlinked.com/models/fastino-gliner2-large-v1).
- HTTP: `POST /v1/extract/{model}` (items + params.labels), `POST /v1/score/{model}` (server defaults msgpack; send `Accept: application/json`), `/v1/encode/{model}` similar.
- OpenAI-compatible: `POST /v1/embeddings` (works with OpenAI SDK / LangChain OpenAIEmbeddings); `POST /v1/chat/completions` (gateway, also sie-server dev convenience); `/v1/completions`, `/v1/responses` (gateway only); `/v1/audio/transcriptions`; `POST /v1/decisions` (OpenAI SDK `client.decisions.create`).
```bash
curl localhost:8080/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"sentence-transformers/all-MiniLM-L6-v2","input":"Hello world"}'
```
### Decisions API (best fit for value/confidence!)
```python
from openai import OpenAI
oa = OpenAI(api_key="x", base_url="http://localhost:8080/v1")
d = oa.decisions.create(   # may need raw httpx POST /v1/decisions if installed openai SDK lacks .decisions
    model="fastino/GLiNER2.5-Decide",
    input="Reminder: renew domain example.com by Friday, $12.",
    questions=[
      {"type":"predicate","name":"routine","instructions":"Is this a routine, low-risk task that can be done automatically?"},
      {"type":"choice","name":"kind","instructions":"What kind of task?","choices":[{"value":"payment"},{"value":"scheduling"},{"value":"reply"},{"value":"other"}]},
      {"type":"score","name":"stakes","instructions":"How high are the stakes?","levels":[{"label":"trivial"},{"label":"moderate"},{"label":"high"}]},
    ])
routine, kind, stakes = d.answers
routine.probability, kind.choice, stakes.score   # predicate -> probability; choice -> choice; score -> expected level + per-level probs
```
Text-only; up to 200 questions; response field names beyond these are inferred (check https://superlinked.com/docs/reference/api). Uses transformers5 image (`latest-cpu-transformers5` listed in docs). Catalog also lists `laya`, `laya-multilingual`, `gliner2.5-decide` as "Decide" models.

## 3. Models (HF IDs)
- Embeddings (CPU-friendly): `sentence-transformers/all-MiniLM-L6-v2` (~90MB, 384d, fastest); `BAAI/bge-m3` (~2.3GB, 1024d, dense+sparse+multivector; heavy on CPU); `Qwen/Qwen3-Embedding-0.6B`; `NovaSearch/stella_en_400M_v5`. Pick MiniLM for hackathon; bge-small-en-v1.5 likely in catalog (UNVERIFIED).
- Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2` (tiny, CPU OK); `BAAI/bge-reranker-v2-m3` (multilingual); `mixedbread-ai/mxbai-rerank-large-v2` (best English, heavy); `jinaai/jina-reranker-v2-base-multilingual`; `qwen3-reranker`. Cap candidates ~50-200.
- Entity/field extraction: `urchade/gliner_multi-v2.1` (docs default), `urchade/gliner_large-v2.1` (459M, English), `numind/NuNER_Zero`, `urchade/gliner_multi_pii-v1`, `fastino/gliner2-large-v1` (schema mode; catalog id gliner2), `jackboyla/glirel-large-v0` (relations; needs NER entities in item.metadata).
- Zero-shot classification: GLiClass `knowledgator/gliclass-small-v1.0` (fast), `gliclass-base-v1.0`, `gliclass-large-v1.0`; catalog also `gliclass-large-v3`, `gliclass-instruct-large`. No NLI cross-encoder named in docs; use GLiClass or Decide models.
- Decide: `fastino/GLiNER2.5-Decide` (typed predicate/choice/score with probabilities), `laya`.
- Generation: `Qwen/Qwen3-4B-Instruct-2507` (default), `Qwen/Qwen3-0.6B` via `latest-cuda12-sglang` image (GPU; CPU unconfirmed; macOS uses MLX on :8081). Larger: qwen3.6-27b etc. Blog says SIE deliberately does not do general text gen in the core; keep your frontier LLM for reasoning. Guard models: qwen3guard-gen-4b, granite-guardian-2b.

## 4. Task triage using only SIE
```python
import math
from sie_sdk import SIEClient
from sie_sdk.types import Item
c = SIEClient("http://localhost:8080", timeout_s=180)

NER="urchade/gliner_multi-v2.1"; CLS="knowledgator/gliclass-small-v1.0"; RR="cross-encoder/ms-marco-MiniLM-L-6-v2"
LABELS=["task","deadline","person","amount","organization"]
sig=lambda x:1/(1+math.exp(-x))

def triage(text):
    ent = c.extract(NER, Item(text=text), labels=LABELS)["entities"]
    fields = {}
    for e in sorted(ent, key=lambda e:-e["score"]):
        fields.setdefault(e["label"], e["text"])
    ext_conf = sum(e["score"] for e in ent)/len(ent) if ent else 0.0
    # zero-shot risk class
    cl = c.extract(CLS, Item(text=text),
                   labels=["routine low-risk task","needs human judgment","financial or irreversible action","not a task"],
                   options={"overflow_policy":"truncate_text"})["classifications"]
    p = {x["label"]:x["score"] for x in cl}
    # rerank vs prototype descriptions (relative signal only)
    protos=[Item(text="routine automatable task: reschedule, reminder, simple reply, confirm", id="auto"),
            Item(text="high stakes task: payment, legal, contract, sensitive, irreversible", id="risky")]
    sc = {s["item_id"]:sig(s["score"]) for s in c.score(RR, Item(text=text), protos)["scores"]}
    auto = 0.6*p.get("routine low-risk task",0) + 0.4*sc["auto"]
    risk = max(p.get("financial or irreversible action",0), p.get("needs human judgment",0), sc["risky"])
    amount_ok = True
    if "amount" in fields:
        try: amount_ok = float("".join(ch for ch in fields["amount"] if ch.isdigit() or ch==".")) < 50
        except ValueError: amount_ok = False
    confidence = auto * ext_conf**0.5 * (1-risk)
    decision = "auto" if (confidence>0.45 and amount_ok and "task" in fields and p.get("not a task",0)<0.3) else "ask_user"
    return dict(fields=fields, confidence=confidence, risk=risk, decision=decision)
```
Better option: replace the classifier+rerank block with one Decide call (predicate "routine", score "stakes") - calibrated probabilities. Tune thresholds on ~20 labeled examples; add hard rules (any money/external-send/delete -> ask).
Retrieval: `client.encode(EMB, [Item(text=t) for t in docs])` into numpy/Chroma/Qdrant; `encode(..., is_query=True)` for queries; then `score(RR, query, top50)`.

## 5. Integrations
- Official: LangChain (`pip install sie-langchain`: `SIEEmbeddings`, `SIEReranker`, `SIEExtractor`), LlamaIndex (`create_sie_extractor_tool`), Haystack, DSPy, CrewAI; vector DBs Chroma (`sie-chroma`), Qdrant, Weaviate, LanceDB.
- Cognee not mentioned by Superlinked, but Cognee supports any OpenAI-compatible endpoint, so SIE `/v1/embeddings` should work:
```
EMBEDDING_PROVIDER="custom"
EMBEDDING_MODEL="openai/sentence-transformers/all-MiniLM-L6-v2"   # litellm prefix required
EMBEDDING_ENDPOINT="http://localhost:8080/v1"                      # base URL only, no /embeddings
EMBEDDING_API_KEY="."
EMBEDDING_DIMENSIONS="384"                                         # MUST set explicitly (default 3072)
```
  Alternative: `EMBEDDING_PROVIDER="openai_compatible"` (no prefix, never sends `dimensions`, accepts base with/without /v1) - safer since SIE may reject the `dimensions` param (else set `litellm.drop_params=True`). Untested against SIE. Cognee's LLM still needs a real chat model (could point at SIE `/v1/chat/completions` only with GPU gen image).

## 6. Hosted / latency / gotchas
- Hosted: SIE Serverless (`https://api.superlinked.com`, Bearer key from Superlinked console, env `SIE_API_KEY`, per-call pricing); blog says new users get $20 credit. No hackathon-specific credits found. SDK >=0.10.0 for remote features. Cold start returns 503 PROVISIONING + Retry-After (SDK retries with wait_for_capacity=True); relay may answer meanwhile.
- Gotchas: models load lazily on FIRST request (seconds to minutes; docs say 10-120s typical, K8s scale-to-zero 3-7 min) -> warm up each model at startup (one dummy call) and raise `timeout_s` (default 30s will time out). Always mount the HF cache volume. bge-m3 ~2.3GB. Multiple models are loaded concurrently with LRU eviction; each model you add costs RAM. Warm MiniLM calls: milliseconds (docs); CPU latency for GLiNER/GLiClass/rerankers is roughly tens-hundreds of ms per short text on CPU (estimate, not documented). No CPU benchmarks published; CPU docs minimal. Transformers-5 models (GLiNER2.5-Decide) need the `-transformers5` image variant; one container image = one model-family bundle, so Decide models may need a second container on another port.
- Docs fetches were summarized by a small model; verify exact response keys (decisions, gliner2 `output_schema`) with a quick curl against your running server (`/docs` or https://superlinked.com/docs/reference/api).
