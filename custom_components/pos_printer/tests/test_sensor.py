"""Tests for sensor entities of POS-Printer Bridge."""

from types import SimpleNamespace

import pytest

from custom_components.pos_printer.binary_sensor import BridgeConnectedBinarySensor
from custom_components.pos_printer.const import DOMAIN, EVENT_AVAILABILITY, VERSION
from custom_components.pos_printer.entity import entry_printer_name, entry_runtime_data
from custom_components.pos_printer.models import PrinterRuntimeData
from custom_components.pos_printer.sensor import (
    BridgeVersionSensor,
    JobErrorBinarySensor,
    LastBridgeLogSensor,
    LastJobDetailSensor,
    LastJobIdSensor,
    LastJobStatusSensor,
    LastStatusTimestampSensor,
    QueueLengthSensor,
    SuccessfulJobsCounterSensor,
)


class FakeBus:
    def __init__(self) -> None:
        self._cbs = {}

    def async_listen(self, event, cb):
        self._cbs.setdefault(event, []).append(cb)

        def _remove() -> None:
            self._cbs[event].remove(cb)

        return _remove

    def async_fire(self, event, data):
        for cb in list(self._cbs.get(event, [])):
            cb(SimpleNamespace(data=data))


class FakeHass:
    def __init__(self) -> None:
        self.bus = FakeBus()

    async def async_block_till_done(self):
        return


@pytest.mark.asyncio
async def test_common_entity_availability_device_info_and_entry_fallbacks():
    """Common entity behavior should cover lifecycle and legacy entry fallback."""
    hass = FakeHass()
    sensor = QueueLengthSensor("printer", "entry")
    sensor.hass = hass
    sensor.entity_id = "sensor.printer_queue"
    writes = []
    sensor.async_write_ha_state = lambda: writes.append(sensor.available)

    await sensor.async_added_to_hass()
    assert sensor.device_info["identifiers"] == {(DOMAIN, "printer")}

    hass.bus.async_fire(
        EVENT_AVAILABILITY, {"printer_name": "other", "available": True}
    )
    assert writes == []
    hass.bus.async_fire(
        EVENT_AVAILABILITY, {"printer_name": "printer", "available": True}
    )
    assert writes == [True]

    await sensor.async_will_remove_from_hass()
    assert hass.bus._cbs[EVENT_AVAILABILITY] == []

    entry = SimpleNamespace(
        data={"printer_name": "from_data"}, options={}, runtime_data=None
    )
    assert entry_printer_name(entry) == "from_data"
    assert entry_runtime_data(entry) is None


@pytest.mark.asyncio
async def test_sensors_update_states():
    """Test that sensors update their states on status and bridge log events."""
    hass = FakeHass()
    sensors = [
        LastJobStatusSensor("printer", "entry"),
        LastJobIdSensor("printer", "entry"),
        LastJobDetailSensor("printer", "entry"),
        LastStatusTimestampSensor("printer", "entry"),
        QueueLengthSensor("printer", "entry"),
        BridgeVersionSensor("printer", "entry"),
        LastBridgeLogSensor("printer", "entry"),
        JobErrorBinarySensor("printer", "entry"),
        SuccessfulJobsCounterSensor("printer", "entry"),
    ]

    for sensor in sensors:
        sensor.hass = hass
        await sensor.async_added_to_hass()

    # Event for a different printer should be ignored.
    hass.bus.async_fire(
        f"{DOMAIN}.status",
        {
            "printer_name": "other",
            "status": "success",
            "job_id": "0",
            "timestamp": 1,
        },
    )
    hass.bus.async_fire(
        f"{DOMAIN}.bridge_log",
        {
            "printer_name": "other",
            "message": "ignore me",
            "level": "INFO",
            "logger": "printer_bridge",
            "timestamp": 2,
        },
    )

    # Matching printer updates sensors.
    hass.bus.async_fire(
        f"{DOMAIN}.status",
        {
            "printer_name": "printer",
            "status": "success",
            "job_id": "1",
            "detail": "",
            "timestamp": 1620000000,
            "queue_len": 2,
            "successful_jobs": 1,
            "heartbeat": {"version": VERSION},
        },
    )
    hass.bus.async_fire(
        f"{DOMAIN}.bridge_log",
        {
            "printer_name": "printer",
            "message": "worker online",
            "level": "INFO",
            "logger": "printer_bridge",
            "timestamp": 1620000100,
        },
    )

    await hass.async_block_till_done()

    assert sensors[0].native_value == "success"
    assert sensors[1].native_value == "1"
    assert sensors[2].native_value == ""
    assert sensors[3].native_value.timestamp() == 1620000000
    assert sensors[4].native_value == 2
    assert sensors[5].native_value == VERSION
    assert sensors[6].native_value == "worker online"
    assert sensors[6].extra_state_attributes["level"] == "INFO"
    assert sensors[7].is_on is False
    assert sensors[8].native_value == 1


@pytest.mark.asyncio
async def test_sensor_removes_listener():
    """Sensor should remove bus listener when removed from hass."""
    hass = FakeHass()
    sensor = LastJobStatusSensor("printer", "entry")
    sensor.hass = hass

    await sensor.async_added_to_hass()
    assert hass.bus._cbs, "Listener was not registered"

    await sensor.async_will_remove_from_hass()
    assert not hass.bus._cbs[f"{DOMAIN}.status"], "Listener was not removed"

    hass.bus.async_fire(
        f"{DOMAIN}.status", {"printer_name": "printer", "status": "success"}
    )
    await hass.async_block_till_done()
    assert sensor.native_value is None


@pytest.mark.asyncio
async def test_bridge_connection_sensor_reports_offline_state():
    """Connectivity should show disconnected rather than become unavailable."""
    hass = FakeHass()
    runtime = PrinterRuntimeData(
        entry_id="entry",
        printer_name="printer",
        print_topic="p",
        status_topic="s",
        log_topic="l",
        availability_topic="a",
        available=True,
        availability_known=True,
    )
    sensor = BridgeConnectedBinarySensor("printer", "entry", runtime)
    sensor.hass = hass
    await sensor.async_added_to_hass()

    assert sensor.available is True
    assert sensor.is_on is True

    hass.bus.async_fire(
        EVENT_AVAILABILITY,
        {"printer_name": "printer", "available": False},
    )
    assert sensor.available is True
    assert sensor.is_on is False


@pytest.mark.asyncio
async def test_job_error_persists_across_heartbeat():
    """A heartbeat must not clear the result of the last failed job."""
    hass = FakeHass()
    sensor = JobErrorBinarySensor("printer", "entry")
    sensor.hass = hass
    await sensor.async_added_to_hass()

    hass.bus.async_fire(
        f"{DOMAIN}.status",
        {"printer_name": "printer", "status": "partial-error"},
    )
    assert sensor.is_on is True

    hass.bus.async_fire(
        f"{DOMAIN}.status",
        {"printer_name": "printer", "heartbeat": {"version": VERSION}},
    )
    assert sensor.is_on is True

    hass.bus.async_fire(
        f"{DOMAIN}.status",
        {"printer_name": "printer", "status": "duplicate"},
    )
    assert sensor.is_on is False


def test_duplicate_is_a_supported_non_error_status():
    """The enum contract should expose duplicate as a normal lifecycle state."""
    sensor = LastJobStatusSensor("printer", "entry")
    assert "duplicate" in sensor.options
