#!/bin/bash

# Business Card Scanner - Setup Script
# This script helps you set up the application

echo "📇 Business Card Scanner - Setup"
echo "================================"
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"
echo ""

# Install Python dependencies
echo "Installing Python dependencies..."
echo "This may take a few minutes..."
pip3 install -r requirements.txt

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
echo "2. In a new terminal, run the FastAPI server:"
echo "   python3 server.py"
echo ""
echo "3. Open your browser to http://localhost:9247"
echo ""
echo "Happy scanning! 📇"

