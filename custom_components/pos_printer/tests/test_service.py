"""Tests for print service of POS-Printer Bridge."""
import json
import logging
from types import SimpleNamespace

import pytest

from custom_components.pos_printer.printer import setup_print_service
from custom_components.pos_printer.const import DOMAIN


class FakeBus:
    def __init__(self):
        self.events = []

    def async_listen(self, *args, **kwargs):
        return

    def async_fire(self, event_type, event_data=None):
        self.events.append((event_type, event_data))


class FakeHass:
    """Minimal hass object for tests."""

    def __init__(self):
        self.data = {}
        self.services = SimpleNamespace(
            _services={}, async_register=self._register, async_call=self._async_call
        )
        self.bus = FakeBus()

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
    async def fake_wait_for_client(hass):
        return
    async def fake_subscribe(hass, topic, callback):
        return lambda: None
    monkeypatch.setattr("homeassistant.components.mqtt.async_publish", fake_publish)
    monkeypatch.setattr(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client",
        fake_wait_for_client,
    )
    monkeypatch.setattr("homeassistant.components.mqtt.async_subscribe", fake_subscribe)
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


@pytest.mark.asyncio
async def test_print_service_with_job_publishes(mqtt_publish_mock):
    """Test that the print service handles a full job dictionary."""
    hass = FakeHass()
    config = {"printer_name": "printer"}
    await setup_print_service(hass, config)
    job = {
        "priority": 4,
        "message": [{"type": "text", "content": "Hi"}],
    }
    await hass.services.async_call(
        DOMAIN,
        "print",
        {"printer_name": "printer", "job": job},
        blocking=True,
    )
    call = mqtt_publish_mock[-1]
    payload = json.loads(call["payload"])
    assert payload["priority"] == 4
    assert payload["message"][0]["content"] == "Hi"


@pytest.mark.asyncio
async def test_multiple_printers_publish_to_correct_topic(mqtt_publish_mock):
    """Ensure service routes jobs to the selected printer."""
    hass = FakeHass()
    await setup_print_service(hass, {"printer_name": "one"})
    await setup_print_service(hass, {"printer_name": "two"})

    await hass.services.async_call(
        DOMAIN,
        "print",
        {"printer_name": "one", "message": [{"type": "text", "content": "A"}]},
        blocking=True,
    )
    assert mqtt_publish_mock[-1]["topic"] == "print/pos/one/job"

    await hass.services.async_call(
        DOMAIN,
        "print",
        {"printer_name": "two", "message": [{"type": "text", "content": "B"}]},
        blocking=True,
    )
    assert mqtt_publish_mock[-1]["topic"] == "print/pos/two/job"


@pytest.mark.asyncio
async def test_status_handler_invalid_json_and_errors(monkeypatch, caplog):
    """Ensure status handler ignores invalid JSON and logs other errors."""
    hass = FakeHass()
    callbacks = {}

    async def fake_publish(hass, topic, payload, qos):
        return

    async def fake_wait_for_client(hass):
        return

    async def fake_subscribe(hass, topic, callback):
        callbacks[topic] = callback
        return lambda: None

    monkeypatch.setattr("homeassistant.components.mqtt.async_publish", fake_publish)
    monkeypatch.setattr(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client",
        fake_wait_for_client,
    )
    monkeypatch.setattr("homeassistant.components.mqtt.async_subscribe", fake_subscribe)

    await setup_print_service(hass, {"printer_name": "printer"})

    status_cb = callbacks["print/pos/printer/ack"]

    status_cb(SimpleNamespace(payload="not-json"))
    assert hass.bus.events == []

    with caplog.at_level(logging.ERROR):
        status_cb(SimpleNamespace(payload="[]"))
    assert "Error handling status payload" in caplog.text
    assert hass.bus.events == []

