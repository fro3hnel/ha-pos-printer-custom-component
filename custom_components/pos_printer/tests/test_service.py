"""Tests for print services of POS-Printer Bridge."""

import json
import logging
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.pos_printer.const import DOMAIN
from custom_components.pos_printer.printer import setup_print_service, unload_print_service


class FakeBus:
    """Minimal event bus for tests."""

    def __init__(self) -> None:
        self._listeners: dict[str, list] = {}
        self.events: list[tuple[str, dict | None]] = []

    def async_listen(self, event, callback):
        self._listeners.setdefault(event, []).append(callback)

        def _unsub() -> None:
            self._listeners[event].remove(callback)

        return _unsub

    def async_fire(self, event, data=None) -> None:
        self.events.append((event, data))
        for callback in list(self._listeners.get(event, [])):
            callback(SimpleNamespace(data=data))


class FakeServices:
    """Minimal service registry for tests."""

    def __init__(self) -> None:
        self._services = {}
        self.removed: list[tuple[str, str]] = []

    def async_register(self, domain, service, func) -> None:
        self._services[(domain, service)] = func

    def has_service(self, domain, service) -> bool:
        return (domain, service) in self._services

    def async_remove(self, domain, service) -> None:
        self.removed.append((domain, service))
        self._services.pop((domain, service), None)

    async def async_call(self, domain, service, data, blocking=True):
        await self._services[(domain, service)](SimpleNamespace(data=data))


class FakeHass:
    """Minimal hass object for tests."""

    def __init__(self) -> None:
        self.data = {}
        self.services = FakeServices()
        self.bus = FakeBus()

    async def async_block_till_done(self):
        return


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
    await setup_print_service(hass, {"printer_name": "printer"})

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
    await setup_print_service(hass, {"printer_name": "printer"})

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
async def test_print_service_builds_text_elements_from_text_lines(mqtt_publish_mock):
    """Test building multiple text elements from text_lines."""
    hass = FakeHass()
    await setup_print_service(hass, {"printer_name": "printer"})

    await hass.services.async_call(
        DOMAIN,
        "print",
        {
            "text_lines": "Line 1\n\nLine 3",
            "text_alignment": "center",
            "text_bold": True,
        },
        blocking=True,
    )

    payload = json.loads(mqtt_publish_mock[-1]["payload"])
    assert payload["message"] == [
        {
            "type": "text",
            "content": "Line 1",
            "alignment": "center",
            "bold": True,
        },
        {
            "type": "text",
            "content": " ",
            "alignment": "center",
            "bold": True,
        },
        {
            "type": "text",
            "content": "Line 3",
            "alignment": "center",
            "bold": True,
        },
    ]


@pytest.mark.asyncio
async def test_print_service_supports_legacy_job_json(mqtt_publish_mock):
    """Test compatibility with deprecated job JSON passed to print."""
    hass = FakeHass()
    await setup_print_service(hass, {"printer_name": "printer"})

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
async def test_print_service_requires_message_content():
    """Test that print service rejects calls without printable content."""
    hass = FakeHass()
    await setup_print_service(hass, {"printer_name": "printer"})

    with pytest.raises(HomeAssistantError, match="No message elements provided"):
        await hass.services.async_call(DOMAIN, "print", {}, blocking=True)


@pytest.mark.asyncio
async def test_print_service_publishes_full_job_object(mqtt_publish_mock):
    """Test sending a full job dictionary via print."""
    hass = FakeHass()
    await setup_print_service(hass, {"printer_name": "printer"})

    job = {
        "priority": 4,
        "timestamp": "2026-02-19T12:00:00+00:00",
        "paper_width": 53,
        "message": [{"type": "text", "content": "Hi"}],
    }
    await hass.services.async_call(
        DOMAIN,
        "print",
        {"job": job},
        blocking=True,
    )

    payload = json.loads(mqtt_publish_mock[-1]["payload"])
    assert payload["priority"] == 4
    assert payload["timestamp"] == "2026-02-19T12:00:00+00:00"
    assert payload["paper_width"] == 53
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
async def test_setup_subscribes_and_forwards_status_and_logs(monkeypatch):
    """Test MQTT subscriptions and forwarding status/log payloads to HA events."""
    hass = FakeHass()
    subscriptions = {}

    async def fake_publish(hass, topic, payload, qos):
        return

    async def fake_wait_for_client(hass):
        return

    async def fake_subscribe(hass, topic, callback):
        subscriptions[topic] = callback
        return lambda: None

    monkeypatch.setattr("homeassistant.components.mqtt.async_publish", fake_publish)
    monkeypatch.setattr(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client",
        fake_wait_for_client,
    )
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

    assert (
        f"{DOMAIN}.status",
        {"status": "success", "printer_name": "printer"},
    ) in hass.bus.events
    assert (
        f"{DOMAIN}.bridge_log",
        {
            "level": "DEBUG",
            "logger": "printer_bridge",
            "message": "queued",
            "timestamp": 1700000000,
            "printer_name": "printer",
        },
    ) in hass.bus.events


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


@pytest.mark.asyncio
async def test_unload_print_service_removes_services_when_last_printer_removed():
    """Unload should unsubscribe and remove services after last printer unload."""
    hass = FakeHass()
    await setup_print_service(hass, {"printer_name": "one"})
    await setup_print_service(hass, {"printer_name": "two"})

    await unload_print_service(hass, {"printer_name": "one"})
    assert (DOMAIN, "print") in hass.services._services

    await unload_print_service(hass, {"printer_name": "two"})
    assert (DOMAIN, "print") not in hass.services._services
