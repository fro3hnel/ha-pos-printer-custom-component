#!/bin/bash
# Simple install script for the POS-Printer Bridge service
set -e
TARGET_DIR="${1:-/opt/pos-printer-bridge}"
REPO_URL="https://github.com/fro3hnel/ha-pos-printer-custom-component.git"

echo "Installing to $TARGET_DIR"

sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-dev build-essential libbluetooth3 redis-server libssl-dev

sudo mkdir -p "$TARGET_DIR"
sudo chown "$USER" "$TARGET_DIR"

if [ ! -d "$TARGET_DIR/.git" ]; then
    git clone "$REPO_URL" "$TARGET_DIR"
else
    git -C "$TARGET_DIR" pull
fi

cd "$TARGET_DIR/bridge"
python3 -m venv .venv
source .venv/bin/activate
pip install .

echo "Installation complete. Start the service with:"
echo "$TARGET_DIR/bridge/.venv/bin/printer-bridge"
