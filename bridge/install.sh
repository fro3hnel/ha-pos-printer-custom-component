#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-/opt/pos-printer-bridge}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BRIDGE_SRC="${SCRIPT_DIR}"
SCHEMA_SRC="${REPO_ROOT}/schema/job.schema.json"
DEFAULT_ENV_TEMPLATE="${REPO_ROOT}/pi-gen-builder/stage-pos-printer/files/etc/default/pos-printer-bridge"

SERVICE_NAME="pos-printer-bridge.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
LEGACY_SERVICE_NAME="pos-printer.service"
LEGACY_SERVICE_FILE="/etc/systemd/system/${LEGACY_SERVICE_NAME}"
ENV_FILE="/etc/default/pos-printer-bridge"
SERVICE_USER="posprinter"
SERVICE_GROUP="posprinter"

log() {
    printf '[install] %s\n' "$*"
}

require_file() {
    local path="$1"
    if [ ! -f "$path" ]; then
        printf 'Missing required file: %s\n' "$path" >&2
        exit 1
    fi
}

ensure_group() {
    if ! getent group "${SERVICE_GROUP}" >/dev/null; then
        log "Creating system group ${SERVICE_GROUP}"
        sudo groupadd --system "${SERVICE_GROUP}"
    fi
}

ensure_user() {
    if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
        log "Creating system user ${SERVICE_USER}"
        sudo useradd \
            --system \
            --home "${TARGET_DIR}" \
            --shell /usr/sbin/nologin \
            --gid "${SERVICE_GROUP}" \
            "${SERVICE_USER}"
    fi

    getent group plugdev >/dev/null 2>&1 && sudo usermod -a -G plugdev "${SERVICE_USER}" || true
    getent group dialout >/dev/null 2>&1 && sudo usermod -a -G dialout "${SERVICE_USER}" || true
}

install_packages() {
    log "Installing runtime packages"
    sudo apt-get update
    sudo apt-get install -y \
        libbluetooth3 \
        python3 \
        python3-dotenv \
        python3-paho-mqtt \
        python3-pil \
        python3-psutil \
        python3-redis \
        redis-server \
        rsync
}

sync_runtime() {
    log "Syncing bridge runtime to ${TARGET_DIR}"
    sudo install -d -m 0755 "${TARGET_DIR}"
    sudo rsync -a --delete \
        --exclude '__pycache__/' \
        --exclude '.pytest_cache/' \
        --exclude 'tests/' \
        --exclude 'README.md' \
        --exclude 'install.sh' \
        --exclude 'create-image.py' \
        "${BRIDGE_SRC}/" "${TARGET_DIR}/"
    sudo install -d -m 0755 "${TARGET_DIR}/schema"
    sudo install -m 0644 "${SCHEMA_SRC}" "${TARGET_DIR}/schema/job.schema.json"
    sudo chmod 0755 "${TARGET_DIR}/configure.sh" "${TARGET_DIR}/uninstall.sh"
}

write_default_config() {
    if [ ! -f "${ENV_FILE}" ]; then
        log "Installing default configuration to ${ENV_FILE}"
        sudo install -D -m 0640 "${DEFAULT_ENV_TEMPLATE}" "${ENV_FILE}"
        sudo chown root:"${SERVICE_GROUP}" "${ENV_FILE}"
    else
        log "Keeping existing configuration at ${ENV_FILE}"
    fi

    sudo install -m 0640 "${ENV_FILE}" "${TARGET_DIR}/.env"
    sudo chown root:"${SERVICE_GROUP}" "${TARGET_DIR}/.env"
}

remove_legacy_service() {
    if [ -f "${LEGACY_SERVICE_FILE}" ]; then
        log "Removing legacy service ${LEGACY_SERVICE_NAME}"
        sudo systemctl disable --now "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
        sudo rm -f "${LEGACY_SERVICE_FILE}"
        sudo systemctl reset-failed "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
    fi
}

write_service_file() {
    log "Writing ${SERVICE_NAME}"
    sudo tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=POS Printer Bridge
After=network-online.target redis-server.service
Wants=network-online.target redis-server.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
SupplementaryGroups=plugdev dialout
WorkingDirectory=${TARGET_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 ${TARGET_DIR}/printer_bridge.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

prompt_configure() {
    if [ ! -t 0 ]; then
        log "Run sudo ${TARGET_DIR}/configure.sh to edit the bridge configuration"
        return
    fi

    local answer
    read -r -p "Run the bridge configurator now? [Y/n]: " answer || true
    case "${answer:-Y}" in
        [Yy]|[Yy][Ee][Ss])
            sudo "${TARGET_DIR}/configure.sh" "${TARGET_DIR}"
            ;;
        *)
            log "Skipping configurator; defaults remain in ${ENV_FILE}"
            ;;
    esac
}

main() {
    require_file "${BRIDGE_SRC}/printer_bridge.py"
    require_file "${BRIDGE_SRC}/configure.sh"
    require_file "${BRIDGE_SRC}/uninstall.sh"
    require_file "${SCHEMA_SRC}"
    require_file "${DEFAULT_ENV_TEMPLATE}"

    log "Installing POS Printer Bridge into ${TARGET_DIR}"
    install_packages
    ensure_group
    ensure_user
    sync_runtime
    write_default_config
    remove_legacy_service
    prompt_configure
    write_service_file

    log "Enabling redis-server.service"
    sudo systemctl enable --now redis-server.service
    log "Enabling ${SERVICE_NAME}"
    sudo systemctl daemon-reload
    sudo systemctl enable --now "${SERVICE_NAME}"

    log "Installation complete"
    log "Service: sudo systemctl status ${SERVICE_NAME}"
    log "Config: sudo ${TARGET_DIR}/configure.sh"
    log "Uninstall: sudo ${TARGET_DIR}/uninstall.sh"
}

main "$@"
