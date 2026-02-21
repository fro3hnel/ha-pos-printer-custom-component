"""Printer service utilities for the POS printer integration."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _parse_json_if_needed(value: Any, field_name: str) -> Any:
    """Parse JSON strings used in service fields."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as err:
            raise HomeAssistantError(
                f"Field '{field_name}' must contain valid JSON."
            ) from err
    return value


def _coerce_message(value: Any) -> list[dict[str, Any]] | None:
    """Normalize the message field to a list."""
    if value is None:
        return None
    message = _parse_json_if_needed(value, "message")
    if not isinstance(message, list):
        raise HomeAssistantError("Field 'message' must be a list of elements.")
    return message


def _coerce_datetime(value: Any) -> Any:
    """Convert datetime/date values to strings for JSON payloads."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _build_text_element(data: dict[str, Any]) -> dict[str, Any] | None:
    """Build a text element from GUI fields."""
    content = data.get("text_content")
    if content in (None, ""):
        return None

    element: dict[str, Any] = {"type": "text", "content": content}

    if (alignment := data.get("text_alignment")) is not None:
        element["alignment"] = alignment
    if data.get("text_bold"):
        element["bold"] = True
    if data.get("text_underline"):
        element["underline"] = True
    if data.get("text_italic"):
        element["italic"] = True
    if data.get("text_double_height"):
        element["double_height"] = True
    if (font := data.get("text_font")) is not None:
        element["font"] = font
    if (size := data.get("text_size")) is not None:
        element["size"] = size
    return element


def _build_barcode_element(data: dict[str, Any]) -> dict[str, Any] | None:
    """Build a barcode element from GUI fields."""
    content = data.get("barcode_content")
    if content in (None, ""):
        return None

    element: dict[str, Any] = {
        "type": "barcode",
        "content": content,
        "barcode_type": data.get("barcode_type") or "code128",
    }

    if (height := data.get("barcode_height")) is not None:
        element["height"] = height
    if (width := data.get("barcode_width")) is not None:
        element["width"] = width
    if (ecc_level := data.get("barcode_ecc_level")) is not None:
        element["eccLevel"] = ecc_level
    if (mode := data.get("barcode_mode")) is not None:
        element["mode"] = mode
    if (alignment := data.get("barcode_alignment")) is not None:
        element["alignment"] = alignment
    if (text_position := data.get("barcode_text_position")) is not None:
        element["textPosition"] = text_position
    if (attribute := data.get("barcode_attribute")) is not None:
        element["attribute"] = attribute
    return element


def _build_image_element(data: dict[str, Any]) -> dict[str, Any] | None:
    """Build an image element from GUI fields."""
    content = data.get("image_content")
    if content in (None, ""):
        return None

    element: dict[str, Any] = {"type": "image", "content": content}
    if (alignment := data.get("image_alignment")) is not None:
        element["alignment"] = alignment
    if (nv_key := data.get("image_nv_key")) is not None:
        element["nv_key"] = nv_key
    return element


def _build_message_from_gui_fields(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Create message list from dedicated GUI fields."""
    message: list[dict[str, Any]] = []
    for builder in (_build_text_element, _build_barcode_element, _build_image_element):
        if element := builder(data):
            message.append(element)
    return message


def _resolve_target_printer(
    call: ServiceCall,
    printers: dict[str, dict[str, Any]],
) -> str:
    """Resolve the printer target for a service call."""
    target = call.data.get("printer_name")
    if target:
        if target not in printers:
            raise HomeAssistantError(f"Unknown printer '{target}'.")
        return target

    if len(printers) == 1:
        return next(iter(printers))

    raise HomeAssistantError(
        "Field 'printer_name' is required when multiple printers are configured."
    )


