"""
Home‑Assistant POS‑Printer Bridge
================================
Raspberry Pi Zero W service that consumes MQTT print jobs, stores them in a Redis‑based
priority spool and prints them on a Bixolon POS printer via the vendor C‑library.

Features
--------
* MQTT Topics       : ``pos/print``  (jobs)  |  ``pos/print/status`` (ack + heartbeat)
* HA Discovery      : sensor + binary_sensor published on startup
* Redis Spool       : 10 lists ``print_queue:0`` … ``print_queue:9`` (0 = highest prio)
* Printer Width     : 80 mm default, overridable per job (field ``paper_width``)
* UTF‑8             : ``SetTextEncoding(ENCODING_ASCII)``
* No automatic retries – on error an error ACK is sent, remaining items keep printing.

Environment (.env)
------------------
MQTT_BROKER=<ip>
MQTT_PORT=1883
MQTT_USERNAME=user
MQTT_PASSWORD=pass
REDIS_URL=redis://:secret@<ip>:6379/0
PRINTER_PORT=USB:
PRINTER_NAME=<Printer Name>
LOG_LEVEL=INFO
HEARTBEAT_INTERVAL=60
LEFT_MARGIN=0
DEFAULT_WIDTH=80
"""
from __future__ import annotations

import base64
import json
import logging
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List

import paho.mqtt.client as mqtt
import redis
from ctypes import (
    CDLL, RTLD_GLOBAL, c_bool, c_char_p, c_int, c_uint, c_ubyte,
    Structure, POINTER, byref
)
import base64
import io
import os
import tempfile
from PIL import Image

from dotenv import load_dotenv

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None  # pragma: no cover

load_dotenv()

