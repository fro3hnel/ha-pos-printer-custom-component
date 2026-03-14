"""Tests for diagnostics output."""

from types import SimpleNamespace

import pytest

from custom_components.pos_printer.diagnostics import async_get_config_entry_diagnostics
from custom_components.pos_printer.models import DomainData, PrinterRuntimeData


@pytest.mark.asyncio
async def test_diagnostics_redacts_sensitive_runtime_fields():
    """Diagnostics should redact printer names, topics, and log/status details."""
    runtime = PrinterRuntimeData(
        entry_id="entry-1",
        printer_name="kitchen_printer",
        print_topic="print/pos/kitchen_printer/job",
        status_topic="print/pos/kitchen_printer/ack",
        log_topic="print/pos/kitchen_printer/log",
        last_status={"job_id": "abc", "detail": "paper jam", "status": "error"},
        last_log={"message": "something happened", "file": "/tmp/x.py", "line": 10},
    )
    hass = SimpleNamespace(data={"pos_printer": DomainData(printers={"kitchen_printer": runtime})})
    entry = SimpleNamespace(
        data={"printer_name": "kitchen_printer"},
        options={},
        as_dict=lambda: {
            "title": "kitchen_printer",
            "data": {"printer_name": "kitchen_printer"},
        },
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["title"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["printer_name"] == "**REDACTED**"
    assert diagnostics["runtime"]["printer_name"] == "**REDACTED**"
    assert diagnostics["runtime"]["topics"]["print"] == "**REDACTED**"
    assert diagnostics["runtime"]["last_status"]["job_id"] == "**REDACTED**"
    assert diagnostics["runtime"]["last_log"]["message"] == "**REDACTED**"
    assert diagnostics["registered_printers_count"] == 1


@pytest.mark.asyncio
async def test_diagnostics_handles_missing_runtime():
    """Diagnostics should still return a valid structure without runtime data."""
    hass = SimpleNamespace(data={"pos_printer": DomainData(printers={})})
    entry = SimpleNamespace(
        data={"printer_name": "printer"},
        options={},
        as_dict=lambda: {"title": "printer", "data": {"printer_name": "printer"}},
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["runtime"] is None
    assert diagnostics["registered_printers_count"] == 0
