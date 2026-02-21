"""Tests for update entities of POS-Printer Bridge."""

import json
from types import SimpleNamespace

import pytest

from custom_components.pos_printer.const import DOMAIN
from custom_components.pos_printer.update import BridgeUpdateEntity


class FakeBus:
    def __init__(self) -> None:
        self._cbs = []

    def async_listen(self, _event, cb):
        self._cbs.append(cb)

        def _remove() -> None:
            self._cbs.remove(cb)

        return _remove

    def async_fire(self, _event, data) -> None:
        for cb in list(self._cbs):
            cb(SimpleNamespace(data=data))


class FakeHass:
    def __init__(self) -> None:
        self.bus = FakeBus()

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
async def test_update_entity_installs_exact_version(mqtt_publish_mock):
    """Ensure update entity publishes versioned install command."""
    hass = FakeHass()
    entity = BridgeUpdateEntity("printer", "entry")
    entity.hass = hass
    await entity.async_added_to_hass()

    # Event from different printer should be ignored.
    hass.bus.async_fire(
        f"{DOMAIN}.status", {"printer_name": "other", "heartbeat": {"version": "0.0.8"}}
    )

    heartbeat = {"printer_name": "printer", "heartbeat": {"version": "0.0.9"}}
    hass.bus.async_fire(f"{DOMAIN}.status", heartbeat)
    await hass.async_block_till_done()
    assert entity.installed_version == "0.0.9"

    await entity.async_install(None, False)
    assert mqtt_publish_mock, "mqtt.async_publish was not called"
    call = mqtt_publish_mock[-1]
    assert call["topic"] == "print/pos/printer/update"
    payload = json.loads(call["payload"])
    assert payload["version"] == entity.latest_version


@pytest.mark.asyncio
async def test_update_entity_installs_requested_version(mqtt_publish_mock):
    """Ensure update entity can publish an explicit target version."""
    hass = FakeHass()
    entity = BridgeUpdateEntity("printer", "entry")
    entity.hass = hass
    await entity.async_added_to_hass()

    hass.bus.async_fire(f"{DOMAIN}.status", {"printer_name": "printer", "version": "0.1.0"})
    await hass.async_block_till_done()
    assert entity.installed_version == "0.1.0"

    await entity.async_install("0.2.0", False)
    assert mqtt_publish_mock, "mqtt.async_publish was not called"
    call = mqtt_publish_mock[-1]
    assert call["topic"] == "print/pos/printer/update"
    payload = json.loads(call["payload"])
    assert payload["version"] == "0.2.0"


@pytest.mark.asyncio
async def test_update_entity_removes_listener():
    """Update entity should detach bus listener when removed."""
    hass = FakeHass()
    entity = BridgeUpdateEntity("printer", "entry")
    entity.hass = hass

    await entity.async_added_to_hass()
    assert hass.bus._cbs, "Listener was not registered"

    await entity.async_will_remove_from_hass()
    assert not hass.bus._cbs, "Listener was not removed"

    hass.bus.async_fire(
        f"{DOMAIN}.status", {"printer_name": "printer", "heartbeat": {"version": "1"}}
    )
    await hass.async_block_till_done()
    assert entity.installed_version is None
