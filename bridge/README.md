# POS-Printer Bridge for Home Assistant

Python service for Raspberry Pi Zero W that consumes MQTT print jobs, buffers
them in Redis, and prints them on a Bixolon POS printer via the native C SDK.

The manual install path is aligned with the `pi-gen` image:

- runtime files live in `/opt/pos-printer-bridge`
- the systemd unit is `pos-printer-bridge.service`
- service configuration is stored in `/etc/default/pos-printer-bridge`
- `/opt/pos-printer-bridge/.env` is kept as a mirror for manual runs
- the Bixolon SRP-330II USB rule is installed as `/etc/udev/rules.d/99-bixolon-srp-330ii.rules`

## Features

- Per-printer MQTT jobs with queued, duplicate, printing, and final acknowledgements
- Retained availability with an MQTT last will
- Redis-backed priority spool with atomic 24-hour job-ID deduplication and a
  persistent successful-job counter
- 53 mm and 80 mm paper width support
- Retained discovery for the Home Assistant custom integration
- Expiry checks before physical output
- Bixolon USB, Bluetooth and LAN port strings via the vendor SDK

## Hardware

- Host: Raspberry Pi Zero W or similar Linux system with Python 3.10 or newer
- Recommended OS: Raspberry Pi OS Bookworm or newer
- Printer: Bixolon POS printer with `libBxlPosAPI.so.1`
- Width: 53 mm or 80 mm

## Manual Install

Prerequisites:

```bash
# The Bixolon SDK shared library must already be present.
ls /usr/lib/libBxlPosAPI.so.1
```

Install from the repository root:

```bash
git clone https://github.com/fro3hnel/ha-pos-printer-custom-component.git
cd ha-pos-printer-custom-component
sudo ./bridge/install.sh
```

The installer:

- creates the `posprinter` system user
- adds `posprinter` to `plugdev`, `dialout` and `lp`
- installs the runtime packages used by the `pi-gen` image
- copies the bridge runtime into `/opt/pos-printer-bridge`
- installs `pos-printer-bridge.service`
- creates `/etc/default/pos-printer-bridge` from the same defaults as the image
- installs udev rules for `1504:006e` on both the raw USB device and `/dev/usb/lp*`
- removes the legacy `pos-printer.service` if it exists

## Configure

Run the interactive configurator after install or whenever the environment changes:

```bash
sudo /opt/pos-printer-bridge/configure.sh
```

It writes:

- `/etc/default/pos-printer-bridge` for systemd
- `/opt/pos-printer-bridge/.env` as a matching mirror for manual starts

Default variables:

```ini
MQTT_BROKER=127.0.0.1
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
REDIS_URL=redis://localhost:6379/0
PRINTER_PORT=USB:
PRINTER_NAME=pos_printer
LOG_LEVEL=INFO
HEARTBEAT_INTERVAL=60
LEFT_MARGIN=0
DEFAULT_WIDTH=80
IMAGE_FETCH_TIMEOUT=10
```

Check the service after configuration:

```bash
sudo systemctl status pos-printer-bridge.service
sudo journalctl -u pos-printer-bridge.service -f
```

## Uninstall

Remove the manual installation with:

```bash
sudo /opt/pos-printer-bridge/uninstall.sh
```

Useful flags:

```bash
sudo /opt/pos-printer-bridge/uninstall.sh --keep-config
sudo /opt/pos-printer-bridge/uninstall.sh --keep-user
sudo /opt/pos-printer-bridge/uninstall.sh --keep-udev
sudo /opt/pos-printer-bridge/uninstall.sh --yes
```

The uninstall script removes the bridge service and runtime files, and optionally
the configuration and service user. Installed OS packages are left untouched.

## Manual Run

For local debugging from the installed runtime:

```bash
cd /opt/pos-printer-bridge
sudo -u posprinter /usr/bin/python3 printer_bridge.py
```

For local development from the repository checkout, create `bridge/.env`
manually or copy the installed configuration:

```bash
cp /etc/default/pos-printer-bridge bridge/.env
python3 bridge/printer_bridge.py
```

## MQTT Topics

- Publish a job to `print/pos/<printer_name>/job`
- Subscribe for acknowledgements on `print/pos/<printer_name>/ack`
- Subscribe for retained bridge status on `print/pos/<printer_name>/status`
- Subscribe for bridge logs on `print/pos/<printer_name>/log`
- Subscribe for retained availability on `print/pos/<printer_name>/availability`
- The bridge announces itself on `pos_printer/discovery/<printer_name>`

The custom integration creates the Home Assistant device and entities. Current
bridge versions remove the old retained MQTT sensor discovery topics to avoid
duplicate devices after an upgrade.

The optional `print/pos/<printer_name>/restart` command restarts only the bridge
service process. Bridge and Pi OS updates are intentionally performed outside
MQTT by updating the checkout and rerunning the installer or rebuilding the Pi
image.

Acknowledgements use `queued` when Redis accepts the job, `duplicate` when the
same job ID was already accepted for this printer within 24 hours, `printing`
when the worker starts it, and one of `success`, `partial-error`, `error`, or
`expired` as the final state. A duplicate acknowledgement also contains
`"duplicate": true` and never creates another queue entry. `expires` is checked
immediately before printing.

`status` is a retained JSON snapshot defined by
[`schema/status.schema.json`](../schema/status.schema.json). Its schema version
is `1`; it contains the current queue length, raw printer status, bridge
version, heartbeat interval, availability hint, and the latest job lifecycle
result. The dedicated availability topic remains authoritative for the MQTT
last-will state. The bridge updates the snapshot on connect, each job transition,
and every heartbeat.

`job_id` must be a non-empty string with at most 128 characters. Use a new ID
for every intended physical print. Reuse an ID only to redeliver the same job;
different content with the same ID is deliberately treated as a duplicate.

Example job:

```json
{
  "job_id": "weather-20250715",
  "priority": 5,
  "paper_width": 80,
  "message": [
    {"type": "text", "alignment": "center", "content": "Weather report"},
    {"type": "text", "alignment": "left", "content": "15.07: cloudy, 25C/14C"},
    {"type": "barcode", "barcode_type": "qr-code", "content": "https://example.invalid"}
  ]
}
```

## Development

Run tests from the repository root:

```bash
pytest
```

## License

MIT License. See `LICENSE`.
