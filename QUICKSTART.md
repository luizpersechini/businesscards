# 🚀 Quick Start Guide

Get up and running in 5 minutes!

## Step 1: Install Dependencies

Open Terminal and run:

```bash
cd "/Users/LuizPersechini_1/Projects/Leitor Otimo Cartoes LLM"
./setup.sh
```

**Or manually:**

```bash
# Python 3.10+ is required (starlette>=1.0.1 / fastapi>=0.111 ship no
# wheels for 3.9). Install into a project-local .venv — the
# BusinessCardScanner.app launcher expects .venv/bin/python3.
python3.13 -m venv .venv          # or: uv venv --python 3.13 .venv
.venv/bin/python -m pip install -r requirements.lock   # hash-pinned

# System libs (QR + HEIC + Tesseract)
brew install zbar libheif tesseract              # macOS
# or: sudo apt-get install libzbar0 libheif1 tesseract-ocr   # Ubuntu/Debian

# Install Ollama (recommended)
# Visit: https://ollama.com/download
# Then: ollama pull glm-ocr
```

## Step 2: Start the Application

Terminal 1 (Ollama, recommended):

```bash
ollama serve
```

Terminal 2 (FastAPI server + React frontend):

```bash
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"   # macOS only — for QR support
python3 server.py
```

> 💡 **macOS shortcut:** double-click `BusinessCardScanner.app` from Finder (or drag it to your Dock). It sets `DYLD_LIBRARY_PATH`, starts the server in the background, and opens the browser. Use `StopBusinessCardScanner.app` to clean shutdown.

## Step 3: Use the App

1. Open browser to `http://localhost:9247`
2. Drop business card images / PDF onto the upload zone
3. Click **Process** — watch live progress, click **Stop** to cancel
4. Review and edit any extracted fields inline
5. Download VCF / Excel / Outlook CSV (or a ZIP bundle of everything)

## Importing to Outlook

### Outlook Desktop

1. File → Open & Export → Import/Export
2. Select "Import a vCard file (.vcf)"
3. Choose your downloaded VCF file

### Outlook Web

1. Click People/Contacts
2. Click "Import contacts"
3. Upload VCF file

## Tips for Best Results

✅ **DO:**

- Use clear, well-lit photos
- Ensure text is readable
- Keep cards flat when photographing
- Use high resolution images

❌ **DON'T:**

- Use blurry photos
- Mix cards with other documents
- Use extremely low light
- Photograph bent or curved cards

## Common Issues

**"Ollama: Not running"**
→ Run `ollama serve` in a separate terminal

**"No cards detected"**
→ Switch detection mode to **Single Card** or **Grid Layout** in the settings panel

**OCR text is wrong**
→ Use better lighting and higher resolution image

**Installation fails**
→ Make sure you have Python 3.10+ installed: `python3 --version`

## Need More Help?

- Full documentation: See `README.md`
- Testing guide: See `TESTING.md`
- Troubleshooting: Check README.md "Troubleshooting" section

---

**That's it! You're ready to digitize your business card collection! 📇✨**
