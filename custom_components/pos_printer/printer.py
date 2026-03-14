"""Service registration and MQTT topic management for the POS printer integration."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from typing import Any, Mapping

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_PRINTER_NAME,
    DEFAULT_FEED_AFTER,
    DEFAULT_PAPER_WIDTH,
    DEFAULT_PRIORITY,
    EVENT_BRIDGE_LOG,
    EVENT_STATUS,
    SERVICE_PRINT,
    SERVICE_PRINT_IMAGE,
    SERVICE_PRINT_TEXT,
    DOMAIN,
)
from .image_processing import async_prepare_image_content
from .models import DomainData, PrinterRuntimeData
from .repairs import async_validate_bridge_version_issue

_LOGGER = logging.getLogger(__name__)

_ALIGNMENTS = ("left", "center", "right")
_BARCODE_TYPES = (
    "upca",
    "upce",
    "ean8",
    "ean13",
    "code39",
    "code93",
    "code128",
    "qr-code",
)
_TEXT_FONTS = ("A", "B", "C")
_IMAGE_ROTATIONS = (0, 90, 180, 270)


def _service_register(
    hass: HomeAssistant,
    service: str,
    handler,
    schema: vol.Schema,
) -> None:
    """Register a service and stay compatible with lightweight test doubles."""
    try:
        hass.services.async_register(DOMAIN, service, handler, schema=schema)
    except TypeError:
        hass.services.async_register(DOMAIN, service, handler)


def _get_domain_data(hass: HomeAssistant) -> DomainData:
    """Return shared domain data for the integration."""
    domain_data = hass.data.get(DOMAIN)
    if isinstance(domain_data, DomainData):
        return domain_data

    domain_data = DomainData()
    hass.data[DOMAIN] = domain_data
    return domain_data


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


def _coerce_message(value: Any, field_name: str = "message") -> list[dict[str, Any]] | None:
    """Normalize message payloads to a list of dictionaries."""
    if value is None:
        return None

    message = _parse_json_if_needed(value, field_name)
    if not isinstance(message, list):
        raise HomeAssistantError(f"Field '{field_name}' must be a list of elements.")
    if not all(isinstance(element, dict) for element in message):
        raise HomeAssistantError(f"Field '{field_name}' must contain only objects.")

    return message


def _coerce_datetime(value: Any) -> Any:
    """Convert datetime/date values to strings for JSON payloads."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _build_text_style(data: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    """Extract common text style attributes from service data."""
    style: dict[str, Any] = {}

    alignment = data.get(f"{prefix}alignment")
    if alignment is not None:
        style["alignment"] = alignment

    if data.get(f"{prefix}bold"):
        style["bold"] = True
    if data.get(f"{prefix}underline"):
        style["underline"] = True
    if data.get(f"{prefix}italic"):
        style["italic"] = True
    if data.get(f"{prefix}double_height"):
        style["double_height"] = True

    font = data.get(f"{prefix}font")
    if font is not None:
        style["font"] = font

    size = data.get(f"{prefix}size")
    if size is not None:
        style["size"] = size

    return style


def _make_text_element(content: str, **style: Any) -> dict[str, Any]:
    """Create a text message element."""
    element: dict[str, Any] = {"type": "text", "content": content}
    element.update(style)
    return element


def _build_text_element(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build a text element from generic GUI fields."""
    content = data.get("text_content")
    if content in (None, ""):
        return None

    return _make_text_element(str(content), **_build_text_style(data, "text_"))


