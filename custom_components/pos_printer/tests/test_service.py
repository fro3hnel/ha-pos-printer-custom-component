"""Tests for print service of POS-Printer Bridge."""
import json
import pytest
from types import SimpleNamespace
from custom_components.pos_printer.printer import setup_print_service
from custom_components.pos_printer.const import DOMAIN


class FakeHass:
    """Minimal hass object for tests."""

    def __init__(self):
        self.services = SimpleNamespace(
            _services={}, async_register=self._register, async_call=self._async_call
        )
        self.bus = SimpleNamespace(async_listen=lambda *args, **kwargs: None)

    async def async_block_till_done(self):
        return

    def _register(self, domain, service, func):
        self.services._services[(domain, service)] = func

    async def _async_call(self, domain, service, data, blocking=True):
        await self.services._services[(domain, service)](SimpleNamespace(data=data))


@pytest.fixture(autouse=True)
def mqtt_publish_mock(monkeypatch):
    """Mock mqtt.async_publish and record calls."""
    calls = []
    async def fake_publish(hass, topic, payload, qos):
        calls.append({"topic": topic, "payload": payload, "qos": qos})
    monkeypatch.setattr("homeassistant.components.mqtt.async_publish", fake_publish)
    return calls

@pytest.mark.asyncio
async def test_print_service_publishes(mqtt_publish_mock):
    """Test that the print service publishes the correct MQTT message."""
    hass = FakeHass()
    config = {"printer_name": "printer"}
    await setup_print_service(hass, config)
    await hass.services.async_call(
        DOMAIN,
        "print",
        {"message": [{"type": "text", "content": "Hello"}]},
        blocking=True,
    )
    assert mqtt_publish_mock, "mqtt.async_publish was not called"
    call = mqtt_publish_mock[-1]
    assert call["topic"] == "print/pos/printer/job"
    payload = json.loads(call["payload"])
    assert payload["job_id"]
    assert payload["message"][0]["content"] == "Hello"

