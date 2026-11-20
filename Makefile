PY=.venv/bin/python
.PHONY: dev demo live test sie seed smoke oauth ingest ready triage demo-mail demo-mail-send
dev:
	$(PY) -m uvicorn backend.app:app --reload --port 8000
demo:
	$(PY) scripts/serve.py demo
live:
	$(PY) scripts/serve.py live
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
ready:
	REAL_CLOCK=1 $(PY) scripts/readiness.py
triage:
	REAL_CLOCK=1 $(PY) scripts/live_triage.py
demo-mail:
	$(PY) scripts/send_demo_emails.py
demo-mail-send:
	$(PY) scripts/send_demo_emails.py --send
