# POS-Printer Bridge

## Overview
The POS-Printer Bridge integration allows Home Assistant to send print jobs over MQTT to a Raspberry Pi Zero W service, which handles printing on Bixolon POS printers.

## Installation

### HACS
1. Add this repository to HACS under “Integrations”.
2. Install the **POS Printer Bridge** integration.
3. Restart Home Assistant.

### Manual
1. Clone this repository into `<config>/custom_components/pos_printer`.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Integrations**.
2. Click **Add Integration** and search for **POS-Printer Bridge**.
3. Enter your MQTT broker address and a printer name.

### Options
After setup, adjust the MQTT broker or printer name via **Configure** on the integration entry.

## Services

| Service              | Description                                           |
|----------------------|-------------------------------------------------------|
| `pos_printer.print`  | Send a print job with automatic `job_id`, `priority`, `message` |

### Service Fields
- **priority**: Print priority (0–9, 0 = highest).
- **message**: List of print elements (text, barcode, image).

## Sensors

- **Last Job Status** (`sensor.<printer_name>_last_job_status`): Status of the last print job.  
- **Last Job ID** (`sensor.<printer_name>_last_job_id`): ID of the last print job.  
- **Last Status Update** (`sensor.<printer_name>_last_status_update`): Timestamp of the last status message.  
- **Successful Jobs** (`sensor.<printer_name>_successful_jobs`): Count of successful print jobs.  
- **Job Error** (`binary_sensor.<printer_name>_job_error`): Indicates if the last job failed; shows a persistent notification on error.

## Translations
This integration includes German (`de.json`) translations. To add more languages, create corresponding JSON files in `translations/`.

## Development and Testing
Install development requirements and run tests:
```bash
pip install pytest
pytest --cov custom_components/pos_printer
---

**`tests/test_config_flow.py`**:

```python
"""Tests for config flow of POS-Printer Bridge."""
import pytest
from homeassistant import config_entries
from custom_components.pos_printer.config_flow import PosPrinterConfigFlow, OptionsFlowHandler
from custom_components.pos_printer.const import DOMAIN, CONF_MQTT_BROKER, CONF_PRINTER_NAME

@pytest.fixture
def config_flow(hass):
    """Return a new config flow instance."""
    flow = PosPrinterConfigFlow()
    flow.hass = hass
    return flow

async def test_show_user_form(config_flow):
    """Test that the user step shows a form."""
    result = await config_flow.async_step_user()
    assert result["type"] == "form"
    assert result["step_id"] == "user"

async def test_create_entry(config_flow):
    """Test that valid data creates an entry."""
    user_input = {CONF_MQTT_BROKER: "broker", CONF_PRINTER_NAME: "printer"}
    result = await config_flow.async_step_user(user_input)
    assert result["type"] == "create_entry"
    assert result["title"] == "printer"
    assert result["data"] == user_input

async def test_options_flow(hass):
    """Test the options flow schema and defaults."""
    entry = config_entries.ConfigEntry(
        domain=DOMAIN,
        data={CONF_MQTT_BROKER: "broker", CONF_PRINTER_NAME: "printer"},
        options={},
        entry_id="test",
        title="printer",
        source=config_entries.SOURCE_USER
    )
    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] == "form"
    schema = result["data_schema"]
    assert CONF_MQTT_BROKER in schema.schema
    assert CONF_PRINTER_NAME in schema.schema