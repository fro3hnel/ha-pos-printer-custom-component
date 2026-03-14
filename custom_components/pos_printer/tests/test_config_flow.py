"""Tests for config and reconfigure flows."""

from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_mqtt_step_invalid_json():
    """Invalid discovery payload should abort the flow."""
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries())
    result = await flow.async_step_mqtt({"payload": "not-json"})
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

    result = await flow.async_step_mqtt({"payload": '{"printer_name": "mqtt_printer"}'})
    assert result["type"] == "create_entry"
    assert result["title"] == "mqtt_printer"


@pytest.mark.asyncio
async def test_mqtt_step_rejects_invalid_discovered_name():
    """Discovery should abort when the printer name contains invalid characters."""
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries())

    result = await flow.async_step_mqtt({"payload": '{"printer_name": "Bad Printer"}'})
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
async def test_reconfigure_rejects_duplicate_printer_name():
    """Reconfigure should reject printer names already used by another entry."""
    current = SimpleNamespace(entry_id="entry-1", data={"printer_name": "one"}, options={})
    other = SimpleNamespace(entry_id="entry-2", data={"printer_name": "two"}, options={})
    flow = PosPrinterConfigFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries([current, other]))
    flow._get_reconfigure_entry = lambda: current

    result = await flow.async_step_reconfigure({"printer_name": "two"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}


@pytest.mark.asyncio
async def test_reconfigure_step_updates_entry(monkeypatch):
    """Reconfigure should update the entry and request a reload."""
    flow = PosPrinterConfigFlow()
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={"printer_name": "old_printer"},
        options={"printer_name": "old_printer"},
        unique_id="old_printer",
    )
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries([entry]))

    async def fake_set_unique_id(value):
        return None

    def fake_update_reload_and_abort(entry, **kwargs):
        return {"type": "abort", "reason": "reconfigure_successful", "kwargs": kwargs}

    monkeypatch.setattr(flow, "async_set_unique_id", fake_set_unique_id)
    monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: entry)
    monkeypatch.setattr(flow, "_abort_if_unique_id_mismatch", lambda: None)
    monkeypatch.setattr(flow, "async_update_reload_and_abort", fake_update_reload_and_abort)

    result = await flow.async_step_reconfigure({"printer_name": "new_printer"})
    assert result["reason"] == "reconfigure_successful"
    assert result["kwargs"]["unique_id"] == "new_printer"
    assert result["kwargs"]["data_updates"] == {"printer_name": "new_printer"}
    assert result["kwargs"]["options"] == {"printer_name": "new_printer"}


@pytest.mark.asyncio
async def test_options_flow_rejects_invalid_or_duplicate_name():
    """Options flow should reject invalid and duplicate printer names."""
    current_entry = SimpleNamespace(
        entry_id="entry-1",
        data={"printer_name": "one"},
        options={},
    )
    other_entry = SimpleNamespace(
        entry_id="entry-2",
        data={"printer_name": "two"},
        options={},
    )
    flow = OptionsFlowHandler(current_entry)
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries([current_entry, other_entry]))

    result = await flow.async_step_init({"printer_name": "Two"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_printer_name"}

    result = await flow.async_step_init({"printer_name": "two"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}

    result = await flow.async_step_init({"printer_name": "three"})
    assert result["type"] == "create_entry"
    assert result["data"] == {"printer_name": "three"}


@pytest.mark.asyncio
async def test_reconfigure_form_and_options_factory():
    """The integration should expose reconfigure and options flow entry points."""
    flow = PosPrinterConfigFlow()
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={"printer_name": "printer"},
        options={},
    )
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries([entry]))
    flow._get_reconfigure_entry = lambda: entry

    result = await flow.async_step_reconfigure()
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    options_flow = flow.async_get_options_flow(entry)
    assert isinstance(options_flow, OptionsFlowHandler)
