#!/bin/bash
# ==============================================================================
# Javris OS Auto-Installer (Kiosk Mode)
# Transforms a minimal Ubuntu/Debian install into a dedicated Javris HUD terminal.
# Usage: sudo ./install_javris_os.sh
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
  echo "Please run this script as root (sudo ./install_javris_os.sh)"
  exit 1
fi

echo "========================================="
echo "   Initiating Javris OS Conversion...    "
echo "========================================="
echo ""

# 1. Update and Install Core Dependencies
echo "[1/6] Installing X11, Openbox, Picom, and Python dependencies..."
apt-get update
apt-get install -y --no-install-recommends \
    xserver-xorg x11-xserver-utils xinit \
    openbox picom \
    python3-pip python3-venv \
    portaudio19-dev libasound2-dev \
    libglx0 libgl1 libegl1 \
    curl git

# 2. Setup Python Environment
echo "[2/6] Setting up Python dependencies in /opt/javris..."
JAVRIS_DIR=$(pwd)
if [ "$JAVRIS_DIR" != "/opt/javris" ]; then
    echo "Copying Javris core files to /opt/javris..."
    mkdir -p /opt/javris
    cp -r "$JAVRIS_DIR"/* /opt/javris/
    cd /opt/javris || exit 1
fi

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt || echo "Make sure a requirements.txt is defined!"

# 3. Configure GPU Compositor (Picom)
echo "[3/6] Tuning Picom for transparent HUD glow effects..."
mkdir -p /etc/xdg/picom
cat << 'EOF' > /etc/xdg/picom/picom.conf
backend = "glx";
vsync = true;
shadow = true;
shadow-radius = 15;
shadow-offset-x = -15;
shadow-offset-y = -15;
shadow-opacity = 0.5;
corner-radius = 12;
# Keep Javris overlay completely borderless and unshadowed if needed
shadow-exclude = [
  "name = 'JavrisHUD'",
  "class_g = 'JavrisHUD'"
];
focus-exclude = [ "class_g = 'JavrisHUD'" ];
blur-background = true;
blur-method = "dual_kawase";
blur-strength = 4;
EOF

# 4. Configure Window Manager (Openbox)
echo "[4/6] Configuring Openbox Autostart..."
OB_DIR="/home/$SUDO_USER/.config/openbox"
mkdir -p "$OB_DIR"
cat << 'EOF' > "$OB_DIR/autostart"
# Disable screen blanking & power management
xset -dpms
xset s noblank
xset s off

# Start Compositor
picom --config /etc/xdg/picom/picom.conf -b &

# Start the Javris HUD
cd /opt/javris
/opt/javris/venv/bin/python ui/overlay.py &
EOF
chown -R "$SUDO_USER:$SUDO_USER" "/home/$SUDO_USER/.config"

# 5. Set up Auto-login Terminal rules
echo "[5/6] Setting up seamless X11 autostart..."
XINIT_FILE="/home/$SUDO_USER/.xinitrc"
cat << 'EOF' > "$XINIT_FILE"
exec openbox-session
EOF
chown "$SUDO_USER:$SUDO_USER" "$XINIT_FILE"

BASH_PROFILE="/home/$SUDO_USER/.bash_profile"
cat << 'EOF' >> "$BASH_PROFILE"
if [[ -z $DISPLAY ]] && [[ $(tty) = /dev/tty1 ]]; then
    exec startx
fi
EOF
chown "$SUDO_USER:$SUDO_USER" "$BASH_PROFILE"

# 6. Systemd Background Daemons
echo "[6/6] Establishing Core Background Services (Brain)..."
cat << EOF > /etc/systemd/system/javris-core.service
[Unit]
Description=Javris AI Core Brain (FastAPI/Engine)
After=network.target

[Service]
Type=simple
User=$SUDO_USER
WorkingDirectory=/opt/javris
ExecStart=/opt/javris/venv/bin/python main.py serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable javris-core.service
systemctl start javris-core.service

echo "========================================="
echo "  INSTALL COMPLETION SUCCESSFUL!         "
echo "========================================="
echo "Your system has been converted to Javris OS."
echo "If you configured Auto-Login in Ubuntu setup, "
echo "the system will now boot straight into the HUD."
echo ""
echo "Type 'sudo reboot' to launch Javris OS."
