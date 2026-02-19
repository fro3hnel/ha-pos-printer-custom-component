#!/bin/bash -e

install -d "${ROOTFS_DIR}/opt/pos-printer-bridge"
cp -a files/opt/pos-printer-bridge/. "${ROOTFS_DIR}/opt/pos-printer-bridge/"

install -D -m 0644 \
    files/etc/default/pos-printer-bridge \
    "${ROOTFS_DIR}/etc/default/pos-printer-bridge"

install -D -m 0644 \
    files/etc/systemd/system/pos-printer-bridge.service \
    "${ROOTFS_DIR}/etc/systemd/system/pos-printer-bridge.service"

on_chroot <<'EOF'
set -e

id -u posprinter >/dev/null 2>&1 || useradd --system --home /opt/pos-printer-bridge --shell /usr/sbin/nologin posprinter
getent group plugdev >/dev/null 2>&1 && usermod -a -G plugdev posprinter || true
getent group dialout >/dev/null 2>&1 && usermod -a -G dialout posprinter || true

chown -R posprinter:posprinter /opt/pos-printer-bridge
chmod 640 /etc/default/pos-printer-bridge

systemctl enable redis-server.service
systemctl enable pos-printer-bridge.service
EOF
