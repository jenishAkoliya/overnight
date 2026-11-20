"""Source connectors (Airbyte agent SDK in real mode) + MOCK fallbacks reading the seed.
Adding a source = one line in REGISTRY. Real classes are wired in Phase 1 (airbyte-agent-sdk).
Also hosts the FaultInjector + effects log used by the local Firedrill-style harness."""
import json
import threading
from pathlib import Path
from typing import Protocol
from .. import runtime
from ..config import use_mock_sources
from ..contracts import SourceItem

SEED = Path(__file__).resolve().parent.parent / "seed" / "demo_user.json"
seed_override: dict | None = None   # {"base": "none"|"full", "items": [...]} set by simulations


def load_seed() -> dict:
    return json.loads(SEED.read_text())


def seed_items() -> list[dict]:
    items = load_seed()["items"]
    if seed_override is not None:
        items = (items if seed_override.get("base") == "full" else []) + seed_override.get("items", [])
    return items


# ---------------- errors a real API can return ----------------
class ServiceUnavailable(ConnectionError):
    """503 dependency_unavailable"""


class RateLimited(Exception):
    """429 with Retry-After"""
    def __init__(self, msg, retry_after: float = 1.0):
        super().__init__(msg)
        self.retry_after = retry_after


class AuthExpired(PermissionError):
    """401 token expired / revoked"""


# ---------------- effects log (what actually happened to the outside world) ----------------
class EffectsLog:
    def __init__(self):
        self.entries: list[dict] = []
        self.lock = threading.Lock()

    def add(self, service, op, args, key, ok, error=None, deduped=False) -> dict:
        with self.lock:
            e = {"seq": len(self.entries) + 1, "service": service, "op": op, "args": {k: (v if not isinstance(v, str) or len(v) <= 80 else v[:80] + "...") for k, v in (args or {}).items() if k not in ("idempotency_key", "body", "raw", "text")},
                 "idempotency_key": key, "ok": ok, "error": error, "deduped": deduped, "t": round(runtime.clock.now(), 3)}
            self.entries.append(e)
            return e

    def ok(self, service=None, op=None, dedupe=True):
        return [e for e in self.entries if e["ok"] and (not dedupe or not e["deduped"])
                and (service is None or e["service"] == service) and (op is None or e["op"] == op)]

    def attempts(self, service=None, op=None):
        return [e for e in self.entries if (service is None or e["service"] == service) and (op is None or e["op"] == op)]

    def clear(self):
        with self.lock:
            self.entries.clear()


effects = EffectsLog()


