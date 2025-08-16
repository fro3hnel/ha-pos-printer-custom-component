import pytest
from custom_components.pos_printer.button import RestartButton


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
