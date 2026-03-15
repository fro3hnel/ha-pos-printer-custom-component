"""Tests for setup portal config persistence and form parsing."""

from __future__ import annotations

from pathlib import Path

from bridge.device_setup_models import BridgeSettings, SetupConfig, WifiSettings
from bridge.device_setup_network import parse_wifi_scan_output
from bridge.device_setup_service import apply_configuration, parse_setup_form
from bridge.device_setup_store import load_setup_config, render_bridge_env, save_setup_config


def test_render_bridge_env_quotes_sensitive_values() -> None:
    settings = BridgeSettings(
        mqtt_broker="broker.local",
        mqtt_username="bridge user",
        mqtt_password="pa ss",
        redis_url="redis://localhost:6379/0",
    )

    rendered = render_bridge_env(settings)

    assert "MQTT_BROKER=broker.local" in rendered
    assert "MQTT_USERNAME='bridge user'" in rendered
    assert "MQTT_PASSWORD='pa ss'" in rendered


def test_load_and_save_setup_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = SetupConfig(
        wifi=WifiSettings(ssid="Office", password="secret", hidden=True),
        bridge=BridgeSettings(mqtt_broker="mqtt.local", printer_name="frontdesk"),
    )

    save_setup_config(config, path=path)
    loaded = load_setup_config(path=path)

    assert loaded == config


def test_parse_setup_form_keeps_existing_secrets() -> None:
    current = SetupConfig(
        wifi=WifiSettings(ssid="Office", password="wifi-secret"),
        bridge=BridgeSettings(
            mqtt_broker="mqtt.local",
            mqtt_username="printer",
            mqtt_password="mqtt-secret",
            printer_name="frontdesk",
        ),
    )
    form = {
        "wifi_ssid": ["Office"],
        "wifi_password": [""],
        "mqtt_broker": ["mqtt.local"],
        "mqtt_port": ["1883"],
        "mqtt_username": ["printer"],
        "mqtt_password": [""],
        "redis_url": ["redis://localhost:6379/0"],
        "printer_port": ["USB:"],
        "printer_name": ["frontdesk"],
        "log_level": ["INFO"],
        "heartbeat_interval": ["60"],
        "left_margin": ["0"],
        "default_width": ["80"],
        "image_fetch_timeout": ["10"],
    }

    parsed, errors = parse_setup_form(form, current)

    assert errors == []
    assert parsed.wifi.password == "wifi-secret"
    assert parsed.bridge.mqtt_password == "mqtt-secret"


def test_parse_setup_form_rejects_invalid_printer_name() -> None:
    current = SetupConfig()
    form = {
        "wifi_ssid": [""],
        "wifi_password": [""],
        "mqtt_broker": ["mqtt.local"],
        "mqtt_port": ["1883"],
        "mqtt_username": [""],
        "mqtt_password": [""],
        "redis_url": ["redis://localhost:6379/0"],
        "printer_port": ["USB:"],
        "printer_name": ["Bad Printer"],
        "log_level": ["INFO"],
        "heartbeat_interval": ["60"],
        "left_margin": ["0"],
        "default_width": ["80"],
        "image_fetch_timeout": ["10"],
    }

    _, errors = parse_setup_form(form, current)

    assert errors == [
        "printer_name darf nur Kleinbuchstaben, Zahlen, Unterstriche und Bindestriche enthalten."
    ]


def test_parse_wifi_scan_output_deduplicates_by_signal() -> None:
    output = """
IN-USE:
SSID:Office
SIGNAL:62
SECURITY:WPA2

IN-USE:*
SSID:Office
SIGNAL:78
SECURITY:WPA2

IN-USE:
SSID:Guest
SIGNAL:51
SECURITY:
"""

    parsed = parse_wifi_scan_output(output)

    assert [network.ssid for network in parsed] == ["Office", "Guest"]
    assert parsed[0].in_use is True
    assert parsed[0].signal == 78
    assert parsed[1].security == "open"


def test_apply_configuration_falls_back_to_access_point(tmp_path: Path) -> None:
    actions: list[tuple[str, str]] = []

    class FailingNetwork:
        def apply_wifi(self, _wifi: WifiSettings) -> None:
            raise RuntimeError("connection failed")

        def ensure_access_point(self) -> None:
            actions.append(("nm", "ensure_access_point"))

        def disable_access_point(self) -> None:
            actions.append(("nm", "disable_access_point"))

    result = apply_configuration(
        SetupConfig(
            wifi=WifiSettings(ssid="Office", password="secret"),
            bridge=BridgeSettings(mqtt_broker="mqtt.local"),
        ),
        network_manager=FailingNetwork(),  # type: ignore[arg-type]
        bridge_env_path=tmp_path / "bridge.env",
        service_runner=lambda action, service: actions.append((action, service)),
    )

    assert result.mode == "access-point"
    assert ("nm", "ensure_access_point") in actions
    assert ("restart", "pos-printer-setup-dnsmasq.service") in actions
    assert ("restart", "pos-printer-bridge.service") in actions
