"""Sensor platform for POS-Printer Bridge integration."""

from __future__ import annotations
from datetime import datetime
import logging

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up POS-Printer Bridge sensors when a config entry is added.
    """
    printer_name = entry.data["printer_name"]
    entry_id = entry.entry_id

    sensors: list[SensorEntity | BinarySensorEntity] = [
        LastJobStatusSensor(printer_name, entry_id),
        LastJobIdSensor(printer_name, entry_id),
        LastStatusTimestampSensor(printer_name, entry_id),
        SuccessfulJobsCounterSensor(printer_name, entry_id),
    ]

    async_add_entities(sensors)


class LastJobStatusSensor(SensorEntity):
    """Sensor for the status of the last print job."""

    _attr_translation_key = "last_job_status"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:printer-3d-check"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        self._printer_name = printer_name
        self._attr_name = f"{printer_name} Last Job Status"
        self._attr_unique_id = f"{entry_id}_last_job_status"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        # Listen to our custom status events
        self.hass.bus.async_listen(f"{DOMAIN}.status", self._handle_event)

    async def async_will_remove_from_hass(self) -> None:
        if hasattr(self, '_unsub'):
            self._unsub()

    @callback
    def _handle_event(self, event: Event) -> None:
        status = event.data.get("status")
        if status is not None:
            self._state = status
            self.async_write_ha_state()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._printer_name)},  # oder entry_id
            "name": self._printer_name,
            "manufacturer": "Bixolon",
            "model": "POS Printer Bridge",
            "sw_version": "1.0.0",
        }


class LastJobIdSensor(SensorEntity):
    """Sensor for the ID of the last print job."""

    _attr_translation_key = "last_job_id"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:identifier"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        self._printer_name = printer_name
        self._attr_name = f"{printer_name} Last Job ID"
        self._attr_unique_id = f"{entry_id}_last_job_id"
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        self.hass.bus.async_listen(f"{DOMAIN}.status", self._handle_event)

    async def async_will_remove_from_hass(self) -> None:
        if hasattr(self, '_unsub'):
            self._unsub()

    @callback
    def _handle_event(self, event: Event) -> None:
        job_id = event.data.get("job_id")
        if job_id is not None:
            self._state = job_id
            self.async_write_ha_state()
            
    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._printer_name)},  # oder entry_id
            "name": self._printer_name,
            "manufacturer": "Bixolon",
            "model": "POS Printer Bridge",
            "sw_version": "1.0.0",
        }


class LastStatusTimestampSensor(SensorEntity):
    """Sensor for the timestamp of the last status update."""

    _attr_translation_key = "last_status_update"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = "timestamp"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        self._printer_name = printer_name
        self._attr_name = f"{printer_name} Last Status Update"
        self._attr_unique_id = f"{entry_id}_last_status_update"
        self._timestamp: int | None = None

    @property
    def native_value(self) -> datetime | None:
        if self._timestamp is None:
            return None
        return datetime.fromtimestamp(self._timestamp)

    async def async_added_to_hass(self) -> None:
        self.hass.bus.async_listen(f"{DOMAIN}.status", self._handle_event)

    async def async_will_remove_from_hass(self) -> None:
        if hasattr(self, '_unsub'):
            self._unsub()

    @callback
    def _handle_event(self, event: Event) -> None:
        ts = event.data.get("timestamp")
        if isinstance(ts, (int, float)):
            self._timestamp = ts
            self.async_write_ha_state()
            
    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._printer_name)},  # oder entry_id
            "name": self._printer_name,
            "manufacturer": "Bixolon",
            "model": "POS Printer Bridge",
            "sw_version": "1.0.0",
        }



class JobErrorBinarySensor(BinarySensorEntity):
    """Binary sensor that turns on when a print job errors."""

    _attr_device_class = "problem"
    _attr_translation_key = "job_error"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:alert-circle"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        self._printer_name = printer_name
        self._attr_name = f"{printer_name} Job Error"
        self._attr_unique_id = f"{entry_id}_job_error"
        self._attr_is_on = False  # <-- wichtig für HA Core

    async def async_added_to_hass(self) -> None:
        # Listener speichern zum späteren Abmelden
        self._unsub = self.hass.bus.async_listen(f"{DOMAIN}.status", self._handle_event)

    async def async_will_remove_from_hass(self) -> None:
        if hasattr(self, "_unsub"):
            self._unsub()

    @callback
    def _handle_event(self, event: Event) -> None:
        status = event.data.get("status")
        is_error = status == "error"
        # Nur Notification erzeugen, wenn Status jetzt auf Error wechselt
        if is_error and not self._attr_is_on:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"{DOMAIN} – Print Job Error",
                        "message": (
                            f"Job {event.data.get('job_id')} failed: "
                            f"{event.data.get('detail', '')}"
                        ),
                    },
                )
            )
        self._attr_is_on = is_error
        self.async_write_ha_state()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._printer_name)},
            "name": self._printer_name,
            "manufacturer": "Bixolon",
            "model": "POS Printer Bridge",
            "sw_version": "1.0.0",
        }
            
    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._printer_name)},  # oder entry_id
            "name": self._printer_name,
            "manufacturer": "Bixolon",
            "model": "POS Printer Bridge",
            "sw_version": "1.0.0",
        }


class SuccessfulJobsCounterSensor(SensorEntity):
    """Sensor counting the number of successful print jobs."""

    _attr_translation_key = "successful_jobs"
    _attr_translation_domain = DOMAIN
    _attr_icon = "mdi:counter"

    def __init__(self, printer_name: str, entry_id: str) -> None:
        self._printer_name = printer_name
        self._attr_name = f"{printer_name} Successful Jobs"
        self._attr_unique_id = f"{entry_id}_successful_jobs"
        self._count: int = 0

    @property
    def native_value(self) -> int:
        return self._count

    async def async_added_to_hass(self) -> None:
        self.hass.bus.async_listen(f"{DOMAIN}.status", self._handle_event)

    async def async_will_remove_from_hass(self) -> None:
        if hasattr(self, '_unsub'):
            self._unsub()

    @callback
    def _handle_event(self, event: Event) -> None:
        if event.data.get("status") == "success":
            self._count += 1
            self.async_write_ha_state()
            
    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._printer_name)},  # oder entry_id
            "name": self._printer_name,
            "manufacturer": "Bixolon",
            "model": "POS Printer Bridge",
            "sw_version": "1.0.0",
        }
            