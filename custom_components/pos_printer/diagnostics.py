"""Diagnostics support for the POS printer integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PRINTER_NAME, DOMAIN
from .models import DomainData, PrinterRuntimeData

_ENTRY_TO_REDACT = {CONF_PRINTER_NAME, "title"}
_RUNTIME_TO_REDACT = {
    CONF_PRINTER_NAME,
    "print",
    "status",
    "log",
    "job_id",
    "detail",
    "message",
    "file",
}


def _serialize_runtime(runtime: PrinterRuntimeData | None) -> dict[str, Any] | None:
    """Convert runtime data into a diagnostics-friendly structure."""
    if runtime is None:
        return None

    return {
        "entry_id": runtime.entry_id,
        "printer_name": runtime.printer_name,
        "topics": {
            "print": runtime.print_topic,
            "status": runtime.status_topic,
            "log": runtime.log_topic,
        },
        "last_status": runtime.last_status,
        "last_log": runtime.last_log,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    domain_data = hass.data.get(DOMAIN)
    runtime = None
    printer_name = entry.options.get(CONF_PRINTER_NAME, entry.data[CONF_PRINTER_NAME])
    if isinstance(domain_data, DomainData):
        runtime = domain_data.printers.get(printer_name)

    return {
        "entry": async_redact_data(entry.as_dict(), _ENTRY_TO_REDACT),
        "runtime": async_redact_data(_serialize_runtime(runtime), _RUNTIME_TO_REDACT),
        "registered_printers_count": (
            len(domain_data.printers) if isinstance(domain_data, DomainData) else 0
        ),
    }
