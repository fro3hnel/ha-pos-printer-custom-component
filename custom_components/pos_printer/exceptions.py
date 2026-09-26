"""Translated exceptions for POS printer actions."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN


def service_validation_error(
    message: str,
    translation_key: str,
    **placeholders: object,
) -> ServiceValidationError:
    """Build a translated error for invalid action input."""
    return ServiceValidationError(
        message,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders={
            key: str(value) for key, value in placeholders.items()
        },
    )


def integration_error(
    message: str,
    translation_key: str,
    **placeholders: object,
) -> HomeAssistantError:
    """Build a translated error for an action execution failure."""
    return HomeAssistantError(
        message,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders={
            key: str(value) for key, value in placeholders.items()
        },
    )
