import pytest
from types import SimpleNamespace

from custom_components.pos_printer.button import (
    PiSoftwareUpdateButton,
    RestartButton,
    async_setup_entry,
)
from custom_components.pos_printer.models import PrinterRuntimeData


class FakeHass:
    async def async_block_till_done(self):
        return


@pytest.fixture(autouse=True)
def mqtt_publish_mock(monkeypatch):
    """Mock mqtt.async_publish and record calls."""
    calls = []

    async def fake_publish(hass, topic, payload, qos):
        calls.append({"topic": topic, "payload": payload, "qos": qos})

    monkeypatch.setattr("homeassistant.components.mqtt.async_publish", fake_publish)
    return calls


@pytest.mark.asyncio
async def test_restart_button_publishes_command(mqtt_publish_mock):
    hass = FakeHass()
    button = RestartButton("printer", "entry")
    button.hass = hass
    await button.async_press()
    assert mqtt_publish_mock, "mqtt.async_publish was not called"
    call = mqtt_publish_mock[-1]
    assert call["topic"] == "print/pos/printer/restart"
    assert call["payload"] == ""


@pytest.mark.asyncio
async def test_pi_update_button_publishes_command(mqtt_publish_mock):
    hass = FakeHass()
    button = PiSoftwareUpdateButton("printer", "entry")
    button.hass = hass
    await button.async_press()
    assert mqtt_publish_mock, "mqtt.async_publish was not called"
    call = mqtt_publish_mock[-1]
    assert call["topic"] == "print/pos/printer/pi_update"
    assert call["payload"] == ""


@pytest.mark.asyncio
async def test_button_platform_setup_uses_runtime_data():
    """Platform setup should add both buttons for the effective printer name."""
    added = []
    entry = SimpleNamespace(
        entry_id="entry",
        data={"printer_name": "from_data"},
        options={},
        runtime_data=PrinterRuntimeData(
            entry_id="entry",
            printer_name="from_runtime",
            print_topic="p",
            status_topic="s",
            log_topic="l",
        ),
    )

    await async_setup_entry(FakeHass(), entry, added.extend)
    assert len(added) == 2
    assert added[0]._printer_name == "from_runtime"
