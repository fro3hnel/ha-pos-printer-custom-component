import pytest
from homeassistant.core import HomeAssistant

from custom_components.pos_printer.config_flow import PosPrinterConfigFlow


@pytest.mark.asyncio
async def test_mqtt_step_invalid_json():
    """Invalid discovery payload should abort the flow."""
    hass = HomeAssistant("")
    flow = PosPrinterConfigFlow()
    flow.hass = hass
    result = await flow.async_step_mqtt({"payload": "not-json"})
    assert result["type"] == "abort"
    assert result["reason"] == "invalid_discovery"
    await hass.async_stop()
