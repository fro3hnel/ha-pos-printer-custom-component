"""Sensor platform for the POS printer integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PRINTER_NAME, DOMAIN, EVENT_BRIDGE_LOG, EVENT_STATUS, VERSION
from .models import PrinterRuntimeData

PARALLEL_UPDATES = 0


class PosPrinterEntity:
    """Base entity class with shared device metadata."""

    _attr_has_entity_name = True
    _attr_available = False

    def __init__(self, printer_name: str, entry_id: str) -> None:
        self._printer_name = printer_name
        self._entry_id = entry_id
        self._unsub: Callable[[], None] | None = None

    async def async_will_remove_from_hass(self) -> None:
        """Remove event listeners when the entity leaves Home Assistant."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @property
    def device_info(self) -> dict[str, Any]:
        """Return shared device information."""
        return {
            "identifiers": {(DOMAIN, self._printer_name)},
            "name": self._printer_name,
            "manufacturer": "Bixolon",
            "model": "POS Printer Bridge",
            "sw_version": VERSION,
        }

    def _match_event(self, event: Event) -> dict[str, Any] | None:
        """Return matching event data for this printer entity."""
        if event.data.get("printer_name") != self._printer_name:
            return None
        if not self._attr_available:
            self._attr_available = True
        return event.data

    def _write_state_if_ready(self) -> None:
        """Write state only after the entity has been added to the platform."""
        if self.entity_id:
            self.async_write_ha_state()


def _entry_printer_name(entry: ConfigEntry) -> str:
    """Resolve the effective printer name for a config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    if isinstance(runtime_data, PrinterRuntimeData):
        return runtime_data.printer_name
    return entry.options.get(CONF_PRINTER_NAME, entry.data[CONF_PRINTER_NAME])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up POS printer sensors for a config entry."""
    printer_name = _entry_printer_name(entry)
    entry_id = entry.entry_id

    async_add_entities(
        [
            LastJobStatusSensor(printer_name, entry_id),
            LastJobIdSensor(printer_name, entry_id),
            LastJobDetailSensor(printer_name, entry_id),
            LastStatusTimestampSensor(printer_name, entry_id),
            QueueLengthSensor(printer_name, entry_id),
            BridgeVersionSensor(printer_name, entry_id),
            LastBridgeLogSensor(printer_name, entry_id),
            SuccessfulJobsCounterSensor(printer_name, entry_id),
        ]
    )


class LastJobStatusSensor(PosPrinterEntity, SensorEntity):
    """Sensor for the status of the last print job."""

    _attr_translation_key = "last_job_status"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:printer-check"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Last Job Status"
        self._attr_unique_id = f"{entry_id}_last_job_status"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_STATUS, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        status = data.get("status")
        if status is not None:
            self._state = str(status)
            self._write_state_if_ready()


class LastJobIdSensor(PosPrinterEntity, SensorEntity):
    """Sensor for the ID of the last print job."""

    _attr_translation_key = "last_job_id"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:identifier"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Last Job ID"
        self._attr_unique_id = f"{entry_id}_last_job_id"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_STATUS, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        job_id = data.get("job_id")
        if job_id is not None:
            self._state = str(job_id)
            self._write_state_if_ready()


class LastJobDetailSensor(PosPrinterEntity, SensorEntity):
    """Sensor exposing the latest bridge detail message for a print job."""

    _attr_translation_key = "last_job_detail"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:text-box-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Last Job Detail"
        self._attr_unique_id = f"{entry_id}_last_job_detail"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_STATUS, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        detail = data.get("detail")
        if detail is not None:
            self._state = str(detail)
            self._write_state_if_ready()


class LastStatusTimestampSensor(PosPrinterEntity, SensorEntity):
    """Sensor for the timestamp of the last bridge update."""

    _attr_translation_key = "last_status_update"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = "timestamp"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Last Status Update"
        self._attr_unique_id = f"{entry_id}_last_status_update"
        self._timestamp: int | None = None

    @property
    def native_value(self) -> datetime | None:
        if self._timestamp is None:
            return None
        return datetime.fromtimestamp(self._timestamp, tz=timezone.utc)

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_STATUS, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        timestamp = data.get("timestamp")
        if isinstance(timestamp, (int, float)):
            self._timestamp = int(timestamp)
            self._write_state_if_ready()


class QueueLengthSensor(PosPrinterEntity, SensorEntity):
    """Sensor for the bridge queue length."""

    _attr_translation_key = "queue_length"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:format-list-numbered"
    _attr_native_unit_of_measurement = "jobs"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Queue Length"
        self._attr_unique_id = f"{entry_id}_queue_length"
        self._value: int | None = None

    @property
    def native_value(self) -> int | None:
        return self._value

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_STATUS, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        queue_length = data.get("queue_len")
        if isinstance(queue_length, int):
            self._value = queue_length
            self._write_state_if_ready()


class BridgeVersionSensor(PosPrinterEntity, SensorEntity):
    """Sensor showing the bridge software version."""

    _attr_translation_key = "bridge_version"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:tag-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Bridge Version"
        self._attr_unique_id = f"{entry_id}_bridge_version"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_STATUS, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        heartbeat = data.get("heartbeat")
        version = heartbeat.get("version") if isinstance(heartbeat, dict) else data.get("version")
        if version:
            self._state = str(version)
            self._write_state_if_ready()


class JobErrorBinarySensor(PosPrinterEntity, BinarySensorEntity):
    """Binary sensor that turns on when a print job errors."""

    _attr_device_class = "problem"
    _attr_translation_key = "job_error"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:alert-circle"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Job Error"
        self._attr_unique_id = f"{entry_id}_job_error"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_STATUS, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        status = data.get("status")
        is_error = status == "error"
        if is_error and not self._attr_is_on:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"{DOMAIN} - Print Job Error",
                        "message": (
                            f"Job {data.get('job_id')} failed: "
                            f"{data.get('detail', '')}"
                        ),
                    },
                )
            )
        self._attr_is_on = is_error
        self._write_state_if_ready()


class LastBridgeLogSensor(PosPrinterEntity, SensorEntity):
    """Sensor showing the latest bridge log message received via MQTT."""

    _attr_translation_key = "last_bridge_log"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:text-box-search-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Last Bridge Log"
        self._attr_unique_id = f"{entry_id}_last_bridge_log"
        self._message: str | None = None
        self._attrs: dict[str, str | int] = {}

    @property
    def native_value(self) -> str | None:
        return self._message

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        return self._attrs

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_BRIDGE_LOG, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        message = data.get("message")
        if message is None:
            return

        self._message = str(message)
        attrs: dict[str, str | int] = {}
        for key in ("level", "logger", "file"):
            value = data.get(key)
            if value is not None:
                attrs[key] = str(value)
        for key in ("timestamp", "line"):
            value = data.get(key)
            if isinstance(value, int):
                attrs[key] = value
        self._attrs = attrs
        self._write_state_if_ready()


class SuccessfulJobsCounterSensor(PosPrinterEntity, SensorEntity):
    """Sensor counting the number of successful print jobs."""

    _attr_translation_key = "successful_jobs"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "jobs"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, printer_name: str, entry_id: str) -> None:
        super().__init__(printer_name, entry_id)
        self._attr_name = f"{printer_name} Successful Jobs"
        self._attr_unique_id = f"{entry_id}_successful_jobs"
        self._count = 0

    @property
    def native_value(self) -> int:
        return self._count

    async def async_added_to_hass(self) -> None:
        self._unsub = self.hass.bus.async_listen(EVENT_STATUS, self._handle_event)

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        if data.get("status") == "success":
            self._count += 1
            self._write_state_if_ready()
