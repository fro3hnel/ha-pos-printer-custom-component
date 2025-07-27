import asyncio
import json
import uuid
from homeassistant.core import HomeAssistant, callback
from homeassistant.components import mqtt
from .const import DOMAIN


async def setup_print_service(hass: HomeAssistant, config: dict):

    PRINT_TOPIC = f"print/pos/{config['printer_name']}/job"
    STATUS_TOPIC = f"print/pos/{config['printer_name']}/ack"

    # Dienst registrieren
    async def handle_print(call):
        job_id = call.data.get("job_id") or uuid.uuid4().hex
        payload = {
            "job_id": job_id,
            "priority": call.data.get("priority", 5),
            "message": call.data["message"],
        }
        await mqtt.async_publish(
            hass,
            topic=PRINT_TOPIC,
            payload=json.dumps(payload),
            qos=1,
        )

    hass.services.async_register(DOMAIN, "print", handle_print)

    # Status-Antworten abonnieren
    @callback
    def handle_status(msg):
        try:
            data = json.loads(msg.payload)
            if "status" in data:
                hass.bus.async_fire(f"{DOMAIN}.status", data)
        except Exception:
            pass

    await mqtt.async_subscribe(hass, STATUS_TOPIC, handle_status)