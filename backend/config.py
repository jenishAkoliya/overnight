"""Central config: env, mock-mode auto-selection, demo clock."""
import os
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo(os.getenv("USER_TZ", "America/Los_Angeles"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MOCK_MODE = os.getenv("MOCK_MODE", "auto")  # auto | true | false
# Demo clock: "tonight" in the mock world. Seed data is generated relative to it.
DEMO_TONIGHT = os.getenv("DEMO_TONIGHT", "2026-12-06T21:00:00-08:00")


def tonight() -> datetime:
    return datetime.fromisoformat(DEMO_TONIGHT).astimezone(TZ)


def tomorrow() -> date:
    return (tonight() + timedelta(days=1)).date()


def has_keys(*names: str) -> bool:
    return all(os.getenv(n) for n in names)


def use_mock(*key_names: str) -> bool:
    """MOCK_MODE=true -> always mock; false -> never; auto -> mock when keys missing."""
    if MOCK_MODE == "true":
        return True
    if MOCK_MODE == "false":
        return False
    return not has_keys(*key_names)
