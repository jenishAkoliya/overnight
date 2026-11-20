"""Runtime-patchable config + virtual clock.
All tunables live in YAML/prompt files so the SRE agent can patch them without touching code:
  policy_rules.yaml, guards_rules.yaml, runtime_config.yaml, prompts/*.txt
`use_config_dir()` redirects reads to a staging copy (used by SRE validation and simulations)."""
import contextlib
import threading
import time
from pathlib import Path
import yaml

LIVE_DIR = Path(__file__).resolve().parent
PATCHABLE = ["policy_rules.yaml", "guards_rules.yaml", "runtime_config.yaml", "prompts/planner_system.txt", "prompts/triage_hints.txt"]
_dir = LIVE_DIR
_lock = threading.RLock()


def config_dir() -> Path:
    return _dir


@contextlib.contextmanager
def use_config_dir(path: Path):
    global _dir
    with _lock:
        prev, _dir = _dir, Path(path)
        try:
            yield
        finally:
            _dir = prev


def load(name: str) -> dict:
    return yaml.safe_load((_dir / name).read_text())


def read_text(name: str) -> str:
    p = _dir / name
    return p.read_text() if p.exists() else ""


def dump_yaml(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, width=110, allow_unicode=True)


# ---- clock (virtual in simulations so backoff doesn't slow tests) ----
class Clock:
    def __init__(self):
        self.virtual = False
        self.offset = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return time.monotonic() + self.offset

    def sleep(self, s: float):
        self.sleeps.append(s)
        if self.virtual:
            self.offset += s
        else:
            time.sleep(s)


clock = Clock()
