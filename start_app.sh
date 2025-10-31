#!/bin/bash

# Business Card Scanner - Startup Script
# This script sets up the environment and starts the application

echo "📇 Starting Business Card Scanner..."
echo ""

# Set library path for zbar (QR code reading)
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"
echo "✓ QR code library path configured"

# Navigate to project directory
cd "/Users/LuizPersechini_1/Projects/Leitor Otimo Cartoes LLM"

# Check if Ollama is running
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✓ Ollama is running"
else
    echo "⚠ Ollama not running - starting it..."
    ollama serve > /dev/null 2>&1 &
    sleep 3
    echo "✓ Ollama started"
fi

echo ""
echo "🚀 Starting application..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Start the app
python3 -m streamlit run app.py

# Note: App will open automatically in your browser

