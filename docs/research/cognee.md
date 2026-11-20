# Cognee research (verified 2026-11-20)

Sources: PyPI/pip install in /tmp venv (introspected real signatures), https://github.com/topoteretes/cognee, https://docs.cognee.ai (llms.txt shards), pages cited inline.

## 1. Version + API
- Latest PyPI: **cognee 1.6.10**, `requires-python >=3.10,<3.15` (tested on 3.13). Installed fine with plain `pip install cognee` (~few minutes, heavy deps).
- Everything is **async** (`await`/`asyncio.run`) except `cognee.start_ui` (sync). v1.0 "memory" API = remember/recall/improve/forget; legacy pipeline = add/cognify/search/memify (still present).

Real signatures (introspected):
```
await cognee.remember(data, dataset_name="main_dataset", *, dataset_id=None, session_id=None, chunk_size=None, chunker=None,
    custom_prompt=None, run_in_background=False, self_improvement=True, session_ids=None, dry_run=False, raise_on_error=True,
    **kw)   # kw: graph_model, extractor("llm"|"gliner_demo"), node_set, incremental_loading, data_per_batch, user, llm_config, embedding_config, ...
await cognee.recall(query_text, query_type=None, *, datasets=None, dataset_ids=None, top_k=15, auto_route=True, scope=None,
    system_prompt=None, node_name=None, node_name_filter_operator="OR", only_context=False, session_id=None,
    context_profile="qa", feedback_influence=0.0, response_model=None, verbose=False, retriever_specific_config=None, ...) -> list[entries]
await cognee.improve(dataset="main_dataset", *, run_in_background=False, node_name=None, session_ids=None,
    build_global_context_index=None, build_truth_subspace=False, review_conflicts=None, feedback_alpha=...)
await cognee.forget(*, data_id=None, dataset=None, dataset_id=None, everything=False, memory_only=False, clean_history=False, user=None)
await cognee.add(data, dataset_name="main_dataset", user=None, node_set=None, ..., importance_weight=0.5, incremental_loading=True, data_per_batch=20, run_in_background=False, ...)
await cognee.cognify(datasets=None, user=None, graph_model=KnowledgeGraph, chunker=None, chunk_size=None, chunks_per_batch=None,
    config=None, run_in_background=False, incremental_loading=True, custom_prompt=None, data_per_batch=20, raise_on_error=True,
    extractor=None, ontology_file_path=None, summary_method=None, ...)
await cognee.search(query_text, query_type=SearchType.HYBRID_COMPLETION, user=None, datasets=None, dataset_ids=None, top_k=15,
    node_name=None, only_context=False, session_id=None, feedback_influence=0.0, ...)
await cognee.memify(extraction_tasks=None, enrichment_tasks=None, data=None, dataset="main_dataset", node_name=None, ...)
await cognee.serve(url=None, api_key=None)   # connect SDK to Cognee Cloud / remote instance
cognee.start_ui(pid_callback, port=3000, ...)  # sync
cognee.session.get_session(session_id=..., last_n=N); cognee.session.add_feedback(session_id=, qa_id=, feedback_text=, feedback_score=1..5); delete_feedback(...)
```
What each does:
- **remember** = add + cognify (+ improve) in one call. No `session_id` -> permanent graph memory (blocking unless `run_in_background=True`). With `session_id` -> writes raw text to session cache only, returns fast (`status="session_stored"`), no LLM extraction; bridges to graph via background improve if `self_improvement=True`. (docs: https://docs.cognee.ai/core-concepts/main-operations/remember.md)
- **recall** = query. Auto-routes (rule-based, not LLM) when `query_type` unset: quoted phrase->CHUNKS_LEXICAL, "how many"->BROAD, "in/on <absolute date>"->TEMPORAL, else HYBRID_COMPLETION. With `session_id` it checks session QA first then graph. (recall.md)
- **improve** = enrich graph; with `session_ids` bridges session QA/traces/feedback into permanent graph (feedback weights -> persist QA -> traces -> distill -> update user preferences -> conflict review). (improve.md)
- **forget** = delete item/dataset/everything; `memory_only=True` wipes graph+vectors but keeps raw data (use to re-cognify). 
- **add/cognify/search/memify** = legacy pipeline: add ingests, cognify builds graph (this is where LLM cost is), search queries with explicit SearchType, memify runs custom enrichment tasks.

## 2. What to use for what
| Need | Use |
|---|---|
| (a) emails/events as documents | `remember(text, dataset_name="gmail"/"calendar"/"slack", node_set=["email","2026-11-20"], self_improvement=False)`. One doc per email/event, text prefixed with a header (From/To/Date/Subject). Batch: pass a list. Or `add(...)` many then one `cognify(datasets=[...])` (cheaper to batch). `incremental_loading=True` (default) skips already-processed items -> safe for repeated Airbyte syncs. |
| (b) user-given tasks & preferences (long-term) | Option 1: `remember("TASK: ...", dataset_name="user_memory", node_set=["tasks"], graph_model=LifeGraph)`; Option 2 (fast/deterministic, no LLM): build `Task`/`Preference` DataPoints and `add_data_points([...])` (from `cognee.tasks.storage`). Preferences also get learned via `improve(session_ids=...)` ("update user preferences" stage). |
| (c) short-term | `remember(text, session_id="today")` and `recall(q, session_id="today")`; cache backend sqlite default (also redis/postgres/fs), TTL 7d (`SESSION_TTL_SECONDS`). Prior Q&A turns are included in later prompts. |
| (d) learning from feedback/failures | `recall(..., session_id=s)` -> `cognee.session.get_session(session_id=s, last_n=5)` -> `qa_id` -> `cognee.session.add_feedback(session_id, qa_id, feedback_score=1-5, feedback_text=...)` -> `await cognee.improve(dataset=..., session_ids=[s])`. Then query with `feedback_influence=0.3` (default 0.0 = off; or env `DEFAULT_FEEDBACK_INFLUENCE`). Per-user: `PERSONALIZATION_ENABLED=true`. Failures: write `TraceEntry` / `FeedbackEntry` typed entries via remember (they don't auto-trigger improve). (https://docs.cognee.ai/guides/feedback-system.md)

SearchType enum (1.6.10): SUMMARIES, CHUNKS, RAG_COMPLETION, HYBRID_COMPLETION, HYBRID_COMPLETION_DECOMPOSITION, GRAPH_COMPLETION, GRAPH_COMPLETION_DECOMPOSITION, GRAPH_SUMMARY_COMPLETION, CYPHER, NATURAL_LANGUAGE, GRAPH_COMPLETION_COT, GRAPH_COMPLETION_CONTEXT_EXTENSION, FEELING_LUCKY, TEMPORAL, CODING_RULES, CHUNKS_LEXICAL, AGENTIC_COMPLETION, CODE, GRAPH_REPORT, BROAD, SKILLS, TRIPLET_COMPLETION(deprecated). **INSIGHTS is NOT in the Python enum** (MCP-only).
- "What does the user need to do tomorrow?": best = **GRAPH_COMPLETION** (or HYBRID_COMPLETION, the default) with the date made explicit in the query text ("Tasks, promises and deadlines due 2026-11-21"), optionally `response_model=` a pydantic list for structured output; or **CHUNKS**/`only_context=True` to get raw context and let your small model triage (cheapest, no Cognee LLM call). TEMPORAL only works with absolute dates; "tomorrow"/"today" yields no time window and falls back to hybrid. So resolve "tomorrow" to an ISO date yourself.

## 3. Custom graph model (DataPoint)
Pass to `remember(graph_model=...)` or `cognify(graph_model=...)`; the root model is what the LLM fills (docs: https://docs.cognee.ai/guides/custom-graph-model.md, custom-data-models.md). `from cognee.low_level import DataPoint, Edge, FromIdentity`.
```python
from typing import Optional
from cognee.low_level import DataPoint

class Person(DataPoint):
    name: str
    email: Optional[str] = None
    metadata: dict = {"index_fields": ["name"], "identity_fields": ["name"]}  # embed name; dedupe by name

class Task(DataPoint):
    title: str
    due_date: Optional[str] = None        # ISO "YYYY-MM-DD" -- keep as str, instruct LLM in prompt
    status: str = "open"
    source: Optional[str] = None          # email/slack/user
    owner: Optional[Person] = None
    requested_by: Optional[Person] = None
    metadata: dict = {"index_fields": ["title"], "identity_fields": ["title"]}

class Promise(Task):                      # something the user promised someone
    promised_to: Optional[Person] = None
class Obligation(Task):
    consequence: Optional[str] = None
class Event(DataPoint):
    title: str
    start: Optional[str] = None
    attendees: list[Person] = []
    metadata: dict = {"index_fields": ["title"]}

class LifeGraph(DataPoint):               # ROOT passed as graph_model
    people: list[Person] = []
    tasks: list[Task] = []
    promises: list[Promise] = []
    obligations: list[Obligation] = []
    events: list[Event] = []
    metadata: dict = {"index_fields": []}
```
Notes: field name becomes edge label; docs' examples use `SkipValidation[Any]` for DataPoint-to-DataPoint refs in manual `add_data_points`. Keep the schema flat/simple (subclassing may be flaky; if so make Promise/Obligation separate classes). Classes must be importable in the process doing recall. JSON-schema dict also accepted as graph_model. Use `custom_prompt="Extract tasks, promises the user made, obligations, with ISO due dates; today is 2026-11-20"` to steer. Ontology (OWL) alternative: `cognify(ontology_file_path=...)` (https://docs.cognee.ai/guides/ontology-support.md).

## 4. Configuration (env vars or `.env`)
- LLM Anthropic (https://docs.cognee.ai/setup-configuration/llm-providers.md): `LLM_PROVIDER="anthropic"`, `LLM_MODEL="anthropic/claude-sonnet-5"` (use any current model id, e.g. a Haiku for cheap), `LLM_API_KEY="sk-ant-..."`. `LLM_ENDPOINT` ignored for Anthropic. Needs a Console API key (not OAuth).
- OpenAI-compatible LLM: `LLM_PROVIDER="custom"`, `LLM_MODEL="openai/<id>"`, `LLM_ENDPOINT=https://host/v1`, `LLM_API_KEY=...`. Default structured-output backend `litellm_native` (`STRUCTURED_OUTPUT_FRAMEWORK=instructor` optional).
- **Embeddings -- YES, a custom OpenAI-compatible endpoint works** (https://docs.cognee.ai/setup-configuration/embedding-providers.md). Anthropic has no embeddings, so you MUST set embeddings separately (otherwise it defaults to OpenAI and needs an OpenAI key). For Superlinked SIE at localhost:8080 use the direct-SDK provider:
```
EMBEDDING_PROVIDER="openai_compatible"
EMBEDDING_MODEL="<model id the server expects>"
EMBEDDING_ENDPOINT="http://localhost:8080/v1"     # it strips a trailing /embeddings and adds /v1 if missing, so ".../v1/embeddings" also OK
EMBEDDING_API_KEY="no-key-required"
EMBEDDING_DIMENSIONS="<exact vector size of that model>"   # MUST match; mismatch errors; fixing needs prune_system + re-ingest
```
  If instead you use `EMBEDDING_PROVIDER="custom"` (LiteLLM routed), do NOT include `/embeddings` in the URL (404) and set `EMBEDDING_API_KEY` explicitly ("."). Server must implement POST /v1/embeddings with OpenAI schema. Offline fallback: `EMBEDDING_PROVIDER=fastembed` (`pip install 'cognee[fastembed]'`, e.g. all-MiniLM-L6-v2, dim 384).
- Single-user/local: `ENABLE_BACKEND_ACCESS_CONTROL=false` (default is multi-tenant w/ auth; for a hackathon set false).
- Default local stores (verified in installed 1.6.10): relational **SQLite**, vector **LanceDB**, graph **Ladybug** (Kuzu successor; `graph_database_provider` default "ladybug"); NetworkX also installed; Neo4j/Postgres/pgvector optional. Data under `<site-packages>/cognee/.cognee_system` (override `SYSTEM_ROOT_DIRECTORY`, `DATA_ROOT_DIRECTORY`). Session cache default sqlite.
- Cognee Cloud: sign up https://platform.cognee.ai/ ; SDK: `client = await cognee.serve(url=..., api_key=...)` then same remember/recall API (https://docs.cognee.ai/cognee-cloud/connections/cloud-sdk.md; I could not confirm env var names/pricing).
- UI: `cognee-cli -ui` (needs Node/npm; UI :3000, API :8000). MCP: Docker `docker compose --profile ui --profile mcp up` (MCP :8001); docs https://docs.cognee.ai/cognee-mcp/mcp-overview.md. CLI: `cognee-cli remember "..." -d ds`, `cognee-cli recall "..." -d ds`.

## 5. Temporal + scoping
- Timestamp extraction is built into default pipeline: dates become `Timestamp` nodes (`time_at/time_until` epoch ms). `SearchType.TEMPORAL` converts the question to a UTC window via LLM. **`temporal_cognify=True` is deprecated/ignored since >1.6.2.** Relative terms ("tomorrow", "today", "last year") produce no window -> falls back to hybrid. So: embed absolute dates in stored text and in queries (https://docs.cognee.ai/guides/temporal-knowledge-graph.md). Most robust for your use: store `due_date`/`start` as explicit fields in your custom model and/or keep your own date filter.
- Datasets = hard containers (separate per source: "gmail", "calendar", "slack", "user_tasks"); `recall(datasets=[...])`. Node sets = tags within a dataset: `remember(..., node_set=["gmail"])`, filter `recall(node_name=["gmail"])` (retrieval filter, not isolation; entities can bridge sets). Pages: core-concepts/further-concepts/datasets.md, node-sets.md.

## 6. Minimal end-to-end (untested against live LLM; signatures verified)
```python
import os, asyncio, datetime as dt
os.environ.update(
  LLM_PROVIDER="anthropic", LLM_MODEL="anthropic/claude-sonnet-5", LLM_API_KEY=os.environ["ANTHROPIC_API_KEY"],
  EMBEDDING_PROVIDER="openai_compatible", EMBEDDING_MODEL="<sie-model>", EMBEDDING_ENDPOINT="http://localhost:8080/v1",
  EMBEDDING_API_KEY="x", EMBEDDING_DIMENSIONS="768", ENABLE_BACKEND_ACCESS_CONTROL="false")
import cognee
from cognee import SearchType
# from models import LifeGraph   (section 3)

PROMPT = "Extract people, tasks, promises the user made, obligations, events. Use ISO dates. Today is 2026-11-20."

async def ingest_email(e):  # e: dict from Airbyte
    doc = f"EMAIL id={e['id']}\nFrom: {e['from']}\nTo: {e['to']}\nDate: {e['date']}\nSubject: {e['subject']}\n\n{e['body']}"
    await cognee.remember(doc, dataset_name="gmail", node_set=["email"], graph_model=LifeGraph,
                          custom_prompt=PROMPT, self_improvement=False)

async def add_user_task(text):
    await cognee.remember(f"USER TASK (explicit, high priority): {text}", dataset_name="user_memory",
                          node_set=["user_tasks"], graph_model=LifeGraph, custom_prompt=PROMPT, self_improvement=False)

async def tomorrow(sid="triage-2026-11-20"):
    d = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    ctx = await cognee.recall(f"List every task, promise, obligation and event due or happening on {d}, plus overdue open items.",
                              query_type=SearchType.GRAPH_COMPLETION, datasets=["gmail","user_memory"],
                              session_id=sid, top_k=30)
    return ctx   # or only_context=True to feed raw context to a small triage model

async def feedback(sid, score):
    last = (await cognee.session.get_session(session_id=sid, last_n=1))[-1]
    await cognee.session.add_feedback(session_id=sid, qa_id=last.qa_id, feedback_score=score)
    await cognee.improve(dataset="user_memory", session_ids=[sid])

asyncio.run(tomorrow())
```

## 7. Gotchas
- Python 3.10-3.14 (3.13 worked). Install is large; do it before demo day.
- **Everything async.** In notebooks use `await`; in scripts `asyncio.run`. Don't call from sync handlers without a loop.
- **Latency/cost:** `remember`/`cognify` makes multiple LLM calls per chunk (graph extraction + summaries; `summary_method="from_extraction"` cuts calls) -> seconds to tens of seconds per doc. Batch docs in lists, use `run_in_background=True`, `self_improvement=False` during bulk ingest, pre-ingest before the demo, and use a small/fast model (Haiku) for extraction. Gliner extractor (`extractor="gliner"`) is LLM-free but generic (no custom schema benefit).
- Embedding dims must match exactly; changing model = `cognee.prune.prune_system()` + re-ingest. Collections fixed at first write.
- `ENABLE_BACKEND_ACCESS_CONTROL` default true -> auth required/multi-tenant; set false locally.
- Relative dates ("tomorrow") are not resolved by TEMPORAL; give ISO dates. Custom model classes must be imported where recall runs.
- Session without cache backend: plain text silently not stored (warning); typed entries raise.
- Docs/search results sometimes show different param names (`dataset` vs `dataset_id` in forget); trust installed signatures above. `cognee.session` is a lazily-resolved attribute (accessible as `cognee.session.get_session`), not importable as `import cognee.session`.
- I did not run a live LLM call (no keys), so end-to-end code is signature-checked only.
