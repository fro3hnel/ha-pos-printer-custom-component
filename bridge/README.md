# POS-Printer Bridge for Home Assistant

Python service for Raspberry Pi Zero W that consumes MQTT print jobs, buffers them in Redis and prints them on a Bixolon POS printer via the native C SDK.

The manual install path is aligned with the `pi-gen` image:

- runtime files live in `/opt/pos-printer-bridge`
- the systemd unit is `pos-printer-bridge.service`
- service configuration is stored in `/etc/default/pos-printer-bridge`
- `/opt/pos-printer-bridge/.env` is kept as a mirror for manual runs
- the Bixolon SRP-330II USB rule is installed as `/etc/udev/rules.d/99-bixolon-srp-330ii.rules`

## Features

- MQTT print jobs with ACK and heartbeat topics
- Redis-backed priority spool
- 53 mm and 80 mm paper width support
- Home Assistant discovery payloads for queue and status sensors
- Bixolon USB, Bluetooth and LAN port strings via the vendor SDK

## Hardware

- Host: Raspberry Pi Zero W or similar Linux system
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
- installs the runtime packages used by the `pi-gen` image
- copies the bridge runtime into `/opt/pos-printer-bridge`
- installs `pos-printer-bridge.service`
- creates `/etc/default/pos-printer-bridge` from the same defaults as the image
- installs a udev rule for `1504:006e` so the SRP-330II is accessible via `plugdev`
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

The uninstall script removes the bridge service, runtime files and optionally the configuration plus service user. Installed OS packages are left untouched.

## Manual Run

For local debugging from the installed runtime:

```bash
cd /opt/pos-printer-bridge
sudo -u posprinter /usr/bin/python3 printer_bridge.py
```

For local development from the repository checkout, create `bridge/.env` manually or copy the installed configuration:

```bash
cp /etc/default/pos-printer-bridge bridge/.env
python3 bridge/printer_bridge.py
```

## MQTT Topics

- Publish a job to `print/pos/<printer_name>/job`
- Subscribe for acknowledgements on `print/pos/<printer_name>/ack`
- Subscribe for bridge logs on `print/pos/<printer_name>/log`

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
