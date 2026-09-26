"""Binary sensor platform for the POS printer integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PRINTER_NAME, DOMAIN
from .entity import PosPrinterEntity, entry_printer_name, entry_runtime_data
from .models import PosPrinterConfigEntry, PrinterRuntimeData
from .sensor import JobErrorBinarySensor

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PosPrinterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up POS printer binary sensors."""
    del hass
    printer_name = entry_printer_name(entry)
    runtime_data = entry_runtime_data(entry)
    async_add_entities(
        [
            BridgeConnectedBinarySensor(
                printer_name, entry.entry_id, runtime_data
            ),
            JobErrorBinarySensor(printer_name, entry.entry_id, runtime_data),
        ]
    )


class BridgeConnectedBinarySensor(PosPrinterEntity, BinarySensorEntity):
    """Binary sensor showing whether the bridge is connected to MQTT."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "bridge_connected"
    _attr_translation_domain = DOMAIN

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_bridge_connected"
        self._attr_available = bool(
            runtime_data is not None and runtime_data.availability_known
        )
        self._attr_is_on = bool(runtime_data is not None and runtime_data.available)

    @callback
    def _handle_availability(self, event: Event) -> None:
        """Represent offline bridges as disconnected instead of unavailable."""
        if event.data.get(CONF_PRINTER_NAME) != self._printer_name:
            return
        self._attr_available = True
        self._attr_is_on = bool(event.data.get("available"))
        self._write_state_if_ready()
