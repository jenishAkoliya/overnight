"""Cognee life-graph client. Mock = local JSON/in-memory store with keyword search.
Real (Phase 2): cognee==1.6.10 remember/recall/improve."""
import re
from datetime import datetime, timezone


class MockCognee:
    def __init__(self):
        self.docs: list[dict] = []

    def remember(self, text: str, dataset: str, node_set: list[str] | None = None, meta: dict | None = None):
        self.docs.append({"text": text, "dataset": dataset, "node_set": node_set or [], "meta": meta or {},
                          "ts": datetime.now(timezone.utc).isoformat()})

    def recall(self, query: str, dataset: str | None = None, k: int = 5) -> list[dict]:
        terms = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        scored = []
        for d in self.docs:
            if dataset and d["dataset"] != dataset:
                continue
            sc = sum(d["text"].lower().count(w) for w in terms)
            if sc:
                scored.append((sc, d))
        return [d for _, d in sorted(scored, key=lambda x: -x[0])[:k]]

    def reset(self):
        self.docs.clear()


_c = None


def get_cognee():
    global _c
    if _c is None:
        _c = MockCognee()
    return _c
