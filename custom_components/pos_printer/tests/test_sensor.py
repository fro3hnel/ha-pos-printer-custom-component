"""Tests for sensor entities of POS-Printer Bridge."""
import pytest
from homeassistant.core import HomeAssistant
from custom_components.pos_printer.sensor import (
    LastJobStatusSensor,
    LastJobIdSensor,
    LastStatusTimestampSensor,
    JobErrorBinarySensor,
    SuccessfulJobsCounterSensor,
)
from custom_components.pos_printer.const import DOMAIN

@pytest.mark.asyncio
async def test_sensors_update_states(hass: HomeAssistant):
    """Test that sensors update their states on status events."""
    sensors = [
        LastJobStatusSensor("printer", "entry"),
        LastJobIdSensor("printer", "entry"),
        LastStatusTimestampSensor("printer", "entry"),
        JobErrorBinarySensor("printer", "entry"),
        SuccessfulJobsCounterSensor("printer", "entry"),
    ]
    for sensor in sensors:
        await sensor.async_added_to_hass()
    event_data = {"status": "success", "job_id": "1", "timestamp": 1620000000}
    hass.bus.async_fire(f"{DOMAIN}.status", event_data)
    await hass.async_block_till_done()
    assert sensors[0].state == "success"
    assert sensors[1].state == "1"
    assert sensors[2].native_value.timestamp() == 1620000000
    assert sensors[3].is_on is False
    assert sensors[4].state == 1
    