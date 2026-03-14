"""Config flow for the POS printer integration."""

from __future__ import annotations

import json

import voluptuous as vol
from homeassistant import config_entries

from .const import CONF_PRINTER_NAME, DOMAIN
from .validation import is_valid_printer_name, normalize_printer_name

STEP_USER_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_PRINTER_NAME, default="kitchen_printer"): str}
)


class PosPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for POS-Printer Bridge."""

    VERSION = 1

    def _build_schema(self, default_printer_name: str) -> vol.Schema:
        """Build a simple printer-name schema."""
        return vol.Schema(
            {vol.Required(CONF_PRINTER_NAME, default=default_printer_name): str}
        )

    def _printer_name_in_use(
        self,
        printer_name: str,
        *,
        ignore_entry_id: str | None = None,
    ) -> bool:
        """Check whether another config entry already uses the printer name."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if ignore_entry_id is not None and entry.entry_id == ignore_entry_id:
                continue
            current_name = entry.options.get(
                CONF_PRINTER_NAME,
                entry.data.get(CONF_PRINTER_NAME),
            )
            if current_name == printer_name:
                return True
        return False

    def _validate_printer_name(
        self,
        printer_name: str,
        *,
        ignore_entry_id: str | None = None,
    ) -> dict[str, str]:
        """Validate a printer name for setup, options, and reconfigure flows."""
        errors: dict[str, str] = {}
        if not printer_name or not is_valid_printer_name(printer_name):
            errors["base"] = "invalid_printer_name"
        elif self._printer_name_in_use(printer_name, ignore_entry_id=ignore_entry_id):
            errors["base"] = "already_configured"
        return errors

    async def async_step_mqtt(self, discovery_info: dict) -> config_entries.ConfigFlowResult:
        """Handle MQTT discovery."""
        try:
            data = json.loads(discovery_info["payload"])
        except json.JSONDecodeError:
            return self.async_abort(reason="invalid_discovery")

        printer_name = normalize_printer_name(str(data.get(CONF_PRINTER_NAME, "")))
        if not printer_name or not is_valid_printer_name(printer_name):
            return self.async_abort(reason="invalid_discovery")

        await self.async_set_unique_id(printer_name)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=printer_name,
            data={CONF_PRINTER_NAME: printer_name},
        )

    async def async_step_user(
        self,
        user_input: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            printer_name = normalize_printer_name(user_input[CONF_PRINTER_NAME])
            errors = self._validate_printer_name(printer_name)
            if not errors:
                await self.async_set_unique_id(printer_name)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=printer_name,
                    data={CONF_PRINTER_NAME: printer_name},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_schema(
                user_input[CONF_PRINTER_NAME] if user_input else "kitchen_printer"
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle reconfiguring the printer name."""
        entry = self._get_reconfigure_entry()
        current_name = entry.options.get(CONF_PRINTER_NAME, entry.data[CONF_PRINTER_NAME])
        errors: dict[str, str] = {}

        if user_input is not None:
            printer_name = normalize_printer_name(user_input[CONF_PRINTER_NAME])
            errors = self._validate_printer_name(
                printer_name,
                ignore_entry_id=entry.entry_id,
            )
            if not errors:
                await self.async_set_unique_id(printer_name)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=printer_name,
                    title=printer_name,
                    data_updates={CONF_PRINTER_NAME: printer_name},
                    options={CONF_PRINTER_NAME: printer_name},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._build_schema(current_name),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OptionsFlowHandler":
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for POS-Printer Bridge."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    def _printer_name_in_use(self, printer_name: str) -> bool:
        """Check whether another config entry already uses the printer name."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == self._config_entry.entry_id:
                continue
            current_name = entry.options.get(
                CONF_PRINTER_NAME,
                entry.data.get(CONF_PRINTER_NAME),
            )
            if current_name == printer_name:
                return True
        return False

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            printer_name = normalize_printer_name(user_input[CONF_PRINTER_NAME])
            if not printer_name or not is_valid_printer_name(printer_name):
                errors["base"] = "invalid_printer_name"
            elif self._printer_name_in_use(printer_name):
                errors["base"] = "already_configured"
            else:
                return self.async_create_entry(
                    title="",
                    data={CONF_PRINTER_NAME: printer_name},
                )

        current_name = self._config_entry.options.get(
            CONF_PRINTER_NAME,
            self._config_entry.data.get(CONF_PRINTER_NAME),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_PRINTER_NAME, default=current_name): str}
            ),
            errors=errors,
        )
