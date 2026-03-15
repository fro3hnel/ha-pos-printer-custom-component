#!/bin/bash -e

cp -a files/. "${ROOTFS_DIR}/"

on_chroot <<'EOF'
set -e

id -u posprinter >/dev/null 2>&1 || useradd --system --home /opt/pos-printer-bridge --shell /usr/sbin/nologin posprinter
getent group plugdev >/dev/null 2>&1 && usermod -a -G plugdev posprinter || true
getent group dialout >/dev/null 2>&1 && usermod -a -G dialout posprinter || true

install -d -m 0755 /etc/pos-printer-setup
chmod 0640 /etc/default/pos-printer-bridge
chmod 0600 /etc/pos-printer-setup/config.json

systemctl enable NetworkManager.service
systemctl enable redis-server.service
systemctl enable pos-printer-setup-apply.service
systemctl enable pos-printer-setup-portal.service
systemctl enable pos-printer-bridge.service
EOF