class FaultInjector:
    """Follows scenario events: dependency_unavailable/restored, rate_limit burst, auth_expired.
    Counts calls per service (writes only unless include_reads) and virtual time since start."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.events: list[dict] = []
        self.calls: dict[str, int] = {}
        self.down: dict[str, float] = {}       # service -> virtual time it went down
        self.auth: set[str] = set()
        self.rl: dict[str, dict] = {}
        self.fired: set[int] = set()
        self.t0 = runtime.clock.now()

    def configure(self, events: list[dict]):
        self.reset()
        self.events = [e for e in events if e["type"] in ("dependency_unavailable", "dependency_restored", "rate_limit", "auth_expired")]

    def _ms(self) -> float:
        return (runtime.clock.now() - self.t0) * 1000

    def check(self, service: str, op: str, is_read: bool = False):
        n = self.calls.get(service, 0)
        for i, e in enumerate(self.events):
            if e.get("service") != service or (is_read and not e.get("include_reads")) :
                continue
            trig = n >= e.get("after_calls", 0) if "after_ms" not in e else self._ms() >= e["after_ms"]
            if i in self.fired or not trig:
                continue
            self.fired.add(i)
            t = e["type"]
            if t == "dependency_unavailable":
                self.down[service] = self._ms()
            elif t == "dependency_restored":
                self.down.pop(service, None); self.auth.discard(service)
            elif t == "auth_expired":
                self.auth.add(service)
            elif t == "rate_limit":
                self.rl[service] = {"remaining": e.get("count", 1), "until": 0.0, "retry_after": e.get("retry_after_s", 1.0)}
        # restoration by virtual time while down
        for i, e in enumerate(self.events):
            if e["type"] == "dependency_restored" and e.get("service") == service and service in self.down and "after_ms" in e and self._ms() >= e["after_ms"]:
                self.down.pop(service, None)
        if not is_read:
            self.calls[service] = n + 1
        if service in self.auth:
            raise AuthExpired(f"{service}: 401 token expired")
        if service in self.down:
            raise ServiceUnavailable(f"{service}: 503 dependency_unavailable")
        rl = self.rl.get(service)
        if rl and not is_read:
            now = runtime.clock.now()
            if rl["remaining"] > 0 or now < rl["until"]:
                if now >= rl["until"]:
                    rl["remaining"] -= 1
                    rl["until"] = now + rl["retry_after"]
                raise RateLimited(f"{service}: 429 rate limited", retry_after=max(rl["until"] - now, 0.0))


faults = FaultInjector()


class Connector(Protocol):
    name: str
    def fetch(self) -> list[SourceItem]: ...
    def execute(self, op: str, params: dict) -> dict: ...


class MockSource:
    """Reads one source's items out of the seed; records write 'effects' like a real API would.
    Honors idempotency keys server-side (like Stripe): same key twice -> one change."""
    writable_ops: set[str] = set()

    def __init__(self, name: str):
        self.name = name
        self.state: list[dict] = []
        self.keys: dict[str, str] = {}

    @property
    def effects(self):  # back-compat for tests: successful, non-deduped writes
        return [{"op": e["op"], **e["args"]} for e in effects.ok(self.name)]

    def fetch(self) -> list[SourceItem]:
        faults.check(self.name, "list", is_read=True)
        return [SourceItem(**i) for i in seed_items() if i["source"] == self.name]

    def execute(self, op: str, params: dict) -> dict:
        key = params.get("idempotency_key", "")
        try:
            faults.check(self.name, op)
            if op not in self.writable_ops:
                raise PermissionError(f"{self.name}: op '{op}' not supported (read-only connector)")
        except Exception as e:
            effects.add(self.name, op, params, key, False, error=f"{type(e).__name__}: {e}")
            raise
        if key and key in self.keys:
            effects.add(self.name, op, params, key, True, deduped=True)
            return {"ok": True, "op": op, "id": self.keys[key], "deduped": True}
        rid = f"{self.name}-{len(self.state) + 1}"
        self.state.append({"op": op, **params})
        if key:
            self.keys[key] = rid
        effects.add(self.name, op, params, key, True)
        return {"ok": True, "op": op, "id": rid}

    def count(self, op: str) -> int:
        return len(effects.ok(self.name, op))


class MockGmail(MockSource):
    writable_ops = {"messages.update", "labels.apply", "drafts.create", "messages.send", "drafts.send"}


class MockSlack(MockSource):
    writable_ops = {"messages.create", "drafts.create", "messages.delete"}


class MockReadOnly(MockSource):
    writable_ops: set[str] = set()


MOCK = {"gmail": MockGmail, "slack": MockSlack, "notion": MockReadOnly, "github": MockReadOnly, "linear": MockSource}
_instances: dict[str, Connector] = {}


def make(name: str) -> Connector:
    # Real (airbyte-agent-sdk / Google APIs) when keys exist and sources aren't forced to mock; else mock.
    if name not in _instances:
        if name == "gmail" and not use_mock_sources(*REGISTRY["gmail"][1]):
            from .real_sources import RealGmail
            _instances[name] = RealGmail()
        elif name == "slack" and not use_mock_sources(*REGISTRY["slack"][1]):
            from .real_sources import RealSlack
            _instances[name] = RealSlack()
        else:
            _instances[name] = MOCK.get(name, MockSource)(name)
    return _instances[name]


# ---- registry: adding a source = one line --------------------------------
REGISTRY: dict[str, tuple] = {
    # name: (factory, env keys needed for real mode, writable?)
    "gmail":    (make, ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"), True),
    "calendar": (None,  ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"), True),  # google_calendar_client
    "slack":    (make, ("SLACK_TOKEN",), True),
    "notion":   (make, ("NOTION_TOKEN",), False),
    "github":   (make, ("GITHUB_TOKEN",), False),
    "linear":   (make, ("LINEAR_API_KEY",), True),
}


def get_connector(name: str) -> Connector:
    if name == "calendar":
        from .google_calendar_client import get_calendar
        return get_calendar()
    return REGISTRY[name][0](name)


def connectors_status() -> list[dict]:
    return [{"name": n, "mode": "mock" if use_mock_sources(*keys) else "real", "writable": w} for n, (_, keys, w) in REGISTRY.items()]


def reset_mocks():
    _instances.clear()
    faults.reset()
    effects.clear()
    from .google_calendar_client import reset_calendar
    reset_calendar()


def is_real(system: str) -> bool:
    """True when this system runs against the real API (keys present and MOCK_MODE != true)."""
    if system in ("pay",):
        return False
    return not use_mock_sources(*REGISTRY[system][1])


def any_real_source() -> bool:
    return any(not use_mock_sources(*keys) for _, keys, _w in REGISTRY.values())
