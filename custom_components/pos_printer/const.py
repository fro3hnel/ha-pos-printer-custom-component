"""Constants for the POS printer integration."""

from __future__ import annotations

import json
from pathlib import Path

DOMAIN = "pos_printer"
CONF_PRINTER_NAME = "printer_name"

SERVICE_PRINT = "print"
SERVICE_PRINT_IMAGE = "print_image"
SERVICE_PRINT_TEXT = "print_text"

EVENT_STATUS = f"{DOMAIN}.status"
EVENT_BRIDGE_LOG = f"{DOMAIN}.bridge_log"

DEFAULT_PRIORITY = 5
DEFAULT_PAPER_WIDTH = 80
DEFAULT_FEED_AFTER = 4
DEFAULT_IMAGE_FETCH_TIMEOUT = 15
DEFAULT_IMAGE_THRESHOLD = 180
DEFAULT_IMAGE_DITHER = True
DEFAULT_IMAGE_ALIGNMENT = "center"

PAPER_WIDTH_TO_PIXELS = {
    53: 384,
    80: 576,
}

_MANIFEST_PATH = Path(__file__).with_name("manifest.json")
with _MANIFEST_PATH.open("r", encoding="utf-8") as manifest_file:
    VERSION = json.load(manifest_file)["version"]
