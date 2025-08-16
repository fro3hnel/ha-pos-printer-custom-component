"""Update platform for POS-Printer Bridge integration."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, VERSION
from .sensor import PosPrinterEntity

_LOGGER = logging.getLogger(__name__)

# Use component version from manifest
_COMPONENT_VERSION: str = VERSION


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the update entity."""
    printer_name = entry.data["printer_name"]
    entry_id = entry.entry_id

    entity = BridgeUpdateEntity(printer_name, entry_id)
    async_add_entities([entity])


class BridgeUpdateEntity(PosPrinterEntity, UpdateEntity):
    """Update entity handling bridge updates."""

    _attr_translation_key = "bridge_update"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:update"
    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_has_entity_name = True

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Bridge"
        self._attr_unique_id = f"{entry_id}_bridge_update"
        self._installed_version: str | None = None
        self._latest_version: str = _COMPONENT_VERSION

    @property
    def installed_version(self) -> str | None:
        return self._installed_version

    @property
    def latest_version(self) -> str | None:
        return self._latest_version

    async def async_added_to_hass(self) -> None:
        """Register event listener for heartbeat messages."""
        self.hass.bus.async_listen(f"{DOMAIN}.status", self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        """Handle status or heartbeat events to extract version."""
        if event.data.get("printer_name") != self._printer_name:
            return
        heartbeat: dict[str, Any] | None = event.data.get("heartbeat")
        if heartbeat and (version := heartbeat.get("version")):
            if version != self._installed_version:
                self._installed_version = str(version)
                if self.hass and self.entity_id:
                    self.async_write_ha_state()

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Trigger an update of the bridge software via MQTT."""
        target_version = version or self._latest_version
        payload = json.dumps({"version": target_version})
        topic = f"print/pos/{self._printer_name}/update"
        await mqtt.async_publish(self.hass, topic=topic, payload=payload, qos=1)
        _LOGGER.debug("Sent update command for version %s", target_version)
