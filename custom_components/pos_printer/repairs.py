"""Repairs helpers for the POS printer integration."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_PRINTER_NAME, DOMAIN, VERSION
from .validation import is_valid_printer_name

ISSUE_INVALID_PRINTER_NAME = "invalid_printer_name"
ISSUE_OUTDATED_BRIDGE_VERSION = "outdated_bridge_version"
_CONFIGURATION_URL = (
    "https://github.com/fro3hnel/ha-pos-printer-custom-component#configuration"
)
_TROUBLESHOOTING_URL = (
    "https://github.com/fro3hnel/ha-pos-printer-custom-component#troubleshooting"
)


def _invalid_printer_issue_id(entry_id: str) -> str:
    return f"{ISSUE_INVALID_PRINTER_NAME}_{entry_id}"


def _outdated_bridge_issue_id(entry_id: str) -> str:
    return f"{ISSUE_OUTDATED_BRIDGE_VERSION}_{entry_id}"


def async_validate_printer_name_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    printer_name: str,
) -> None:
    """Create or clear a repair issue for legacy invalid printer names."""
    issue_id = _invalid_printer_issue_id(entry.entry_id)
    if is_valid_printer_name(printer_name):
        ir.delete_issue(hass, DOMAIN, issue_id)
        return

    ir.create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_INVALID_PRINTER_NAME,
        translation_placeholders={"printer_name": printer_name},
        learn_more_url=_CONFIGURATION_URL,
    )


def async_validate_bridge_version_issue(
    hass: HomeAssistant,
    entry_id: str | None,
    printer_name: str,
    bridge_version: str | None,
) -> None:
    """Create or clear a repair issue for outdated bridge versions."""
    if entry_id is None:
        return

    issue_id = _outdated_bridge_issue_id(entry_id)
    if not bridge_version:
        ir.delete_issue(hass, DOMAIN, issue_id)
        return

    try:
        current_version = Version(bridge_version)
        minimum_version = Version(VERSION)
    except InvalidVersion:
        ir.delete_issue(hass, DOMAIN, issue_id)
        return

    if current_version >= minimum_version:
        ir.delete_issue(hass, DOMAIN, issue_id)
        return

    ir.create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_OUTDATED_BRIDGE_VERSION,
        translation_placeholders={
            "printer_name": printer_name,
            "bridge_version": bridge_version,
            "minimum_version": VERSION,
        },
        learn_more_url=_TROUBLESHOOTING_URL,
    )


def async_validate_entry_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Validate all entry-level repair issues."""
    printer_name = entry.options.get(CONF_PRINTER_NAME, entry.data[CONF_PRINTER_NAME])
    async_validate_printer_name_issue(hass, entry, printer_name)


def async_clear_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Clear all repair issues for a config entry."""
    ir.delete_issue(hass, DOMAIN, _invalid_printer_issue_id(entry_id))
    ir.delete_issue(hass, DOMAIN, _outdated_bridge_issue_id(entry_id))
