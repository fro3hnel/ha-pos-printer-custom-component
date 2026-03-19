#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-/opt/pos-printer-bridge}"
ENV_FILE="/etc/default/pos-printer-bridge"
DOTENV_FILE="${TARGET_DIR}/.env"
SERVICE_NAME="pos-printer-bridge.service"
SERVICE_GROUP="posprinter"

DEFAULT_MQTT_BROKER="127.0.0.1"
DEFAULT_MQTT_PORT="1883"
DEFAULT_MQTT_USERNAME=""
DEFAULT_MQTT_PASSWORD=""
DEFAULT_REDIS_URL="redis://localhost:6379/0"
DEFAULT_PRINTER_PORT="USB:"
DEFAULT_PRINTER_NAME="pos_printer"
DEFAULT_LOG_LEVEL="INFO"
DEFAULT_HEARTBEAT_INTERVAL="60"
DEFAULT_LEFT_MARGIN="0"
DEFAULT_DEFAULT_WIDTH="80"
DEFAULT_IMAGE_FETCH_TIMEOUT="10"

log() {
    printf '[configure] %s\n' "$*"
}

load_defaults() {
    if [ -f "${ENV_FILE}" ]; then
        log "Using existing values from ${ENV_FILE} as defaults"
        set -a
        # shellcheck disable=SC1090
        . "${ENV_FILE}"
        set +a
    elif [ -f "${DOTENV_FILE}" ]; then
        log "Using existing values from ${DOTENV_FILE} as defaults"
        set -a
        # shellcheck disable=SC1090
        . "${DOTENV_FILE}"
        set +a
    fi

    MQTT_BROKER="${MQTT_BROKER:-${DEFAULT_MQTT_BROKER}}"
    MQTT_PORT="${MQTT_PORT:-${DEFAULT_MQTT_PORT}}"
    MQTT_USERNAME="${MQTT_USERNAME:-${DEFAULT_MQTT_USERNAME}}"
    MQTT_PASSWORD="${MQTT_PASSWORD:-${DEFAULT_MQTT_PASSWORD}}"
    REDIS_URL="${REDIS_URL:-${DEFAULT_REDIS_URL}}"
    PRINTER_PORT="${PRINTER_PORT:-${DEFAULT_PRINTER_PORT}}"
    PRINTER_NAME="${PRINTER_NAME:-${DEFAULT_PRINTER_NAME}}"
    LOG_LEVEL="${LOG_LEVEL:-${DEFAULT_LOG_LEVEL}}"
    HEARTBEAT_INTERVAL="${HEARTBEAT_INTERVAL:-${DEFAULT_HEARTBEAT_INTERVAL}}"
    LEFT_MARGIN="${LEFT_MARGIN:-${DEFAULT_LEFT_MARGIN}}"
    DEFAULT_WIDTH="${DEFAULT_WIDTH:-${DEFAULT_DEFAULT_WIDTH}}"
    IMAGE_FETCH_TIMEOUT="${IMAGE_FETCH_TIMEOUT:-${DEFAULT_IMAGE_FETCH_TIMEOUT}}"
}

prompt_value() {
    local var_name="$1"
    local label="$2"
    local default="$3"
    local input

    read -r -p "${label} [${default}]: " input || true
    printf -v "${var_name}" '%s' "${input:-${default}}"
}

prompt_secret() {
    local var_name="$1"
    local label="$2"
    local default="$3"
    local input

    if [ -n "${default}" ]; then
        read -r -s -p "${label} [hidden]: " input || true
    else
        read -r -s -p "${label} [empty]: " input || true
    fi
    printf '\n'
    printf -v "${var_name}" '%s' "${input:-${default}}"
}

prompt_int() {
    local var_name="$1"
    local label="$2"
    local default="$3"
    local minimum="$4"
    local maximum="$5"
    local value

    while true; do
        prompt_value value "${label}" "${default}"
        if [[ "${value}" =~ ^[0-9]+$ ]] && (( value >= minimum && value <= maximum )); then
            printf -v "${var_name}" '%s' "${value}"
            return
        fi
        printf 'Bitte einen Wert zwischen %s und %s eingeben.\n' "${minimum}" "${maximum}" >&2
    done
}

prompt_printer_name() {
    local value

    while true; do
        prompt_value value "Printer name" "${PRINTER_NAME}"
        if [[ "${value}" =~ ^[a-z0-9_-]+$ ]]; then
            PRINTER_NAME="${value}"
            return
        fi
        printf 'Nur Kleinbuchstaben, Zahlen, Unterstriche und Bindestriche sind erlaubt.\n' >&2
    done
}

