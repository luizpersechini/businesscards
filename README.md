# 📇 Business Card Scanner

Local-first, AI-powered business card scanner. Drop in JPEG / PNG / PDF cards, get back clean contact records you can export to **VCF**, **Excel**, or **Outlook CSV** — without any image leaving your machine.

[![CI](https://github.com/luizpersechini/businesscards/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/luizpersechini/businesscards/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#-license)
[![Last commit](https://img.shields.io/github/last-commit/luizpersechini/businesscards.svg)](https://github.com/luizpersechini/businesscards/commits/main)

> **v2.1** — FastAPI + React frontend, multi-provider LLM strategy (Ollama / vLLM / Claude / OpenAI), model benchmarking against your own verified contacts, QR-link resolution, duplicate detection, 362-test suite, CI on Python 3.10/3.11/3.12.

---

## 🎬 Screenshots

| Scanner                                                          | Results                                                                | Contacts                                                           |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------ |
| ![Scanner](business-card-reader/project/screenshots/initial.png) | ![Results](business-card-reader/project/screenshots/results-state.png) | ![Wide](business-card-reader/project/screenshots/results-wide.png) |

---

## ✨ Highlights

- 🧠 **Multi-model vision** — defaults to **Qwen2.5-VL 7B** (best overall on real business cards in the built-in benchmark), with **MiniCPM-V**, **GLM-OCR** (fastest), **llama3.2-vision**, **llava**, **Claude**, or **OpenAI** a click away. The picker shows measured speed/quality ranks, and the requested model is honoured end-to-end (no silent fallback to whatever Ollama happens to have loaded).
- 📊 **Benchmark against your own contacts** — your locked (human-verified) contacts are ground truth. The **Benchmark** button re-runs extraction on their card images with each model and scores field-level accuracy, so "which model should I use?" is answered by _your_ cards, not vendor claims. Forgiving matching (accent-folded, containment, acronym + brand short-forms, a user-editable `company_aliases.json`) keeps the scores honest.
- 🔗 **QR-link resolution** — when a card's QR encodes a URL (a hosted vCard / digital business card) instead of inline fields, a **Fetch contact data** button pulls the contact from that page — after an SSRF/scheme/Safe-Browsing threat check. User-initiated: nothing hits the network during an unattended scan.
- 👥 **Duplicate detection** — conservatively flags the same person scanned twice with a different or typo'd email (exact-email dupes already merge on save). Review pairs side by side and merge non-destructively into the record you keep; locked name/email are never overwritten.
- 📷 **Smart card detection** — automatic OpenCV pipeline with gap-detection + median-regularize for non-uniform grids, plus manual single-card and N×M-grid modes. Each detected tile is refined to its actual card boundary (CLAHE + multi-strategy edges + perspective-correct) before being sent to the vision model — drops the inter-card-gap pixels that confuse OCR.
- 🎛️ **Interactive preview** — `Preview` runs detection only (no LLM), shows annotated tiles + count. In Grid mode you can drag the dashed dividers and the solid outer crop edges to reposition every line by hand; debounced auto-refresh shows the new tiling in ~350 ms. When Auto falls back to a grid, a one-click _"Apply N×M grid"_ banner offers to switch modes with the inferred dims.
- 🧭 **Optional auto-deskew** — opt-in checkbox warps the card cluster to an axis-aligned rectangle (four-point perspective transform) before detection. Useful for phone-camera photos with perspective distortion; auto-skipped if the cluster is already orthogonal.
- 🧾 **QR-first short-circuit** — QR decoded by **zxing-cpp** (fast, arm64-native). If a card's QR encodes a vCard / MECARD with enough data, vision is skipped entirely (saves ~20-30 s per card).
- 📤 **Multi-format export** — Results panel buttons export the just-scanned cards directly: VCF (Outlook / iPhone Contacts), Excel, Outlook CSV, or a ZIP bundle (all three + one VCF per card).
- 🛑 **Stop button** — cancel an in-flight scan from the UI; in-flight card finishes, no further work runs.
- 📜 **Scan history** — every run is archived locally with original images, parsed contacts, and exports. Browse, ZIP-download, or relaunch with new settings.
- 🏷️ **Smart name & phone parsing** — `phonenumbers` (Google libphonenumber) for international phone validation, `probablepeople` (CRF) for distinguishing "Banco do Brasil" (company) from "João da Silva" (person). Plus email-anchored repair of scrambled name/title/company fields, and multilingual title-in-name demotion.
- 🩹 **CJK→Latin repair** — defensive post-process that maps the visually-similar Chinese ideographs GLM-OCR sometimes emits in place of accented Portuguese/Spanish characters (`é→矇`, `ç→癟`, `ã→瓊`) back to their Latin originals. Applied at every contact-extraction return point (including the QR-only fast path).
- 🔐 **100% local** — no external API calls unless you explicitly configure a cloud fallback. Contacts stored atomically (crash-safe writes).

---

## 🚀 Quick Start

### 1. Install system deps

```bash
# macOS
brew install zbar libheif tesseract

# Ubuntu / Debian
sudo apt-get install libzbar0 libheif1 tesseract-ocr
```

### 2. Install Ollama (recommended) and pull a vision model

```bash
curl -fsSL https://ollama.com/install.sh | sh   # macOS / Linux
ollama pull qwen2.5vl:7b       # default — best overall on real cards
ollama pull glm-ocr            # optional — fastest, great for phone/email/web
```

> **Which model?** `qwen2.5vl:7b` is the default because it scored highest on the built-in benchmark against real verified contacts. `glm-ocr` (0.9 B) is ~4× faster and excellent for phone/email/website but weaker on names/titles. Run the **Benchmark** button (Contacts tab) to compare them on _your_ cards.

### 3. Install Python deps and run

**Python 3.10+ required** (`starlette>=1.0.1` / `fastapi>=0.111` publish no wheels for 3.9). Deps install into a project-local `.venv` — the `BusinessCardScanner.app` launcher expects `.venv/bin/python3`.

```bash
./setup.sh              # creates .venv + installs from requirements.lock
.venv/bin/python server.py
```

Open **<http://localhost:9247>**. The FastAPI backend serves the React UI at `/` and exposes REST + SSE endpoints for the scan pipeline.

> QR decoding uses **zxing-cpp** (self-contained arm64 wheels), so no `DYLD_LIBRARY_PATH` / zbar setup is needed. `pyzbar` is included but disabled by default — it segfaults `libzbar` on arm64; opt back in with `USE_PYZBAR=1` if you're on a platform where it works.

> 💡 On macOS, double-click the included `BusinessCardScanner.app` (built locally — see [QUICKSTART.md](QUICKSTART.md)) to start the server with one click and auto-open the browser.

---

## 🧩 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  React UI (frontend/index.html)                                 │
│  ─ Upload, scan, edit, export, history, contacts                │
└──────────┬──────────────────────────────────────────────────────┘
           │ REST + SSE
┌──────────▼──────────────────────────────────────────────────────┐
│  FastAPI server.py                                              │
│  ─ /api/scan          (multipart upload → SSE stream)           │
│  ─ /api/scan/stop     (cooperative cancel)                      │
│  ─ /api/contacts      (CRUD + export VCF / XLSX / CSV)          │
│  ─ /api/contacts/duplicates + /merge  (dedup review)            │
│  ─ /api/resolve-qr-url  (guarded fetch of a QR-linked page)     │
│  ─ /api/benchmark     (score models vs locked contacts, SSE)    │
│  ─ /api/history       (list / ZIP / delete past runs)           │
└──────────┬──────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────┐
│  utils/                                                         │
│  ├─ card_processor       Per-card orchestration                 │
│  ├─ improved_card_detector   OpenCV detection + grid fallback   │
│  ├─ qr_reader            zxing-cpp (primary) + OpenCV, MECARD   │
│  ├─ qr_url_resolver      Safe fetch + parse of QR-linked pages  │
│  ├─ model_benchmark      Field-accuracy scoring vs ground truth │
│  ├─ providers/           Strategy pattern, LOCAL-FIRST          │
│  │  ├─ ollama_provider   Qwen2.5-VL / MiniCPM-V / GLM-OCR / …   │
│  │  ├─ vllm_provider     vLLM OpenAI-compatible API             │
│  │  ├─ claude_provider   Anthropic Claude vision                │
│  │  └─ openai_provider   OpenAI GPT-4o vision                   │
│  ├─ vcf_generator        vobject (round-trip tested)            │
│  ├─ export_processor     pandas + openpyxl                      │
│  ├─ history_manager      JSON metadata + per-run artifacts      │
│  └─ contacts_repository  Atomic JSON store + dedup/merge        │
└─────────────────────────────────────────────────────────────────┘
```

LOCAL-FIRST provider chain: every scan tries Ollama → vLLM → Claude → OpenAI in priority order, with the first available provider winning. Local providers stay loaded (`keep_alive: -1`) between cards so subsequent scans cost only an inference, not a model reload.

---

## 🛠️ Tech stack

| Layer           | Library                                                         |
| --------------- | --------------------------------------------------------------- |
| Web UI          | React (single-file shell)                                       |
| API             | FastAPI + uvicorn (REST + SSE)                                  |
| Computer vision | OpenCV, zxing-cpp (QR), pillow-heif                             |
| OCR / vision    | Ollama (qwen2.5vl, minicpm-v, glm-ocr, llama3.2-vision, llava…) |
| Cloud fallback  | Anthropic Claude, OpenAI                                        |
| Phone parsing   | `phonenumbers` (Google libphonenumber)                          |
| Name parsing    | `probablepeople` (CRF)                                          |
| VCF generation  | `vobject`                                                       |
| Excel export    | `pandas` + `openpyxl`                                           |
| PDF rendering   | `pymupdf`                                                       |
| Tests           | `pytest`, `pytest-cov`, `pytest-timeout`, `httpx` (TestClient)  |

---

## 🤖 Recommended models

| Model            | Size  | Best for                                                                    |
| ---------------- | ----- | --------------------------------------------------------------------------- |
| **qwen2.5vl** ⭐ | 7 B   | Default. Best overall field accuracy on real cards (~84% in benchmark).     |
| minicpm-v        | 8 B   | Best speed/quality balance; strongest on names, ~2× faster than Qwen.       |
| glm-ocr          | 0.9 B | Fastest (~5 s/card). Great for phone/email/website; weaker on names/titles. |
| llama3.2-vision  | 11 B  | General vision, used historically.                                          |
| llava:13b        | 13 B  | High-accuracy fallback when GPU memory allows.                              |

`ollama pull <model>` installs any of them. The picker shows measured speed/quality ranks; the model you choose is honoured end-to-end. Use the **Benchmark** button (Contacts tab) to rank them on your own verified cards.

---

## 🎮 Usage

1. **Upload** business card images or PDF (drag-and-drop or file picker).
2. **Configure** detection mode and vision model in the settings panel — defaults are usually fine.
3. **Process Cards** — watch live SSE progress per page / per card. Click **Stop scan** to cancel.
4. **Review** extracted contacts inline. **Edit** any field by clicking the pencil icon. If a card's QR links to a contact page, click **Fetch contact data** to pull it in.
5. **Download** VCF / Excel / Outlook CSV individually or as a ZIP bundle.

On the **Contacts** tab: **Benchmark** ranks your installed models against your locked (verified) contacts; **Duplicates** finds and merges near-duplicate records. Every run is auto-archived under `temp/history/` — see the **History** tab to browse, relaunch with new settings, or delete.

---

## 🔧 Troubleshooting

<details>
<summary><b>Ollama not detected</b></summary>

```bash
ollama serve                            # start the server
curl http://localhost:11434/api/tags    # verify it responds
ollama list                             # check installed models
```

</details>

<details>
<summary><b>QR codes not reading</b></summary>

QR decoding uses **zxing-cpp**, which is self-contained (no zbar / `DYLD_LIBRARY_PATH` needed). If a QR still won't read, the card image is likely too small or low-contrast — the reader already tries ~14 preprocessing variants, but a higher-resolution scan helps most. (`pyzbar` is disabled by default because it segfaults `libzbar` on arm64; `USE_PYZBAR=1` re-enables it where it works.)

</details>

<details>
<summary><b>Only some cards detected in a grid scan</b></summary>

Switch the detection mode to **Manual — Grid Layout** in the settings panel and enter the correct rows × cols. The automatic mode falls back to a 4×2 / 2×4 grid based on aspect ratio when it can't detect cards individually, which doesn't always match real layouts.

</details>

<details>
<summary><b>Vision timeout / slow first card</b></summary>

- Bump the **Vision Timeout** slider (up to 600 s) for the cold-start case.
- Prefer **GLM-OCR** on slower hardware — it's an order of magnitude faster than 7 B+ vision models (at some cost to name/title accuracy).
- `ollama ps` — confirm the model is on GPU. If it shows `100% CPU`, you're missing CUDA / Metal acceleration.
</details>

---

## 🧪 Tests

```bash
pytest tests/                           # 362 tests, ~2 s
pytest tests/ --cov=utils               # with coverage report (htmlcov/)
```

Providers' heavy network paths are intentionally not covered in unit tests; everything else — detection, parsing, VCF/CSV/XLSX export, contacts store (incl. concurrency + atomic writes), duplicate detection/merge, benchmark scoring, QR-URL SSRF guards — is.

---

## 📤 Importing to Outlook

**VCF**: File → Open & Export → Import/Export → _Import a vCard file (.vcf)_.

**Outlook CSV**: File → Open & Export → Import/Export → _Import from another program_ → **Comma Separated Values (Windows)**. If fields don't auto-map, use **Map Custom Fields**. Try the **Simplified Format** toggle in the export options if your Outlook version chokes on certain field-name variants.

---

## 🔐 Privacy

- **100 % local by default.** Images and contact data never leave your machine.
- No external API calls unless you explicitly set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`.
- Scan history is stored in `temp/history/` — delete anytime; it's gitignored.

---

## 📜 Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for the full history. v2.0: Streamlit removed, FastAPI/React frontend, multi-provider strategy, full test suite + CI. v2.1 (latest): model benchmarking vs verified contacts, qwen2.5vl default, zxing-cpp QR, QR-link resolution, duplicate detection, atomic contacts store, email-anchored field repair.

## 📄 License

MIT — see [`pyproject.toml`](pyproject.toml).

---

**Happy scanning! 📇✨**
