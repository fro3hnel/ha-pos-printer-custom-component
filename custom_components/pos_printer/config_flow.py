"""Config flow for the POS printer integration."""

from __future__ import annotations

import json

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .const import (
    CONF_FEED_AFTER,
    CONF_PAPER_WIDTH,
    CONF_PRINTER_NAME,
    DEFAULT_FEED_AFTER,
    DEFAULT_PAPER_WIDTH,
    DOMAIN,
)
from .validation import is_valid_printer_name, normalize_printer_name


class PosPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for POS-Printer Bridge."""

    VERSION = 3

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
        """Validate a printer name for manual setup."""
        errors: dict[str, str] = {}
        if not printer_name or not is_valid_printer_name(printer_name):
            errors["base"] = "invalid_printer_name"
        elif self._printer_name_in_use(printer_name, ignore_entry_id=ignore_entry_id):
            errors["base"] = "already_configured"
        return errors

    async def async_step_mqtt(
        self, discovery_info: MqttServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle MQTT discovery."""
        try:
            data = json.loads(discovery_info.payload)
        except (AttributeError, TypeError, json.JSONDecodeError):
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

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OptionsFlowHandler":
        """Return the per-printer print-default options flow."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Configure per-printer print defaults."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, int] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage paper width and feed defaults."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_PAPER_WIDTH: int(user_input[CONF_PAPER_WIDTH]),
                    CONF_FEED_AFTER: int(user_input[CONF_FEED_AFTER]),
                },
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PAPER_WIDTH,
                        default=self._config_entry.options.get(
                            CONF_PAPER_WIDTH, DEFAULT_PAPER_WIDTH
                        ),
                    ): vol.In({53: "53 mm", 80: "80 mm"}),
                    vol.Required(
                        CONF_FEED_AFTER,
                        default=self._config_entry.options.get(
                            CONF_FEED_AFTER, DEFAULT_FEED_AFTER
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=20)),
                }
            ),
        )
