"""Sensor platform for the POS printer integration."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT_BRIDGE_LOG, EVENT_STATUS
from .entity import PosPrinterEntity, entry_printer_name, entry_runtime_data
from .models import PosPrinterConfigEntry, PrinterRuntimeData

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PosPrinterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up POS printer sensors for a config entry."""
    printer_name = entry_printer_name(entry)
    entry_id = entry.entry_id
    runtime_data = entry_runtime_data(entry)

    async_add_entities(
        [
            LastJobStatusSensor(printer_name, entry_id, runtime_data),
            LastJobIdSensor(printer_name, entry_id, runtime_data),
            LastJobDetailSensor(printer_name, entry_id, runtime_data),
            LastStatusTimestampSensor(printer_name, entry_id, runtime_data),
            QueueLengthSensor(printer_name, entry_id, runtime_data),
            BridgeVersionSensor(printer_name, entry_id, runtime_data),
            LastBridgeLogSensor(printer_name, entry_id, runtime_data),
            SuccessfulJobsCounterSensor(printer_name, entry_id, runtime_data),
        ]
    )


class LastJobStatusSensor(PosPrinterEntity, SensorEntity):
    """Sensor for the status of the last print job."""

    _attr_translation_key = "last_job_status"
    _attr_translation_domain = DOMAIN
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "queued",
        "duplicate",
        "printing",
        "success",
        "partial-error",
        "error",
        "expired",
    ]

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_last_job_status"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_unsub(self.hass.bus.async_listen(EVENT_STATUS, self._handle_event))

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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_last_job_id"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_unsub(self.hass.bus.async_listen(EVENT_STATUS, self._handle_event))

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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_last_job_detail"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_unsub(self.hass.bus.async_listen(EVENT_STATUS, self._handle_event))

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
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_last_status_update"
        self._timestamp: int | None = None

    @property
    def native_value(self) -> datetime | None:
        if self._timestamp is None:
            return None
        return datetime.fromtimestamp(self._timestamp, tz=timezone.utc)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_unsub(self.hass.bus.async_listen(EVENT_STATUS, self._handle_event))

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
    _attr_native_unit_of_measurement = "jobs"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_queue_length"
        self._value: int | None = None

    @property
    def native_value(self) -> int | None:
        return self._value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_unsub(self.hass.bus.async_listen(EVENT_STATUS, self._handle_event))

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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_bridge_version"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_unsub(self.hass.bus.async_listen(EVENT_STATUS, self._handle_event))

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

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "job_error"
    _attr_translation_domain = DOMAIN

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_job_error"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_unsub(self.hass.bus.async_listen(EVENT_STATUS, self._handle_event))

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        status = data.get("status")
        if status is None:
            return
        self._attr_is_on = status in {"error", "partial-error", "expired"}
        self._write_state_if_ready()


class LastBridgeLogSensor(PosPrinterEntity, SensorEntity):
    """Sensor showing the latest bridge log message received via MQTT."""

    _attr_translation_key = "last_bridge_log"
    _attr_translation_domain = DOMAIN
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
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
        await super().async_added_to_hass()
        self._track_unsub(
            self.hass.bus.async_listen(EVENT_BRIDGE_LOG, self._handle_event)
        )

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
    """Sensor exposing the bridge-persisted successful print-job count."""

    _attr_translation_key = "successful_jobs"
    _attr_translation_domain = DOMAIN
    _attr_native_unit_of_measurement = "jobs"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        printer_name: str,
        entry_id: str,
        runtime_data: PrinterRuntimeData | None = None,
    ) -> None:
        super().__init__(printer_name, entry_id, runtime_data)
        self._attr_unique_id = f"{entry_id}_successful_jobs"
        self._count = 0

    @property
    def native_value(self) -> int:
        return self._count

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_unsub(self.hass.bus.async_listen(EVENT_STATUS, self._handle_event))

    @callback
    def _handle_event(self, event: Event) -> None:
        data = self._match_event(event)
        if data is None:
            return

        successful_jobs = data.get("successful_jobs")
        if isinstance(successful_jobs, int):
            self._count = successful_jobs
            self._write_state_if_ready()
