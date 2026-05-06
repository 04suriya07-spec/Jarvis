#!/usr/bin/env bash
set -e

echo "Installing Javris OS..."

# Create installation directory
sudo mkdir -p /opt/javris
sudo cp -r ./* /opt/javris/
sudo chown -R root:root /opt/javris

cd /opt/javris

# Create venv and install requirements
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install systemd service
sudo cp javris.service /etc/systemd/system/javris.service
sudo systemctl daemon-reload
sudo systemctl enable javris.service

echo "Javris OS installed successfully to /opt/javris."
echo "Run 'sudo systemctl start javris.service' to start the daemon."
