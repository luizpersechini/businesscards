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
# Install Python packages
pip3 install -r requirements.txt

# Install zbar (for QR codes)
brew install zbar

# Install Ollama (optional but recommended)
# Visit: https://ollama.com/download
# Then: ollama pull llama3.2
```

## Step 2: Start the Application

Terminal 1 (Ollama, optional but recommended):
```bash
ollama serve
```

Terminal 2 (FastAPI server + React frontend):
```bash
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"   # macOS only — for QR support
python3 server.py
```

> 💡 The DYLD_LIBRARY_PATH export is only needed on macOS so `pyzbar` finds zbar.

## Step 3: Use the App

1. Open browser to `http://localhost:8501`
2. Click "Browse files" and select business card photos
3. Click "🚀 Process Business Cards"
4. Download the VCF files
5. Import to Outlook!

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
→ Make sure you have Python 3.8+ installed: `python3 --version`

## Need More Help?

- Full documentation: See `README.md`
- Testing guide: See `TESTING.md`
- Troubleshooting: Check README.md "Troubleshooting" section

---

**That's it! You're ready to digitize your business card collection! 📇✨**

