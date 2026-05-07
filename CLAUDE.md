# Leitor Ótimo Cartões LLM — Business card scanner (local-first, multi-LLM)

## Stack
Python · Streamlit · OpenCV · Pillow · multi-LLM (Ollama local / Claude / OpenAI fallback) · pandas · openpyxl · vobject (VCF export)

## Run
```
bash start_app.sh       # preferred: sets up env and launches Streamlit
streamlit run app.py    # direct launch
bash setup.sh           # first-time setup (venv + deps)
```

## Test
```
pytest                  # runs tests/ (see pyproject.toml for config)
pytest --cov=utils      # with coverage report → htmlcov/
```

## Structure
- `app.py` — Streamlit UI entry point
- `utils/models.py` — dataclasses: ContactInfo, ScanResult, ProviderConfig
- `utils/` — vision providers, image processing, export logic
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

---

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
