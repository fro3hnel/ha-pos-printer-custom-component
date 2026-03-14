"""The POS printer integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PRINTER_NAME, DOMAIN
from .models import PrinterRuntimeData
from .printer import async_register_services, setup_print_service, unload_print_service
from .repairs import async_clear_entry_issues, async_validate_entry_issues

PLATFORMS = ["sensor", "binary_sensor", "update", "button"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the POS printer domain."""
    del config
    await async_register_services(hass)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload an entry after options changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up POS-Printer Bridge from a config entry."""
    await async_register_services(hass)
    async_validate_entry_issues(hass, entry)

    printer_name = entry.options.get(CONF_PRINTER_NAME, entry.data[CONF_PRINTER_NAME])
    runtime_data = await setup_print_service(
        hass,
        {
            "entry_id": entry.entry_id,
            CONF_PRINTER_NAME: printer_name,
        },
    )
    entry.runtime_data = runtime_data
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a POS-Printer Bridge config entry."""
    runtime_data: PrinterRuntimeData | None = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and runtime_data is not None:
        await unload_print_service(
            hass,
            {
                "entry_id": entry.entry_id,
                CONF_PRINTER_NAME: runtime_data.printer_name,
            },
        )
        async_clear_entry_issues(hass, entry.entry_id)
        entry.runtime_data = None

    return unload_ok
