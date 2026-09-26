"""The POS printer integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_FEED_AFTER,
    CONF_PAPER_WIDTH,
    CONF_PRINTER_NAME,
    DEFAULT_FEED_AFTER,
    DEFAULT_PAPER_WIDTH,
    DOMAIN,
)
from .models import PosPrinterConfigEntry, PrinterRuntimeData
from .printer import async_register_services, setup_print_service, unload_print_service
from .repairs import (
    async_clear_entry_issues,
    async_validate_entry_issues,
    async_validate_legacy_mqtt_discovery_issue,
)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

_DEPRECATED_ENTITIES = (
    (Platform.UPDATE, "bridge_update"),
    (Platform.BUTTON, "pi_software_update"),
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the POS printer domain."""
    del config
    await async_register_services(hass)
    return True


async def _async_reload_entry(
    hass: HomeAssistant, entry: PosPrinterConfigEntry
) -> None:
    """Reload an entry after options changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: PosPrinterConfigEntry
) -> bool:
    """Set up POS-Printer Bridge from a config entry."""
    await async_register_services(hass)
    async_validate_entry_issues(hass, entry)
    async_validate_legacy_mqtt_discovery_issue(hass, entry)

    printer_name = entry.options.get(CONF_PRINTER_NAME, entry.data[CONF_PRINTER_NAME])
    runtime_data = await setup_print_service(
        hass,
        {
            "entry_id": entry.entry_id,
            CONF_PRINTER_NAME: printer_name,
            CONF_PAPER_WIDTH: entry.options.get(
                CONF_PAPER_WIDTH, DEFAULT_PAPER_WIDTH
            ),
            CONF_FEED_AFTER: entry.options.get(CONF_FEED_AFTER, DEFAULT_FEED_AFTER),
        },
    )
    entry.runtime_data = runtime_data
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PosPrinterConfigEntry
) -> bool:
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


async def async_migrate_entry(
    hass: HomeAssistant, entry: PosPrinterConfigEntry
) -> bool:
    """Migrate identity options and remove unsupported host controls."""
    if entry.version >= 3:
        return True

    data = dict(entry.data)
    options = dict(entry.options)
    title = entry.title
    unique_id = entry.unique_id

    if entry.version < 2:
        printer_name = options.pop(CONF_PRINTER_NAME, data[CONF_PRINTER_NAME])
        data[CONF_PRINTER_NAME] = printer_name
        title = printer_name
        unique_id = printer_name

    registry = er.async_get(hass)
    for platform, unique_id_suffix in _DEPRECATED_ENTITIES:
        entity_id = registry.async_get_entity_id(
            platform,
            DOMAIN,
            f"{entry.entry_id}_{unique_id_suffix}",
        )
        if entity_id is not None:
            registry.async_remove(entity_id)

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        title=title,
        unique_id=unique_id,
        version=3,
    )
    return True
