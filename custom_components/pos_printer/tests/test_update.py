import json
import pytest
from types import SimpleNamespace

from custom_components.pos_printer.update import BridgeUpdateEntity
from custom_components.pos_printer.const import DOMAIN


class FakeBus:
    def __init__(self):
        self._cbs = []

    def async_listen(self, _event, cb):
        self._cbs.append(cb)

    def async_fire(self, _event, data):
        for cb in list(self._cbs):
            cb(SimpleNamespace(data=data))


class FakeHass:
    def __init__(self):
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

    heartbeat = {"heartbeat": {"version": "0.0.9"}}
    hass.bus.async_fire(f"{DOMAIN}.status", heartbeat)
    await hass.async_block_till_done()
    assert entity.installed_version == "0.0.9"

    await entity.async_install(None, False)
    assert mqtt_publish_mock, "mqtt.async_publish was not called"
    call = mqtt_publish_mock[-1]
    assert call["topic"] == "print/pos/printer/update"
    payload = json.loads(call["payload"])
    assert payload["version"] == entity.latest_version
