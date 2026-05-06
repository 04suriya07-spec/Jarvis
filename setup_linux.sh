#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
#  JAVRIS — One-command Linux Setup
#  Tested on Ubuntu 24.04 LTS and Arch Linux
# ═══════════════════════════════════════════════════════
set -e

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   JAVRIS v2.0 — Linux Setup                     ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

OS_ID=$(. /etc/os-release && echo "$ID")

# ── 1. System packages ────────────────────────────────
echo "[1/6] Installing system packages..."

if [[ "$OS_ID" == "ubuntu" || "$OS_ID" == "debian" ]]; then
    sudo apt-get update -qq
    sudo apt-get install -y \
        python3.12 python3.12-dev python3.12-venv python3-pip \
        portaudio19-dev libpulse-dev ffmpeg mpg123 \
        xdotool wmctrl libnotify-bin \
        python3-pyqt6 python3-pyqt6.qtsvg \
        libasound2-dev \
        git curl wget build-essential libssl-dev libffi-dev \
        xclip xdotool

elif [[ "$OS_ID" == "arch" || "$OS_ID" == "manjaro" ]]; then
    sudo pacman -Sy --noconfirm \
        python python-pip pyqt6 \
        portaudio ffmpeg mpg123 \
        libnotify xdotool wmctrl \
        git curl wget base-devel

elif [[ "$OS_ID" == "fedora" ]]; then
    sudo dnf install -y \
        python3 python3-devel python3-pip \
        portaudio-devel ffmpeg mpg123 \
        libnotify xdotool \
        python3-pyqt6 \
        git curl wget gcc gcc-c++ openssl-devel
fi

echo "  OK System packages installed"

# ── 2. Python virtual environment ────────────────────
echo "[2/6] Creating virtual environment..."
cd "$(dirname "$0")"

python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip -q

echo "  OK Venv ready at .venv/"

# ── 3. Python dependencies ────────────────────────────
echo "[3/6] Installing Python packages..."

pip install -q \
    anthropic \
    "fastapi[standard]" "uvicorn[standard]" \
    pydantic pydantic-settings \
    httpx websockets \
    rich click \
    psutil \
    PyQt6 \
    pynput \
    openai-whisper \
    edge-tts \
    playwright \
    ddgs \
    python-dotenv \
    aiofiles

# pyaudio sometimes needs special install
pip install -q pyaudio 2>/dev/null || \
    pip install -q pyaudio --extra-index-url https://pypi.org/simple/ 2>/dev/null || \
    echo "  NOTE: pyaudio install failed - voice STT may not work, but TTS will"

echo "  OK Python packages installed"

# ── 4. Playwright browsers ────────────────────────────
echo "[4/6] Installing Playwright Chromium..."
playwright install chromium
echo "  OK Chromium ready"

# ── 5. Configure Ollama (free local AI) ──────────────
echo "[5/6] Checking Ollama..."
if command -v ollama &>/dev/null; then
    echo "  OK Ollama found"
    if ! ollama list 2>/dev/null | grep -q "phi3"; then
        echo "  Pulling phi3 (3.8GB, this may take a while)..."
        ollama pull phi3
    fi
else
    echo "  Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull phi3
    echo "  OK Ollama installed with phi3"
fi

# ── 6. Create systemd user service (optional) ────────
echo "[6/6] Creating systemd user service..."
mkdir -p ~/.config/systemd/user

JAVRIS_DIR="$(pwd)"

cat > ~/.config/systemd/user/javris.service << EOF
[Unit]
Description=Javris AI Personal Intelligence System
After=network.target

[Service]
Type=simple
WorkingDirectory=$JAVRIS_DIR
ExecStart=$JAVRIS_DIR/.venv/bin/python $JAVRIS_DIR/main.py serve
Restart=on-failure
RestartSec=5s
Environment=DISPLAY=:0

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload 2>/dev/null || true
echo "  OK Systemd service created (javris.service)"
echo "  To auto-start: systemctl --user enable --now javris"

# ── Done ──────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Setup complete!                               ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "  HOW TO RUN:"
echo ""
echo "  Terminal 1 — AI brain + web dashboard"
echo "    source .venv/bin/activate && python main.py serve"
echo ""
echo "  Terminal 2 — Iron Man HUD overlay"
echo "    source .venv/bin/activate && python ui/overlay.py"
echo ""
echo "  Terminal 3 — Global hotkeys"
echo "    source .venv/bin/activate && python ui/hotkey_daemon.py"
echo ""
echo "  Dashboard:   http://localhost:8000"
echo "  Hotkeys:     Ctrl+Alt+J = voice  |  Ctrl+Alt+N = news"
echo "  HUD toggle:  Ctrl+Shift+J"
echo ""
echo "  Add ANTHROPIC_API_KEY to .env for Claude (computer agent)"
echo ""
