# POS-Printer Bridge

Home Assistant custom integration and Raspberry Pi bridge for printing text,
barcodes, QR codes, and images on Bixolon POS printers.
Home Assistant publishes jobs over MQTT, the bridge stores them in a
Redis-backed priority queue, and the printer processes them in order.

## Architecture

```text
Home Assistant action -> MQTT broker -> Raspberry Pi bridge -> Redis queue -> printer
                                      <- status, logs, heartbeat, availability
```

The integration is push-based. It does not poll: acknowledgements, queue data,
bridge health, and logs arrive over MQTT. The bridge publishes retained
availability with an MQTT last will, so Home Assistant can distinguish an
offline bridge from stale data.

## Prerequisites

- Home Assistant 2025.11 or newer.
- Home Assistant with the MQTT integration configured and connected.
- A Raspberry Pi or compatible Linux host running the bridge.
- Redis reachable by the bridge.
- A supported Bixolon printer, or an ESC/POS-compatible printer known to work
  with the bridge host and driver.

## Installation

### Home Assistant integration via HACS

1. Add this repository to HACS as a custom **Integration** repository.
2. Install **POS-Printer Bridge**.
3. Restart Home Assistant.

### Manual Home Assistant installation

1. Copy `custom_components/pos_printer` into the Home Assistant `config/custom_components`
   directory.
2. Restart Home Assistant.

### Raspberry Pi bridge

Run this on the Raspberry Pi:

```bash
git clone https://github.com/fro3hnel/ha-pos-printer-custom-component.git
cd ha-pos-printer-custom-component
sudo ./bridge/install.sh
```

The installer installs the bridge dependencies from Raspberry Pi OS packages,
copies the runtime, configures the system service, and starts the bridge.
See [bridge/README.md](./bridge/README.md) for manual setup and environment
parameters.

### Upgrade compatibility

Update the Home Assistant integration and Raspberry Pi bridge together. They
form one MQTT protocol pair for discovery, availability, acknowledgements, and
job deduplication. Existing clients can continue to submit compatible jobs after
the upgrade, but clients that do not know the new `duplicate` status may display
it as an unknown value.

## Home Assistant setup

The preferred flow is MQTT discovery:

1. Start the configured bridge.
2. Open **Settings > Devices & services** in Home Assistant.
3. Select the discovered **POS-Printer Bridge** and confirm setup.

Manual setup is also available through **Add integration > POS-Printer Bridge**.
Enter the exact MQTT printer identifier configured on the bridge. It may contain
only lowercase letters, numbers, underscores, and hyphens.

The printer identifier is a stable technical identity, not its friendly display
name. Rename the Home Assistant device if a nicer name is desired. To change the
MQTT identifier itself, update the bridge and remove/add the Home Assistant entry
as a new printer.

### Per-printer defaults

Select **Configure** on an integration entry to set:

- receipt paper width: 53 mm or 80 mm;
- line feeds after a job: 0-20.

Actions use these values when they do not provide an explicit override.

## Actions

New automations should select the printer through `config_entry_id`. The Actions
editor presents this as a filtered printer picker. `printer_name` remains
available as an advanced compatibility field for older automations.

When the bridge is known to be offline, an action fails visibly instead of
publishing a job that would be lost. A successful action call means MQTT accepted
the job; final print completion is reported asynchronously by the status entity.

### `pos_printer.print_text`

The normal action for notes, reminders, tickets, and templated automation text.

```yaml
action: pos_printer.print_text
data:
  config_entry_id: 01JEXAMPLECONFIGENTRY
  title: Kitchen
  text: |-
    Table 7
    2x Burger
    Total: 19.90 EUR
  alignment: left
```

Fields:

- Target: `config_entry_id`; legacy `printer_name`.
- Content: `title`, `text`, and `footer`; at least one must contain text.
- Style: `alignment`, `title_alignment`, `footer_alignment`, `title_bold`,
  `title_double_height`, `body_bold`, and `footer_bold`.
- Job settings: `priority` (0 is highest), `paper_width`, `feed_after`, `expires`,
  `timestamp`, and optional `job_id`.

Home Assistant generates a UUID when `job_id` is omitted. A custom ID must be a
non-empty string of at most 128 characters and unique for each intended physical
print. Reuse an ID only when redelivering that same job: the bridge remembers it
per printer for 24 hours and will not enqueue it again.

### `pos_printer.print_image`

Prints one image after processing it on the Home Assistant host.

```yaml
action: pos_printer.print_image
data:
  config_entry_id: 01JEXAMPLECONFIGENTRY
  title: Doorbell
  camera_entity_id: camera.front_door
  caption: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
```

