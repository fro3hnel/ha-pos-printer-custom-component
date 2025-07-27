#!/bin/bash
# Simple install script for the POS-Printer Bridge service
set -e
TARGET_DIR="${1:-/opt/pos-printer-bridge}"
REPO_URL="https://github.com/fro3hnel/ha-pos-printer-custom-component.git"

echo "Installing to $TARGET_DIR"

sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-dev build-essential libbluetooth3 redis-server libssl-dev python3-pil

sudo mkdir -p "$TARGET_DIR"
sudo chown "$USER" "$TARGET_DIR"

if [ ! -d "$TARGET_DIR/.git" ]; then
    git clone "$REPO_URL" "$TARGET_DIR"
else
    git -C "$TARGET_DIR" pull
fi

cd "$TARGET_DIR/bridge"
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install .

deactivate

sudo usermod -a -G plugdev "$USER"

SERVICE_FILE="/etc/systemd/system/pos-printer.service"
sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=POS Printer Bridge
After=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$TARGET_DIR/bridge
Environment="PYTHONUNBUFFERED=1"
ExecStart=$TARGET_DIR/bridge/.venv/bin/printer-bridge
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pos-printer.service

echo "Installation complete. Service installed as pos-printer.service"
echo "Use 'sudo systemctl status pos-printer.service' to check the status"

