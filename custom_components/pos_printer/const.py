DOMAIN = "pos_printer"
CONF_PRINTER_NAME = "printer_name"

import json
from pathlib import Path

with open(Path(__file__).with_name("manifest.json"), "r", encoding="utf-8") as _f:
    VERSION = json.load(_f)["version"]

