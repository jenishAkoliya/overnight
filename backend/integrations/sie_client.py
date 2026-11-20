"""Superlinked SIE client with automatic tiering: hosted (SIE_API_KEY) -> local (SIE_URL) -> mock.
Hosted catalog differs from the OSS docs: no MiniLM/ms-marco/gliclass-small, so we use
  triage   fastino/GLiNER2.5-Decide (POST /v1/decisions)
  extract  urchade/gliner_multi-v2.1
  rerank   Qwen/Qwen3-Reranker-0.6B
  embed    BAAI/bge-m3 (1024d) via OpenAI-compatible /v1/embeddings
Treated as FREE sponsor access: on 402/401/403/quota/credit errors (or low balance) hosted is disabled for the
process, we fall back to local then mock, and the reason is surfaced (health + UI) so the user can decide."""
import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
import httpx
from ..bus import bus

HOSTED_URL = os.getenv("SIE_HOSTED_URL", "https://api.superlinked.com")
LOCAL_URL = os.getenv("SIE_URL", "http://localhost:8080")
DECIDE_MODEL = "fastino/GLiNER2.5-Decide"
NER_MODEL = "urchade/gliner_multi-v2.1"
RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"
EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIMS = 1024
GEN_MODEL = os.getenv("SIE_GEN_MODEL", "Qwen/Qwen3.5-4B")
MIN_AVAILABLE_CREDITS = int(os.getenv("SIE_MIN_CREDITS", "50000"))   # self-imposed floor: stop hosted below this


class QuotaError(Exception):
    pass


@dataclass
class TriageSignal:
    routine_prob: float            # predicate "routine" -> confidence
    kind: str                      # payment|scheduling|reply|archive|reminder|other
    stakes: str                    # trivial|moderate|high -> value
    entities: dict = field(default_factory=dict)
    via: str = "mock-sie"


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.calls = {"hosted": 0, "local": 0, "mock": 0}
        self.ops: dict[str, int] = {}
        self.credits = 0.0
        self.gen_calls = 0
        self.disabled_reason = ""
        self.balance = None
        self.errors: list[str] = []

    def add(self, tier: str, op: str, credits: float = 0.0):
        with self.lock:
            self.calls[tier] += 1
            self.ops[f"{tier}:{op}"] = self.ops.get(f"{tier}:{op}", 0) + 1
            self.credits += credits

    def snapshot(self) -> dict:
        with self.lock:
            return {"calls": dict(self.calls), "ops": dict(self.ops), "credits": round(self.credits, 2), "gen_calls": self.gen_calls,
                    "disabled_reason": self.disabled_reason, "balance": self.balance}


stats = Stats()
_state = {"force_mock": False, "hosted_disabled": False, "local_ok": None, "local_checked": 0.0}


def offline() -> bool:
    return os.getenv("OVERNIGHT_OFFLINE") == "1" or _state["force_mock"]


@contextmanager
def forced_mock():
    prev = _state["force_mock"]
    _state["force_mock"] = True
    try:
        yield
    finally:
        _state["force_mock"] = prev


def real_data_active() -> bool:
    """True when any REAL personal source (Gmail/Calendar/Slack...) feeds the pipeline."""
    try:
        from .airbyte_client import any_real_source
        return any_real_source()
    except Exception:
        return False


def hosted_available() -> bool:
    # Privacy: real inbox content is NOT sent to a hosted third party unless explicitly allowed.
    if real_data_active() and os.getenv("ALLOW_HOSTED_FOR_REAL_DATA") != "1":
        return False
    return bool(os.getenv("SIE_API_KEY")) and not _state["hosted_disabled"] and not offline() and os.getenv("MOCK_MODE") != "true"


def disable_hosted(reason: str):
    if not _state["hosted_disabled"]:
        _state["hosted_disabled"] = True
        stats.disabled_reason = reason
        bus.emit("SIE", "hosted_disabled", "Hosted Superlinked disabled - falling back to local/mock", why=reason + " (ask the user before re-enabling)")


def local_available() -> bool:
    if offline() or os.getenv("MOCK_MODE") == "true":
        return False
    if time.time() - _state["local_checked"] > 30:
        _state["local_checked"] = time.time()
        try:
            _state["local_ok"] = httpx.get(LOCAL_URL + "/readyz", timeout=0.6).status_code == 200
        except Exception:
            _state["local_ok"] = False
    return bool(_state["local_ok"])


