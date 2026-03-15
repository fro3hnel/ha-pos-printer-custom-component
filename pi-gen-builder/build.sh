#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PIGEN_REPO="${PIGEN_REPO:-https://github.com/RPi-Distro/pi-gen.git}"
PIGEN_REF="${PIGEN_REF:-master}"
WORK_DIR="${WORK_DIR:-${SCRIPT_DIR}/.work}"
PIGEN_DIR="${PIGEN_DIR:-${WORK_DIR}/pi-gen}"
CUSTOM_STAGE_NAME="stage-pos-printer"
CUSTOM_STAGE_SRC="${SCRIPT_DIR}/${CUSTOM_STAGE_NAME}"
CUSTOM_STAGE_DST="${PIGEN_DIR}/${CUSTOM_STAGE_NAME}"
BRIDGE_SRC="${REPO_ROOT}/bridge"
BRIDGE_DST="${CUSTOM_STAGE_DST}/files/opt/pos-printer-bridge"
GENERATED_CONFIG="${WORK_DIR}/config.generated"

log() {
    printf '[pi-gen-builder] %s\n' "$*"
}

require_command() {
    local cmd="$1"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "Missing required command: ${cmd}" >&2
        exit 1
    fi
}

ensure_checkout() {
    if [ ! -d "${PIGEN_DIR}/.git" ]; then
        log "Cloning pi-gen from ${PIGEN_REPO}"
        git clone "${PIGEN_REPO}" "${PIGEN_DIR}"
    fi

    log "Fetching latest pi-gen refs"
    git -C "${PIGEN_DIR}" fetch --tags --prune origin

    if git -C "${PIGEN_DIR}" rev-parse --verify --quiet "refs/remotes/origin/${PIGEN_REF}" >/dev/null; then
        log "Checking out pi-gen branch origin/${PIGEN_REF}"
        git -C "${PIGEN_DIR}" -c advice.detachedHead=false checkout --detach "origin/${PIGEN_REF}"
        return
    fi

    log "Checking out pi-gen ref ${PIGEN_REF}"
    git -C "${PIGEN_DIR}" -c advice.detachedHead=false checkout --detach "${PIGEN_REF}"
}

sync_custom_stage() {
    log "Preparing custom stage ${CUSTOM_STAGE_NAME}"
    rm -rf "${CUSTOM_STAGE_DST}"
    mkdir -p "${CUSTOM_STAGE_DST}"
    rsync -a --delete "${CUSTOM_STAGE_SRC}/" "${CUSTOM_STAGE_DST}/"

    log "Syncing bridge runtime into custom stage"
    mkdir -p "${BRIDGE_DST}"
    rsync -a --delete \
        --exclude '__pycache__/' \
        --exclude '.pytest_cache/' \
        --exclude 'tests/' \
        --exclude '*.pyc' \
        --exclude 'README.md' \
        --exclude 'install.sh' \
        --exclude 'create-image.py' \
        "${BRIDGE_SRC}/" "${BRIDGE_DST}/"

    mkdir -p "${BRIDGE_DST}/schema"
    install -m 0644 \
        "${REPO_ROOT}/schema/job.schema.json" \
        "${BRIDGE_DST}/schema/job.schema.json"
}

write_generated_config() {
    log "Generating pi-gen config"
    cp "${SCRIPT_DIR}/config" "${GENERATED_CONFIG}"
    cp "${GENERATED_CONFIG}" "${PIGEN_DIR}/config"
}

main() {
    require_command docker
    require_command git
    require_command rsync

    if [ ! -d "${CUSTOM_STAGE_SRC}" ]; then
        echo "Missing custom stage directory: ${CUSTOM_STAGE_SRC}" >&2
        exit 1
    fi

    if [ ! -d "${BRIDGE_SRC}" ]; then
        echo "Missing bridge directory: ${BRIDGE_SRC}" >&2
        exit 1
    fi

    mkdir -p "${WORK_DIR}"

    ensure_checkout
    write_generated_config
    sync_custom_stage

    log "Starting pi-gen build"
    pushd "${PIGEN_DIR}" >/dev/null
    ./build-docker.sh "$@"
    popd >/dev/null

    log "Image build finished. Output is in: ${PIGEN_DIR}/deploy"
}

main "$@"
