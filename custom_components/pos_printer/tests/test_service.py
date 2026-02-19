"""Tests for print service of POS-Printer Bridge."""
import json
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.pos_printer.const import DOMAIN
from custom_components.pos_printer.printer import setup_print_service


class FakeBus:
    """Minimal event bus for tests."""

    def __init__(self):
        self._listeners = {}
        self.events = []

    def async_listen(self, event, callback):
        self._listeners.setdefault(event, []).append(callback)

        def _unsub():
            self._listeners[event].remove(callback)

        return _unsub

    def async_fire(self, event, data):
        self.events.append((event, data))
        for callback in list(self._listeners.get(event, [])):
            callback(SimpleNamespace(data=data))


class FakeHass:
    """Minimal hass object for tests."""

    def __init__(self, with_config_entries=False):
        self.services = SimpleNamespace(
            _services={}, async_register=self._register, async_call=self._async_call
        )
        self.bus = FakeBus()
        if with_config_entries:
            self.config_entries = SimpleNamespace()

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

    monkeypatch.setattr("homeassistant.components.mqtt.async_publish", fake_publish)
    monkeypatch.setattr(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client",
        fake_wait_for_client,
    )
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
async def test_print_service_builds_message_from_gui_fields(mqtt_publish_mock):
    """Test building text/barcode/image elements from GUI fields."""
    hass = FakeHass()
    config = {"printer_name": "printer"}
    await setup_print_service(hass, config)

    await hass.services.async_call(
        DOMAIN,
        "print",
        {
            "priority": 2,
            "paper_width": 53,
            "feed_after": 3,
            "expires": 90,
            "timestamp": "2026-02-19T12:00:00+00:00",
            "text_content": "Hello GUI",
            "text_alignment": "center",
            "text_bold": True,
            "text_size": 2,
            "barcode_content": "12345678",
            "barcode_type": "code128",
            "barcode_height": 50,
            "barcode_width": 2,
            "barcode_ecc_level": "M",
            "barcode_alignment": "left",
            "barcode_text_position": 0,
            "barcode_attribute": 1,
            "image_content": "data:image/png;base64,iVBORw0KGgo=",
            "image_alignment": "right",
            "image_nv_key": 7,
        },
        blocking=True,
    )

    payload = json.loads(mqtt_publish_mock[-1]["payload"])
    assert payload["priority"] == 2
    assert payload["paper_width"] == 53
    assert payload["feed_after"] == 3
    assert payload["expires"] == 90
    assert payload["timestamp"] == "2026-02-19T12:00:00+00:00"
    assert payload["message"] == [
        {
            "type": "text",
            "content": "Hello GUI",
            "alignment": "center",
            "bold": True,
            "size": 2,
        },
        {
            "type": "barcode",
            "content": "12345678",
            "barcode_type": "code128",
            "height": 50,
            "width": 2,
            "eccLevel": "M",
            "alignment": "left",
            "textPosition": 0,
            "attribute": 1,
        },
        {
            "type": "image",
            "content": "data:image/png;base64,iVBORw0KGgo=",
            "alignment": "right",
            "nv_key": 7,
        },
    ]


@pytest.mark.asyncio
async def test_print_service_supports_legacy_job_json(mqtt_publish_mock):
    """Test compatibility with deprecated job JSON passed to print."""
    hass = FakeHass()
    config = {"printer_name": "printer"}
    await setup_print_service(hass, config)

    await hass.services.async_call(
        DOMAIN,
        "print",
        {
            "job": json.dumps(
                {
                    "job_id": "legacy-job",
                    "priority": 4,
                    "paper_width": 80,
                    "message": [{"type": "text", "content": "Legacy"}],
                }
            )
        },
        blocking=True,
    )

    payload = json.loads(mqtt_publish_mock[-1]["payload"])
    assert payload["job_id"] == "legacy-job"
    assert payload["priority"] == 4
    assert payload["paper_width"] == 80
    assert payload["message"][0]["content"] == "Legacy"


@pytest.mark.asyncio
async def test_print_service_requires_message_content(mqtt_publish_mock):
    """Test that print service rejects calls without printable content."""
    hass = FakeHass()
    config = {"printer_name": "printer"}
    await setup_print_service(hass, config)

    with pytest.raises(HomeAssistantError, match="No message elements provided"):
        await hass.services.async_call(
            DOMAIN,
            "print",
            {},
            blocking=True,
        )


@pytest.mark.asyncio
async def test_print_job_service_publishes(mqtt_publish_mock):
    """Test sending a full job dictionary."""
    hass = FakeHass()
    config = {"printer_name": "printer"}
    await setup_print_service(hass, config)
    job = {
        "priority": 4,
        "message": [{"type": "text", "content": "Hi"}],
    }
    await hass.services.async_call(
        DOMAIN,
        "print_job",
        {"job": job},
        blocking=True,
    )
    call = mqtt_publish_mock[-1]
    payload = json.loads(call["payload"])
    assert payload["priority"] == 4
    assert payload["message"][0]["content"] == "Hi"


@pytest.mark.asyncio
async def test_print_job_service_accepts_job_json(mqtt_publish_mock):
    """Test that print_job service accepts JSON string payloads."""
    hass = FakeHass()
    config = {"printer_name": "printer"}
    await setup_print_service(hass, config)

    await hass.services.async_call(
        DOMAIN,
        "print_job",
        {"job": json.dumps({"priority": 3, "message": [{"type": "text", "content": "JSON"}]})},
        blocking=True,
    )

    payload = json.loads(mqtt_publish_mock[-1]["payload"])
    assert payload["priority"] == 3
    assert payload["message"][0]["content"] == "JSON"


@pytest.mark.asyncio
async def test_setup_subscribes_and_forwards_status_and_logs(monkeypatch):
    """Test MQTT subscriptions and forwarding status/log payloads to HA events."""
    hass = FakeHass(with_config_entries=True)
    subscriptions = {}

    async def fake_subscribe(_hass, topic, callback):
        subscriptions[topic] = callback
        return lambda: None

    monkeypatch.setattr("homeassistant.components.mqtt.async_subscribe", fake_subscribe)

    await setup_print_service(hass, {"printer_name": "printer"})

    status_topic = "print/pos/printer/ack"
    log_topic = "print/pos/printer/log"

    assert status_topic in subscriptions
    assert log_topic in subscriptions

    subscriptions[status_topic](SimpleNamespace(payload=json.dumps({"status": "success"})))
    subscriptions[log_topic](
        SimpleNamespace(
            payload=json.dumps(
                {
                    "level": "DEBUG",
                    "logger": "printer_bridge",
                    "message": "queued",
                    "timestamp": 1700000000,
                }
            )
        )
    )

    assert (f"{DOMAIN}.status", {"status": "success"}) in hass.bus.events
    assert (
        f"{DOMAIN}.bridge_log",
        {
            "level": "DEBUG",
            "logger": "printer_bridge",
            "message": "queued",
            "timestamp": 1700000000,
        },
    ) in hass.bus.events
