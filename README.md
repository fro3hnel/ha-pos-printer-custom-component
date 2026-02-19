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
| `pos_printer.print`  | Build and send a print job fully via GUI fields |
| `pos_printer.print_job` | Send a full job object |

### Service Fields for `print`
- **Job fields**: `job_id`, `priority`, `paper_width`, `feed_after`, `expires`, `timestamp`.
- **Text element fields**: `text_content`, `text_alignment`, `text_bold`, `text_underline`, `text_italic`, `text_double_height`, `text_font`, `text_size`.
- **Barcode element fields**: `barcode_content`, `barcode_type`, `barcode_height`, `barcode_width`, `barcode_ecc_level`, `barcode_mode`, `barcode_alignment`, `barcode_text_position`, `barcode_attribute`.
- **Image element fields**: `image_content` (Base64/Data-URI), `image_alignment`, `image_nv_key`.
- **Advanced compatibility**: `message` (raw element list) and `job` (legacy full job object).

### Service Fields for `print_job`
- **job**: Full job object matching `job.schema.json` (advanced mode).

## Sensors

- **Last Job Status** (`sensor.<printer_name>_last_job_status`): Status of the last print job.  
- **Last Job ID** (`sensor.<printer_name>_last_job_id`): ID of the last print job.  
- **Last Status Update** (`sensor.<printer_name>_last_status_update`): Timestamp of the last status message.  
- **Successful Jobs** (`sensor.<printer_name>_successful_jobs`): Count of successful print jobs.  
- **Job Error** (`binary_sensor.<printer_name>_job_error`): Indicates if the last job failed; shows a persistent notification on error.

## Device Controls and Updates

- **Bridge update** (`update.<printer_name>_bridge`): Uses the Home Assistant update mechanism and triggers a bridge software update on the Pi.
- **Restart bridge** button: Reboots the Raspberry Pi running the bridge service.
- **Update Pi software** button: Runs `apt-get update/upgrade/autoremove` on the Raspberry Pi via MQTT command.

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

## Minimal Raspberry Pi Zero W Image Build (pi-gen + Docker)
A dedicated builder component is available in:

```bash
./pi-gen-builder
```

It builds a minimal Raspberry Pi OS Lite image with the POS printer bridge preinstalled, using `pi-gen` in Docker.

Start the build from repository root:

```bash
./pi-gen-builder/build.sh
```
