"""Tests for sensor entities of POS-Printer Bridge."""
from types import SimpleNamespace

import pytest

from custom_components.pos_printer.const import DOMAIN, VERSION
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
