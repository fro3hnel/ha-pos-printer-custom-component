#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-/opt/pos-printer-bridge}"
SERVICE_NAME="pos-printer-bridge.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
ENV_FILE="/etc/default/pos-printer-bridge"
SERVICE_USER="posprinter"
SERVICE_GROUP="posprinter"

KEEP_CONFIG=0
KEEP_USER=0
ASSUME_YES=0

log() {
    printf '[uninstall] %s\n' "$*"
}

usage() {
    cat <<EOF
Usage: $0 [--keep-config] [--keep-user] [--yes] [target-dir]

Options:
  --keep-config  Keep ${ENV_FILE}
  --keep-user    Keep the ${SERVICE_USER} system user and group
  --yes          Skip the confirmation prompt
EOF
}

while (($# > 0)); do
    case "$1" in
        --keep-config)
            KEEP_CONFIG=1
            shift
            ;;
        --keep-user)
            KEEP_USER=1
            shift
            ;;
        --yes)
            ASSUME_YES=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            TARGET_DIR="$1"
            shift
            ;;
    esac
done

confirm() {
    local answer
    if (( ASSUME_YES == 1 )); then
        return
    fi

    printf 'This removes %s and %s' "${SERVICE_NAME}" "${TARGET_DIR}"
    if (( KEEP_CONFIG == 0 )); then
        printf ', plus %s' "${ENV_FILE}"
    fi
    printf '.\n'
    read -r -p "Continue? [y/N]: " answer || true
    case "${answer:-N}" in
        [Yy]|[Yy][Ee][Ss]) ;;
        *)
            log "Aborted"
            exit 1
            ;;
    esac
}

remove_service() {
    log "Stopping and disabling ${SERVICE_NAME}"
    sudo systemctl disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
    sudo rm -f "${SERVICE_FILE}"
    sudo systemctl daemon-reload
    sudo systemctl reset-failed "${SERVICE_NAME}" >/dev/null 2>&1 || true
}

remove_files() {
    log "Removing ${TARGET_DIR}"
    sudo rm -rf "${TARGET_DIR}"

    if (( KEEP_CONFIG == 0 )); then
        log "Removing ${ENV_FILE}"
        sudo rm -f "${ENV_FILE}"
    else
        log "Keeping ${ENV_FILE}"
    fi
}

remove_identity() {
    if (( KEEP_USER == 1 )); then
        log "Keeping ${SERVICE_USER} user and group"
        return
    fi

    if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
        log "Removing user ${SERVICE_USER}"
        sudo userdel "${SERVICE_USER}" >/dev/null 2>&1 || true
    fi

    if getent group "${SERVICE_GROUP}" >/dev/null 2>&1; then
        log "Removing group ${SERVICE_GROUP}"
        sudo groupdel "${SERVICE_GROUP}" >/dev/null 2>&1 || true
    fi
}

main() {
    confirm
    remove_service
    remove_files
    remove_identity
    log "Uninstall complete"
    log "Runtime packages were left installed"
}

main "$@"
