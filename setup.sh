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

    # Check if llama3.2 model is available
    echo "Checking for llama3.2 model..."
    if ollama list | grep -q "llama3.2"; then
        echo "✓ llama3.2 model is already installed"
    else
        echo "Downloading llama3.2 model (this may take a while)..."
        ollama pull llama3.2
        if [ $? -eq 0 ]; then
            echo "✓ llama3.2 model installed"
        else
            echo "⚠ Could not download model. You can do this later with:"
            echo "  ollama pull llama3.2"
        fi
    fi
else
    echo "⚠ Ollama is not installed"
    echo "For best results, install Ollama from: https://ollama.com"
    echo "Then run: ollama pull llama3.2"
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
echo "2. In a new terminal, run:"
echo "   streamlit run app.py"
echo ""
echo "3. Open your browser to the URL shown (typically http://localhost:8501)"
echo ""
echo "Happy scanning! 📇"

