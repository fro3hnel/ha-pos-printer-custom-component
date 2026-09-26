"""Common entities for the POS printer integration."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.core import Event, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_PRINTER_NAME, DOMAIN, EVENT_AVAILABILITY
from .models import PosPrinterConfigEntry, PrinterRuntimeData


class PosPrinterEntity(Entity):
    """Base entity with shared device and availability handling."""

    _attr_has_entity_name = True
    _attr_available = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        self._printer_name = printer_name
        self._entry_id = entry_id
        self._runtime_data = runtime_data
        self._unsubs: list[Callable[[], None]] = []
        if runtime_data is not None:
            self._attr_available = runtime_data.available

    async def async_added_to_hass(self) -> None:
        """Subscribe to bridge availability changes."""
        await super().async_added_to_hass()
        self._track_unsub(
            self.hass.bus.async_listen(EVENT_AVAILABILITY, self._handle_availability)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Remove all listeners when the entity leaves Home Assistant."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await super().async_will_remove_from_hass()

    def _track_unsub(self, unsub: Callable[[], None]) -> None:
        """Track an event unsubscribe callback."""
        self._unsubs.append(unsub)

    @property
    def device_info(self) -> DeviceInfo:
        """Return shared device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._printer_name)},
            name=self._printer_name,
            manufacturer="Bixolon",
            model="POS Printer Bridge",
        )

    @callback
    def _handle_availability(self, event: Event) -> None:
        """Update entity availability from bridge lifecycle messages."""
        if event.data.get(CONF_PRINTER_NAME) != self._printer_name:
            return
        self._attr_available = bool(event.data.get("available"))
        self._write_state_if_ready()

    def _match_event(self, event: Event) -> dict[str, Any] | None:
        """Return matching event data for this printer entity."""
        if event.data.get(CONF_PRINTER_NAME) != self._printer_name:
            return None
        if not self._attr_available:
            self._attr_available = True
        return event.data

    def _write_state_if_ready(self) -> None:
        """Write state only after the entity has been added to the platform."""
        if self.entity_id:
            self.async_write_ha_state()


def entry_printer_name(entry: PosPrinterConfigEntry) -> str:
    """Resolve the effective printer name for a config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    if isinstance(runtime_data, PrinterRuntimeData):
        return runtime_data.printer_name
    return entry.options.get(CONF_PRINTER_NAME, entry.data[CONF_PRINTER_NAME])


def entry_runtime_data(entry: PosPrinterConfigEntry) -> PrinterRuntimeData | None:
    """Return runtime data when the config entry has been set up."""
    runtime_data = getattr(entry, "runtime_data", None)
    return runtime_data if isinstance(runtime_data, PrinterRuntimeData) else None
