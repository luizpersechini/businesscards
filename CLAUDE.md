# Leitor Ótimo Cartões LLM — Business card scanner (local-first, multi-LLM)

## Stack

Python 3.10+ (`.venv` via uv) · FastAPI + uvicorn · React (frontend/) · OpenCV · zxing-cpp (QR) · Pillow · multi-LLM (Ollama local / Claude / OpenAI fallback) · pandas · openpyxl · vobject (VCF export)

## Run

```
.venv/bin/python server.py   # FastAPI server on :9247 — serves React UI + REST/SSE
bash setup.sh                # first-time setup (creates .venv, installs from requirements.lock)
```

- Default port is **9247** (NOT 8501 — that collides with the user's Streamlit projects). Override with `PORT`. Auto-reload is OFF by default (set `RELOAD=1` for dev) — a reloader parent that keeps the socket bound after a worker crash turns a crash into a silent hang.
- No `DYLD_LIBRARY_PATH` needed — QR uses zxing-cpp (self-contained). `pyzbar` is disabled by default (segfaults libzbar on arm64); `USE_PYZBAR=1` to opt in.
- macOS: double-click `BusinessCardScanner.app` to start + open the browser (it sets DYLD, pins 9247, verifies identity before opening).

## Test

```
.venv/bin/python -m pytest   # 389 tests (see pyproject.toml for config)
pytest --cov=utils           # with coverage report → htmlcov/
```

## Structure

- `server.py` — FastAPI entry point (REST + SSE endpoints, serves frontend/index.html at /)
- `frontend/` — React UI shell (index.html) — single-file React, ~10k lines
- `business-card-reader/project/` — React component sources (jsx)
- `utils/models.py` — dataclasses: ContactInfo, ScanResult, ProviderConfig
- `utils/card_processor.py` — per-card orchestration (QR-first, then vision, then post-processing)
- `utils/qr_reader.py` — zxing-cpp primary + OpenCV fallback (pyzbar disabled)
- `utils/qr_url_resolver.py` — safe fetch+parse of QR-linked contact pages (SSRF-guarded)
- `utils/model_benchmark.py` — score models vs locked contacts; field-match logic + company aliases
- `utils/contacts_repository.py` — atomic JSON store, locked-field protection, dedup/merge
- `utils/providers/base.py` — extraction prompt + post-processing repairs (CJK sprinkle repair, `detect_cjk_script`, field-permutation, echo strip, title demotion)
- `utils/` — other vision providers, image processing, export logic, FastAPI helpers
- `tests/` — pytest test suite
- `temp/` — runtime temp files, don't commit (contacts_repository.json, thumbnails/, history/, company_aliases.json)
- `htmlcov/` — coverage output, don't commit

## LLM providers (in priority order)

1. Ollama (local) — default model **qwen2.5vl:7b** (best on the locked-contact benchmark), zero API cost
2. Claude (Anthropic) — cloud fallback
3. OpenAI — cloud fallback

Model routing (two gotchas, both previously caused silent bugs):

- The requested model is applied to the provider config in `extract_with_fallback(model=...)` **AFTER** the availability check, because Ollama's `check_availability()` rewrites `model_name` to whatever is loaded in memory. Without this the UI's model choice is silently ignored.
- …but only **if that model is installed** (`_model_is_installed`, tag-tolerant). Forcing a missing tag makes Ollama 404 and the whole scan returns **zero cards**. When it's missing we keep the installed model `check_availability()` picked and log the substitution + the `ollama pull` command.
- CJK cards (ja/zh/ko): `detect_cjk_script` keeps the printed script intact (the `?`-repair only fires on the ≤2-ideograph sprinkle pattern) and the Ollama provider runs one extra translation call; Latin goes into name/company/title, the original line into `notes` as `原文: …`. `OLLAMA_CJK_TRANSLATE=0` disables.
- `ScanResult.model_used` records the model that **actually** ran (post-fallback). It reaches the UI badge via a `_model_used` stash on `contact_data`, popped in `server._contact_data_to_frontend` — same pattern as `_qr_url` / `_detected_lang`, so it never lands in the saved contact.

## Don't touch

- `temp/` — runtime uploads + the live contacts store / thumbnails / history / `company_aliases.json`
- `htmlcov/`, `__pycache__/`, `*.egg-info/` — generated artifacts
- `.venv/` — regenerate with `setup.sh`, don't edit

## Docs

- See QUICKSTART.md for first-run instructions
- See TESTING.md for test strategy

## graphify

Graph at `graphify-out/`. Usage rules live in `~/Projects/CLAUDE.md`.

<!-- api-credits-note -->
## Anthropic API credits
Luiz has monthly API credits (Claude Max plan, linked Console org; see platform.claude.com/settings/billing > Promotional credits). If this project needs Claude API calls (Messages, Batch, Agent SDK, `claude -p`), use an API key from that linked org and say so before suggesting other paid providers. Credits expire at end of each billing cycle (no rollover), so prefer spending them on batch/headless work. They do NOT cover interactive Claude Code. Never commit the key; keep it in `.env`/env var, and set `ANTHROPIC_API_KEY` only per-script, not globally.
