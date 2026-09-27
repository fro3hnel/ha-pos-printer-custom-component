"""
Home‑Assistant POS‑Printer Bridge
================================
Raspberry Pi Zero W service that consumes MQTT print jobs, stores them in a Redis‑based
priority spool and prints them on a Bixolon POS printer via the vendor C‑library.

Features
--------
* MQTT Topics       : per-printer job, acknowledgement, log and availability topics
* HA Discovery      : retained bridge announcement for the custom integration
* Redis Spool       : 10 lists ``print_queue:0`` … ``print_queue:9`` (0 = highest prio)
* Status Lifecycle  : queued, printing and a correlated final acknowledgement
* Printer Width     : 80 mm default, overridable per job (field ``paper_width``)
* UTF‑8             : ``SetTextEncoding(ENCODING_ASCII)``
* No automatic retries – on error an error ACK is sent, remaining items keep printing.

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
IMAGE_FETCH_TIMEOUT=10
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import logging
import os
import signal
import tempfile
import threading
import time
from ctypes import (
    CDLL,
    POINTER,
    RTLD_GLOBAL,
    Structure,
    byref,
    c_bool,
    c_char_p,
    c_int,
    c_ubyte,
    c_uint,
)
from dataclasses import dataclass
from typing import Any, Dict
from urllib.parse import unquote_to_bytes, urlparse
from urllib.request import Request, urlopen

import paho.mqtt.client as mqtt
import redis
from dotenv import load_dotenv
from PIL import Image

try:
    from .bridge_version import BRIDGE_VERSION
except ImportError:  # pragma: no cover - direct script execution on the bridge
    from bridge_version import BRIDGE_VERSION

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
    image_fetch_timeout: int = int(os.getenv("IMAGE_FETCH_TIMEOUT", 10))

CFG = Config()
logging.basicConfig(level=getattr(logging, CFG.log_level.upper()))
LOGGER = logging.getLogger("printer_bridge")

JOB_ID_DEDUPLICATION_TTL = 24 * 60 * 60
MAX_JOB_ID_LENGTH = 128
STATUS_SCHEMA_VERSION = 1


def _decode_data_uri(content: str) -> bytes:
    """Decode a data URI into raw image bytes."""
    if "," not in content:
        raise ValueError("Data URI is missing comma separator")
    header, payload = content.split(",", 1)
    if ";base64" in header.lower():
        try:
            return base64.b64decode(payload, validate=True)
        except binascii.Error as exc:
            raise ValueError("Invalid base64 payload in data URI") from exc
    return unquote_to_bytes(payload)


def _fetch_image_from_uri(uri: str, timeout: int) -> bytes:
    """Download image bytes from a URI."""
    request = Request(uri, headers={"User-Agent": f"ha-pos-printer-bridge/{BRIDGE_VERSION}"})
    with urlopen(request, timeout=timeout) as response:  # nosec B310
        return response.read()


def _load_image_bytes(content: str, timeout: int) -> bytes:
    """Load image bytes from Base64, data URI, or URI string."""
    source = content.strip()
    if not source:
        raise ValueError("Image content is empty")

    if source.startswith("data:"):
        return _decode_data_uri(source)

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https", "file"}:
        data = _fetch_image_from_uri(source, timeout=timeout)
        if not data:
            raise ValueError("URI returned empty image payload")
        return data

    try:
        return base64.b64decode(source, validate=True)
    except binascii.Error as exc:
        raise ValueError(
            "Image content must be Base64, data URI, or URI (http/https/file)"
        ) from exc


class MQTTLogHandler(logging.Handler):
    """Publish bridge logs to MQTT so Home Assistant can consume them."""

    def __init__(self, client: mqtt.Client, topic: str, printer_name: str) -> None:
        super().__init__()
        self._client = client
        self._topic = topic
        self._printer_name = printer_name

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "printer_name": self._printer_name,
                "timestamp": int(record.created),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "file": record.filename,
                "line": record.lineno,
            }
            self._client.publish(self._topic, json.dumps(payload), qos=0, retain=False)
        except Exception:
            # Never let telemetry logging break bridge execution.
            pass


class RedisSpool:
    """Priority spool backed by 10 Redis lists."""

    _ATOMIC_ENQUEUE_SCRIPT = """
    if redis.call('SET', KEYS[1], '1', 'NX', 'EX', ARGV[1]) then
        redis.call('RPUSH', KEYS[2], ARGV[2])
        return 1
    end
    return 0
    """

    def __init__(self, url: str, printer_name: str | None = None):
        self.redis = redis.Redis.from_url(url, decode_responses=True)
        self.printer_name = printer_name or CFG.printer_name

    def dedupe_key(self, job_id: str) -> str:
        """Return a non-reversible, per-printer deduplication marker key."""
        job_id_hash = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
        return f"print_dedupe:{self.printer_name}:{job_id_hash}"

    def push(self, job: dict[str, Any], priority: int) -> bool:
        """Atomically deduplicate and enqueue a job.

        Return ``True`` when Redis accepted the job and ``False`` when its ID was
        already accepted for this printer during the deduplication window.
        """
        prio = max(0, min(priority, 9))
        job_id = str(job["job_id"])
        accepted = self.redis.eval(
            self._ATOMIC_ENQUEUE_SCRIPT,
            2,
            self.dedupe_key(job_id),
            f"print_queue:{prio}",
            JOB_ID_DEDUPLICATION_TTL,
            json.dumps(job),
        )
        if accepted:
            LOGGER.debug("Job %s pushed to priority %s", job_id, prio)
        else:
            LOGGER.info("Duplicate job %s ignored for %s", job_id, self.printer_name)
        return bool(accepted)

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

    def record_success(self) -> int:
        """Persist and return the successful-job count for this printer."""
        return int(
            self.redis.incr(f"print_stats:{self.printer_name}:successful_jobs")
        )

    def successful_jobs(self) -> int:
        """Return the persisted successful-job count."""
        value = self.redis.get(
            f"print_stats:{self.printer_name}:successful_jobs"
        )
        return int(value or 0)

    def record_last_job(self, job: dict[str, Any]) -> None:
        """Persist the latest lifecycle result for status restoration."""
        self.redis.set(
            f"print_stats:{self.printer_name}:last_job",
            json.dumps(job),
        )

    def last_job(self) -> dict[str, Any] | None:
        """Return the persisted latest lifecycle result, if it is valid."""
        raw_job = self.redis.get(f"print_stats:{self.printer_name}:last_job")
        if not raw_job:
            return None
        try:
            job = json.loads(raw_job)
        except (TypeError, json.JSONDecodeError):
            LOGGER.warning("Ignoring invalid persisted last-job status")
            return None
        return job if isinstance(job, dict) else None


def _job_is_expired(job: dict[str, Any], now: float | None = None) -> bool:
    """Return whether a queued job exceeded its optional lifetime."""
    queued_at = float(job.pop("_queued_at", time.time()))
    expires = job.get("expires")
    if expires is None:
        return False
    return (now if now is not None else time.time()) >= queued_at + int(expires)

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

        # PrintImage lets the SDK convert a regular image file directly to the
        # printer raster format.  It avoids writing every dynamic image into
        # the printer's non-volatile memory first.
        self.lib.PrintImage.argtypes = [c_char_p, c_bool, c_uint]
        self.lib.PrintImage.restype = c_int

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
                            item.get("alignment", "left"),
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
            self._feed(int(job.get("feed_after", 4)))
            self._cut()
        return failed

    # ---------------- helpers ----------------

    def _print_barcode(self, spec: dict[str, Any]) -> None:
        """
        Specification keys:
          - barcode_type: str (e.g., 'ean13')
          - content: str
          - mode: int (for QR/2D barcodes)
          - height: int
          - width: int
          - eccLevel: int or single-character str
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
        Print an image from Base64, data URI, or URI in spec['content'].
        Uses the Bixolon SDK's direct PrintImage path.
        """
        # Home Assistant uses paper_w to cap the rendered image at 384 or 576
        # pixels before it is sent to the bridge.  The SDK receives the final
        # bitmap and handles the printer-specific raster conversion.
        del paper_w

        raw_content = spec.get("content")
        if not isinstance(raw_content, str):
            raise ValueError("Image content must be a string")

        image_data = _load_image_bytes(raw_content, timeout=CFG.image_fetch_timeout)

        try:
            with Image.open(io.BytesIO(image_data)) as image:
                image.load()
                img_rgb = image.convert("RGB")
        except Exception as exc:
            raise ValueError("Image load/convert failed") from exc

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bmp") as tmpf:
                img_rgb.save(tmpf, format="BMP")
                tmp_path = tmpf.name

            alignment = spec.get("alignment", "left")
            if alignment not in self._ALIGN:
                raise ValueError(f"Unsupported image alignment: {alignment}")

            result = self.lib.PrintImage(
                tmp_path.encode(),
                True,
                c_uint(self._ALIGN[alignment]),
            )
            if result != 0:
                message = self._ERR_MAP.get(result, "unknown error")
                raise RuntimeError(f"PrintImage failed: {message} (code {result})")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ---------------- status ----------------
    def get_status(self) -> int:
        if hasattr(self.lib, "GetStatus"):
            return self.lib.GetStatus()
        return 0

class MQTTBridge:
    SUB_TOPIC = f"print/pos/{CFG.printer_name}/job"
    PUB_TOPIC = f"print/pos/{CFG.printer_name}/ack"
    STATUS_TOPIC = f"print/pos/{CFG.printer_name}/status"
    LOG_TOPIC = f"print/pos/{CFG.printer_name}/log"
    AVAILABILITY_TOPIC = f"print/pos/{CFG.printer_name}/availability"
    DISCOVERY_TOPIC = f"pos_printer/discovery/{CFG.printer_name}"
    RESTART_TOPIC = f"print/pos/{CFG.printer_name}/restart"

    def __init__(self, printer: BixolonPrinter, spool: RedisSpool):
        self.printer, self.spool = printer, spool
        self.client = mqtt.Client()
        self.client.username_pw_set(CFG.mqtt_user, CFG.mqtt_pass)
        self.client.will_set(
            self.AVAILABILITY_TOPIC,
            payload="offline",
            qos=1,
            retain=True,
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.message_callback_add(self.RESTART_TOPIC, self._on_restart)
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        last_job_getter = getattr(self.spool, "last_job", None)
        self._last_job = last_job_getter() if callable(last_job_getter) else None
        self._log_handler = MQTTLogHandler(self.client, self.LOG_TOPIC, CFG.printer_name)
        self._log_handler.setLevel(getattr(logging, CFG.log_level.upper(), logging.INFO))
        LOGGER.addHandler(self._log_handler)

    # ---------------- public API ----------------
    def start(self):
        self.client.connect(CFG.mqtt_broker, CFG.mqtt_port)
        threading.Thread(target=self._worker_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        self.client.loop_start()

    def stop(self):
        self._stop.set()
        self._publish_status(online=False)
        publish_info = self.client.publish(
            self.AVAILABILITY_TOPIC,
            payload="offline",
            qos=1,
            retain=True,
        )
        wait_for_publish = getattr(publish_info, "wait_for_publish", None)
        if wait_for_publish is not None:
            wait_for_publish(timeout=2)
        self.client.loop_stop()
        self.client.disconnect()
        LOGGER.removeHandler(self._log_handler)
        self._log_handler.close()

    # ---------------- callbacks ----------------
    def _on_connect(self, cli, _userdata, _flags, rc):  # noqa: D401,N802
        if rc == 0:
            cli.subscribe(self.SUB_TOPIC, qos=1)
            cli.subscribe(self.RESTART_TOPIC, qos=1)
            cli.publish(
                self.AVAILABILITY_TOPIC,
                payload="online",
                qos=1,
                retain=True,
            )
            self._publish_bridge_announcement()
            self._publish_status()
            self._remove_legacy_discovery()
            LOGGER.info(
                "MQTT connected; subscribed to %s and %s",
                self.SUB_TOPIC,
                self.RESTART_TOPIC,
            )
        else:
            LOGGER.error("MQTT connection failed: rc=%s", rc)

    def _on_message(self, _cli, _userdata, msg):  # noqa: D401
        try:
            payload = json.loads(msg.payload)
            if not isinstance(payload, dict):
                raise TypeError("job payload must be a JSON object")
            if not isinstance(payload.get("message"), list):
                raise TypeError("job payload requires a message list")
            job_id = payload.get("job_id")
            if not isinstance(job_id, str):
                raise TypeError("job_id must be a string")
            if not job_id.strip():
                raise ValueError("job_id must not be empty")
            if len(job_id) > MAX_JOB_ID_LENGTH:
                raise ValueError(
                    f"job_id must not exceed {MAX_JOB_ID_LENGTH} characters"
                )
            priority = int(payload.get("priority", 5))
            payload["_queued_at"] = time.time()
            if self.spool.push(payload, priority):
                self._publish_ack(job_id, "queued", "")
                LOGGER.debug("Job queued: %s", job_id)
            else:
                self._publish_ack(
                    job_id,
                    "duplicate",
                    "Job ID was already accepted for this printer within the "
                    "24-hour deduplication window; the job was not queued again.",
                    duplicate=True,
                )
        except json.JSONDecodeError as exc:
            LOGGER.error("Invalid JSON on %s: %s", msg.topic, exc, exc_info=True)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Invalid job payload structure on %s: %s", msg.topic, exc, exc_info=True
            )

    def _on_restart(self, _cli, _userdata, _msg):  # noqa: D401
        """Restart only the bridge process; systemd brings it back up."""
        LOGGER.info("Restart command received; restarting bridge service process")
        os._exit(1)

    # ---------------- worker ----------------
    def _worker_loop(self):
        while not self._stop.is_set():
            job = self.spool.pop(timeout=5)
            if not job:
                continue
            job_id = job.get("job_id", f"ts{int(time.time()*1000)}")
            try:
                if _job_is_expired(job):
                    self._publish_ack(job_id, "expired", "Job expired before printing")
                    continue
                self._publish_ack(job_id, "printing", "")
                failures = self.printer.execute_job(job)
                status = "partial-error" if failures else "success"
                detail = ", ".join(failures)
                if not failures:
                    self.spool.record_success()
            except Exception as exc:  # noqa: BLE001
                status, detail = "error", str(exc)
            self._publish_ack(job_id, status, detail)

    # ---------------- heartbeat ----------------
    def _heartbeat_loop(self):
        while not self._stop.is_set():
            self._publish_bridge_announcement()
            self._publish_status()
            time.sleep(CFG.heartbeat_interval)

    # ---------------- helpers ----------------
    def _publish_ack(
        self,
        job_id: str,
        status: str,
        detail: str,
        *,
        duplicate: bool = False,
    ):
        timestamp = int(time.time())
        last_job = {
            "id": job_id,
            "status": status,
            "detail": detail,
            "duplicate": duplicate,
            "timestamp": timestamp,
        }
        with self._state_lock:
            self._last_job = last_job

        record_last_job = getattr(self.spool, "record_last_job", None)
        if callable(record_last_job):
            try:
                record_last_job(last_job)
            except Exception:  # noqa: BLE001
                LOGGER.exception("Could not persist last-job status")

        payload = {
            "job_id": job_id,
            "status": status,
            "detail": detail,
            "duplicate": duplicate,
            "queue_len": self.spool.length(),
            "printer_status": self.printer.get_status(),
            "successful_jobs": self.spool.successful_jobs(),
            "timestamp": timestamp,
        }
        self.client.publish(self.PUB_TOPIC, json.dumps(payload), qos=1)
        self._publish_status(timestamp=timestamp)

    def _publish_status(
        self,
        *,
        online: bool = True,
        timestamp: int | None = None,
    ) -> None:
        """Publish the retained, versioned bridge-status snapshot."""
        with self._state_lock:
            last_job = dict(self._last_job) if self._last_job is not None else None

        payload: Dict[str, Any] = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "printer_name": CFG.printer_name,
            "bridge_version": BRIDGE_VERSION,
            "online": online,
            "timestamp": timestamp if timestamp is not None else int(time.time()),
            "heartbeat_interval": CFG.heartbeat_interval,
            "queue_length": self.spool.length(),
            "printer_status": self.printer.get_status(),
            "successful_jobs": self.spool.successful_jobs(),
            "last_job": last_job,
        }
        if psutil:
            try:
                payload.update(
                    {
                        "cpu_percent": psutil.cpu_percent(interval=None),
                        "mem_available": psutil.virtual_memory().available,
                    }
                )
                get_temperatures = getattr(psutil, "sensors_temperatures", None)
                if callable(get_temperatures):
                    temperatures = get_temperatures()
                    payload["cpu_temp"] = (
                        temperatures["cpu-thermal"][0].current
                        if "cpu-thermal" in temperatures
                        else None
                    )
            except Exception:  # noqa: BLE001
                LOGGER.debug("Could not collect optional host telemetry", exc_info=True)
        self.client.publish(
            self.STATUS_TOPIC,
            json.dumps(payload),
            qos=1,
            retain=True,
        )

    def _publish_bridge_announcement(self):
        payload = {
            "printer_name": CFG.printer_name,
            "version": BRIDGE_VERSION,
            "heartbeat_interval": CFG.heartbeat_interval,
        }
        self.client.publish(
            self.DISCOVERY_TOPIC,
            json.dumps(payload),
            qos=1,
            retain=True,
        )

    def _remove_legacy_discovery(self):
        """Remove retained discovery payloads that created duplicate MQTT entities."""
        topics = (
            "pos_printer/discovery",
            f"homeassistant/sensor/{CFG.printer_name}/queue/config",
            f"homeassistant/sensor/{CFG.printer_name}/status/config",
        )
        for topic in topics:
            self.client.publish(topic, payload="", qos=1, retain=True)

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
