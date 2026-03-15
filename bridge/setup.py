import re
from pathlib import Path

from setuptools import setup


def _read_bridge_version() -> str:
    """Read the bridge version without importing runtime dependencies."""
    version_file = Path(__file__).with_name("bridge_version.py")
    content = version_file.read_text(encoding="utf-8")
    match = re.search(r'^BRIDGE_VERSION = "([^"]+)"$', content, re.MULTILINE)
    if match is None:
        raise RuntimeError("Unable to determine bridge version")
    return match.group(1)


BRIDGE_VERSION = _read_bridge_version()

setup(
    name="hass-pos-printer-bridge",
    version=BRIDGE_VERSION,
    description="Home-Assistant POS-Printer Bridge for Bixolon printers",
    author="Nico Froehnel",
    python_requires=">=3.8",
    py_modules=[
        "printer_bridge",
        "bridge_version",
        "device_setup_apply",
        "device_setup_models",
        "device_setup_network",
        "device_setup_portal",
        "device_setup_service",
        "device_setup_store",
    ],
    install_requires=[
        "paho-mqtt",
        "redis",
        "python-dotenv",
        "Pillow",
        "psutil",
    ],
    entry_points={
        "console_scripts": [
            "printer-bridge=printer_bridge:main",
            "printer-setup-apply=device_setup_apply:main",
            "printer-setup-portal=device_setup_portal:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: POSIX :: Linux",
    ],
)
