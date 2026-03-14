"""Validation helpers for the POS printer integration."""

from __future__ import annotations

import re

_PRINTER_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def normalize_printer_name(value: str) -> str:
    """Return a stripped printer name."""
    return value.strip()


def is_valid_printer_name(value: str) -> bool:
    """Return whether a printer name is safe to use in MQTT topics."""
    return bool(_PRINTER_NAME_PATTERN.fullmatch(normalize_printer_name(value)))