class HTTPSIE:
    """OpenAI-style raw HTTP against hosted or local SIE (JSON)."""
    def __init__(self, tier: str):
        self.tier = tier
        self.base = HOSTED_URL if tier == "hosted" else LOCAL_URL
        self.http = httpx.Client(timeout=60)

    def _headers(self):
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.tier == "hosted":
            h["Authorization"] = f"Bearer {os.environ['SIE_API_KEY']}"
        return h

    def post(self, path: str, body: dict, op: str, retries: int = 4):
        for attempt in range(retries):
            r = self.http.post(self.base + path, headers=self._headers(), json=body)
            if r.status_code == 503 and attempt < retries - 1:      # PROVISIONING cold start
                time.sleep(min(float(r.headers.get("retry-after", 2)), 15)); continue
            txt = r.text.lower()
            if r.status_code in (401, 402, 403) or (r.status_code == 429 and re.search(r"quota|credit|balance|payment", txt)) or "insufficient" in txt:
                raise QuotaError(f"{r.status_code} {r.text[:120]}")
            r.raise_for_status()
            credits = float(r.headers.get("x-sie-credits-debited-decimal", 0) or 0)
            stats.add(self.tier, op, credits)
            return r.json()

    # ---- operations ----
    def decide(self, text: str) -> TriageSignal:
        j = self.post("/v1/decisions", {"model": DECIDE_MODEL, "input": text[:2000], "questions": [
            {"type": "predicate", "name": "routine", "instructions": "Is this a routine, low-risk task that can be done automatically without the person?"},
            {"type": "choice", "name": "kind", "instructions": "What kind of task is this?", "choices": [{"value": v} for v in ("payment", "scheduling", "reply", "archive", "reminder", "other")]},
            {"type": "score", "name": "stakes", "instructions": "How high are the stakes if this is handled wrongly?", "levels": [{"label": "trivial"}, {"label": "moderate"}, {"label": "high"}]}]}, "decide")
        a = {x["name"]: x for x in j["answers"]}
        lv = max(a["stakes"]["probabilities"], key=lambda p: p["probability"])["label"]
        return TriageSignal(float(a["routine"]["probability"]), a["kind"]["choice"], lv, via=f"sie-{self.tier}")

    def extract(self, text: str) -> dict:
        j = self.post(f"/v1/extract/{NER_MODEL}", {"items": [{"text": text[:2000]}], "params": {"labels": ["task", "deadline", "person", "amount", "organization"]}}, "extract")
        ents = (j.get("items") or [{}])[0].get("entities", []) if isinstance(j, dict) else []
        out = {}
        for e in sorted(ents, key=lambda e: -e.get("score", 0)):
            out.setdefault(e["label"], e["text"])
        m = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", out.get("amount", ""))
        if m:
            out["amount"] = float(m.group(1).replace(",", ""))
        else:
            out.pop("amount", None)
        return out

    def rerank(self, query: str, items: list[tuple[str, str]]) -> dict[str, float]:
        j = self.post(f"/v1/score/{RERANK_MODEL}", {"query": {"text": query}, "items": [{"id": i, "text": t[:500]} for i, t in items]}, "rerank")
        return {s["item_id"]: float(s["score"]) for s in j["scores"]}

    def embed(self, texts: list[str]) -> list[list[float]]:
        j = self.post("/v1/embeddings", {"model": EMBED_MODEL, "input": [t[:1500] for t in texts]}, "embed")
        return [d["embedding"] for d in j["data"]]

    def chat(self, messages: list[dict], max_tokens: int = 400) -> str:
        j = self.post("/v1/chat/completions", {"model": GEN_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}, "generate")
        with stats.lock:
            stats.gen_calls += 1
        return j["choices"][0]["message"]["content"] or ""

    def usage(self) -> dict | None:
        try:
            r = self.http.get(self.base + "/v1/usage", headers=self._headers(), timeout=10)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None


