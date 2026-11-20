"""Source connectors (Airbyte agent SDK in real mode) + MOCK fallbacks reading the seed.
Adding a source = one line in REGISTRY. Real classes are wired in Phase 1 (airbyte-agent-sdk)."""
import json
import threading
from pathlib import Path
from typing import Protocol
from ..config import use_mock
from ..contracts import SourceItem

SEED = Path(__file__).resolve().parent.parent / "seed" / "demo_user.json"


def load_seed() -> dict:
    return json.loads(SEED.read_text())


class Faults:
    """Fault injection used by the local Firedrill harness (outage, flaky, restore)."""
    def __init__(self):
        self.down: set[str] = set()
        self.fail_next: dict[str, int] = {}
        self.lock = threading.Lock()

    def check(self, system: str):
        with self.lock:
            if system in self.down:
                raise ConnectionError(f"{system} unavailable")
            if self.fail_next.get(system, 0) > 0:
                self.fail_next[system] -= 1
                raise TimeoutError(f"{system} timed out")

    def reset(self):
        with self.lock:
            self.down.clear(); self.fail_next.clear()


faults = Faults()


class Connector(Protocol):
    name: str
    def fetch(self) -> list[SourceItem]: ...
    def execute(self, op: str, params: dict) -> dict: ...


class MockSource:
    """Reads one source's items out of the seed; records write 'effects' like a real API would."""
    writable_ops: set[str] = set()

    def __init__(self, name: str):
        self.name = name
        self.effects: list[dict] = []

    def fetch(self) -> list[SourceItem]:
        faults.check(self.name)
        return [SourceItem(**i) for i in load_seed()["items"] if i["source"] == self.name]

    def execute(self, op: str, params: dict) -> dict:
        faults.check(self.name)
        if op not in self.writable_ops:
            raise PermissionError(f"{self.name}: op '{op}' not supported (read-only connector)")
        self.effects.append({"op": op, **params})
        return {"ok": True, "op": op, "id": f"{self.name}-{len(self.effects)}"}

    def count(self, op: str) -> int:
        return sum(1 for e in self.effects if e["op"] == op)


class MockGmail(MockSource):
    writable_ops = {"messages.update", "labels.apply", "drafts.create", "messages.send", "drafts.send"}


class MockSlack(MockSource):
    writable_ops = {"messages.create", "drafts.create"}


class MockReadOnly(MockSource):
    writable_ops: set[str] = set()


MOCK = {"gmail": MockGmail, "slack": MockSlack, "notion": MockReadOnly, "github": MockReadOnly, "linear": MockSource}
_instances: dict[str, Connector] = {}


def make(name: str) -> Connector:
    # Real: airbyte_agent_sdk.connectors.<name> (Phase 1). Mock when keys missing.
    if name not in _instances:
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
    return [{"name": n, "mode": "mock" if use_mock(*keys) else "real", "writable": w} for n, (_, keys, w) in REGISTRY.items()]


def reset_mocks():
    _instances.clear()
    faults.reset()
    from .google_calendar_client import reset_calendar
    reset_calendar()


def is_real(system: str) -> bool:
    """True when this system runs against the real API (keys present and MOCK_MODE != true)."""
    if system in ("pay",):
        return False
    return not use_mock(*REGISTRY[system][1])
