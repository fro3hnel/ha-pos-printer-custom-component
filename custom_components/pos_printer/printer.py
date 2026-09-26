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
from homeassistant.helpers import config_validation as cv

from .const import (
    AVAILABILITY_ONLINE,
    CONF_CONFIG_ENTRY_ID,
    CONF_FEED_AFTER,
    CONF_PAPER_WIDTH,
    CONF_PRINTER_NAME,
    DEFAULT_FEED_AFTER,
    DEFAULT_PAPER_WIDTH,
    DEFAULT_PRIORITY,
    DOMAIN,
    EVENT_AVAILABILITY,
    EVENT_BRIDGE_LOG,
    EVENT_STATUS,
    MAX_JOB_ID_LENGTH,
    SERVICE_PRINT,
    SERVICE_PRINT_IMAGE,
    SERVICE_PRINT_PICTOGRAMS,
    SERVICE_PRINT_TEXT,
)
from .exceptions import integration_error, service_validation_error
from .image_processing import async_prepare_image_content
from .models import DomainData, PrinterRuntimeData
from .pictograms import (
    MAX_PICTOGRAMS,
    PICTOGRAM_NAMES,
    render_pictogram_data_uri,
)
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


def _validate_job_id(value: Any) -> str:
    """Validate a caller-provided print job identifier."""
    if not isinstance(value, str):
        raise vol.Invalid("job_id must be a string")
    if not value.strip():
        raise vol.Invalid("job_id must not be empty")
    if len(value) > MAX_JOB_ID_LENGTH:
        raise vol.Invalid(
            f"job_id must not exceed {MAX_JOB_ID_LENGTH} characters"
        )
    return value


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
            raise service_validation_error(
                f"Field '{field_name}' must contain valid JSON.",
                "invalid_json",
                field=field_name,
            ) from err
    return value


def _coerce_message(value: Any, field_name: str = "message") -> list[dict[str, Any]] | None:
    """Normalize message payloads to a list of dictionaries."""
    if value is None:
        return None

    message = _parse_json_if_needed(value, field_name)
    if not isinstance(message, list):
        raise service_validation_error(
            f"Field '{field_name}' must be a list of elements.",
            "field_must_be_list",
            field=field_name,
        )
    if not all(isinstance(element, dict) for element in message):
        raise service_validation_error(
            f"Field '{field_name}' must contain only objects.",
            "field_items_must_be_objects",
            field=field_name,
        )

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
            raise service_validation_error(
                "Set 'image_process_on_host' to true when using URLs, files, "
                "media sources, or cameras.",
                "host_processing_required",
            )
        raw_content = data.get("image_content")
        if raw_content in (None, ""):
            raise service_validation_error(
                "Field 'image_content' is required for raw image passthrough.",
                "raw_image_content_required",
            )
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
        raise service_validation_error(
            "No POS printers are configured.", "no_printers_configured"
        )

    config_entry_id = call.data.get(CONF_CONFIG_ENTRY_ID)
    if config_entry_id:
        for runtime_data in printers.values():
            if runtime_data.entry_id == config_entry_id:
                return runtime_data
        raise service_validation_error(
            f"Unknown POS printer config entry '{config_entry_id}'.",
            "unknown_config_entry",
            config_entry_id=config_entry_id,
        )

    target = call.data.get(CONF_PRINTER_NAME)
    if target:
        if target not in printers:
            raise service_validation_error(
                f"Unknown printer '{target}'.",
                "unknown_printer",
                printer_name=target,
            )
        return printers[target]

    if len(printers) == 1:
        return next(iter(printers.values()))

    raise service_validation_error(
        "Select a POS printer config entry when multiple printers are configured.",
        "printer_target_required",
    )


