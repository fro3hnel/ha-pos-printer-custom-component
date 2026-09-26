"""Button platform for bridge control actions."""

from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import PosPrinterEntity, entry_printer_name, entry_runtime_data
from .models import PosPrinterConfigEntry, PrinterRuntimeData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PosPrinterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up bridge control buttons."""
    printer_name = entry_printer_name(entry)
    entry_id = entry.entry_id
    runtime_data = entry_runtime_data(entry)
    async_add_entities([RestartButton(printer_name, entry_id, runtime_data)])


class RestartButton(PosPrinterEntity, ButtonEntity):
    """Button to restart the Raspberry Pi bridge via MQTT."""

    _attr_translation_key = "bridge_restart"
    _attr_translation_domain = DOMAIN
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_restart"

    async def async_press(self) -> None:
        """Publish a restart command."""
        topic = f"print/pos/{self._printer_name}/restart"
        await mqtt.async_publish(self.hass, topic=topic, payload="", qos=1)
        _LOGGER.debug("Sent restart command to %s", topic)
