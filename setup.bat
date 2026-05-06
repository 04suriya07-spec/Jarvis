@echo off
echo ============================================================
echo  JAVRIS - Windows Setup Script
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.10+ not found. Download from https://python.org
    pause
    exit /b 1
)

echo [1/5] Creating virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat

echo [2/5] Upgrading pip...
python -m pip install --upgrade pip

echo [3/5] Installing core dependencies...
pip install anthropic openai fastapi uvicorn[standard] websockets pydantic pydantic-settings
pip install duckduckgo-search httpx requests beautifulsoup4 lxml python-dotenv
pip install rich click arrow aiosqlite sqlalchemy apscheduler psutil

echo [4/5] Installing voice dependencies...
pip install SpeechRecognition pyaudio sounddevice soundfile edge-tts pyttsx3
pip install openai-whisper

echo [5/5] Setting up config...
if not exist .env (
    copy .env.example .env
    echo IMPORTANT: Edit .env and add your API keys!
)

mkdir data 2>nul
mkdir logs 2>nul

echo.
echo ============================================================
echo  Setup complete!
echo.
echo  Next steps:
echo  1. Edit .env and add your ANTHROPIC_API_KEY
echo  2. Run: python main.py serve
echo  3. Open: http://localhost:8000
echo ============================================================
pause
