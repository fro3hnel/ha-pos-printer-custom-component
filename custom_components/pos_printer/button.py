"""Button platform for bridge control actions."""

from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import PosPrinterEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up bridge control buttons."""
    printer_name = entry.data["printer_name"]
    entry_id = entry.entry_id
    async_add_entities(
        [
            RestartButton(printer_name, entry_id),
            PiSoftwareUpdateButton(printer_name, entry_id),
        ]
    )


class RestartButton(PosPrinterEntity, ButtonEntity):
    """Button to restart the Raspberry Pi bridge via MQTT."""

    _attr_translation_key = "bridge_restart"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:restart"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Restart"
        self._attr_unique_id = f"{entry_id}_restart"

    async def async_press(self) -> None:
        """Publish a restart command."""
        topic = f"print/pos/{self._printer_name}/restart"
        await mqtt.async_publish(self.hass, topic=topic, payload="", qos=1)
        _LOGGER.debug("Sent restart command to %s", topic)


class PiSoftwareUpdateButton(PosPrinterEntity, ButtonEntity):
    """Button to trigger Raspberry Pi software updates."""

    _attr_translation_key = "pi_software_update"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:package-up"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Pi Software Update"
        self._attr_unique_id = f"{entry_id}_pi_software_update"

    async def async_press(self) -> None:
        """Publish a Pi software update command."""
        topic = f"print/pos/{self._printer_name}/pi_update"
        await mqtt.async_publish(self.hass, topic=topic, payload="", qos=1)
        _LOGGER.debug("Sent Pi software update command to %s", topic)
