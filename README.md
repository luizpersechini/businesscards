# 📇 Business Card Scanner

A local-first, AI-powered web application that extracts contact information from business card images and exports to VCF, Excel, and Outlook CSV — all running 100% on your machine.

**Version:** 1.4.0
**Status:** Production Ready ✅
**Last Updated:** March 2026

---

## ✨ Features

### AI Extraction (Local-First)
- **GLM-OCR** (default, recommended) — #1 ranked OCR model on OmniDocBench v1.5 with 94.62 score, only 0.9B parameters, loads fast and runs fully local via Ollama
- **llama3.2-vision** — general-purpose vision fallback (11B)
- **llava, llava:13b, bakllava, moondream** — additional Ollama-compatible options
- **vLLM** — self-hosted API fallback
- **Claude / OpenAI** — cloud fallback (requires API key)
- **Strategy pattern**: LOCAL → CLOUD, auto-selects best available provider
- **QR-first logic**: skips vision entirely if QR code already contains an email — saves 20-30s per card

### Card Detection
- **Automatic** — document scanner algorithm with edge-density grid fallback
- **Manual Grid Layout** — specify rows × cols with visual preview overlay and adjustable margins
- **Manual Single Card** — treats the full image as one card

### Export Formats
- **VCF (vCard)** — Outlook / Contacts / iPhone compatible
- **Excel (XLSX)** — formatted workbook with auto-sized columns
- **Outlook CSV** — field-name variants and quoting options tuned for different Outlook versions
- **ZIP Package** — all selected formats in one download

### Other
- **Scan History** — every run archived locally; browse, relaunch, or ZIP-download past scans
- **Background warmup** — GLM-OCR preloads into GPU on app start so the first card is fast
- **Dynamic model dropdown** — shows currently GPU-loaded model (🟢) to avoid costly swaps
- **QR Code reading** — pyzbar with 5 preprocessing variants + OpenCV fallback

---

## 🛠️ Technology Stack

| Layer | Library |
|---|---|
| UI | Streamlit |
| Card detection | OpenCV |
| QR codes | pyzbar + OpenCV |
| Vision/OCR | Ollama (GLM-OCR, llama3.2-vision, llava…) |
| Cloud fallback | Anthropic Claude, OpenAI |
| VCF generation | vobject |
| Excel export | pandas + openpyxl |
| JPEG encoding | cv2.imencode (avoids PIL JPEG bugs) |

---

## 📋 Prerequisites

