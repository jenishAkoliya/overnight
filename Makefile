PY=.venv/bin/python
.PHONY: dev demo test sie seed
dev:
	$(PY) -m uvicorn backend.app:app --reload --port 8000
demo:
	@echo "Overnight demo -> http://localhost:8000  (zero keys needed)"; MOCK_MODE=auto $(PY) -m uvicorn backend.app:app --port 8000
test:
	DISABLE_SCHEDULER=1 $(PY) -m pytest -q tests
sie:
	docker run --rm -p 8080:8080 -v sie-hf-cache:/app/.cache/huggingface ghcr.io/superlinked/sie-server:latest-cpu-default
seed:
	$(PY) -m backend.seed.build_seed
