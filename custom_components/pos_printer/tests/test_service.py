"""Tests for print service of POS-Printer Bridge."""
import json
import pytest
from homeassistant.core import HomeAssistant
from custom_components.pos_printer.printer import setup_print_service
from custom_components.pos_printer.const import DOMAIN

@pytest.fixture(autouse=True)
def mqtt_publish_mock(monkeypatch):
    """Mock mqtt.async_publish and record calls."""
    calls = []
    async def fake_publish(hass, topic, payload, qos):
        calls.append({"topic": topic, "payload": payload, "qos": qos})
    monkeypatch.setattr("homeassistant.components.mqtt.async_publish", fake_publish)
    return calls

@pytest.mark.asyncio
async def test_print_service_publishes(mqtt_publish_mock, hass: HomeAssistant):
    """Test that the print service publishes the correct MQTT message."""
    config = {"printer_name": "printer"}
    await setup_print_service(hass, config)
    await hass.services.async_call(
        DOMAIN, "print",
        {"job_id": "id", "message": [{"type": "text", "content": "Hello"}]},
        blocking=True
    )
    assert mqtt_publish_mock, "mqtt.async_publish was not called"
    call = mqtt_publish_mock[-1]
    assert call["topic"] == "print/pos/printer/job"
    payload = json.loads(call["payload"])
    assert payload["job_id"] == "id"
    assert payload["message"][0]["content"] == "Hello"
    