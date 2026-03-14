"""Runtime models for the POS printer integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class PrinterRuntimeData:
    """Runtime data for a configured printer."""

    entry_id: str | None
    printer_name: str
    print_topic: str
    status_topic: str
    log_topic: str
    unsub_status: Callable[[], None] | None = None
    unsub_log: Callable[[], None] | None = None
    last_status: dict[str, Any] = field(default_factory=dict)
    last_log: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DomainData:
    """Shared domain data stored in ``hass.data``."""

    printers: dict[str, PrinterRuntimeData] = field(default_factory=dict)
    services_registered: bool = False
