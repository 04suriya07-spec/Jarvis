#!/usr/bin/env bash
set -e

echo "============================================================"
echo " JAVRIS - Linux/Mac Setup Script"
echo "============================================================"
echo

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3.10+ not found."
    exit 1
fi

echo "[1/5] Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "[2/5] Upgrading pip..."
pip install --upgrade pip

echo "[3/5] Installing core dependencies..."
pip install anthropic openai fastapi "uvicorn[standard]" websockets pydantic pydantic-settings
pip install duckduckgo-search httpx requests beautifulsoup4 lxml python-dotenv
pip install rich click arrow aiosqlite sqlalchemy apscheduler psutil

echo "[4/5] Installing voice dependencies..."
pip install SpeechRecognition sounddevice soundfile edge-tts pyttsx3
pip install openai-whisper
# pyaudio may need: sudo apt-get install portaudio19-dev (Ubuntu)
pip install pyaudio || echo "pyaudio install failed - install portaudio first"

echo "[5/5] Setting up config..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "IMPORTANT: Edit .env and add your API keys!"
fi

mkdir -p data logs

echo
echo "============================================================"
echo " Setup complete!"
echo
echo " Next steps:"
echo " 1. Edit .env and add your ANTHROPIC_API_KEY"
echo " 2. Run: python main.py serve"
echo " 3. Open: http://localhost:8000"
echo "============================================================"
