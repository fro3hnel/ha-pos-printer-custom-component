from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .printer import setup_print_service
from .sensor import async_setup_entry as async_setup_sensors
from .const import DOMAIN

async def async_setup(hass: HomeAssistant, config: dict):
    """Nur Legacy YAML, falls du das unterstützen willst."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data
    await setup_print_service(hass, entry.data)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    # hier ggf. unsubscribe und cleanup
    hass.data[DOMAIN].pop(entry.entry_id)
    return True