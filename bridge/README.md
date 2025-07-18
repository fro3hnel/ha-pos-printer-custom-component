# POS‑Printer Bridge for Home Assistant

Python service for Raspberry Pi Zero W that consumes MQTT print jobs, buffers them in a **Redis priority queue** and prints them on a **Bixolon POS printer** via the native C‑SDK. Designed to integrate seamlessly with **Home Assistant** via MQTT Discovery.

---

## Features

| Area               | Details                                                                     |
| ------------------ | --------------------------------------------------------------------------- |
| **MQTT Topics**    | `pos/print` (jobs) → `pos/print/status` (ack + heartbeat)                   |
| **Priority Spool** | Single Redis *sorted‑set*; priorities 0–9, FIFO within same priority        |
| **Paper Width**    | 80 mm default, 53 mm per‑job override                                       |
| **JSON Schema**    | Strict validation, one‑of section for `text` / `barcode` / `image` elements |
| **Heart‑Beat**     | Printer + Pi status every *n* seconds (configurable)                        |
| **HA Discovery**   | Queue length + printer status sensors auto‑created                          |
| **Threading**      | Independent threads: MQTT client • Worker • Heart‑beat                      |
| **UTF‑8**          | `SetTextEncoding(ENCODING_ASCII)` for raw UTF‑8 passthrough                 |

---

## Hardware

* **Host**: Raspberry Pi Zero W (32‑bit Raspbian Bookworm/Ubuntu)
* **Printer**: Any Bixolon POS model with libBxlPosAPI (USB, BT, LAN)
* **Width**: 53 mm or 80 mm

---

## Quick‑Start

### Prerequisites

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-dev \
     redis-server gcc build-essential libbluetooth3 libssl-dev

# Bixolon SDK headers / .so must be in /usr/lib/libBxlPosAPI.so.1
```

### Clone & Install

```bash
git clone https://github.com/fro3hnel/hass-pos-printer-bridge.git
cd hass-pos-printer-bridge
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

Create `.env` in project root:

```ini
MQTT_BROKER=<IP>
MQTT_PORT=1883
MQTT_USERNAME=mqttuser
MQTT_PASSWORD=secret
REDIS_URL=redis://:redispass@<IP>:6379/0
PRINTER_PORT=USB:
PRINTER_NAME=<Printer Name>
LOG_LEVEL=INFO
HEARTBEAT_INTERVAL=60
LEFT_MARGIN=0
DEFAULT_WIDTH=80
```

Optional printer defaults (left margin, width) can be set here as well.

### Run

```bash
python printer_bridge.py
```

The service connects to MQTT, publishes Home‑Assistant discovery topics and waits for jobs.

---

## Systemd Service (recommended)

```ini
[Unit]
Description=POS Printer Bridge
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/pos-printer-bridge
Environment="PYTHONUNBUFFERED=1"
ExecStart=/opt/pos-printer-bridge/.venv/bin/python printer_bridge.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable with:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pos-printer.service
```

---

## MQTT Topics

* **Publish** a job → `pos/print`
* **Subscribe** for acknowledgements → `pos/print/status`

### Example Job (Weather‑Report)

```json
{
  "job_id": "weather-20250715",
  "priority": 5,
  "paper_width": 80,
  "message": [
    {"type": "text", "orientation": "center", "content": "Weather report", "bold": true},
    {"type": "text", "orientation": "center", "content": "15.07.2025", "underline": true},
    {"type": "text", "orientation": "left", "content": "15.07: cloudy, 25°C/14°C"},
    {"type": "barcode", "barcode_type": "qr-code", "content": "https://wetter.de/city"}
  ]
}
```

### ACK / Heartbeat Payload

```json
{
  "job_id": "weather-20250715",
  "status": "success",
  "detail": "",
  "queue_len": 0,
  "printer_status": 0,
  "timestamp": 1752557352
}
```

---

## JSON‑Schema

Schema file: [`job.schema.json`](job.schema.json)

Validation from Python:

```python
import json, jsonschema
from job_schema import SCHEMA  # load as dict
jsonschema.validate(payload, SCHEMA)
```

---

## Development

* Formatting: `black`, `isort`
* Tests: `pytest` (+ `pytest-mqtt` mocks)
* Linting: `ruff` / `mypy`

```bash
pip install -r dev-requirements.txt
pytest -q
```

---

## License

MIT License – see `LICENSE` file.
