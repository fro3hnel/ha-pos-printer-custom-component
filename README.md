# POS-Printer Bridge

Home Assistant custom integration plus Raspberry Pi bridge service for Bixolon POS printers. Jobs are sent from Home Assistant via MQTT, queued on the Pi, and printed on the POS printer.

## What Is New In This Revision

- Image preprocessing can now happen on the Home Assistant host instead of the Raspberry Pi.
- Two dashboard-friendly services were added: `pos_printer.print_text` and `pos_printer.print_image`.
- Camera entities, local media browser images, local files, URLs, Base64, and data URIs are supported as image sources.
- New sensors expose queue length, bridge version, and last job detail.
- Diagnostics support was added for easier troubleshooting.
- The bridge now respects `feed_after` from the job payload.
- Example blueprints were added for dashboard text printing and camera snapshot printing.

## Installation

### Prerequisites
- Home Assistant with the MQTT integration configured and connected to your broker.
- A Raspberry Pi running the `bridge/` service from this repository.
- A Bixolon or ESC/POS-compatible printer that works with the bridge host.

### HACS
1. Add this repository to HACS under `Integrations`.
2. Install `POS-Printer Bridge`.
3. Restart Home Assistant.

### Manual
1. Copy this repository into `<config>/custom_components/pos_printer`.
2. Restart Home Assistant.

## Configuration

1. Go to `Settings -> Devices & Services -> Integrations`.
2. Click `Add Integration` and search for `POS-Printer Bridge`.
3. Enter a printer name using only lowercase letters, numbers, underscores, and hyphens.
4. Repeat setup for each printer. Each printer uses its own MQTT topics.

You can rename a printer later via `Configure` on the integration entry.

### Configuration Parameters
- `printer_name`: Logical printer identifier and MQTT topic suffix. It must be unique per config entry and safe for MQTT topic usage.

## Removal

1. Remove the config entry in `Settings -> Devices & Services`.
2. Stop or uninstall the Raspberry Pi bridge if the printer should no longer publish discovery or status messages.
3. Delete any dashboard helpers or automations that referenced the removed printer.

## Services

### `pos_printer.print`
Advanced low-level service for full custom job payloads. It still supports the original JSON-based workflow, but now also supports host-side image processing.

### `pos_printer.print_text`
Simple text printing for dashboard helpers, buttons, and automations.

Example:

```yaml
service: pos_printer.print_text
data:
  printer_name: kitchen_printer
  title: "Kitchen"
  text: |
    Table 7
    2x Burger
    Total: 19.90 EUR
  alignment: center
```

### `pos_printer.print_image`
Simple image printing with preprocessing on the Home Assistant host.

Example with a camera entity:

```yaml
service: pos_printer.print_image
data:
  printer_name: kitchen_printer
  title: "Doorbell Snapshot"
  camera_entity_id: camera.front_door
  paper_width: 80
  image_alignment: center
```

Example with a local media file:

```yaml
service: pos_printer.print_image
data:
  printer_name: kitchen_printer
  image_media_source:
    media_content_id: media-source://media_source/local/receipts/logo.png
  caption: "Printed from local media"
```

## Supported Image Sources

The integration can resolve and preprocess these image sources on the Home Assistant host:

- Home Assistant `camera` entities
- Local media browser images (`media-source://media_source/local/...`)
- Local files inside `config`, `media`, or `www`
- `http://`, `https://`, and `file://` URLs
- Raw Base64 and data URIs

Processing options include:

- automatic paper-width based resizing
- optional max width override
- Floyd-Steinberg dithering
- manual threshold mode
- inversion
- rotation

## Dashboard Workflows

### Dashboard text input
Use the blueprint [print_input_text_message.yaml](./blueprints/automation/pos_printer/print_input_text_message.yaml) with:

- one `input_text` helper
- one `input_button` helper
- a simple dashboard card containing both helpers

Pressing the button prints the current helper content.

### Camera snapshot printing
Use the blueprint [print_camera_snapshot.yaml](./blueprints/automation/pos_printer/print_camera_snapshot.yaml) with:

- one `camera` entity
- one `input_button` helper

Pressing the button prints the latest snapshot.

## Important Limitation

