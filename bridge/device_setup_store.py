"""Persistent storage helpers for the Raspberry Pi setup portal."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

try:
    from .device_setup_models import BridgeSettings, SetupConfig
except ImportError:  # pragma: no cover - script execution on target image
    from device_setup_models import BridgeSettings, SetupConfig

DEFAULT_SETUP_CONFIG_PATH = Path("/etc/pos-printer-setup/config.json")
DEFAULT_BRIDGE_ENV_PATH = Path("/etc/default/pos-printer-bridge")


def load_setup_config(path: Path = DEFAULT_SETUP_CONFIG_PATH) -> SetupConfig:
    """Load the saved onboarding configuration or return defaults."""
    if not path.exists():
        return SetupConfig()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return SetupConfig()

    if not isinstance(payload, dict):
        return SetupConfig()
    return SetupConfig.from_mapping(payload)


def save_setup_config(config: SetupConfig, path: Path = DEFAULT_SETUP_CONFIG_PATH) -> None:
    """Persist onboarding settings in a single JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def render_bridge_env(settings: BridgeSettings) -> str:
    """Render the bridge environment file consumed by systemd."""
    values = {
        "MQTT_BROKER": settings.mqtt_broker,
        "MQTT_PORT": str(settings.mqtt_port),
        "MQTT_USERNAME": settings.mqtt_username,
        "MQTT_PASSWORD": settings.mqtt_password,
        "REDIS_URL": settings.redis_url,
        "PRINTER_PORT": settings.printer_port,
        "PRINTER_NAME": settings.printer_name,
        "LOG_LEVEL": settings.log_level,
        "HEARTBEAT_INTERVAL": str(settings.heartbeat_interval),
        "LEFT_MARGIN": str(settings.left_margin),
        "DEFAULT_WIDTH": str(settings.default_width),
        "IMAGE_FETCH_TIMEOUT": str(settings.image_fetch_timeout),
    }
    lines = [f"{key}={shlex.quote(value)}" for key, value in values.items()]
    return "\n".join(lines) + "\n"


def write_bridge_env(
    settings: BridgeSettings, path: Path = DEFAULT_BRIDGE_ENV_PATH
) -> None:
    """Write the bridge environment file to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_bridge_env(settings), encoding="utf-8")
