import json
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_PRINTER_NAME

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_PRINTER_NAME, default="kitchen_printer"): str,
})

class PosPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for POS-Printer Bridge."""

    VERSION = 1

    async def async_step_mqtt(self, discovery_info: dict):
        """Handle MQTT discovery."""
        try:
            data = json.loads(discovery_info["payload"])
        except Exception:  # noqa: BLE001
            return self.async_abort(reason="invalid_discovery")

        printer_name = data.get(CONF_PRINTER_NAME)
        if not printer_name:
            return self.async_abort(reason="invalid_discovery")

        await self.async_set_unique_id(printer_name)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=printer_name,
            data={CONF_PRINTER_NAME: printer_name},
        )

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_PRINTER_NAME])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_PRINTER_NAME],
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for POS-Printer Bridge."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=user_input,
            )

        # Set defaults from existing entry data and options
        current_data = self.config_entry.data
        current_options = self.config_entry.options

        data_schema = vol.Schema({
            vol.Required(
                CONF_PRINTER_NAME,
                default=current_options.get(CONF_PRINTER_NAME, current_data.get(CONF_PRINTER_NAME)),
            ): str,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )
