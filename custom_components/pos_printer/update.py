"""Update platform for POS-Printer Bridge integration."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT_STATUS, VERSION
from .sensor import PosPrinterEntity, _entry_printer_name

_LOGGER = logging.getLogger(__name__)

# Use component version from manifest
_COMPONENT_VERSION: str = VERSION
_RELEASE_URL = "https://github.com/fro3hnel/ha-pos-printer-custom-component/releases"
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the update entity."""
    printer_name = _entry_printer_name(entry)
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
    _attr_release_url = _RELEASE_URL
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Bridge"
        self._attr_unique_id = f"{entry_id}_bridge_update"
        self._installed_version: str | None = None
        self._latest_version: str = _COMPONENT_VERSION
        self._unsub = None

    @property
    def installed_version(self) -> str | None:
        return self._installed_version

    @property
    def latest_version(self) -> str | None:
        return self._latest_version

    async def async_added_to_hass(self) -> None:
        """Register event listener for heartbeat messages."""
        self._unsub = self.hass.bus.async_listen(
            EVENT_STATUS, self._handle_event
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up listener on removal."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _handle_event(self, event: Event) -> None:
        """Handle status or heartbeat events to extract version."""
        if event.data.get("printer_name") != self._printer_name:
            return
        heartbeat: dict[str, Any] | None = event.data.get("heartbeat")
        version = (
            heartbeat.get("version")
            if heartbeat
            else event.data.get("version")
        )
        if version:
            if version != self._installed_version:
                self._installed_version = str(version)
                self._attr_available = True
                if self.hass and self.entity_id:
                    self.async_write_ha_state()

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Trigger an update of the bridge software via MQTT."""
        target_version = version or self._latest_version
        payload = json.dumps({"version": target_version})
        topic = f"print/pos/{self._printer_name}/update"
        await mqtt.async_publish(self.hass, topic=topic, payload=payload, qos=1)
        _LOGGER.debug("Sent update command for version %s", target_version)
