from setuptools import setup

setup(
    name="hass-pos-printer-bridge",
    version="0.1.0",
    description="Home-Assistant POS-Printer Bridge for Bixolon printers",
    author="Your Name",
    author_email="you@example.com",
    python_requires=">=3.8",
    py_modules=["printer_bridge"],
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
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: POSIX :: Linux",
    ],
)

