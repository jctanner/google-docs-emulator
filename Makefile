.PHONY: test lint serve smoke

test:
	uv run --extra dev pytest -q
lint:
	uv run --extra dev ruff check src tests
serve:
	uv run uvicorn google_docs_emulator.app:app --host 127.0.0.1 --port 8080
smoke:
	curl --fail http://127.0.0.1:8080/healthz
