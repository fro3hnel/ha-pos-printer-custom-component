from __future__ import annotations
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .sensor import JobErrorBinarySensor

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    printer_name = entry.data["printer_name"]
    entry_id = entry.entry_id
    async_add_entities([JobErrorBinarySensor(printer_name, entry_id)])