- Python 3.9+
- [Ollama](https://ollama.com) (recommended, free)

### System dependency (QR reading)

```bash
# macOS
brew install zbar

# Ubuntu / Debian
sudo apt-get install libzbar0
```

---

## 🚀 Quick Start

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install and start Ollama

```bash
# Install (macOS / Linux)
curl -fsSL https://ollama.com/install.sh | sh

# Pull the recommended model
ollama pull glm-ocr

# Start the server
ollama serve
```

> **Why GLM-OCR?** Only 0.9B parameters, loads in seconds, and outperforms models 260× its size on document OCR benchmarks. Ideal for business cards.

### 3. Run the app

```bash
# Recommended (sets correct library paths for QR reading)
./start_app.sh

# Or directly
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## 🎮 Usage

1. **Upload** one or more business card images (PNG / JPG / JPEG / BMP)
2. **Configure** detection mode and vision model in the sidebar (defaults are usually fine)
3. **Click "Process Business Cards"**
4. **Review** extracted contacts — edit any fields inline
5. **Download** VCF, Excel, Outlook CSV, or a ZIP of everything

### Scan History

Every run is automatically saved under `temp/history/`. Use the **Scan History** panel at the bottom of the app to:
- Browse past runs with date filters
- **👀 View** saved contacts and export files
- **💾 ZIP** all uploads + exports for a run
- **🔁 Relaunch** to reprocess stored images with new settings
- **🗑️ Delete** runs you no longer need

---

## 🤖 Recommended Models

| Model | Size | Best for |
|---|---|---|
| **glm-ocr** ⭐ | 0.9B | Business cards — fastest, most accurate OCR |
| llama3.2-vision | 11B | General-purpose vision tasks |
| llava:13b | 13B | High-accuracy fallback if glm-ocr unavailable |

Pull any model with `ollama pull <model-name>`. The app automatically detects what's installed and pre-selects the currently GPU-loaded model to avoid reload delays.

---

## 📁 Project Structure

```
Leitor Otimo Cartoes LLM/
├── app.py                          # Main Streamlit application
├── requirements.txt                # Python dependencies
├── setup.sh                        # Initial setup script
├── start_app.sh                    # Recommended launch script (sets library paths)
├── ollama_test.py                  # Standalone Ollama diagnostic tool
├── utils/
│   ├── improved_card_detector.py   # OpenCV card detection + grid fallback
│   ├── qr_reader.py                # QR code reading (pyzbar + OpenCV)
│   ├── vcf_generator.py            # VCF/vCard file generation
│   ├── export_processor.py         # Excel + Outlook CSV export
│   ├── history_manager.py          # Scan history archive
│   ├── ms_graph.py                 # Optional Outlook 365 push via MS Graph
│   ├── models.py                   # Dataclasses (ContactInfo, ScanResult, etc.)
│   └── providers/
│       ├── factory.py              # ProviderFactory — LOCAL-FIRST strategy
│       ├── base.py                 # VisionProvider base class + JPEG utilities
│       ├── ollama_provider.py      # Ollama (glm-ocr, llama3.2-vision, llava…)
│       ├── vllm_provider.py        # vLLM self-hosted API
│       ├── claude_provider.py      # Anthropic Claude API
│       └── openai_provider.py      # OpenAI API
└── temp/
    └── history/                    # Auto-saved scan runs
```

---

## 🔧 Troubleshooting

### Ollama not detected
```bash
ollama serve                            # start the server
curl http://localhost:11434/api/tags    # verify it responds
ollama list                             # check installed models
```

### Run the Ollama diagnostic tool
```bash
python3 ollama_test.py
# Test a specific model:
python3 ollama_test.py --model glm-ocr
```

### Only 2 cards detected in a grid scan
Switch detection mode to **Manual - Grid Layout** and enter the correct row/col count. The automatic mode also attempts aspect-ratio-based grid inference as a fallback.

### QR codes not reading
Run via `./start_app.sh` to ensure the `zbar` library path is set correctly on macOS.

### `DYLD_LIBRARY_PATH` error on macOS
```bash
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH
streamlit run app.py
```

### Vision timeout
- Increase the **Vision Timeout** slider in the sidebar (up to 600s)
- GLM-OCR is much faster than larger models — prefer it on slower hardware
- Check GPU usage: `ollama ps` — if model isn't on GPU, performance will be slow

---

## 📤 Importing to Outlook

### VCF
File → Open & Export → Import/Export → Import a vCard file (.vcf)

### Outlook CSV
1. File → Open & Export → Import/Export → Import from another program
2. Choose **Comma Separated Values (Windows)**
3. If fields don't auto-map, use **Map Custom Fields** to align columns

**Troubleshooting CSV import**: try enabling **Simplified Format** and adjusting field name variants (E-mail Address / Email Address / Email) in the ⚙️ Outlook CSV Options expander.

---

## 🔐 Privacy

- **100% local** — images and contact data never leave your machine
- No external API calls unless you explicitly configure a cloud provider (Claude/OpenAI)
- Scan history stored in `temp/history/` — delete anytime

---

## 📊 Changelog

### v1.4.0 (March 2026)
- **GLM-OCR** added as default recommended model (#1 on OmniDocBench v1.5, 0.9B params)
- Background model preload at startup (GLM-OCR loads into GPU before first card)
- Replaced all deprecated `use_container_width` with `width='stretch'`
- Removed legacy `VisionProcessor` (fully replaced by provider strategy pattern)
- Sidebar system status now driven by `ProviderFactory`

### v1.3.0 (2025)
- Dynamic model dropdown — shows GPU-loaded model to prevent swap timeouts
- `cv2.imencode` JPEG encoding (fixes PIL `missing 0xff00` errors)
- Grid card detection via edge-density projection (8-card scans now detected correctly)
- QR-first logic: skip vision when QR code contains email
- Warmup with `st.status` step display before batch processing
- `keep_alive: -1` on Ollama to keep model in RAM between cards

### v1.2.0 (2025)
- Scan History archive with relaunch, ZIP download, and filters
- LOCAL-FIRST provider strategy (Ollama → vLLM → Claude → OpenAI)
- `ollama_test.py` standalone diagnostic script

### v1.1.0 (2025)
- Vision mode with configurable timeout
- Dual QR code detection (pyzbar + OpenCV fallback)
- Multiple export formats (VCF, Excel, Outlook CSV, ZIP)

---

**Happy Scanning! 📇✨**
