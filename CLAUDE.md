# Leitor Ótimo Cartões LLM — Business card scanner (local-first, multi-LLM)

## Stack
Python · FastAPI + uvicorn · React (frontend/) · OpenCV · Pillow · multi-LLM (Ollama local / Claude / OpenAI fallback) · pandas · openpyxl · vobject (VCF export)

## Run
```
python3 server.py       # FastAPI server on :9247 — serves React UI + REST/SSE
bash setup.sh           # first-time setup (venv + deps)
```
On macOS, prefix with `DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH` so pyzbar can find zbar — or just double-click `BusinessCardScanner.app` (sets it for you, opens browser).

## Test
```
pytest                  # runs tests/ (see pyproject.toml for config)
pytest --cov=utils      # with coverage report → htmlcov/
```

## Structure
- `server.py` — FastAPI entry point (REST + SSE endpoints, serves frontend/index.html at /)
- `frontend/` — React UI shell (index.html)
- `business-card-reader/project/` — React component sources (jsx)
- `utils/models.py` — dataclasses: ContactInfo, ScanResult, ProviderConfig
- `utils/` — vision providers, image processing, export logic, FastAPI helpers
- `tests/` — pytest test suite
- `temp/` — runtime temp files, don't commit
- `htmlcov/` — coverage output, don't commit

## LLM providers (in priority order)
1. Ollama (local) — default, zero API cost
2. Claude (Anthropic) — cloud fallback
3. OpenAI — cloud fallback

## Don't touch
- `temp/` — runtime uploads
- `htmlcov/`, `__pycache__/`, `*.egg-info/` — generated artifacts

## Docs
- See QUICKSTART.md for first-run instructions
- See TESTING.md for test strategy

## graphify
Graph at `graphify-out/`. Usage rules live in `~/Projects/CLAUDE.md`.