Choose exactly one source:

- `camera_entity_id`;
- `image_media_source` from the local media browser;
- `image_path` inside the Home Assistant config, media, or `www` directory;
- `image_url` using HTTP(S) or an allowed `file://` path;
- `image_content` containing Base64 or a data URI.

Image options are `image_alignment`, `image_max_width`, `image_threshold`,
`image_dither`, `image_invert`, `image_rotation`, `image_fetch_timeout`, and the
advanced passthrough fields `image_process_on_host` and `image_nv_key`. Title and
caption alignment/bold options plus the common job settings are also supported.
Input is limited to 10 MiB and 40 megapixels.

### `pos_printer.print_pictograms`

Combines one to twelve child-friendly black-and-white pictograms into a single
offline-rendered receipt image. No external image host, font, or bridge update
is required.

```yaml
action: pos_printer.print_pictograms
data:
  config_entry_id: 01JEXAMPLECONFIGENTRY
  title: Was ziehe ich heute an?
  subtitle: 21.07.2026 · 07:00–17:00 · 18–25 °C
  pictograms:
    - t_shirt
    - shorts
    - sneakers
```

Supported names are `t_shirt`, `long_sleeve`, `shorts`, `trousers`, `sweater`,
`light_jacket`, `winter_coat`, `raincoat`, `beanie`, `gloves`, `sneakers`,
`rain_boots`, `winter_boots`, `umbrella`, and `unknown`. Names must be unique;
their order is preserved. The action automatically uses a two-column grid on
53 mm paper and a three-column grid on 80 mm paper. `title` and `subtitle` are
optional, and the common job settings are supported.

### `pos_printer.print`

Advanced action for mixed text/barcode/image jobs or a complete protocol object.
It accepts:

- `job`: a full job object or JSON string;
- `message`: a list of protocol elements or JSON string;
- text builder fields: `text_content`, `text_lines`, `text_alignment`,
  `text_bold`, `text_underline`, `text_italic`, `text_double_height`,
  `text_font`, and `text_size`;
- barcode builder fields: `barcode_content`, `barcode_type`, `barcode_height`,
  `barcode_width`, `barcode_ecc_level`, `barcode_mode`, `barcode_alignment`,
  `barcode_text_position`, and `barcode_attribute`;
- the same image source/options and common job settings described above.

The protocol is documented by [schema/job.schema.json](./schema/job.schema.json).
The Actions editor and
[services.yaml](./custom_components/pos_printer/services.yaml) are the canonical
field reference.

## Job lifecycle

The last-job status uses these states:

- `queued`: persisted in the bridge queue;
- `duplicate`: the same job ID was already accepted for this printer during the
  24-hour window; no second queue entry or physical print is created;
- `printing`: handed to the printer driver;
- `success`: completed without an element error;
- `partial-error`: at least one job element failed;
- `error`: the job failed;
- `expired`: its `expires` lifetime elapsed before printing.

The bridge does not automatically retry a failed physical print. This avoids
duplicate receipts when a printer error occurs after partial output.

## Entities and controls

| Entity | Default | Purpose |
| --- | --- | --- |
| Bridge connection | Enabled | MQTT/LWT connectivity |
| Last print job status | Enabled | Current job lifecycle state |
| Print job error | Enabled | On for error, partial error, or expiry |
| Last print job ID | Disabled | Correlation/debugging |
| Last print job detail | Disabled | Bridge error detail |
| Last status update | Disabled | Last bridge timestamp |
| Queue length | Disabled | Jobs waiting on the bridge |
| Bridge version | Disabled | Installed bridge version |
| Last bridge log message | Disabled | Diagnostic bridge log |
| Successful print jobs | Disabled | Redis-persisted total |
| Restart bridge service | Disabled | Restart only the bridge process through systemd |

Bridge and host OS updates are deliberately not executable through MQTT. Update
the checked-out repository and rerun `sudo ./bridge/install.sh`, or rebuild the
managed Pi image. This avoids granting the unprivileged print service package-
management or reboot rights.

## Automations and blueprints

Blueprints in this repository are not installed automatically by HACS. Import
the raw URL through **Settings > Automations & scenes > Blueprints > Import
blueprint**.