async def setup_print_service(hass: HomeAssistant, config: dict[str, Any]) -> None:
    """Register print services and MQTT listeners for a printer."""
    await mqtt.async_wait_for_mqtt_client(hass)

    data = hass.data.setdefault(DOMAIN, {})
    printers: dict[str, dict[str, Any]] = data.setdefault("printers", {})

    printer_name: str = config["printer_name"]
    print_topic = f"print/pos/{printer_name}/job"
    status_topic = f"print/pos/{printer_name}/ack"
    log_topic = f"print/pos/{printer_name}/log"

    if printer_name in printers:
        existing = printers.pop(printer_name)
        if (unsub_status := existing.get("unsub_status")):
            unsub_status()
        if (unsub_log := existing.get("unsub_log")):
            unsub_log()

    if not data.get("service_registered"):

        async def handle_print(call: ServiceCall) -> None:
            """Send print data via MQTT to the selected printer."""
            target = _resolve_target_printer(call, printers)
            publish_topic: str = printers[target]["print_topic"]

            job_data: dict[str, Any] | None = None
            message = _coerce_message(call.data.get("message"))
            priority = call.data.get("priority")

            if message is None and (raw_job := call.data.get("job")) is not None:
                parsed_job = _parse_json_if_needed(raw_job, "job")
                if not isinstance(parsed_job, dict):
                    raise HomeAssistantError("Field 'job' must be an object.")
                job_data = dict(parsed_job)
                message = _coerce_message(job_data.get("message"))
                if priority is None:
                    priority = job_data.get("priority")

            if message is None:
                message = _build_message_from_gui_fields(call.data)
                if not message:
                    raise HomeAssistantError(
                        "No message elements provided. "
                        "Use 'message' or fill at least one of "
                        "'text_content', 'barcode_content', or 'image_content'."
                    )

            job_id = (
                call.data.get("job_id")
                or (job_data.get("job_id") if job_data else None)
                or uuid.uuid4().hex
            )

            payload: dict[str, Any] = {
                "job_id": job_id,
                "priority": 5 if priority is None else priority,
                "message": message,
            }

            for field in ("paper_width", "feed_after", "expires", "timestamp"):
                value = call.data.get(field)
                if value is None and job_data:
                    value = job_data.get(field)
                if value is not None:
                    payload[field] = _coerce_datetime(value)

            await mqtt.async_publish(
                hass,
                topic=publish_topic,
                payload=json.dumps(payload),
                qos=1,
            )

        async def handle_print_job(call: ServiceCall) -> None:
            """Send full job object via MQTT to the selected printer."""
            target = _resolve_target_printer(call, printers)
            publish_topic: str = printers[target]["print_topic"]

            raw_job = _parse_json_if_needed(call.data.get("job", {}), "job")
            if not isinstance(raw_job, dict):
                raise HomeAssistantError("Field 'job' must be an object.")

            job = dict(raw_job)
            job.setdefault("job_id", call.data.get("job_id") or uuid.uuid4().hex)
            if (timestamp := job.get("timestamp")) is not None:
                job["timestamp"] = _coerce_datetime(timestamp)

            await mqtt.async_publish(
                hass,
                topic=publish_topic,
                payload=json.dumps(job),
                qos=1,
            )

        hass.services.async_register(DOMAIN, "print", handle_print)
        hass.services.async_register(DOMAIN, "print_job", handle_print_job)
        data["service_registered"] = True

    @callback
    def handle_status(msg: Any) -> None:
        try:
            payload = json.loads(msg.payload)
            if not isinstance(payload, dict):
                raise TypeError("Status payload must be a JSON object")
            payload["printer_name"] = printer_name
        except json.JSONDecodeError:
            return
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error handling status payload")
            return
        hass.bus.async_fire(f"{DOMAIN}.status", payload)

    @callback
    def handle_bridge_log(msg: Any) -> None:
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error handling bridge log payload")
            return

        if not isinstance(payload, dict):
            return

        payload.setdefault("printer_name", printer_name)
        hass.bus.async_fire(f"{DOMAIN}.bridge_log", payload)

        level_name = str(payload.get("level", "INFO")).upper()
        level = getattr(logging, level_name, logging.INFO)
        logger_name = str(payload.get("logger", "printer_bridge"))
        message = str(payload.get("message", ""))
        _LOGGER.log(level, "Bridge log [%s]: %s", logger_name, message)

    unsub_status = await mqtt.async_subscribe(hass, status_topic, handle_status)
    unsub_log = await mqtt.async_subscribe(hass, log_topic, handle_bridge_log)
    printers[printer_name] = {
        "print_topic": print_topic,
        "unsub_status": unsub_status,
        "unsub_log": unsub_log,
    }


async def unload_print_service(hass: HomeAssistant, config: dict[str, Any]) -> None:
    """Remove MQTT subscriptions and services for a printer."""
    data = hass.data.get(DOMAIN)
    if not data:
        return

    printers: dict[str, dict[str, Any]] = data.get("printers", {})
    printer_name = config["printer_name"]

    info = printers.pop(printer_name, None)
    if info:
        if (unsub_status := info.get("unsub_status")):
            unsub_status()
        if (unsub_log := info.get("unsub_log")):
            unsub_log()

    if not printers:
        hass.services.async_remove(DOMAIN, "print")
        hass.services.async_remove(DOMAIN, "print_job")
        hass.data.pop(DOMAIN, None)