def _apply_job_metadata(
    payload: dict[str, Any],
    data: Mapping[str, Any],
    job_data: Mapping[str, Any] | None,
) -> None:
    """Populate common job fields on a payload."""
    has_custom_job_id = "job_id" in data or (
        job_data is not None and "job_id" in job_data
    )
    if has_custom_job_id:
        job_id = data.get("job_id")
        if "job_id" not in data and job_data is not None:
            job_id = job_data.get("job_id")
        try:
            payload["job_id"] = _validate_job_id(job_id)
        except vol.Invalid as err:
            raise service_validation_error(
                f"Job ID must be a non-empty string with at most "
                f"{MAX_JOB_ID_LENGTH} characters.",
                "invalid_job_id",
                maximum_length=MAX_JOB_ID_LENGTH,
            ) from err
    else:
        payload["job_id"] = uuid.uuid4().hex
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
            raise service_validation_error(
                "Field 'job' must be an object.", "job_must_be_object"
            )
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
        raise service_validation_error(
            "No message elements provided. Fill at least one text, barcode, or image field.",
            "no_message_elements",
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
        raise service_validation_error(
            "At least one of title, text, or footer must contain printable content.",
            "no_text_content",
        )

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
        raise service_validation_error(
            "An image source is required for the image print service.",
            "image_source_required",
        )

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


async def _async_build_pictogram_payload(
    hass: HomeAssistant,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one job containing a title, subtitle, and pictogram sheet."""
    paper_width = int(data.get("paper_width", DEFAULT_PAPER_WIDTH))
    pictograms = list(data["pictograms"])
    title = str(data.get("title", "") or "").strip()
    subtitle = str(data.get("subtitle", "") or "").strip()

    image_content = await hass.async_add_executor_job(
        render_pictogram_data_uri,
        pictograms,
        paper_width,
    )

    message: list[dict[str, Any]] = []
    if title:
        message.append(
            _make_text_element(
                title,
                alignment="center",
                bold=True,
                double_height=True,
            )
        )
    if subtitle:
        message.extend(
            _build_simple_text_lines(
                subtitle,
                alignment="center",
                bold=False,
            )
        )
    message.append({"type": "image", "content": image_content})

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
    if runtime_data.availability_known and not runtime_data.available:
        raise integration_error(
            f"The bridge for '{runtime_data.printer_name}' is offline.",
            "bridge_offline",
            printer_name=runtime_data.printer_name,
        )
    await mqtt.async_publish(
        hass,
        topic=runtime_data.print_topic,
        payload=json.dumps(payload),
        qos=1,
    )


def _with_printer_defaults(
    data: Mapping[str, Any], runtime_data: PrinterRuntimeData
) -> dict[str, Any]:
    """Apply configured defaults to service data without mutating the call."""
    prepared = dict(data)
    job = prepared.get("job")
    job_fields: Mapping[str, Any] | None = job if isinstance(job, Mapping) else None
    if isinstance(job, str):
        try:
            parsed_job = json.loads(job)
        except json.JSONDecodeError:
            parsed_job = None
        if isinstance(parsed_job, Mapping):
            job_fields = parsed_job

    for field, default in (
        (CONF_PAPER_WIDTH, runtime_data.default_paper_width),
        (CONF_FEED_AFTER, runtime_data.default_feed_after),
    ):
        if field in prepared:
            continue
        if job_fields is not None and field in job_fields:
            continue
        prepared[field] = default
    return prepared


def _int_range(*, minimum: int, maximum: int | None = None):
    """Return a simple integer range validator."""
    validator = vol.All(vol.Coerce(int), vol.Range(min=minimum, max=maximum))
    return validator


def _int_choice(*options: int):
    """Return a validator for integer options that also accepts UI strings."""
    validator = vol.All(vol.Coerce(int), vol.In(options))
    return validator


def _validate_pictograms(value: Any) -> list[str]:
    """Validate a bounded, ordered list of unique pictogram names."""
    if not isinstance(value, (list, tuple)):
        raise vol.Invalid("pictograms must be a list")

    pictograms = list(value)
    if not pictograms:
        raise vol.Invalid("at least one pictogram is required")
    if len(pictograms) > MAX_PICTOGRAMS:
        raise vol.Invalid(f"at most {MAX_PICTOGRAMS} pictograms are supported")
    if not all(
        isinstance(name, str) and name in PICTOGRAM_NAMES for name in pictograms
    ):
        raise vol.Invalid("pictograms contains an unknown name")
    if len(set(pictograms)) != len(pictograms):
        raise vol.Invalid("pictograms must not contain duplicates")
    return pictograms


_COMMON_JOB_FIELDS: dict[Any, Any] = {
    vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
    vol.Optional(CONF_PRINTER_NAME): cv.string,
    vol.Optional("job_id"): _validate_job_id,
    vol.Optional("priority"): _int_range(minimum=0, maximum=9),
    vol.Optional("paper_width"): _int_choice(53, 80),
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
    vol.Optional("image_rotation"): _int_choice(*_IMAGE_ROTATIONS),
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

SERVICE_PRINT_PICTOGRAMS_SCHEMA = vol.Schema(
    {
        **_COMMON_JOB_FIELDS,
        vol.Required("pictograms"): _validate_pictograms,
        vol.Optional("title"): cv.string,
        vol.Optional("subtitle"): cv.string,
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
        payload = await _async_build_generic_payload(
            hass, _with_printer_defaults(call.data, runtime_data)
        )
        await _async_publish_payload(hass, runtime_data, payload)

    async def handle_print_text(call: ServiceCall) -> None:
        """Send a text-focused print job via MQTT."""
        runtime_data = _resolve_target_printer(call, domain_data.printers)
        payload = await _async_build_text_payload(
            _with_printer_defaults(call.data, runtime_data)
        )
        await _async_publish_payload(hass, runtime_data, payload)

    async def handle_print_image(call: ServiceCall) -> None:
        """Send an image-focused print job via MQTT."""
        runtime_data = _resolve_target_printer(call, domain_data.printers)
        payload = await _async_build_image_payload(
            hass, _with_printer_defaults(call.data, runtime_data)
        )
        await _async_publish_payload(hass, runtime_data, payload)

    async def handle_print_pictograms(call: ServiceCall) -> None:
        """Send an offline-rendered pictogram job via MQTT."""
        runtime_data = _resolve_target_printer(call, domain_data.printers)
        payload = await _async_build_pictogram_payload(
            hass, _with_printer_defaults(call.data, runtime_data)
        )
        await _async_publish_payload(hass, runtime_data, payload)

    _service_register(hass, SERVICE_PRINT, handle_print, SERVICE_PRINT_SCHEMA)
    _service_register(
        hass, SERVICE_PRINT_TEXT, handle_print_text, SERVICE_PRINT_TEXT_SCHEMA
    )
    _service_register(
        hass, SERVICE_PRINT_IMAGE, handle_print_image, SERVICE_PRINT_IMAGE_SCHEMA
    )
    _service_register(
        hass,
        SERVICE_PRINT_PICTOGRAMS,
        handle_print_pictograms,
        SERVICE_PRINT_PICTOGRAMS_SCHEMA,
    )
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
        availability_topic=f"print/pos/{printer_name}/availability",
        default_paper_width=int(config.get(CONF_PAPER_WIDTH, DEFAULT_PAPER_WIDTH)),
        default_feed_after=int(config.get(CONF_FEED_AFTER, DEFAULT_FEED_AFTER)),
    )

    if printer_name in domain_data.printers:
        existing = domain_data.printers.pop(printer_name)
        if existing.unsub_status is not None:
            existing.unsub_status()
        if existing.unsub_log is not None:
            existing.unsub_log()
        if existing.unsub_availability is not None:
            existing.unsub_availability()

    @callback
    def update_availability(available: bool) -> None:
        """Update runtime availability and emit one transition event."""
        changed = runtime_data.available != available
        was_known = runtime_data.availability_known
        runtime_data.available = available
        runtime_data.availability_known = True

        if changed or not was_known:
            hass.bus.async_fire(
                EVENT_AVAILABILITY,
                {
                    CONF_PRINTER_NAME: printer_name,
                    "available": available,
                },
            )

        if was_known and changed:
            if available:
                _LOGGER.info("POS printer bridge %s is available again", printer_name)
            else:
                _LOGGER.warning("POS printer bridge %s became unavailable", printer_name)

    @callback
    def handle_availability(msg: Any) -> None:
        """Handle retained online/offline lifecycle messages from the bridge."""
        raw_payload = msg.payload
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode(errors="replace")
        update_availability(str(raw_payload).strip().lower() == AVAILABILITY_ONLINE)

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

        payload[CONF_PRINTER_NAME] = printer_name
        heartbeat = payload.get("heartbeat")
        if isinstance(heartbeat, dict):
            for key in (
                "queue_len",
                "printer_status",
                "successful_jobs",
                "timestamp",
                "version",
            ):
                if key in heartbeat:
                    payload.setdefault(key, heartbeat[key])
        runtime_data.last_status = payload
        update_availability(True)
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
    runtime_data.unsub_availability = await mqtt.async_subscribe(
        hass,
        runtime_data.availability_topic,
        handle_availability,
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
    if runtime_data.unsub_availability is not None:
        runtime_data.unsub_availability()
