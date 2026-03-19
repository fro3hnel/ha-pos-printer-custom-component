# pi-gen Builder for Raspberry Pi Zero W

This component builds a Raspberry Pi OS Lite image for a Raspberry Pi Zero W using [pi-gen](https://github.com/RPi-Distro/pi-gen) in Docker.

The image includes:

- Raspberry Pi OS Lite base (`stage0 stage1 stage2`)
- A custom `stage-pos-printer` stage
- All Python/runtime dependencies required by the bridge
- A local setup portal on port `80`
- Automatic AP fallback when no working Wi-Fi configuration is stored
- `pos-printer-bridge.service` plus provisioning units enabled on boot
- A udev rule for the Bixolon SRP-330II (`1504:006e`) plus `lp` group access for `posprinter`

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

## First boot flow

When no Wi-Fi credentials are configured, the image starts an open setup access point:

- SSID: `POS-Printer-Setup-<hostname suffix>`
- Portal URL: `http://10.42.0.1/`

The portal lets you:

- scan and save local Wi-Fi credentials
- configure the printer bridge MQTT/printer settings
- switch back to AP mode by clearing the Wi-Fi configuration

Saved settings are written to:

- `/etc/pos-printer-setup/config.json`
- `/etc/default/pos-printer-bridge`

Relevant services:

- `pos-printer-setup-apply.service`
- `pos-printer-setup-portal.service`
- `pos-printer-setup-dnsmasq.service`
- `pos-printer-bridge.service`

## Notes

- `build.sh` updates the local `pi-gen` checkout to the requested ref before each build.
- The image stays on Raspberry Pi OS `bookworm` in `pi-gen-builder/config` for bridge compatibility, while the builder itself tracks current `pi-gen`.
- The Bixolon runtime library `libBxlPosAPI.so.1` must be available on the target device.
- The build copies the bridge runtime, the setup portal and the schema into `/opt/pos-printer-bridge`.
