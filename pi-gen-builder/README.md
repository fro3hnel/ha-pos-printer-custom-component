# pi-gen Builder for Raspberry Pi Zero W

This component builds a minimal Raspberry Pi OS image for a Raspberry Pi Zero W using [pi-gen](https://github.com/RPi-Distro/pi-gen) in Docker.

The image includes:

- Raspberry Pi OS Lite base (`stage0 stage1 stage2`)
- A custom `stage-pos-printer` stage
- Minimal runtime dependencies for the bridge
- `pos-printer-bridge.service` (enabled on boot)

## Prerequisites

- Docker
- Git
- rsync

## Build

From the repository root:

```bash
./pi-gen-builder/build.sh
```

Optional environment variables:

- `PIGEN_REF` (default: `master`) - pi-gen branch/tag/commit
- `PIGEN_REPO` (default: official pi-gen repository)
- `WORK_DIR` (default: `./pi-gen-builder/.work`)
- `PIGEN_DIR` (overrides the pi-gen checkout directory)

Example:

```bash
PIGEN_REF=master ./pi-gen-builder/build.sh
```

Output images are written to:

```bash
./pi-gen-builder/.work/pi-gen/deploy/
```

## Bridge configuration on target device

The image ships with `/etc/default/pos-printer-bridge`. Update it after first boot:

- `MQTT_BROKER`
- `MQTT_USERNAME`
- `MQTT_PASSWORD`
- `PRINTER_NAME`
- `PRINTER_PORT`

Then restart:

```bash
sudo systemctl restart pos-printer-bridge.service
```

## Notes

- The Bixolon runtime library `libBxlPosAPI.so.1` must be available on the target device.
- The build copies `bridge/printer_bridge.py` (plus schema) into `/opt/pos-printer-bridge`.
