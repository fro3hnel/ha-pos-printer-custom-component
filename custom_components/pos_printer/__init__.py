from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .printer import setup_print_service
from .const import DOMAIN

PLATFORMS = ["sensor", "binary_sensor"]

async def async_setup(hass: HomeAssistant, config: dict):
    """Nur Legacy YAML, falls du das unterstützen willst."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up POS-Printer Bridge from a config entry."""
    entry.runtime_data = entry.data
    await setup_print_service(hass, entry.runtime_data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a POS-Printer Bridge config entry."""
    entry.runtime_data = None
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
