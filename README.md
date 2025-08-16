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
3. Enter a printer name. The MQTT settings from Home Assistant are used automatically.

### Options
After setup, you can adjust the printer name via **Configure** on the integration entry.

## Services

| Service              | Description                                           |
|----------------------|-------------------------------------------------------|
| `pos_printer.print`  | Send print elements with automatic `job_id` |
| `pos_printer.print_job` | Send a full job object |

### Service Fields for `print`
- **priority**: Print priority (0–9, 0 = highest).
- **message**: List of print elements (text, barcode, image).

### Service Fields for `print_job`
- **job**: Full job JSON matching `job.schema.json`.

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
A helper script installs the Raspberry Pi service **and** sets up a systemd unit. Run on the Pi:
```bash
curl -sL https://raw.githubusercontent.com/fro3hnel/ha-pos-printer-custom-component/main/bridge/install.sh | bash
```
The script clones this repository, installs dependencies (including `python3-pil`),
creates a virtual environment with `--system-site-packages`, adds your user to the
`plugdev` group for USB printer access and starts `pos-printer.service`.

## Removal
Delete the integration in Home Assistant and remove the `pos_printer` folder from
`custom_components` to clean up.

## Development and Testing
Install dependencies and run tests:
```bash
pip install -r bridge/setup.py
pytest
```