def _build_text_line_elements(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build text elements from a multi-line text field."""
    raw_lines = data.get("text_lines")
    if raw_lines in (None, ""):
        return []

    lines = str(raw_lines).splitlines()
    if not any(line.strip() for line in lines):
        return []

    style = _build_text_style(data, "text_")
    return [_make_text_element(line or " ", **style) for line in lines]


def _build_barcode_element(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build a barcode element from GUI fields."""
    content = data.get("barcode_content")
    if content in (None, ""):
        return None

    element: dict[str, Any] = {
        "type": "barcode",
        "content": str(content),
        "barcode_type": data.get("barcode_type") or "code128",
    }

    mapping = {
        "barcode_height": "height",
        "barcode_width": "width",
        "barcode_ecc_level": "eccLevel",
        "barcode_mode": "mode",
        "barcode_alignment": "alignment",
        "barcode_text_position": "textPosition",
        "barcode_attribute": "attribute",
    }
    for source_key, target_key in mapping.items():
        value = data.get(source_key)
        if value is not None:
            element[target_key] = value

    return element


def _has_image_source(data: Mapping[str, Any]) -> bool:
    """Return whether service data contains any image source."""
    image_source_fields = (
        "image_content",
        "image_url",
        "image_path",
        "image_media_source",
        "camera_entity_id",
    )
    return any(data.get(field) not in (None, "") for field in image_source_fields)


async def _async_build_image_element(
    hass: HomeAssistant,
    data: Mapping[str, Any],
    paper_width: int,
) -> dict[str, Any] | None:
    """Build an image element and optionally preprocess it on the HA host."""
    if not _has_image_source(data):
        return None

    process_on_host = data.get("image_process_on_host", True)
    if process_on_host:
        content = await async_prepare_image_content(hass, dict(data), paper_width)
    else:
        if any(
            data.get(field) not in (None, "")
            for field in ("image_url", "image_path", "image_media_source", "camera_entity_id")
        ):
            raise HomeAssistantError(
                "Set 'image_process_on_host' to true when using URLs, files, media sources, or cameras."
            )
        raw_content = data.get("image_content")
        if raw_content in (None, ""):
            raise HomeAssistantError("Field 'image_content' is required for raw image passthrough.")
        content = str(raw_content)

    element: dict[str, Any] = {"type": "image", "content": content}
    if (alignment := data.get("image_alignment")) is not None:
        element["alignment"] = alignment
    if (nv_key := data.get("image_nv_key")) is not None:
        element["nv_key"] = nv_key
    return element


async def _async_build_message_from_gui_fields(
    hass: HomeAssistant,
    data: Mapping[str, Any],
    paper_width: int,
) -> list[dict[str, Any]]:
    """Create a message list from dedicated GUI fields."""
    message: list[dict[str, Any]] = []

    if element := _build_text_element(data):
        message.append(element)
    message.extend(_build_text_line_elements(data))

    if element := _build_barcode_element(data):
        message.append(element)

    if element := await _async_build_image_element(hass, data, paper_width):
        message.append(element)

    return message


def _resolve_target_printer(
    call: ServiceCall,
    printers: Mapping[str, PrinterRuntimeData],
) -> PrinterRuntimeData:
    """Resolve the printer target for a service call."""
    if not printers:
        raise HomeAssistantError("No POS printers are configured.")

    target = call.data.get(CONF_PRINTER_NAME)
    if target:
        if target not in printers:
            raise HomeAssistantError(f"Unknown printer '{target}'.")
        return printers[target]

    if len(printers) == 1:
        return next(iter(printers.values()))

    raise HomeAssistantError(
        "Field 'printer_name' is required when multiple printers are configured."
    )


def _apply_job_metadata(
    payload: dict[str, Any],
    data: Mapping[str, Any],
    job_data: Mapping[str, Any] | None,
) -> None:
    """Populate common job fields on a payload."""
    payload["job_id"] = (
        data.get("job_id")
        or (job_data or {}).get("job_id")
        or uuid.uuid4().hex
    )
    payload["priority"] = data.get(
        "priority",
        (job_data or {}).get("priority", DEFAULT_PRIORITY),
    )

    for field in ("paper_width", "feed_after", "expires", "timestamp"):
        value = data.get(field)
        if value is None and job_data is not None:
            value = job_data.get(field)
        if value is None:
            continue
        payload[field] = _coerce_datetime(value)

    payload.setdefault("paper_width", DEFAULT_PAPER_WIDTH)
    payload.setdefault("feed_after", DEFAULT_FEED_AFTER)


async def _async_build_generic_payload(
    hass: HomeAssistant,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a payload for the generic print service."""
    job_data: dict[str, Any] | None = None
    if (raw_job := data.get("job")) is not None:
        parsed_job = _parse_json_if_needed(raw_job, "job")
        if not isinstance(parsed_job, dict):
            raise HomeAssistantError("Field 'job' must be an object.")
        job_data = dict(parsed_job)

    paper_width = int(
        data.get(
            "paper_width",
            (job_data or {}).get("paper_width", DEFAULT_PAPER_WIDTH),
        )
    )

    message = _coerce_message(data.get("message"))
    if message is None and job_data is not None:
        message = _coerce_message(job_data.get("message"), "job.message")

    if message is None:
        message = await _async_build_message_from_gui_fields(hass, data, paper_width)

    if not message:
        raise HomeAssistantError(
            "No message elements provided. Fill at least one text, barcode, or image field."
        )

    payload: dict[str, Any] = dict(job_data or {})
    _apply_job_metadata(payload, data, job_data)
    payload["message"] = message
    return payload


def _build_simple_text_lines(
    raw_text: str,
    alignment: str,
    bold: bool,
) -> list[dict[str, Any]]:
    """Split a block of text into printable lines."""
    lines = raw_text.splitlines() or [raw_text]
    style: dict[str, Any] = {"alignment": alignment}
    if bold:
        style["bold"] = True
    return [_make_text_element(line or " ", **style) for line in lines]


async def _async_build_text_payload(
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a payload for the dashboard-friendly text service."""
    title = str(data.get("title", "") or "").strip()
    body = str(data.get("text", "") or "")
    footer = str(data.get("footer", "") or "").strip()

    if not any(part.strip() for part in (title, body, footer)):
        raise HomeAssistantError("At least one of title, text, or footer must contain printable content.")

    body_alignment = str(data.get("alignment", "left"))
    title_alignment = str(data.get("title_alignment", "center"))
    footer_alignment = str(data.get("footer_alignment", body_alignment))

    message: list[dict[str, Any]] = []
    if title:
        title_style: dict[str, Any] = {"alignment": title_alignment}
        if data.get("title_bold", True):
            title_style["bold"] = True
        if data.get("title_double_height", True):
            title_style["double_height"] = True
        message.append(_make_text_element(title, **title_style))

    if body:
        message.extend(
            _build_simple_text_lines(
                body,
                alignment=body_alignment,
                bold=bool(data.get("body_bold", False)),
            )
        )

    if footer:
        message.extend(
            _build_simple_text_lines(
                footer,
                alignment=footer_alignment,
                bold=bool(data.get("footer_bold", False)),
            )
        )

    payload: dict[str, Any] = {}
    _apply_job_metadata(payload, data, None)
    payload["message"] = message
    return payload


async def _async_build_image_payload(
    hass: HomeAssistant,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a payload for the dashboard-friendly image service."""
    paper_width = int(data.get("paper_width", DEFAULT_PAPER_WIDTH))
    title = str(data.get("title", "") or "").strip()
    caption = str(data.get("caption", "") or "").strip()

    image_element = await _async_build_image_element(hass, data, paper_width)
    if image_element is None:
        raise HomeAssistantError("An image source is required for the image print service.")

    message: list[dict[str, Any]] = []
    if title:
        message.append(
            _make_text_element(
                title,
                alignment=str(data.get("title_alignment", "center")),
                bold=True,
                double_height=True,
            )
        )

    message.append(image_element)

    if caption:
        message.extend(
            _build_simple_text_lines(
                caption,
                alignment=str(data.get("caption_alignment", "center")),
                bold=bool(data.get("caption_bold", False)),
            )
        )

    payload: dict[str, Any] = {}
    _apply_job_metadata(payload, data, None)
    payload["message"] = message
    return payload


async def _async_publish_payload(
    hass: HomeAssistant,
    runtime_data: PrinterRuntimeData,
    payload: dict[str, Any],
) -> None:
    """Publish a prepared job payload to MQTT."""
    await mqtt.async_publish(
        hass,
        topic=runtime_data.print_topic,
        payload=json.dumps(payload),
        qos=1,
    )


def _int_range(*, minimum: int, maximum: int | None = None):
    """Return a simple integer range validator."""
    validator = vol.All(vol.Coerce(int), vol.Range(min=minimum, max=maximum))
    return validator


_COMMON_JOB_FIELDS: dict[Any, Any] = {
    vol.Optional(CONF_PRINTER_NAME): cv.string,
    vol.Optional("job_id"): cv.string,
    vol.Optional("priority"): _int_range(minimum=0, maximum=9),
    vol.Optional("paper_width"): vol.In([53, 80]),
    vol.Optional("feed_after"): _int_range(minimum=0),
    vol.Optional("expires"): _int_range(minimum=1),
    vol.Optional("timestamp"): vol.Any(cv.string, datetime, date),
}

_IMAGE_SOURCE_FIELDS: dict[Any, Any] = {
    vol.Optional("image_content"): cv.string,
    vol.Optional("image_url"): cv.string,
    vol.Optional("image_path"): cv.string,
    vol.Optional("image_media_source"): vol.Any(dict, cv.string),
    vol.Optional("camera_entity_id"): cv.entity_id,
    vol.Optional("image_process_on_host"): cv.boolean,
    vol.Optional("image_max_width"): _int_range(minimum=1),
    vol.Optional("image_threshold"): _int_range(minimum=0, maximum=255),
    vol.Optional("image_dither"): cv.boolean,
    vol.Optional("image_invert"): cv.boolean,
    vol.Optional("image_rotation"): vol.In(_IMAGE_ROTATIONS),
    vol.Optional("image_fetch_timeout"): _int_range(minimum=1),
    vol.Optional("image_alignment"): vol.In(_ALIGNMENTS),
    vol.Optional("image_nv_key"): _int_range(minimum=0, maximum=255),
}

SERVICE_PRINT_SCHEMA = vol.Schema(
    {
        **_COMMON_JOB_FIELDS,
        vol.Optional("job"): vol.Any(dict, cv.string),
        vol.Optional("message"): vol.Any(list, cv.string),
        vol.Optional("text_content"): cv.string,
        vol.Optional("text_lines"): cv.string,
        vol.Optional("text_alignment"): vol.In(_ALIGNMENTS),
        vol.Optional("text_bold"): cv.boolean,
        vol.Optional("text_underline"): cv.boolean,
        vol.Optional("text_italic"): cv.boolean,
        vol.Optional("text_double_height"): cv.boolean,
        vol.Optional("text_font"): vol.In(_TEXT_FONTS),
        vol.Optional("text_size"): _int_range(minimum=1, maximum=8),
        vol.Optional("barcode_content"): cv.string,
        vol.Optional("barcode_type"): vol.In(_BARCODE_TYPES),
        vol.Optional("barcode_height"): _int_range(minimum=0),
        vol.Optional("barcode_width"): _int_range(minimum=1, maximum=20),
        vol.Optional("barcode_ecc_level"): vol.In(("L", "M", "Q", "H")),
        vol.Optional("barcode_mode"): _int_range(minimum=0),
        vol.Optional("barcode_alignment"): vol.In(_ALIGNMENTS),
        vol.Optional("barcode_text_position"): _int_range(minimum=0),
        vol.Optional("barcode_attribute"): _int_range(minimum=0),
        **_IMAGE_SOURCE_FIELDS,
    },
    extra=vol.PREVENT_EXTRA,
)

SERVICE_PRINT_TEXT_SCHEMA = vol.Schema(
    {
        **_COMMON_JOB_FIELDS,
        vol.Optional("title"): cv.string,
        vol.Optional("text"): cv.string,
        vol.Optional("footer"): cv.string,
        vol.Optional("alignment"): vol.In(_ALIGNMENTS),
        vol.Optional("title_alignment"): vol.In(_ALIGNMENTS),
        vol.Optional("footer_alignment"): vol.In(_ALIGNMENTS),
        vol.Optional("title_bold"): cv.boolean,
        vol.Optional("title_double_height"): cv.boolean,
        vol.Optional("body_bold"): cv.boolean,
        vol.Optional("footer_bold"): cv.boolean,
    },
    extra=vol.PREVENT_EXTRA,
)

SERVICE_PRINT_IMAGE_SCHEMA = vol.Schema(
    {
        **_COMMON_JOB_FIELDS,
        vol.Optional("title"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional("title_alignment"): vol.In(_ALIGNMENTS),
        vol.Optional("caption_alignment"): vol.In(_ALIGNMENTS),
        vol.Optional("caption_bold"): cv.boolean,
        **_IMAGE_SOURCE_FIELDS,
    },
    extra=vol.PREVENT_EXTRA,
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once per Home Assistant instance."""
    domain_data = _get_domain_data(hass)
    if domain_data.services_registered:
        return

    async def handle_print(call: ServiceCall) -> None:
        """Send a generic print job via MQTT."""
        runtime_data = _resolve_target_printer(call, domain_data.printers)
        payload = await _async_build_generic_payload(hass, call.data)
        await _async_publish_payload(hass, runtime_data, payload)

    async def handle_print_text(call: ServiceCall) -> None:
        """Send a text-focused print job via MQTT."""
        runtime_data = _resolve_target_printer(call, domain_data.printers)
        payload = await _async_build_text_payload(call.data)
        await _async_publish_payload(hass, runtime_data, payload)

    async def handle_print_image(call: ServiceCall) -> None:
        """Send an image-focused print job via MQTT."""
        runtime_data = _resolve_target_printer(call, domain_data.printers)
        payload = await _async_build_image_payload(hass, call.data)
        await _async_publish_payload(hass, runtime_data, payload)

    _service_register(hass, SERVICE_PRINT, handle_print, SERVICE_PRINT_SCHEMA)
    _service_register(hass, SERVICE_PRINT_TEXT, handle_print_text, SERVICE_PRINT_TEXT_SCHEMA)
    _service_register(hass, SERVICE_PRINT_IMAGE, handle_print_image, SERVICE_PRINT_IMAGE_SCHEMA)
    domain_data.services_registered = True


async def setup_print_service(
    hass: HomeAssistant,
    config: Mapping[str, Any],
) -> PrinterRuntimeData:
    """Register MQTT listeners for a configured printer."""
    await async_register_services(hass)
    await mqtt.async_wait_for_mqtt_client(hass)

    domain_data = _get_domain_data(hass)
    printer_name = str(config[CONF_PRINTER_NAME])

    runtime_data = PrinterRuntimeData(
        entry_id=config.get("entry_id"),
        printer_name=printer_name,
        print_topic=f"print/pos/{printer_name}/job",
        status_topic=f"print/pos/{printer_name}/ack",
        log_topic=f"print/pos/{printer_name}/log",
    )

    if printer_name in domain_data.printers:
        existing = domain_data.printers.pop(printer_name)
        if existing.unsub_status is not None:
            existing.unsub_status()
        if existing.unsub_log is not None:
            existing.unsub_log()

    @callback
    def handle_status(msg: Any) -> None:
        """Forward bridge status payloads onto the Home Assistant bus."""
        try:
            payload = json.loads(msg.payload)
            if not isinstance(payload, dict):
                raise TypeError("Status payload must be a JSON object")
        except json.JSONDecodeError:
            return
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error handling status payload")
            return

        payload["printer_name"] = printer_name
        runtime_data.last_status = payload
        heartbeat = payload.get("heartbeat")
        bridge_version = (
            heartbeat.get("version")
            if isinstance(heartbeat, dict)
            else payload.get("version")
        )
        async_validate_bridge_version_issue(
            hass,
            runtime_data.entry_id,
            printer_name,
            str(bridge_version) if bridge_version else None,
        )
        hass.bus.async_fire(EVENT_STATUS, payload)

    @callback
    def handle_bridge_log(msg: Any) -> None:
        """Forward bridge log payloads onto the Home Assistant bus."""
        try:
            payload = json.loads(msg.payload)
            if not isinstance(payload, dict):
                raise TypeError("Bridge log payload must be a JSON object")
        except json.JSONDecodeError:
            return
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error handling bridge log payload")
            return

        payload.setdefault("printer_name", printer_name)
        runtime_data.last_log = payload
        hass.bus.async_fire(EVENT_BRIDGE_LOG, payload)

        level_name = str(payload.get("level", "INFO")).upper()
        level = getattr(logging, level_name, logging.INFO)
        logger_name = str(payload.get("logger", "printer_bridge"))
        message = str(payload.get("message", ""))
        _LOGGER.log(level, "Bridge log [%s]: %s", logger_name, message)

    runtime_data.unsub_status = await mqtt.async_subscribe(
        hass,
        runtime_data.status_topic,
        handle_status,
    )
    runtime_data.unsub_log = await mqtt.async_subscribe(
        hass,
        runtime_data.log_topic,
        handle_bridge_log,
    )

    domain_data.printers[printer_name] = runtime_data
    return runtime_data


async def unload_print_service(
    hass: HomeAssistant,
    config: Mapping[str, Any],
) -> None:
    """Remove MQTT subscriptions for a configured printer."""
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, DomainData):
        return

    printer_name = str(config[CONF_PRINTER_NAME])
    runtime_data = domain_data.printers.pop(printer_name, None)
    if runtime_data is None:
        return

    if runtime_data.unsub_status is not None:
        runtime_data.unsub_status()
    if runtime_data.unsub_log is not None:
        runtime_data.unsub_log()
