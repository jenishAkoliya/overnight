"""Superlinked SIE client. Interface: signal(text) -> TriageSignal. Mock = keyword heuristics.
Real (Phase 3): Decisions API fastino/GLiNER2.5-Decide, fallback GLiNER+GLiClass+reranker."""
import re
from dataclasses import dataclass, field
from ..config import use_mock


@dataclass
class TriageSignal:
    routine_prob: float            # predicate "routine" -> confidence
    kind: str                      # payment|scheduling|reply|archive|reminder|other
    stakes: str                    # trivial|moderate|high -> value
    entities: dict = field(default_factory=dict)
    via: str = "mock-sie"


class MockSIE:
    calls = 0

    def signal(self, text: str, meta: dict | None = None) -> TriageSignal:
        MockSIE.calls += 1
        meta = meta or {}
        s = text.lower()
        ent = {}
        m = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", text)
        if m:
            ent["amount"] = float(m.group(1).replace(",", ""))
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


_sie = None


def get_sie():
    global _sie
    if _sie is None:
        _sie = MockSIE()  # Phase 3: RealSIE when not use_mock("SIE_URL")
    return _sie
