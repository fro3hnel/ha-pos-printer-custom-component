"""Tests for config and options flows."""

from types import SimpleNamespace

import pytest
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from custom_components.pos_printer.config_flow import (
    OptionsFlowHandler,
    PosPrinterConfigFlow,
)


class FakeConfigEntries:
    """Minimal config entry registry."""

    def __init__(self, entries=None) -> None:
        self._entries = entries or []

    def async_entries(self, _domain):
        return list(self._entries)


def mqtt_discovery(payload: str) -> MqttServiceInfo:
    """Build the MQTT service-info object passed by Home Assistant."""
    return MqttServiceInfo(
        topic="pos_printer/discovery/printer",
        payload=payload,
        qos=1,
        retain=True,
        subscribed_topic="pos_printer/discovery/+",
        timestamp=0,
    )


@pytest.mark.asyncio
async def test_mqtt_step_invalid_json():
    """Invalid discovery payload should abort the flow."""
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries())
    result = await flow.async_step_mqtt(mqtt_discovery("not-json"))
    assert result["type"] == "abort"
    assert result["reason"] == "invalid_discovery"


@pytest.mark.asyncio
async def test_mqtt_step_missing_payload():
    """Malformed discovery data should abort instead of raising."""
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries())
    result = await flow.async_step_mqtt(SimpleNamespace())
    assert result["type"] == "abort"
    assert result["reason"] == "invalid_discovery"


@pytest.mark.asyncio
async def test_mqtt_step_creates_entry(monkeypatch):
    """Valid MQTT discovery should create an entry."""
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries())

    async def fake_set_unique_id(value):
        return None

    monkeypatch.setattr(flow, "async_set_unique_id", fake_set_unique_id)
    monkeypatch.setattr(flow, "_abort_if_unique_id_configured", lambda: None)

    result = await flow.async_step_mqtt(
        mqtt_discovery('{"printer_name": "mqtt_printer"}')
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "mqtt_printer"


@pytest.mark.asyncio
async def test_mqtt_step_rejects_invalid_discovered_name():
    """Discovery should abort when the printer name contains invalid characters."""
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries())

    result = await flow.async_step_mqtt(
        mqtt_discovery('{"printer_name": "Bad Printer"}')
    )
    assert result["type"] == "abort"
    assert result["reason"] == "invalid_discovery"


@pytest.mark.asyncio
async def test_user_step_creates_entry(monkeypatch):
    """Valid user input should create a config entry."""
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries())

    async def fake_set_unique_id(value):
        return None

    monkeypatch.setattr(flow, "async_set_unique_id", fake_set_unique_id)
    monkeypatch.setattr(flow, "_abort_if_unique_id_configured", lambda: None)

    result = await flow.async_step_user({"printer_name": "kitchen_printer"})
    assert result["type"] == "create_entry"
    assert result["title"] == "kitchen_printer"
    assert result["data"] == {"printer_name": "kitchen_printer"}


@pytest.mark.asyncio
async def test_user_step_rejects_invalid_printer_name():
    """Invalid printer names should return a form error."""
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries())

    result = await flow.async_step_user({"printer_name": "Kitchen Printer"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_printer_name"}


@pytest.mark.asyncio
async def test_user_step_rejects_duplicate_printer_name():
    """User setup should reject duplicate printer names."""
    other_entry = SimpleNamespace(entry_id="entry-2", data={"printer_name": "printer"}, options={})
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries([other_entry]))

    result = await flow.async_step_user({"printer_name": "printer"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}


@pytest.mark.asyncio
async def test_options_flow_stores_print_defaults():
    """Options should store per-printer paper and feed defaults."""
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={"printer_name": "printer"},
        options={},
    )
    flow = OptionsFlowHandler(entry)
    result = await flow.async_step_init({"paper_width": 53, "feed_after": 2})
    assert result["type"] == "create_entry"
    assert result["data"] == {"paper_width": 53, "feed_after": 2}


@pytest.mark.asyncio
async def test_options_form():
    """The integration should expose its printer-default options form."""
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={"printer_name": "printer"},
        options={"paper_width": 53, "feed_after": 2},
    )
    flow = PosPrinterConfigFlow.async_get_options_flow(entry)
    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert result["step_id"] == "init"
