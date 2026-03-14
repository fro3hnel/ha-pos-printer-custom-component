"""Tests for setup lifecycle, binary sensor setup, and repairs helpers."""

from types import SimpleNamespace

import pytest

import custom_components.pos_printer as integration
from custom_components.pos_printer.const import VERSION
from custom_components.pos_printer.binary_sensor import async_setup_entry as setup_binary_sensor
from custom_components.pos_printer.models import PrinterRuntimeData
from custom_components.pos_printer.repairs import (
    async_clear_entry_issues,
    async_validate_bridge_version_issue,
    async_validate_printer_name_issue,
    async_validate_entry_issues,
)


class FakeConfigEntries:
    """Minimal config entries manager."""

    def __init__(self) -> None:
        self.forwarded = []
        self.reloaded = []

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry.entry_id, tuple(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.forwarded.append(("unload", entry.entry_id, tuple(platforms)))
        return True

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


class FakeEntry:
    """Minimal config entry."""

    def __init__(self, printer_name="printer") -> None:
        self.entry_id = "entry-1"
        self.data = {"printer_name": printer_name}
        self.options = {}
        self.runtime_data = None
        self._listeners = []

    def add_update_listener(self, listener):
        self._listeners.append(listener)
        return listener

    def async_on_unload(self, callback):
        self._listeners.append(callback)


@pytest.mark.asyncio
async def test_async_setup_and_entry_lifecycle(monkeypatch):
    """Setup and unload should register services, runtime data, and repairs."""
    calls = {"register": 0, "setup": [], "unload": [], "issues": [], "cleared": []}
    hass = SimpleNamespace(config_entries=FakeConfigEntries())
    entry = FakeEntry("printer")

    async def fake_register_services(hass):
        calls["register"] += 1

    async def fake_setup_print_service(hass, config):
        calls["setup"].append(config)
        return SimpleNamespace(printer_name=config["printer_name"])

    async def fake_unload_print_service(hass, config):
        calls["unload"].append(config)

    monkeypatch.setattr(integration, "async_register_services", fake_register_services)
    monkeypatch.setattr(integration, "setup_print_service", fake_setup_print_service)
    monkeypatch.setattr(integration, "unload_print_service", fake_unload_print_service)
    monkeypatch.setattr(integration, "async_validate_entry_issues", lambda hass, entry: calls["issues"].append(entry.entry_id))
    monkeypatch.setattr(integration, "async_clear_entry_issues", lambda hass, entry_id: calls["cleared"].append(entry_id))

    assert await integration.async_setup(hass, {}) is True
    assert await integration.async_setup_entry(hass, entry) is True
    assert entry.runtime_data.printer_name == "printer"
    assert calls["issues"] == ["entry-1"]

    assert await integration.async_unload_entry(hass, entry) is True
    assert calls["unload"] == [{"entry_id": "entry-1", "printer_name": "printer"}]
    assert calls["cleared"] == ["entry-1"]


@pytest.mark.asyncio
async def test_binary_sensor_setup_uses_runtime_data():
    """Binary sensor setup should honor the effective printer name from runtime data."""
    added = []
    entry = FakeEntry("from_data")
    entry.runtime_data = PrinterRuntimeData(
        entry_id="entry-1",
        printer_name="from_runtime",
        print_topic="p",
        status_topic="s",
        log_topic="l",
    )

    await setup_binary_sensor(SimpleNamespace(), entry, added.extend)
    assert added[0]._printer_name == "from_runtime"


def test_repairs_helpers_create_and_clear_issues(monkeypatch):
    """Repair helpers should create issues for invalid names and old bridge versions."""
    calls = {"create": [], "delete": []}
    entry = FakeEntry("invalid name")
    hass = SimpleNamespace()

    monkeypatch.setattr(
        "homeassistant.helpers.issue_registry.async_create_issue",
        lambda hass, domain, issue_id, **kwargs: calls["create"].append((issue_id, kwargs["translation_key"])),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.issue_registry.async_delete_issue",
        lambda hass, domain, issue_id: calls["delete"].append(issue_id),
    )

    async_validate_entry_issues(hass, entry)
    async_validate_printer_name_issue(hass, FakeEntry("valid_printer"), "valid_printer")
    async_validate_bridge_version_issue(hass, entry.entry_id, "printer", "0.1.0")
    async_validate_bridge_version_issue(hass, entry.entry_id, "printer", VERSION)
    async_validate_bridge_version_issue(hass, entry.entry_id, "printer", None)
    async_validate_bridge_version_issue(hass, entry.entry_id, "printer", "broken")
    async_clear_entry_issues(hass, entry.entry_id)

    assert ("invalid_printer_name_entry-1", "invalid_printer_name") in calls["create"]
    assert ("outdated_bridge_version_entry-1", "outdated_bridge_version") in calls["create"]
    assert "outdated_bridge_version_entry-1" in calls["delete"]
    assert "invalid_printer_name_entry-1" in calls["delete"]
