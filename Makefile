PY=.venv/bin/python
.PHONY: dev demo live test sie seed smoke oauth ingest
dev:
	$(PY) -m uvicorn backend.app:app --reload --port 8000
demo:
	@echo "Overnight demo (Maya's seed) -> http://localhost:8000"; SOURCES_MOCK=1 $(PY) -m uvicorn backend.app:app --port 8000
live:
	@echo "LIVE: real Gmail/Calendar + real clock. Writes are DRY_RUN unless you set DRY_RUN=false in .env"; REAL_CLOCK=1 $(PY) -m uvicorn backend.app:app --port 8000
oauth:
	$(PY) scripts/google_oauth.py
ingest:
	REAL_CLOCK=1 $(PY) scripts/live_ingest.py
test:
	DISABLE_SCHEDULER=1 $(PY) -m pytest -q tests
sie:
	docker run --rm -p 8080:8080 -v sie-hf-cache:/app/.cache/huggingface ghcr.io/superlinked/sie-server:latest-cpu-default
seed:
	$(PY) -m backend.seed.build_seed
smoke:
	node tests/frontend_smoke.mjs
