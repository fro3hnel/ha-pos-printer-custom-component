"""Tests for sensor entities of POS-Printer Bridge."""
import pytest
from types import SimpleNamespace
from custom_components.pos_printer.sensor import (
    LastJobStatusSensor,
    LastJobIdSensor,
    LastStatusTimestampSensor,
    JobErrorBinarySensor,
    SuccessfulJobsCounterSensor,
)
from custom_components.pos_printer.const import DOMAIN


class FakeBus:
    def __init__(self):
        self._cbs = []

    def async_listen(self, _event, cb):
        self._cbs.append(cb)
        def _remove():
            self._cbs.remove(cb)
        return _remove

    def async_fire(self, _event, data):
        for cb in list(self._cbs):
            cb(SimpleNamespace(data=data))


class FakeHass:
    def __init__(self):
        self.bus = FakeBus()

    async def async_block_till_done(self):
        return

@pytest.mark.asyncio
async def test_sensors_update_states():
    """Test that sensors update their states on status events."""
    hass = FakeHass()
    sensors = [
        LastJobStatusSensor("printer", "entry"),
        LastJobIdSensor("printer", "entry"),
        LastStatusTimestampSensor("printer", "entry"),
        JobErrorBinarySensor("printer", "entry"),
        SuccessfulJobsCounterSensor("printer", "entry"),
    ]
    for sensor in sensors:
        sensor.hass = hass
        await sensor.async_added_to_hass()
    # Event for a different printer should be ignored
    hass.bus.async_fire(
        f"{DOMAIN}.status",
        {"printer_name": "other", "status": "error", "job_id": "0", "timestamp": 1},
    )
    # Matching printer updates sensors
    event_data = {
        "printer_name": "printer",
        "status": "success",
        "job_id": "1",
        "timestamp": 1620000000,
    }
    hass.bus.async_fire(f"{DOMAIN}.status", event_data)
    await hass.async_block_till_done()
    assert sensors[0].state == "success"
    assert sensors[1].state == "1"
    assert sensors[2].native_value.timestamp() == 1620000000
    assert sensors[3].is_on is False
    assert sensors[4].state == 1


@pytest.mark.asyncio
async def test_sensor_removes_listener():
    """Sensor should remove bus listener when removed from hass."""
    hass = FakeHass()
    sensor = LastJobStatusSensor("printer", "entry")
    sensor.hass = hass
    await sensor.async_added_to_hass()
    assert hass.bus._cbs, "Listener was not registered"
    await sensor.async_will_remove_from_hass()
    assert not hass.bus._cbs, "Listener was not removed"
    hass.bus.async_fire(
        f"{DOMAIN}.status", {"printer_name": "printer", "status": "success"}
    )
    await hass.async_block_till_done()
    assert sensor.state is None

