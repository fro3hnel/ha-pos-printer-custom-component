"""Printer service utilities for the POS printer integration."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, ServiceCall, callback

from .const import DOMAIN


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "job.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
    JOB_SCHEMA: dict[str, Any] = json.load(schema_file)


async def setup_print_service(hass: HomeAssistant, config: dict) -> None:
    """Register print services and MQTT status listener.

    This function can be called multiple times for different printers. The first
    call registers a single ``pos_printer.print`` service which routes print
    jobs to the correct MQTT topic based on the ``printer_name`` field.
    Subsequent calls only add new printer topics and status subscriptions.
    """

    await mqtt.async_wait_for_mqtt_client(hass)

    data = hass.data.setdefault(DOMAIN, {})
    printers: dict[str, dict[str, Any]] = data.setdefault("printers", {})

    printer_name: str = config["printer_name"]
    print_topic = f"print/pos/{printer_name}/job"
    status_topic = f"print/pos/{printer_name}/ack"

    # Register the service once
    if "service_registered" not in data:

        async def handle_print(call: ServiceCall) -> None:
            """Send print data via MQTT to the selected printer."""

            target = call.data.get("printer_name")
            if not target:
                if len(printers) == 1:
                    target = next(iter(printers))
                else:
                    # No printer specified and multiple available
                    return

            topics = printers.get(target)
            if not topics:
                return

            publish_topic: str = topics["print_topic"]

            if (job := call.data.get("job")) is not None:
                if isinstance(job, str):
                    try:
                        job = json.loads(job)
                    except json.JSONDecodeError:
                        job = {}
                job.setdefault(
                    "job_id", call.data.get("job_id") or uuid.uuid4().hex
                )
                try:
                    jsonschema.validate(job, JOB_SCHEMA)
                except jsonschema.ValidationError as err:
                    raise ValueError(f"Invalid job data: {err.message}") from err
                await mqtt.async_publish(
                    hass,
                    topic=publish_topic,
                    payload=json.dumps(job),
                    qos=1,
                )
                return

            job_id = call.data.get("job_id") or uuid.uuid4().hex
            message = call.data.get("message")
            priority = call.data.get("priority", 5)
            payload = {"job_id": job_id, "priority": priority, "message": message}
            try:
                jsonschema.validate(payload, JOB_SCHEMA)
            except jsonschema.ValidationError as err:
                raise ValueError(f"Invalid job data: {err.message}") from err
            await mqtt.async_publish(
                hass,
                topic=publish_topic,
                payload=json.dumps(payload),
                qos=1,
            )

        hass.services.async_register(DOMAIN, "print", handle_print)
        data["service_registered"] = True

    # Status-Antworten und Heartbeats abonnieren
    @callback
    def handle_status(msg):
        try:
            payload = json.loads(msg.payload)
            payload["printer_name"] = printer_name
            hass.bus.async_fire(f"{DOMAIN}.status", payload)
        except Exception:  # noqa: BLE001
            # Ignore invalid JSON payloads
            pass

    unsub = await mqtt.async_subscribe(hass, status_topic, handle_status)

    printers[printer_name] = {"print_topic": print_topic, "unsub": unsub}


async def unload_print_service(hass: HomeAssistant, config: dict) -> None:
    """Remove MQTT subscriptions and service for a printer."""

    data = hass.data.get(DOMAIN)
    if not data:
        return

    printers: dict[str, dict[str, Any]] = data.get("printers", {})
    printer_name: str = config["printer_name"]

    info = printers.pop(printer_name, None)
    if info and (unsub := info.get("unsub")):
        unsub()

    if not printers:
        await hass.services.async_remove(DOMAIN, "print")
        hass.data.pop(DOMAIN)
