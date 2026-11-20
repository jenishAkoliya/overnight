from .. import config
from ..bus import bus
from ..contracts import SourceItem
from ..integrations.airbyte_client import REGISTRY, get_connector, connectors_status


class IngestAgent:
    errors: dict[str, str] = {}   # source -> last fetch error (surfaced in /health, UI and readiness)

    def run(self) -> list[SourceItem]:
        items: list[SourceItem] = []
        IngestAgent.errors = {}
        for name in REGISTRY:
            if config.REAL_CLOCK and next(c["mode"] for c in connectors_status() if c["name"] == name) == "mock":
                bus.emit("IngestAgent", "skipped", f"{name}: mock source excluded in live mode", why="no credentials; demo data is never mixed into a real run")
                continue
            with bus.timed("IngestAgent", "fetch", f"{name}: fetching") as _:
                try:
                    conn = get_connector(name)
                    got = conn.fetch()
                    if hasattr(conn, "known_contacts"):
                        from .memory import memory
                        memory.known_contacts |= conn.known_contacts()
                except Exception as e:  # outage: continue with other sources, report honestly
                    IngestAgent.errors[name] = str(e)[:200]
                    bus.emit("IngestAgent", "fetch_failed", f"{name} unavailable: {e}", why="continuing with other sources")
                    continue
            mode = next(c["mode"] for c in connectors_status() if c["name"] == name)
            bus.emit("IngestAgent", "fetched", f"{name}: {len(got)} items ({mode})")
            items.extend(got)
        deduped, seen = [], {}
        for it in items:
            key = it.id
            if it.type == "event":
                key = ("event", it.subject.strip().lower(), it.timestamp.isoformat())
            if key in seen:
                bus.emit("IngestAgent", "dedupe", f"Dropped duplicate: {it.subject}", why="same title and start time as existing event")
                continue
            seen[key] = 1
            deduped.append(it)
        bus.emit("IngestAgent", "done", f"{len(deduped)} normalized SourceItems from {len(REGISTRY)} sources")
        return deduped
