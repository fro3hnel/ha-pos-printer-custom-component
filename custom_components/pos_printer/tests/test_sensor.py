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
    event_data = {"status": "success", "job_id": "1", "timestamp": 1620000000}
    hass.bus.async_fire(f"{DOMAIN}.status", event_data)
    await hass.async_block_till_done()
    assert sensors[0].state == "success"
    assert sensors[1].state == "1"
    assert sensors[2].native_value.timestamp() == 1620000000
    assert sensors[3].is_on is False
    assert sensors[4].state == 1