prompt_log_level() {
    local value

    while true; do
        prompt_value value "Log level (DEBUG/INFO/WARNING/ERROR)" "${LOG_LEVEL}"
        case "${value^^}" in
            DEBUG|INFO|WARNING|ERROR)
                LOG_LEVEL="${value^^}"
                return
                ;;
            *)
                printf 'Bitte DEBUG, INFO, WARNING oder ERROR eingeben.\n' >&2
                ;;
        esac
    done
}

quote_env() {
    python3 -c 'import shlex, sys; print(shlex.quote(sys.argv[1]))' "$1"
}

render_env() {
    printf 'MQTT_BROKER=%s\n' "$(quote_env "${MQTT_BROKER}")"
    printf 'MQTT_PORT=%s\n' "$(quote_env "${MQTT_PORT}")"
    printf 'MQTT_USERNAME=%s\n' "$(quote_env "${MQTT_USERNAME}")"
    printf 'MQTT_PASSWORD=%s\n' "$(quote_env "${MQTT_PASSWORD}")"
    printf 'REDIS_URL=%s\n' "$(quote_env "${REDIS_URL}")"
    printf 'PRINTER_PORT=%s\n' "$(quote_env "${PRINTER_PORT}")"
    printf 'PRINTER_NAME=%s\n' "$(quote_env "${PRINTER_NAME}")"
    printf 'LOG_LEVEL=%s\n' "$(quote_env "${LOG_LEVEL}")"
    printf 'HEARTBEAT_INTERVAL=%s\n' "$(quote_env "${HEARTBEAT_INTERVAL}")"
    printf 'LEFT_MARGIN=%s\n' "$(quote_env "${LEFT_MARGIN}")"
    printf 'DEFAULT_WIDTH=%s\n' "$(quote_env "${DEFAULT_WIDTH}")"
    printf 'IMAGE_FETCH_TIMEOUT=%s\n' "$(quote_env "${IMAGE_FETCH_TIMEOUT}")"
}

write_env_file() {
    local path="$1"
    local tmp_file

    tmp_file="$(mktemp)"
    render_env >"${tmp_file}"
    sudo install -D -m 0640 "${tmp_file}" "${path}"
    sudo chown root:"${SERVICE_GROUP}" "${path}" 2>/dev/null || sudo chown root:root "${path}"
    rm -f "${tmp_file}"
}

maybe_restart_service() {
    local answer
    if [ ! -f "/etc/systemd/system/${SERVICE_NAME}" ] && [ ! -f "/lib/systemd/system/${SERVICE_NAME}" ]; then
        return
    fi

    read -r -p "Restart ${SERVICE_NAME} now? [Y/n]: " answer || true
    case "${answer:-Y}" in
        [Yy]|[Yy][Ee][Ss])
            sudo systemctl daemon-reload
            sudo systemctl restart "${SERVICE_NAME}"
            ;;
    esac
}

main() {
    load_defaults

    printf 'Bridge configuration\n'
    printf 'Values are written to %s and mirrored to %s.\n' "${ENV_FILE}" "${DOTENV_FILE}"

    prompt_value MQTT_BROKER "MQTT broker host/IP" "${MQTT_BROKER}"
    prompt_int MQTT_PORT "MQTT port" "${MQTT_PORT}" 1 65535
    prompt_value MQTT_USERNAME "MQTT username" "${MQTT_USERNAME}"
    prompt_secret MQTT_PASSWORD "MQTT password" "${MQTT_PASSWORD}"
    prompt_value REDIS_URL "Redis URL" "${REDIS_URL}"
    prompt_value PRINTER_PORT "Printer port" "${PRINTER_PORT}"
    prompt_printer_name
    prompt_log_level
    prompt_int HEARTBEAT_INTERVAL "Heartbeat interval (seconds)" "${HEARTBEAT_INTERVAL}" 5 3600
    prompt_int LEFT_MARGIN "Left margin" "${LEFT_MARGIN}" 0 200
    prompt_int DEFAULT_WIDTH "Default paper width" "${DEFAULT_WIDTH}" 32 120
    prompt_int IMAGE_FETCH_TIMEOUT "Image fetch timeout (seconds)" "${IMAGE_FETCH_TIMEOUT}" 1 120

    write_env_file "${ENV_FILE}"
    write_env_file "${DOTENV_FILE}"

    log "Configuration written to ${ENV_FILE}"
    log "Mirror .env written to ${DOTENV_FILE}"
    maybe_restart_service
}

main "$@"
