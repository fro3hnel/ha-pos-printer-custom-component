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
This integration includes English (`en.json`) and German (`de.json`) translations.
Additional languages can be added under `translations/`.

## Bridge Installation
A helper script is provided to install the Raspberry Pi service. Run on the Pi:
```bash
curl -sL https://raw.githubusercontent.com/fro3hnel/ha-pos-printer-custom-component/main/bridge/install.sh | bash
```

## Removal
Delete the integration in Home Assistant and remove the `pos_printer` folder from
`custom_components` to clean up.

## Development and Testing
Install dependencies and run tests:
```bash
pip install -r bridge/setup.py
pytest
```
