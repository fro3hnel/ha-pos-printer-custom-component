import json
import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.components import mqtt
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


def _coerce_message(value: Any) -> Optional[List[Dict[str, Any]]]:
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


def _build_text_element(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build a text element from GUI fields."""
    content = data.get("text_content")
    if content in (None, ""):
        return None

    element: Dict[str, Any] = {"type": "text", "content": content}

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


def _build_barcode_element(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build a barcode element from GUI fields."""
    content = data.get("barcode_content")
    if content in (None, ""):
        return None

    element: Dict[str, Any] = {
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


def _build_image_element(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build an image element from GUI fields."""
    content = data.get("image_content")
    if content in (None, ""):
        return None

    element: Dict[str, Any] = {"type": "image", "content": content}
    if (alignment := data.get("image_alignment")) is not None:
        element["alignment"] = alignment
    if (nv_key := data.get("image_nv_key")) is not None:
        element["nv_key"] = nv_key
    return element


def _build_message_from_gui_fields(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create message list from dedicated GUI fields."""
    message: List[Dict[str, Any]] = []
    for builder in (_build_text_element, _build_barcode_element, _build_image_element):
        if element := builder(data):
            message.append(element)
    return message


async def setup_print_service(hass: HomeAssistant, config: dict):
    """Register print services and MQTT status listener."""

    # Ensure the MQTT integration is available before using it
    await mqtt.async_wait_for_mqtt_client(hass)

    PRINT_TOPIC = f"print/pos/{config['printer_name']}/job"
    STATUS_TOPIC = f"print/pos/{config['printer_name']}/ack"
    LOG_TOPIC = f"print/pos/{config['printer_name']}/log"

    # Dienst registrieren
    async def handle_print(call):
        """Send simplified print data via MQTT."""
        job_data = None

        # Support both the new 'message' format and deprecated 'job'
        message = _coerce_message(call.data.get("message"))
        priority = call.data.get("priority")
        if message is None and (job := call.data.get("job")):
            job_data = _parse_json_if_needed(job, "job")
            if not isinstance(job_data, dict):
                raise HomeAssistantError("Field 'job' must be an object.")

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

        job_id = call.data.get("job_id") or (
            job_data.get("job_id") if job_data else None
        ) or uuid.uuid4().hex

        if priority is None:
            priority = 5

        payload = {
            "job_id": job_id,
            "priority": priority,
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
            topic=PRINT_TOPIC,
            payload=json.dumps(payload),
            qos=1,
        )

    async def handle_print_job(call):
        """Send full job object via MQTT."""
        raw_job = _parse_json_if_needed(call.data.get("job", {}), "job")
        if not isinstance(raw_job, dict):
            raise HomeAssistantError("Field 'job' must be an object.")

        job = dict(raw_job)
        job.setdefault("job_id", uuid.uuid4().hex)
        if (timestamp := job.get("timestamp")) is not None:
            job["timestamp"] = _coerce_datetime(timestamp)

        await mqtt.async_publish(
            hass,
            topic=PRINT_TOPIC,
            payload=json.dumps(job),
            qos=1,
        )

    hass.services.async_register(DOMAIN, "print", handle_print)
    hass.services.async_register(DOMAIN, "print_job", handle_print_job)

    # Status-Antworten und Heartbeats abonnieren
    @callback
    def handle_status(msg):
        try:
            data = json.loads(msg.payload)
            hass.bus.async_fire(f"{DOMAIN}.status", data)
        except Exception:
            # Ignore invalid JSON payloads
            pass

    @callback
    def handle_bridge_log(msg):
        try:
            data = json.loads(msg.payload)
        except Exception:
            # Ignore invalid JSON payloads
            return

        if not isinstance(data, dict):
            return

        hass.bus.async_fire(f"{DOMAIN}.bridge_log", data)

        level_name = str(data.get("level", "INFO")).upper()
        level = getattr(logging, level_name, logging.INFO)
        logger_name = str(data.get("logger", "printer_bridge"))
        message = str(data.get("message", ""))
        _LOGGER.log(
            level,
            "Bridge log [%s]: %s",
            logger_name,
            message,
        )

    if hasattr(hass, "config_entries"):
        await mqtt.async_subscribe(hass, STATUS_TOPIC, handle_status)
        await mqtt.async_subscribe(hass, LOG_TOPIC, handle_bridge_log)
