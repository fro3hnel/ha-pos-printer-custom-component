"""Runtime models for the POS printer integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry


@dataclass(slots=True)
class PrinterRuntimeData:
    """Runtime data for a configured printer."""

    entry_id: str | None
    printer_name: str
    print_topic: str
    status_topic: str
    log_topic: str
    ack_topic: str = ""
    availability_topic: str = ""
    unsub_ack: Callable[[], None] | None = None
    unsub_status: Callable[[], None] | None = None
    unsub_log: Callable[[], None] | None = None
    unsub_availability: Callable[[], None] | None = None
    unsub_heartbeat_timeout: Callable[[], None] | None = None
    available: bool = False
    availability_known: bool = False
    online: bool = False
    bridge_version: str | None = None
    last_status_at: float | None = None
    heartbeat_interval: int = 60
    default_paper_width: int = 80
    default_feed_after: int = 4
    last_status: dict[str, Any] = field(default_factory=dict)
    last_log: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DomainData:
    """Shared domain data stored in ``hass.data``."""

    printers: dict[str, PrinterRuntimeData] = field(default_factory=dict)
    services_registered: bool = False


PosPrinterConfigEntry = ConfigEntry[PrinterRuntimeData]
