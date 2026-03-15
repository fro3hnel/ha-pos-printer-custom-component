"""Typed configuration models for Raspberry Pi provisioning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class WifiSettings:
    """Wi-Fi client credentials stored for device onboarding."""

    ssid: str = ""
    password: str = ""
    hidden: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "WifiSettings":
        data = dict(payload or {})
        return cls(
            ssid=str(data.get("ssid", "")).strip(),
            password=str(data.get("password", "")),
            hidden=_as_bool(data.get("hidden", False)),
        )

    def is_configured(self) -> bool:
        return bool(self.ssid.strip())


@dataclass(slots=True)
class BridgeSettings:
    """Environment-backed printer bridge settings."""

    mqtt_broker: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    redis_url: str = "redis://localhost:6379/0"
    printer_port: str = "USB:"
    printer_name: str = "pos_printer"
    log_level: str = "INFO"
    heartbeat_interval: int = 60
    left_margin: int = 0
    default_width: int = 80
    image_fetch_timeout: int = 10

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "BridgeSettings":
        data = dict(payload or {})
        defaults = cls()
        return cls(
            mqtt_broker=str(data.get("mqtt_broker", defaults.mqtt_broker)).strip()
            or defaults.mqtt_broker,
            mqtt_port=_as_int(data.get("mqtt_port"), defaults.mqtt_port),
            mqtt_username=str(data.get("mqtt_username", "")),
            mqtt_password=str(data.get("mqtt_password", "")),
            redis_url=str(data.get("redis_url", defaults.redis_url)).strip() or defaults.redis_url,
            printer_port=str(data.get("printer_port", defaults.printer_port)).strip()
            or defaults.printer_port,
            printer_name=str(data.get("printer_name", defaults.printer_name)).strip()
            or defaults.printer_name,
            log_level=str(data.get("log_level", defaults.log_level)).strip().upper()
            or defaults.log_level,
            heartbeat_interval=_as_int(
                data.get("heartbeat_interval"), defaults.heartbeat_interval
            ),
            left_margin=_as_int(data.get("left_margin"), defaults.left_margin),
            default_width=_as_int(data.get("default_width"), defaults.default_width),
            image_fetch_timeout=_as_int(
                data.get("image_fetch_timeout"), defaults.image_fetch_timeout
            ),
        )


@dataclass(slots=True)
class SetupConfig:
    """Combined onboarding configuration."""

    version: int = 1
    wifi: WifiSettings = field(default_factory=WifiSettings)
    bridge: BridgeSettings = field(default_factory=BridgeSettings)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "SetupConfig":
        data = dict(payload or {})
        return cls(
            version=_as_int(data.get("version"), 1),
            wifi=WifiSettings.from_mapping(data.get("wifi")),
            bridge=BridgeSettings.from_mapping(data.get("bridge")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WifiNetwork:
    """Visible Wi-Fi network entry from nmcli scan output."""

    ssid: str
    signal: int
    security: str
    in_use: bool = False


@dataclass(slots=True)
class DeviceStatus:
    """Current runtime status shown in the setup portal."""

    mode: str
    hostname: str
    ip_address: str
    client_ssid: str
    access_point_ssid: str
    saved_wifi_ssid: str
    networks: list[WifiNetwork] = field(default_factory=list)


@dataclass(slots=True)
class ApplyResult:
    """Result of applying saved onboarding settings."""

    mode: str
    message: str
