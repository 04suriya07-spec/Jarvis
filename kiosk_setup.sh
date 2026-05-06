#!/usr/bin/env bash
# Javris OS Kiosk Mode Installer for Ubuntu Server
set -e

echo "============================================="
echo " Installing Javris OS Fullscreen Interface"
echo "============================================="

# 1. Update and install required packages
sudo apt-get update
sudo apt-get install -y \
    python3-venv python3-pip python3-dev \
    libportaudio2 libasound2-dev \
    libgl1-mesa-glx libglib2.0-0 gcc \
    cage chromium-browser \
    plymouth-themes

# 2. Install Javris Core
sudo mkdir -p /opt/javris
sudo cp -r ./* /opt/javris/
sudo chown -R $USER:$USER /opt/javris
cd /opt/javris

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Setup Javris Background Daemon
sudo cp javris.service /etc/systemd/system/javris.service
sudo systemctl daemon-reload
sudo systemctl enable javris.service

# 4. Setup the GUI Kiosk Service (Boots directly into the web UI)
cat <<EOF | sudo tee /etc/systemd/system/javris-kiosk.service
[Unit]
Description=Javris OS Kiosk GUI
After=systemd-user-sessions.service network-online.target javris.service
Wants=javris.service

[Service]
Type=simple
User=$USER
Environment=DISPLAY=:0
ExecStart=/usr/bin/cage -s -- chromium-browser --kiosk --incognito --disable-infobars --no-first-run --window-size=1920,1080 http://127.0.0.1:8000
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable javris-kiosk.service

# 5. Hide boot text for a clean, "Windows-like" boot experience
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="maybe-ubiquity"/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"/g' /etc/default/grub
sudo update-grub

echo "============================================="
echo " Setup Complete! "
echo " Reboot your laptop. It will now boot directly into Javris OS."
echo "============================================="
