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

for cmd in docker git rsync; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "Missing required command: ${cmd}" >&2
        exit 1
    fi
done

if [ ! -d "${CUSTOM_STAGE_SRC}" ]; then
    echo "Missing custom stage directory: ${CUSTOM_STAGE_SRC}" >&2
    exit 1
fi

if [ ! -d "${BRIDGE_SRC}" ]; then
    echo "Missing bridge directory: ${BRIDGE_SRC}" >&2
    exit 1
fi

mkdir -p "${WORK_DIR}"

if [ ! -d "${PIGEN_DIR}/.git" ]; then
    git clone "${PIGEN_REPO}" "${PIGEN_DIR}"
fi

git -C "${PIGEN_DIR}" fetch --tags --prune origin
git -C "${PIGEN_DIR}" checkout "${PIGEN_REF}"

if git -C "${PIGEN_DIR}" ls-remote --exit-code --heads origin "${PIGEN_REF}" >/dev/null 2>&1; then
    git -C "${PIGEN_DIR}" pull --ff-only origin "${PIGEN_REF}"
fi

cp "${SCRIPT_DIR}/config" "${PIGEN_DIR}/config"

rm -rf "${CUSTOM_STAGE_DST}"
mkdir -p "${CUSTOM_STAGE_DST}"
rsync -a --delete "${CUSTOM_STAGE_SRC}/" "${CUSTOM_STAGE_DST}/"

mkdir -p "${BRIDGE_DST}"
install -m 0755 \
    "${BRIDGE_SRC}/printer_bridge.py" \
    "${BRIDGE_DST}/printer_bridge.py"

if [ -f "${BRIDGE_SRC}/LICENSE" ]; then
    install -m 0644 "${BRIDGE_SRC}/LICENSE" "${BRIDGE_DST}/LICENSE"
fi

mkdir -p "${CUSTOM_STAGE_DST}/files/opt/pos-printer-bridge/schema"
install -m 0644 \
    "${REPO_ROOT}/schema/job.schema.json" \
    "${CUSTOM_STAGE_DST}/files/opt/pos-printer-bridge/schema/job.schema.json"

pushd "${PIGEN_DIR}" >/dev/null
./build-docker.sh "$@"
popd >/dev/null

echo "Image build finished. Output is in: ${PIGEN_DIR}/deploy"