class MockSIE:
    """Keyword heuristics - deterministic, offline."""
    def decide(self, text: str, meta: dict | None = None) -> TriageSignal:
        meta = meta or {}
        s = text.lower()
        ent = {}
        m = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", text)
        if m:
            ent["amount"] = float(m.group(1).replace(",", ""))
        r = self._rules(s, meta, ent)
        stats.add("mock", "decide")
        return r

    @staticmethod
    def _rules(s, meta, ent):
        if meta.get("list_unsubscribe") or "unsubscribe" in s:
            return TriageSignal(0.97, "archive", "trivial", ent)
        if meta.get("receipt") or "receipt" in s:
            return TriageSignal(0.93, "archive", "trivial", ent)
        if any(k in s for k in ["pay now", "pay this invoice", "renews", "premium", "wire"]):
            return TriageSignal(0.15, "payment", "high", ent)
        if meta.get("recurring") or "recurring" in s:
            return TriageSignal(0.9, "scheduling", "trivial", ent)
        if meta.get("rsvp") or "rsvp" in s:
            return TriageSignal(0.84, "scheduling", "trivial", ent)
        if "check-in opens" in s or meta.get("flight"):
            return TriageSignal(0.88, "reminder", "trivial", ent)
        if "will send" in s and "by" in s:
            return TriageSignal(0.82, "reminder", "trivial", ent)
        if any(k in s for k in ["delete", "share", "grant access"]):
            return TriageSignal(0.3, "other", "high", ent)
        if "?" in s or "review" in s or "prd" in s:
            return TriageSignal(0.45, "reply", "moderate", ent)
        return TriageSignal(0.6, "other", "moderate", ent)

    def extract(self, text: str) -> dict:
        m = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", text)
        return {"amount": float(m.group(1).replace(",", ""))} if m else {}

    def rerank(self, query, items):
        return {}

    def embed(self, texts):
        return None


class Router:
    """hosted -> local -> mock, per call. Caches by text so identical items never cost twice."""
    def __init__(self):
        self.hosted, self.local, self.mock = HTTPSIE("hosted"), HTTPSIE("local"), MockSIE()
        self.cache: dict = {}
        self.lock = threading.Lock()

    def tier(self) -> str:
        return "hosted" if hosted_available() else "local" if local_available() else "mock"

    def _try(self, op: str, fn_name: str, *args):
        for name, impl, avail in (("hosted", self.hosted, hosted_available()), ("local", self.local, local_available())):
            if not avail:
                continue
            try:
                return getattr(impl, fn_name)(*args)
            except QuotaError as e:
                if name == "hosted":
                    disable_hosted(f"quota/credit/auth error: {e}")
            except Exception as e:
                with stats.lock:
                    stats.errors.append(f"{name}.{op}: {type(e).__name__}: {str(e)[:80]}")
        return None

    def signal(self, text: str, meta: dict | None = None):
        key = ("sig", hashlib.sha1(text.encode()).hexdigest(), self.tier())
        with self.lock:
            if key in self.cache:
                return self.cache[key]
        sig = self._try("decide", "decide", text)
        if sig is not None:
            ent = self._try("extract", "extract", text) or {}
            sig.entities = ent
        else:
            sig = self.mock.decide(text, meta)
        with self.lock:
            self.cache[key] = sig
        return sig

    def prefetch(self, texts: list[str]):
        """Warm the cache in parallel (hosted/local only)."""
        if self.tier() == "mock":
            return
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda t: self.signal(t), texts))

    def rerank(self, query: str, items: list[tuple[str, str]]) -> dict[str, float]:
        return self._try("rerank", "rerank", query, items) or {}

    def embed(self, texts: list[str]):
        return self._try("embed", "embed", texts)

    def chat(self, messages, max_tokens=400):
        if not hosted_available():
            return None
        try:
            return self.hosted.chat(messages, max_tokens)
        except QuotaError as e:
            disable_hosted(f"quota/credit/auth error: {e}")
        except Exception as e:
            with stats.lock:
                stats.errors.append(f"hosted.chat: {type(e).__name__}: {str(e)[:80]}")
        return None

    def health(self) -> dict:
        s = stats.snapshot()
        if hosted_available() and (s["balance"] is None or time.time() - _state.get("usage_ts", 0) > 60):
            u = self.hosted.usage(); _state["usage_ts"] = time.time()
            if u:
                stats.balance = int(float(u.get("available_decimal", u.get("available", 0))))
                if stats.balance < MIN_AVAILABLE_CREDITS:
                    disable_hosted(f"hosted credits low ({stats.balance} available < floor {MIN_AVAILABLE_CREDITS})")
                s = stats.snapshot()
        return {"tier": self.tier(), "hosted_key_present": bool(os.getenv("SIE_API_KEY")), "hosted_disabled": _state["hosted_disabled"],
                "local_up": bool(local_available()), "gen_model": GEN_MODEL, **s, "errors": stats.errors[-3:]}


_router = None


def get_sie() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router
