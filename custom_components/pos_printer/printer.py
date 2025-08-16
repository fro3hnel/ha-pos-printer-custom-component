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
        """Send print data via MQTT.

        Accepts either a simplified ``message`` or a full ``job`` structure.
        """
        if (job := call.data.get("job")) is not None:
            if isinstance(job, str):
                try:
                    job = json.loads(job)
                except json.JSONDecodeError:
                    job = {}
            job.setdefault("job_id", call.data.get("job_id") or uuid.uuid4().hex)
            await mqtt.async_publish(
                hass,
                topic=PRINT_TOPIC,
                payload=json.dumps(job),
                qos=1,
            )
            return

        job_id = call.data.get("job_id") or uuid.uuid4().hex
        message = call.data.get("message")
        priority = call.data.get("priority", 5)
        payload = {"job_id": job_id, "priority": priority, "message": message}
        await mqtt.async_publish(
            hass,
            topic=PRINT_TOPIC,
            payload=json.dumps(payload),
            qos=1,
        )

    hass.services.async_register(DOMAIN, "print", handle_print)

    # Status-Antworten und Heartbeats abonnieren
    @callback
    def handle_status(msg):
        try:
            data = json.loads(msg.payload)
            hass.bus.async_fire(f"{DOMAIN}.status", data)
        except Exception:
            # Ignore invalid JSON payloads
            pass

    if hasattr(hass, "config_entries"):
        await mqtt.async_subscribe(hass, STATUS_TOPIC, handle_status)
