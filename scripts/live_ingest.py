"""Read-only live ingest of the last N days from real sources (Gmail + Calendar [+ Slack if token]).
Prints counts and a few truncated subjects; never writes anything. Run: make ingest"""
import collections
import os
import sys
sys.path.insert(0, ".")
from backend import config
from backend.agents.ingest import IngestAgent
from backend.agents.memory import memory
from backend.integrations.airbyte_client import connectors_status

print("connectors:", [(c["name"], c["mode"]) for c in connectors_status()])
items = IngestAgent().run()
by = collections.Counter((i.source, i.type) for i in items)
print("items:", dict(by), "| known contacts learned:", len(memory.known_contacts))
for src in ("gmail", "calendar"):
    xs = [i for i in items if i.source == src][:4]
    for i in xs:
        print(f"  {src:8} {i.timestamp.astimezone(config.TZ):%a %b %d %H:%M} | {i.subject[:60]!r} | flags:{[k for k in ('list_unsubscribe','receipt','invite','known_contact','direction') if i.metadata.get(k)]}")
