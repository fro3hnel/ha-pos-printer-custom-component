"""High-level configuration parsing and apply logic for device onboarding."""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

try:
    from .device_setup_models import ApplyResult, BridgeSettings, SetupConfig, WifiSettings
    from .device_setup_network import NetworkManager
    from .device_setup_store import DEFAULT_BRIDGE_ENV_PATH, write_bridge_env
except ImportError:  # pragma: no cover - script execution on target image
    from device_setup_models import ApplyResult, BridgeSettings, SetupConfig, WifiSettings
    from device_setup_network import NetworkManager
    from device_setup_store import DEFAULT_BRIDGE_ENV_PATH, write_bridge_env

LOGGER = logging.getLogger("device_setup")
PORTAL_DNSMASQ_SERVICE = "pos-printer-setup-dnsmasq.service"
BRIDGE_SERVICE = "pos-printer-bridge.service"
PRINTER_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


def systemctl(action: str, service: str) -> None:
    """Run a best-effort systemctl action for a unit."""
    completed = subprocess.run(
        ["systemctl", action, service],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        LOGGER.warning(
            "systemctl %s %s failed: %s",
            action,
            service,
            (completed.stderr or completed.stdout).strip(),
        )


def parse_setup_form(
    form: Mapping[str, Sequence[str]], current: SetupConfig
) -> tuple[SetupConfig, list[str]]:
    """Validate portal form input and merge it with existing secrets."""
    errors: list[str] = []

    def value(name: str) -> str:
        values = form.get(name, [""])
        if not values:
            return ""
        return str(values[0]).strip()

    def parse_int(name: str, *, minimum: int, maximum: int, default: int) -> int:
        raw = value(name)
        if not raw:
            return default
        try:
            parsed = int(raw)
        except ValueError:
            errors.append(f"{name} muss eine Zahl sein.")
            return default
        if parsed < minimum or parsed > maximum:
            errors.append(f"{name} muss zwischen {minimum} und {maximum} liegen.")
            return default
        return parsed

    action = value("action")
    wifi_ssid = "" if action == "clear_wifi" else value("wifi_ssid")
    wifi_password = value("wifi_password")
    if not wifi_password and wifi_ssid and wifi_ssid == current.wifi.ssid:
        wifi_password = current.wifi.password
    wifi = WifiSettings(
        ssid=wifi_ssid,
        password=wifi_password,
        hidden=bool(form.get("wifi_hidden")),
    )

    mqtt_broker = value("mqtt_broker") or current.bridge.mqtt_broker
    mqtt_username = value("mqtt_username")
    mqtt_password = value("mqtt_password")
    if not mqtt_password and mqtt_username == current.bridge.mqtt_username:
        mqtt_password = current.bridge.mqtt_password

    printer_name = value("printer_name") or current.bridge.printer_name
    if not PRINTER_NAME_RE.fullmatch(printer_name):
        errors.append("printer_name darf nur Kleinbuchstaben, Zahlen, Unterstriche und Bindestriche enthalten.")

    log_level = (value("log_level") or current.bridge.log_level).upper()
    if log_level not in LOG_LEVELS:
        errors.append("log_level muss DEBUG, INFO, WARNING oder ERROR sein.")
        log_level = current.bridge.log_level

    bridge = BridgeSettings(
        mqtt_broker=mqtt_broker,
        mqtt_port=parse_int(
            "mqtt_port", minimum=1, maximum=65535, default=current.bridge.mqtt_port
        ),
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        redis_url=value("redis_url") or current.bridge.redis_url,
        printer_port=value("printer_port") or current.bridge.printer_port,
        printer_name=printer_name,
        log_level=log_level,
        heartbeat_interval=parse_int(
            "heartbeat_interval",
            minimum=5,
            maximum=3600,
            default=current.bridge.heartbeat_interval,
        ),
        left_margin=parse_int(
            "left_margin", minimum=0, maximum=200, default=current.bridge.left_margin
        ),
        default_width=parse_int(
            "default_width", minimum=32, maximum=120, default=current.bridge.default_width
        ),
        image_fetch_timeout=parse_int(
            "image_fetch_timeout",
            minimum=1,
            maximum=120,
            default=current.bridge.image_fetch_timeout,
        ),
    )

    config = SetupConfig(version=current.version, wifi=wifi, bridge=bridge)
    return config, errors


def apply_configuration(
    config: SetupConfig,
    *,
    network_manager: NetworkManager | None = None,
    bridge_env_path: Path = DEFAULT_BRIDGE_ENV_PATH,
    service_runner=systemctl,
) -> ApplyResult:
    """Apply bridge settings and either join Wi-Fi or expose the setup AP."""
    network = network_manager or NetworkManager()
    write_bridge_env(config.bridge, path=bridge_env_path)

    def activate_access_point(reason: str) -> ApplyResult:
        network.ensure_access_point()
        service_runner("restart", PORTAL_DNSMASQ_SERVICE)
        service_runner("restart", BRIDGE_SERVICE)
        return ApplyResult(mode="access-point", message=reason)

    if config.wifi.is_configured():
        try:
            network.apply_wifi(config.wifi)
        except RuntimeError as exc:
            return activate_access_point(
                (
                    "WLAN-Verbindung fehlgeschlagen. "
                    "Der Setup-Access-Point bleibt aktiv: "
                    f"{exc}"
                )
            )

        network.disable_access_point()
        service_runner("stop", PORTAL_DNSMASQ_SERVICE)
        service_runner("restart", BRIDGE_SERVICE)
        return ApplyResult(
            mode="wifi",
            message=(
                "WLAN und Bridge-Konfiguration gespeichert. "
                "Der Raspberry Pi verbindet sich jetzt mit dem angegebenen Netzwerk."
            ),
        )

    return activate_access_point(
        (
            "Keine WLAN-Zugangsdaten gespeichert. "
            "Der Setup-Access-Point bleibt aktiv und stellt das Portal bereit."
        )
    )
