import asyncio
import json
import uuid
from homeassistant.core import HomeAssistant, callback
from homeassistant.components import mqtt
from .const import DOMAIN


async def setup_print_service(hass: HomeAssistant, config: dict):
    """Register print services and MQTT status listener."""

    # Ensure the MQTT integration is available before using it
    await mqtt.async_wait_for_mqtt_client(hass)

    PRINT_TOPIC = f"print/pos/{config['printer_name']}/job"
    STATUS_TOPIC = f"print/pos/{config['printer_name']}/ack"

    # Dienst registrieren
    async def handle_print(call):
        """Send simplified print data via MQTT."""
        job_id = call.data.get("job_id") or uuid.uuid4().hex
        # Support both the new 'message' format and deprecated 'job'
        message = call.data.get("message")
        priority = call.data.get("priority")
        if message is None and (job := call.data.get("job")):
            if isinstance(job, str):
                try:
                    job = json.loads(job)
                except json.JSONDecodeError:
                    job = {}
            message = job.get("message")
            if priority is None:
                priority = job.get("priority")
        if priority is None:
            priority = 5
        payload = {
            "job_id": job_id,
            "priority": priority,
            "message": message,
        }
        await mqtt.async_publish(
            hass,
            topic=PRINT_TOPIC,
            payload=json.dumps(payload),
            qos=1,
        )

    async def handle_print_job(call):
        """Send full job object via MQTT."""
        job = dict(call.data.get("job", {}))
        job.setdefault("job_id", uuid.uuid4().hex)
        await mqtt.async_publish(
            hass,
            topic=PRINT_TOPIC,
            payload=json.dumps(job),
            qos=1,
        )

    hass.services.async_register(DOMAIN, "print", handle_print)
    hass.services.async_register(DOMAIN, "print_job", handle_print_job)

    # Status-Antworten abonnieren
    @callback
    def handle_status(msg):
        try:
            data = json.loads(msg.payload)
            if "status" in data:
                hass.bus.async_fire(f"{DOMAIN}.status", data)
        except Exception:
            pass

    if hasattr(hass, "config_entries"):
        await mqtt.async_subscribe(hass, STATUS_TOPIC, handle_status)
