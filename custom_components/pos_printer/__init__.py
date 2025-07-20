from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .printer import setup_print_service
from .const import DOMAIN

PLATFORMS = ["sensor", "binary_sensor"]

async def async_setup(hass: HomeAssistant, config: dict):
    """Nur Legacy YAML, falls du das unterstützen willst."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data
    await setup_print_service(hass, entry.data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data[DOMAIN].pop(entry.entry_id)
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