@dataclass(slots=True)
class Config:
    mqtt_broker: str = os.getenv("MQTT_BROKER", "localhost")
    mqtt_port: int = int(os.getenv("MQTT_PORT", 1883))
    mqtt_user: str = os.getenv("MQTT_USERNAME", "")
    mqtt_pass: str = os.getenv("MQTT_PASSWORD", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    printer_port: bytes = os.getenv("PRINTER_PORT", "USB:").encode()
    printer_name: str = os.getenv("PRINTER_NAME", "pos_printer")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    heartbeat_interval: int = int(os.getenv("HEARTBEAT_INTERVAL", 60))
    left_margin: int = int(os.getenv("LEFT_MARGIN", 0))
    default_width: int = int(os.getenv("DEFAULT_WIDTH", 80))

CFG = Config()
logging.basicConfig(level=getattr(logging, CFG.log_level.upper()))
LOGGER = logging.getLogger("printer_bridge")


class RedisSpool:
    """Priority spool backed by 10 Redis lists."""

    def __init__(self, url: str):
        self.redis = redis.Redis.from_url(url, decode_responses=True)
        self._lock = threading.Lock()

    def push(self, job: dict[str, Any], priority: int) -> None:
        prio = max(0, min(priority, 9))
        self.redis.rpush(f"print_queue:{prio}", json.dumps(job))
        LOGGER.debug("Job pushed to priority %s", prio)

    def pop(self, timeout: int = 5) -> dict[str, Any] | None:
        """Pop job with highest priority available – blocking BRPOP."""
        keys = [f"print_queue:{i}" for i in range(10)]  # 0..9
        res = self.redis.blpop(keys, timeout=timeout)
        if res:
            _key, raw = res
            return json.loads(raw)
        return None

    def length(self) -> int:
        return sum(self.redis.llen(f"print_queue:{i}") for i in range(10))

class _BarcodeInfo(Structure):
    _fields_ = [
        ("mode", c_uint),
        ("height", c_uint),
        ("width", c_uint),
        ("eccLevel", c_ubyte),
        ("alignment", c_uint),
        ("textPosition", c_uint),
        ("attribute", c_uint),
    ]

class BixolonPrinter:
    _ALIGN = {"left": 0, "center": 1, "right": 2}
    _FONTA = 0  # ATTR_FONTTYPE_A
    _SIZE0 = 0  # TS_HEIGHT_0 | TS_WIDTH_0

    # Barcode maps (simplified)
    _BC_TYPE = {
        "upca": 0,
        "upce": 1,
        "ean8": 2,
        "ean13": 3,
        "code39": 8,
        "code93": 9,
        "code128": 10,
        "qr-code": 12,
    }

    _ERR_MAP = {
        0: "SUCCESS",
        -99: "PORT_OPEN_ERROR",
        -100: "NO_CONNECTED_PRINTER",
        -101: "NO_BIXOLON_PRINTER",
        -102: "FAIL_SEND_DATA",
        -103: "DISCONNECTED_PRINTER",
        -104: "PORT_SET_ERROR",
        -105: "WRITE_ERROR",
        -106: "READ_ERROR",
        -107: "BT_SDPCONNECT_ERROR",
        -108: "BT_SDPSEARCH_ERROR",
        -109: "BT_SOCKET_ERROR",
        -110: "BT_BIND_ERROR",
        -111: "BT_CONNECT_ERROR",
        -112: "INVALID_IPADDRESS",
        -113: "FAIL_CREATE_SOCKET",
        -115: "WRONG_BARCODE_TYPE",
        -116: "WRONG_BC_DATA_ERROR",
        -117: "BAD_ARGUMENT",
        -118: "IMAGE_OPEN_ERROR",
        -119: "BAD_FILE",
        -120: "MEM_ALLOC_ERROR",
        -121: "NV_NO_KEY",
        -122: "WRONG_RESPONSE",
        -123: "FAIL_CREATE_THREAD",
        -124: "NOT_SUPPORT",
        -125: "FAIL_FIND_SENTINEL",
        -126: "SCR_RESPONSE_ERROR",
        -127: "READ_TIMEOUT",
        -128: "DISABLE_BCD",
    }

    def __init__(self, lib_path: str = "/usr/lib/libBxlPosAPI.so.1", port: bytes = b"USB:"):
        CDLL("libbluetooth.so.3", mode=RTLD_GLOBAL)
        self.lib = CDLL(lib_path)
        self.lib.ConnectToPrinter.argtypes = [c_char_p]
        self.lib.ConnectToPrinter.restype = c_int
        self.lib.DisconnectPrinter.restype = c_int
        self.lib.PrintText.argtypes = [c_char_p, c_int, c_uint, c_uint]
        self.lib.PrintText.restype = c_int
        self.lib.LineFeed.argtypes = [c_uint]
        self.lib.LineFeed.restype = c_int
        self.lib.PartialCut.restype = c_int
        self.lib.SetLeftMargin.argtypes = [c_int]
        self.lib.SetLeftMargin.restype = c_int
        self.lib.SetTextEncoding.argtypes = [c_uint]
        self.lib.SetTextEncoding.restype = c_int
        self.lib.PrintBarcode.argtypes = [c_int, c_char_p, POINTER(_BarcodeInfo)]
        self.lib.PrintBarcode.restype = c_int

        # NV Image function prototypes
        self.lib.DownloadNVImage.argtypes = [c_char_p, c_ubyte]
        self.lib.DownloadNVImage.restype = c_int
        self.lib.PrintNVImage.argtypes = [c_ubyte]
        self.lib.PrintNVImage.restype = c_int
        self.lib.RemoveNVImage.argtypes = [c_ubyte]
        self.lib.RemoveNVImage.restype = c_int
        self.lib.RemoveAllNVImage.restype = c_int

        self.port = port
        self._lock = threading.Lock()
        self._connected = False

    # ---------------- connection ----------------
    def connect(self) -> None:
        rc = self.lib.ConnectToPrinter(self.port)
        if rc != 0:
            msg = self._ERR_MAP.get(rc, f"unknown error {rc}")
            raise RuntimeError(f"Printer connection failed: {msg} (code {rc})")
        self.lib.SetTextEncoding(0)  # ENCODING_ASCII
        self._connected = True
        LOGGER.info("Printer connected on %s", self.port.decode())

    def disconnect(self) -> None:
        if self._connected:
            self.lib.DisconnectPrinter()
            self._connected = False

    # ---------------- primitives ----------------
    def _txt(self, txt: str, align: str = "left") -> None:
        if self.lib.PrintText(txt.encode(), self._ALIGN[align], self._FONTA, self._SIZE0) != 0:
            raise RuntimeError("PrintText failed")

    def _feed(self, n: int = 5) -> None:
        self.lib.LineFeed(c_uint(n))

    def _cut(self) -> None:
        self.lib.PartialCut()

    # ---------------- job executor ----------------
    def execute_job(self, job: dict[str, Any]) -> list[str]:
        """Executes job; returns list of failed element indices."""
        failed: list[str] = []
        paper_w = job.get("paper_width", CFG.default_width)
        self.lib.SetLeftMargin(c_int(CFG.left_margin))
        with self._lock:
            for idx, item in enumerate(job["message"]):
                t = "unknown"
                try:
                    if not isinstance(item, dict):
                        raise TypeError(
                            f"message element must be dict, got {type(item).__name__}"
                        )
                    t = item.get("type", "unknown")
                    if t == "text":
                        self._txt(
                            item["content"] + "\n",
                            item.get("orientation", "left"),
                        )
                    elif t == "barcode":
                        self._print_barcode(item)
                    elif t == "image":
                        self._print_image(item, paper_w)
                    else:
                        raise ValueError(f"unknown type {t}")
                except Exception as exc:  # noqa: BLE001
                    element_desc = f"type={t}"
                    if t == "text":
                        snippet = item.get("content", "")[:20]
                        element_desc += f", content='{snippet}'"
                    elif t == "barcode":
                        element_desc += f", barcode_type={item.get('barcode_type')}"
                    LOGGER.error(
                        "Element %s (%s) failed: %s", idx, element_desc, exc, exc_info=True
                    )
                    failed.append(f"{idx}:{element_desc}:{exc}")
            self._feed(4)
            self._cut()
        return failed

    # ---------------- helpers ----------------

    def _print_barcode(self, spec: dict[str, any]) -> None:
        """
        spec keys:
          - barcode_type: str  (z.B. 'ean13')
          - content: str
          - mode: int (für QR/2D barcodes)
          - height: int
          - width: int
          - eccLevel: int oder single-char str
          - alignment: 'left'|'center'|'right'
          - textPosition: int
          - attribute: int
        """
        # prepare info struct
        info = _BarcodeInfo()
        info.mode = spec.get("mode", 0)
        info.height = spec.get("height", 512)
        info.width = spec.get("width", 512)

        ecc = spec.get("eccLevel", 0)
        # if provided as char like 'L', take its ASCII code
        info.eccLevel = ecc if isinstance(ecc, int) else ord(ecc)

        info.alignment = self._ALIGN.get(spec.get("alignment", "left"), 0)
        info.textPosition = spec.get("textPosition", 0)
        info.attribute = spec.get("attribute", 0)

        # call the C function
        bc_type = self._BC_TYPE.get(spec.get("barcode_type", "code128"), 10)
        data = spec["content"].encode()

        result = self.lib.PrintBarcode(bc_type, c_char_p(data), byref(info))
        if result != 0:
            raise RuntimeError(f"PrintBarcode failed with code {result}")

    def _print_image(self, spec: dict[str, Any], paper_w: int) -> None:
        """
        Prints an image provided as a Base64-encoded string in spec['content'].
        Uses NV image functions: DownloadNVImage, PrintNVImage, RemoveNVImage.
        """
        # extract and decode base64
        b64 = spec["content"]
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        try:
            image_data = base64.b64decode(b64)
        except Exception as exc:
            raise ValueError("Base64 decode failed") from exc

        # robustly load image into memory and convert
        buf = io.BytesIO(image_data)
        try:
            with Image.open(buf) as img:
                img.load()  # ensure full image is loaded
                img = img.convert("RGB")
        except Exception as exc:
            raise ValueError("Image load/convert failed") from exc

        # save as BMP to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bmp") as tmpf:
            img.save(tmpf, format="BMP")
            tmp_path = tmpf.name

        # choose NV key (default 1)
        key = spec.get("nv_key", 1)

        # download to printer NV storage
        if self.lib.DownloadNVImage(tmp_path.encode(), c_ubyte(key)) != 0:
            raise RuntimeError(
                f"DownloadNVImage failed for key {key} (temp file {tmp_path})"
            )

        # print the NV-stored image
        if self.lib.PrintNVImage(c_ubyte(key)) != 0:
            raise RuntimeError(f"PrintNVImage failed for key {key}")

        # remove from NV storage to free memory
        self.lib.RemoveNVImage(c_ubyte(key))

        # cleanup temp file
        os.remove(tmp_path)

    # ---------------- status ----------------
    def get_status(self) -> int:
        if hasattr(self.lib, "GetStatus"):
            return self.lib.GetStatus()
        return 0

class MQTTBridge:
    SUB_TOPIC = f"print/pos/{CFG.printer_name}/job"
    PUB_TOPIC = f"print/pos/{CFG.printer_name}/ack"

    def __init__(self, printer: BixolonPrinter, spool: RedisSpool):
        self.printer, self.spool = printer, spool
        self.client = mqtt.Client()
        self.client.username_pw_set(CFG.mqtt_user, CFG.mqtt_pass)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self._stop = threading.Event()

    # ---------------- public API ----------------
    def start(self):
        self.client.connect(CFG.mqtt_broker, CFG.mqtt_port)
        threading.Thread(target=self._worker_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        self.client.loop_start()

    def stop(self):
        self._stop.set()
        self.client.loop_stop()

    # ---------------- callbacks ----------------
    def _on_connect(self, cli, _userdata, _flags, rc):  # noqa: D401,N802
        if rc == 0:
            cli.subscribe(self.SUB_TOPIC, qos=1)
            self._publish_bridge_announcement()
            self._publish_discovery()
            LOGGER.info("MQTT connected; subscribed to %s", self.SUB_TOPIC)
        else:
            LOGGER.error("MQTT connection failed: rc=%s", rc)

    def _on_message(self, _cli, _userdata, msg):  # noqa: D401
        try:
            payload = json.loads(msg.payload)
            priority = int(payload.get("priority", 5))
            self.spool.push(payload, priority)
            LOGGER.debug("Job queued: %s", payload.get("job_id"))
        except json.JSONDecodeError as exc:
            LOGGER.error("Invalid JSON on %s: %s", msg.topic, exc, exc_info=True)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Invalid job payload structure on %s: %s", msg.topic, exc, exc_info=True
            )

    # ---------------- worker ----------------
    def _worker_loop(self):
        while not self._stop.is_set():
            job = self.spool.pop(timeout=5)
            if not job:
                continue
            job_id = job.get("job_id", f"ts{int(time.time()*1000)}")
            try:
                failures = self.printer.execute_job(job)
                status = "partial-error" if failures else "success"
                detail = ", ".join(failures)
            except Exception as exc:  # noqa: BLE001
                status, detail = "error", str(exc)
            self._publish_ack(job_id, status, detail)

    # ---------------- heartbeat ----------------
    def _heartbeat_loop(self):
        while not self._stop.is_set():
            self._publish_bridge_announcement()
            self._publish_heartbeat()
            time.sleep(CFG.heartbeat_interval)

    # ---------------- helpers ----------------
    def _publish_ack(self, job_id: str, status: str, detail: str):
        payload = {
            "job_id": job_id,
            "status": status,
            "detail": detail,
            "queue_len": self.spool.length(),
            "printer_status": self.printer.get_status(),
            "timestamp": int(time.time()),
        }
        self.client.publish(self.PUB_TOPIC, json.dumps(payload), qos=1)

    def _publish_heartbeat(self):
        info: Dict[str, Any] = {
            "timestamp": int(time.time()),
            "queue_len": self.spool.length(),
            "printer_status": self.printer.get_status(),
        }
        if psutil:
            info.update({
                "cpu_temp": psutil.sensors_temperatures()["cpu-thermal"][0].current  # type: ignore[index]
                if "cpu-thermal" in psutil.sensors_temperatures() else None,
                "cpu_percent": psutil.cpu_percent(interval=None),
                "mem_available": psutil.virtual_memory().available,
            })
        self.client.publish(self.PUB_TOPIC, json.dumps({"heartbeat": info}), qos=0, retain=False)

    def _publish_bridge_announcement(self):
        payload = {"printer_name": CFG.printer_name}
        self.client.publish("pos_printer/discovery", json.dumps(payload), qos=1, retain=True)

    def _publish_discovery(self):
        base = f"homeassistant/sensor/{CFG.printer_name}"
        device = {
            "identifiers": [CFG.printer_name],
            "name": CFG.printer_name,
            "manufacturer": "Bixolon",
            "model": "POS",
        }
        sensors = {
            "queue": {
                "unique_id": f"{CFG.printer_name}_queue",
                "state_topic": self.PUB_TOPIC,
                "name": f"{CFG.printer_name} Queue Length",
                "unit_of_measurement": "jobs",
                "value_template": "{{ value_json.queue_len }}",
                "device": device,
            },
            "status": {
                "unique_id": f"{CFG.printer_name}_status",
                "state_topic": self.PUB_TOPIC,
                "name": f"{CFG.printer_name} Status",
                "value_template": "{{ value_json.status or value_json.heartbeat.printer_status }}",
                "device": device,
            },
        }
        for s, cfg in sensors.items():
            topic = f"{base}/{s}/config"
            self.client.publish(topic, json.dumps(cfg), qos=1, retain=True)

# --------------------------- 5. Main ------------------------------------

def main():  # noqa: D401
    # graceful shutdown
    stop_event = threading.Event()

    def _sig_handler(_sig, _frame):  # noqa: D401
        stop_event.set()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    printer = BixolonPrinter(port=CFG.printer_port)
    printer.connect()

    spool = RedisSpool(CFG.redis_url)
    bridge = MQTTBridge(printer, spool)
    bridge.start()

    LOGGER.info("Service started")
    while not stop_event.is_set():
        time.sleep(1)

    LOGGER.info("Shutting down…")
    bridge.stop()
    printer.disconnect()


if __name__ == "__main__":
    main()

