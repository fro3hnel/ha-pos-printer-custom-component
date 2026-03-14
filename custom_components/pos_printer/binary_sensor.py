"""Binary sensor platform for the POS printer integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .sensor import JobErrorBinarySensor, _entry_printer_name

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up POS printer binary sensors."""
    del hass
    printer_name = _entry_printer_name(entry)
    async_add_entities([JobErrorBinarySensor(printer_name, entry.entry_id)])
