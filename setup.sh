#!/bin/bash

# Business Card Scanner - Setup Script
# This script helps you set up the application

echo "📇 Business Card Scanner - Setup"
echo "================================"
echo ""

# ── Python version floor ─────────────────────────────────────────────────────
# pyproject.toml declares requires-python = ">=3.10", and the pinned deps
# (fastapi>=0.111, starlette>=1.0.1 — the CVE-2026-48710 fix) only publish
# wheels for 3.10+. On an older interpreter pip fails with a wall of
# "Ignored the following versions that require a different python version",
# which is impossible to read. Fail loudly and early instead.
MIN_MAJOR=3
MIN_MINOR=10

# Returns 0 if "$1" is a python >= 3.10
py_is_supported() {
    "$1" -c "import sys; sys.exit(0 if sys.version_info[:2] >= ($MIN_MAJOR, $MIN_MINOR) else 1)" 2>/dev/null
}

echo "Checking Python version..."

PYBIN=""
# Prefer an explicit modern interpreter, then fall back to plain python3.
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 && py_is_supported "$cand"; then
        PYBIN="$(command -v "$cand")"
        break
    fi
done

USE_UV=0
if command -v uv >/dev/null 2>&1; then
    USE_UV=1
fi

if [ -z "$PYBIN" ] && [ "$USE_UV" -eq 0 ]; then
    found="$(python3 --version 2>&1 | awk '{print $2}')"
    echo "✗ Python ${MIN_MAJOR}.${MIN_MINOR}+ is required (found: ${found:-none})."
    echo ""
    echo "  This project pins starlette>=1.0.1 (CVE-2026-48710) and"
    echo "  fastapi>=0.111, which publish no wheels for Python < 3.10."
    echo ""
    echo "  Install a supported Python, then re-run this script:"
    echo "    brew install python@3.13          # Homebrew"
    echo "    # or install uv, which manages its own Pythons:"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if [ -n "$PYBIN" ]; then
    echo "✓ Python version: $("$PYBIN" --version 2>&1 | awk '{print $2}')  ($PYBIN)"
else
    echo "✓ No system Python ≥${MIN_MAJOR}.${MIN_MINOR}; uv will provide one."
fi
echo ""

# ── Virtualenv + dependencies ────────────────────────────────────────────────
# Always install into a project-local .venv. The BusinessCardScanner.app
# launcher execs "$PROJECT_DIR/.venv/bin/python3", so a user-site install
# (the old behaviour) left the desktop shortcut broken.
echo "Creating virtual environment (.venv)..."
if [ "$USE_UV" -eq 1 ]; then
    uv venv --clear --python 3.13 .venv || { echo "✗ Failed to create .venv"; exit 1; }
else
    "$PYBIN" -m venv --clear .venv || { echo "✗ Failed to create .venv"; exit 1; }
fi
echo "✓ .venv created ($(.venv/bin/python --version 2>&1 | awk '{print $2}'))"
echo ""

echo "Installing Python dependencies..."
echo "This may take a few minutes..."
# Prefer the hash-pinned lock when present — reproducible + supply-chain safe.
if [ -f requirements.lock ]; then
    REQ_FILE=requirements.lock
else
    REQ_FILE=requirements.txt
fi
echo "  (from $REQ_FILE)"

if [ "$USE_UV" -eq 1 ]; then
    uv pip install --python .venv/bin/python -r "$REQ_FILE"
else
    .venv/bin/python -m pip install --upgrade pip >/dev/null
    .venv/bin/python -m pip install -r "$REQ_FILE"
fi

if [ $? -eq 0 ]; then
    echo "✓ Python dependencies installed successfully"
else
    echo "✗ Error installing Python dependencies"
    exit 1
fi
echo ""

# Check for zbar (needed for QR code reading)
echo "Checking for zbar library (needed for QR codes)..."
if command -v zbarcam &> /dev/null; then
    echo "✓ zbar is already installed"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Installing zbar via Homebrew..."
    if command -v brew &> /dev/null; then
        brew install zbar
        echo "✓ zbar installed"
    else
        echo "⚠ Homebrew not found. Please install zbar manually:"
        echo "  brew install zbar"
    fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "Installing zbar..."
    sudo apt-get update
    sudo apt-get install -y libzbar0
    echo "✓ zbar installed"
else
    echo "⚠ Please install zbar manually for your system"
fi
echo ""

# Check for Ollama
echo "Checking for Ollama..."
if command -v ollama &> /dev/null; then
    echo "✓ Ollama is installed"

    # Check if glm-ocr model is available
    echo "Checking for glm-ocr model..."
    if ollama list | grep -q "glm-ocr"; then
        echo "✓ glm-ocr model is already installed"
    else
        echo "Downloading glm-ocr model (this may take a while)..."
        ollama pull glm-ocr
        if [ $? -eq 0 ]; then
            echo "✓ glm-ocr model installed"
        else
            echo "⚠ Could not download model. You can do this later with:"
            echo "  ollama pull glm-ocr"
        fi
    fi
else
    echo "⚠ Ollama is not installed"
    echo "For best results, install Ollama from: https://ollama.com"
    echo "Then run: ollama pull glm-ocr"
fi
echo ""

# Create temp directory if it doesn't exist
mkdir -p temp

echo "================================"
echo "✓ Setup complete!"
echo ""
echo "To start the application:"
echo "1. Start Ollama (optional but recommended):"
echo "   ollama serve"
echo ""
echo "2. In a new terminal, run the FastAPI server from the venv."
echo "   On macOS, DYLD_LIBRARY_PATH lets pyzbar find zbar:"
echo "   DYLD_LIBRARY_PATH=/opt/homebrew/lib:\$DYLD_LIBRARY_PATH .venv/bin/python server.py"
echo ""
echo "   (Or just double-click BusinessCardScanner.app — it does both.)"
echo ""
echo "3. Open your browser to http://localhost:9247"
echo ""
echo "Happy scanning! 📇"

