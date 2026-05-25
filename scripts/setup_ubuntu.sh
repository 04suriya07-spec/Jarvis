#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  Javris Ubuntu Setup Script
#  Run once after installing Ubuntu 24.04 LTS
#  Usage:  chmod +x setup_ubuntu.sh && ./setup_ubuntu.sh
# ─────────────────────────────────────────────────────────────────

set -e
JAVRIS_DIR="$HOME/Javris"
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

banner() {
  echo -e "${CYAN}"
  echo "  ╔══════════════════════════════════════╗"
  echo "  ║     J A V R I S  — Ubuntu Setup      ║"
  echo "  ╚══════════════════════════════════════╝"
  echo -e "${NC}"
}

step() { echo -e "\n${CYAN}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; }

banner

# ── 1. System packages ──────────────────────────────────────────
step "Installing system packages"
sudo apt update -qq
sudo apt install -y \
  python3 python3-pip python3-venv \
  portaudio19-dev ffmpeg \
  libsm6 libxext6 libxrender-dev \
  network-manager \
  bluetooth bluez bluez-tools \
  pulseaudio-utils playerctl \
  brightnessctl xdotool wmctrl \
  libnotify-bin \
  chromium-browser \
  git curl wget \
  build-essential python3-dev
ok "System packages installed"

# ── 2. Python virtual environment ───────────────────────────────
step "Setting up Python virtual environment"
if [ ! -d "$JAVRIS_DIR/.venv" ]; then
  python3 -m venv "$JAVRIS_DIR/.venv"
  ok "Virtual environment created"
else
  ok "Virtual environment already exists"
fi

source "$JAVRIS_DIR/.venv/bin/activate"

# ── 3. Python dependencies ──────────────────────────────────────
step "Installing Python dependencies"
pip install --upgrade pip -q
pip install -r "$JAVRIS_DIR/requirements.txt" -q
ok "Python packages installed"

# ── 4. Playwright browsers ──────────────────────────────────────
step "Installing Playwright Chromium browser"
playwright install chromium
ok "Playwright ready"

# ── 5. Bluetooth user permissions ───────────────────────────────
step "Configuring Bluetooth permissions"
sudo usermod -aG bluetooth "$USER"
ok "User added to bluetooth group (re-login to take effect)"

# ── 6. Brightness permissions ───────────────────────────────────
step "Configuring brightness permissions"
# Allow $USER to run brightnessctl without sudo
sudo usermod -aG video "$USER"
ok "User added to video group for brightness control"

# ── 7. systemd service ──────────────────────────────────────────
step "Installing Javris as a systemd service"
SERVICE_FILE="$JAVRIS_DIR/scripts/javris.service"
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

sed "s|JAVRIS_DIR|$JAVRIS_DIR|g" "$SERVICE_FILE" > "$SYSTEMD_DIR/javris.service"
systemctl --user daemon-reload
systemctl --user enable javris.service
ok "Javris service installed (starts on login)"
warn "Run 'systemctl --user start javris' to start now"

# ── 8. Desktop shortcut ─────────────────────────────────────────
step "Creating desktop shortcut"
DESKTOP="$HOME/Desktop"
mkdir -p "$DESKTOP"
cat > "$DESKTOP/Javris.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Javris
Comment=Personal AI Assistant
Exec=bash -c 'cd $JAVRIS_DIR && $JAVRIS_DIR/.venv/bin/python main.py serve --voice'
Icon=utilities-terminal
Terminal=true
Categories=Utility;
EOF
chmod +x "$DESKTOP/Javris.desktop"
ok "Desktop shortcut created"

# ── 9. .env check ───────────────────────────────────────────────
step "Checking .env configuration"
if [ ! -f "$JAVRIS_DIR/.env" ]; then
  cp "$JAVRIS_DIR/.env.example" "$JAVRIS_DIR/.env"
  warn ".env created from example — edit it with your API keys!"
  warn "  nano $JAVRIS_DIR/.env"
else
  ok ".env exists"
fi

# ── Done ────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Javris setup complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo "  Next steps:"
echo "  1. Edit your API keys:  nano $JAVRIS_DIR/.env"
echo "  2. Run setup wizard:    cd $JAVRIS_DIR && python main.py setup"
echo "  3. Start Javris:        python main.py serve --voice"
echo "  4. Or use service:      systemctl --user start javris"
echo ""
warn "Log out and back in for bluetooth/brightness group changes."
echo ""