- [Dashboard text helper](https://raw.githubusercontent.com/fro3hnel/ha-pos-printer-custom-component/main/blueprints/automation/pos_printer/print_input_text_message.yaml)
- [Camera snapshot](https://raw.githubusercontent.com/fro3hnel/ha-pos-printer-custom-component/main/blueprints/automation/pos_printer/print_camera_snapshot.yaml)
- [Text on any trigger](https://raw.githubusercontent.com/fro3hnel/ha-pos-printer-custom-component/main/blueprints/automation/pos_printer/print_text_on_trigger.yaml)
- [To-do or shopping list](https://raw.githubusercontent.com/fro3hnel/ha-pos-printer-custom-component/main/blueprints/automation/pos_printer/print_todo_list.yaml)
- [Child-friendly clothing recommendation](https://raw.githubusercontent.com/fro3hnel/ha-pos-printer-custom-component/main/blueprints/automation/pos_printer/print_clothing_recommendation.yaml)

The clothing recommendation blueprint requires an hourly-capable `weather`
entity and Home Assistant 2025.11 or newer. It evaluates a configurable daytime
window, converts Fahrenheit forecasts to Celsius for its threshold rules, and
prints a question-mark pictogram when no usable forecast is available. Its
default window is 07:00–17:00; after that window ends, the next day's window is
used. The standard rules are:

- T-shirt from an 18 °C maximum, otherwise a long-sleeve shirt;
- shorts from a 16 °C minimum and 22 °C maximum, otherwise trousers;
- sweater below a 16 °C minimum;
- light jacket below a 12 °C minimum unless rain or winter clothing applies;
- winter coat, beanie, gloves, and winter boots below a 5 °C minimum or for
  snow/hail;
- raincoat and rain boots from 40% rain probability or a rainy condition, with
  umbrella alternatives selectable in the blueprint.

All thresholds are available in the collapsed advanced section. With the
summary enabled, a header looks like
`21.07.2026 · 07:00–17:00 · 12–22 °C · Regen: 40 %`.

Useful automation ideas include:

- print a shopping list from a dashboard button or at departure time;
- print a doorbell snapshot;
- print workshop, kitchen, or household task tickets;
- print a daily calendar agenda or medication reminder;
- print guest Wi-Fi or inventory QR labels;
- notify when the error sensor turns on or queue length crosses a threshold.

The integration does not register custom automation triggers or conditions.
Use native state/numeric-state triggers and conditions with its entities. This
keeps automations editable in the visual editor and avoids integration-specific
device IDs.

## Diagnostics and repairs

Config-entry diagnostics contain redacted configuration, MQTT topics, the latest
status payload, and the latest bridge log payload. Printer names, topics, job
IDs, message text, details, and file paths are redacted.

Repair issues are created when:

- a legacy config entry contains an invalid MQTT printer identifier;
- the bridge reports a version older than the installed integration.

## Known limitations

- Smartphone camera/photo-library pickers belong to the Home Assistant frontend;
  backend actions can use camera entities and the media browser instead.
- The integration targets Bixolon first. Other ESC/POS devices are best-effort.
- Printer hardware status is currently exposed only as raw bridge diagnostics;
  paper-out and cover-open entities require verified SDK status-bit mappings.
- Action completion confirms MQTT publication, not physical paper output. Watch
  the last-job status for the final result.
- Bridge and integration releases should be kept aligned.

## Security notes

The MQTT account used by the bridge can receive print and bridge-process restart
commands. Use broker authentication, TLS where appropriate, and topic ACLs that
restrict each bridge to its own `print/pos/<printer>/#` namespace. Do not expose
the broker or the setup portal directly to the public internet.

## Removal

1. Remove the integration entry in **Settings > Devices & services**.
2. Stop or uninstall the Raspberry Pi bridge.
3. Remove automations, helpers, or dashboards that reference the printer.
4. If upgrading from an old bridge, the current bridge automatically removes
   its former retained MQTT sensor-discovery topics.

## Quality and development

The current Quality Scale self-audit and remaining roadmap are documented in
[QUALITY_SCALE.md](./QUALITY_SCALE.md). The Home Assistant integration code has
more than 95% automated line coverage.

Install the test dependencies and run the suite from the repository root:

```bash
python3 -m pip install -r requirements_test.txt
python3 -m pytest
```

Create a release with:

```bash
python3 scripts/release.py --bump patch
```

The helper aligns integration/bridge versions, runs tests, builds the manual
installation ZIP, and generates release notes. See `--help` for explicit
versions, dry runs, commits, and tags.

## Raspberry Pi image build

`pi-gen-builder/` can create a minimal Raspberry Pi OS Lite image with the
bridge and local onboarding portal preinstalled:

```bash
./pi-gen-builder/build.sh
```

On first boot without Wi-Fi, the image exposes a setup access point and local
portal at `http://10.42.0.1/`.
