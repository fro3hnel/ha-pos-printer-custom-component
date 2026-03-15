"""Boot-time entry point that applies saved onboarding settings."""

from __future__ import annotations

import logging

try:
    from .device_setup_service import apply_configuration
    from .device_setup_store import load_setup_config
except ImportError:  # pragma: no cover - script execution on target image
    from device_setup_service import apply_configuration
    from device_setup_store import load_setup_config

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("device_setup_apply")


def main() -> None:
    """Load and apply the saved onboarding configuration."""
    config = load_setup_config()
    result = apply_configuration(config)
    LOGGER.info("Provisioning mode: %s", result.mode)
    LOGGER.info("%s", result.message)


if __name__ == "__main__":
    main()