Opening the native smartphone camera or private device photo library directly from an integration service is controlled by the Home Assistant frontend and mobile app, not by this backend integration. The implemented HA-native alternatives are:

- print from a Home Assistant camera entity
- print from the Home Assistant media browser
- print from dashboard text helpers and buttons

## Supported Devices

- Bixolon POS printers attached to the Raspberry Pi bridge.
- Other ESC/POS-compatible printers may work when the bridge can access them, but they are not the primary tested target.

## Supported Functions

- Text, barcode, and image print jobs
- Host-side image preprocessing on Home Assistant
- Dashboard-friendly text and image print services
- Queue, bridge version, and error diagnostics
- Bridge restart and bridge software update controls

## Data Updates

The integration is push-based. The Raspberry Pi bridge publishes status and log payloads over MQTT, and Home Assistant updates entities immediately from those events. There is no polling loop in Home Assistant for printer state.

## Use Cases

- Print kitchen or workshop task tickets from dashboards and automations
- Print doorbell or camera snapshots on receipt paper
- Print ad-hoc notes, reminders, labels, or QR/barcode slips

## Sensors And Controls

- `sensor.<printer>_last_job_status`
- `sensor.<printer>_last_job_id`
- `sensor.<printer>_last_job_detail`
- `sensor.<printer>_last_status_update`
- `sensor.<printer>_queue_length`
- `sensor.<printer>_bridge_version`
- `sensor.<printer>_last_bridge_log`
- `sensor.<printer>_successful_jobs`
- `binary_sensor.<printer>_job_error`
- `update.<printer>_bridge`
- bridge restart button
- Pi software update button

## Diagnostics

The integration now exposes diagnostics via Home Assistant diagnostics downloads. This includes config entry data, MQTT topics, and the latest status/log payloads for the selected printer.

Sensitive values are redacted before export, including printer names, MQTT topics, job IDs, message text, detail strings, and file paths.

## Repairs

Home Assistant repair issues are raised when:

- a legacy config entry still uses an invalid printer name
- the bridge reports an older version than the installed integration expects

These issue cards link back to configuration or troubleshooting guidance.

## Troubleshooting

- If no printer appears, verify that Home Assistant MQTT is connected and that the bridge publishes discovery to `pos_printer/discovery`.
- If printing works inconsistently, check the `last_bridge_log`, `queue_length`, and `bridge_version` entities for the affected printer.
- If Home Assistant shows an outdated bridge repair issue, run the bridge update action or update the Pi manually.
- If image printing fails, ensure file paths stay inside `config`, `media`, or `www`, or use a local media-source item or camera entity instead.
- Download diagnostics from the config entry before filing an issue so the latest redacted MQTT status/log payloads are available.

## Bridge Installation

Run on the Raspberry Pi:

```bash
curl -sL https://raw.githubusercontent.com/fro3hnel/ha-pos-printer-custom-component/main/bridge/install.sh | bash
```

The script clones the repository, installs dependencies, creates a virtual environment with `--system-site-packages`, adds your user to `plugdev`, and starts the bridge service.

## Development And Testing

Install test dependencies and run the test suite from repository root:

```bash
python3 -m pip install -r requirements_test.txt
python3 -m pytest
```

## Releasing

Use the local release helper from the repository root:

```bash
python3 scripts/release.py --bump patch
```

What the script does:

- validates that integration and bridge versions are aligned
- bumps the version in `custom_components/pos_printer/manifest.json` and `bridge/bridge_version.py`
- runs `pytest` by default
- builds `dist/releases/<version>/pos_printer-v<version>.zip` for manual Home Assistant installs
- generates `dist/releases/<version>/RELEASE_NOTES.md`

Useful options:

- `--version 0.3.0` to set an explicit release version
- `--skip-tests` if you intentionally want to bypass `pytest`
- `--commit --tag` to create the release commit and the git tag automatically
- `--dry-run --allow-dirty` to preview the next release without changing files

Important: the git tag created by the script intentionally matches the plain version number, for example `0.3.0`. The bridge self-update flow installs from that exact tag name.

## Minimal Raspberry Pi Zero W Image Build

The repository also contains `pi-gen-builder/` for building a minimal Raspberry Pi OS Lite image with the bridge preinstalled:

```bash
./pi-gen-builder/build.sh
```
