"""Unit and protocol integration tests for the Redis print spool."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import redis

from bridge import printer_bridge

_SOCKET_CONNECT = socket.socket.connect


class FakeRedis:
    """Small Redis double that records Lua enqueue calls."""

    def __init__(self) -> None:
        self.markers: set[str] = set()
        self.queues: dict[str, list[str]] = {}
        self.calls: list[tuple[str, str, int, str]] = []

    def eval(
        self,
        _script: str,
        key_count: int,
        marker_key: str,
        queue_key: str,
        ttl: int,
        payload: str,
    ) -> int:
        assert key_count == 2
        self.calls.append((marker_key, queue_key, ttl, payload))
        if marker_key in self.markers:
            return 0
        self.markers.add(marker_key)
        self.queues.setdefault(queue_key, []).append(payload)
        return 1


def test_spool_deduplicates_per_printer_and_job_id(monkeypatch):
    """The spool should scope hashed markers to one printer for 24 hours."""
    fake_redis = FakeRedis()
    monkeypatch.setattr(
        printer_bridge.redis.Redis,
        "from_url",
        lambda *_args, **_kwargs: fake_redis,
    )
    printer_a = printer_bridge.RedisSpool("redis://test", "printer_a")
    printer_b = printer_bridge.RedisSpool("redis://test", "printer_b")
    first = {
        "job_id": "customer-visible-id",
        "priority": 2,
        "message": [{"type": "text", "content": "first"}],
    }
    changed = {
        **first,
        "message": [{"type": "text", "content": "changed"}],
    }

    assert printer_a.push(first, 2) is True
    assert printer_a.push(changed, 2) is False
    assert printer_b.push(first, 2) is True
    assert printer_a.push({**first, "job_id": "another-id"}, 2) is True

    assert len(fake_redis.queues["print_queue:2"]) == 3
    assert fake_redis.calls[0][2] == printer_bridge.JOB_ID_DEDUPLICATION_TTL
    assert "customer-visible-id" not in fake_redis.calls[0][0]
    assert printer_a.dedupe_key(first["job_id"]) != printer_b.dedupe_key(
        first["job_id"]
    )


def _wait_for_redis(redis_url: str, timeout: float = 5.0) -> None:
    """Wait until a newly started Redis instance accepts connections."""
    client = redis.Redis.from_url(redis_url)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            client.ping()
            return
        except redis.RedisError:
            time.sleep(0.05)
    raise RuntimeError(f"Redis did not become ready at {redis_url}")


@pytest.fixture
def isolated_redis_url(tmp_path: Path, socket_enabled, monkeypatch):
    """Use the CI Redis service or launch an isolated temporary local server."""
    monkeypatch.setattr(socket.socket, "connect", _SOCKET_CONNECT)
    configured_url = os.getenv("TEST_REDIS_URL")
    if configured_url:
        _wait_for_redis(configured_url)
        yield configured_url
        return

    redis_server = shutil.which("redis-server")
    if redis_server is None:
        pytest.skip("redis-server is required for the Redis protocol test")

    data_directory = tmp_path
    socket_path = Path("/tmp") / f"pos-printer-redis-{uuid.uuid4().hex}.sock"
    process = subprocess.Popen(  # noqa: S603
        [
            redis_server,
            "--port",
            "0",
            "--unixsocket",
            str(socket_path),
            "--unixsocketperm",
            "700",
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(data_directory),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    redis_url = f"unix://{socket_path}"
    try:
        _wait_for_redis(redis_url)
        yield redis_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        socket_path.unlink(missing_ok=True)


def test_atomic_enqueue_and_ttl_against_real_redis(isolated_redis_url):
    """Concurrent delivery must create one queue item and one live TTL marker."""
    namespace = uuid.uuid4().hex
    printer_a = printer_bridge.RedisSpool(
        isolated_redis_url, f"pytest_{namespace}_a"
    )
    printer_b = printer_bridge.RedisSpool(
        isolated_redis_url, f"pytest_{namespace}_b"
    )
    queue_key = "print_queue:3"
    client = printer_a.redis
    job = {
        "job_id": f"{namespace}-job",
        "priority": 3,
        "message": [{"type": "text", "content": "original"}],
    }
    marker_a = printer_a.dedupe_key(job["job_id"])
    marker_b = printer_b.dedupe_key(job["job_id"])
    second_marker = printer_a.dedupe_key(f"{namespace}-second")
    client.delete(queue_key, marker_a, marker_b, second_marker)

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            accepted = list(executor.map(lambda _index: printer_a.push(job, 3), range(16)))

        assert accepted.count(True) == 1
        assert accepted.count(False) == 15
        assert client.llen(queue_key) == 1
        queued_job = json.loads(client.lindex(queue_key, 0))
        assert queued_job["message"][0]["content"] == "original"
        assert list(
            client.scan_iter(match=f"print_dedupe:{printer_a.printer_name}:*")
        ) == [marker_a]
        marker_ttl = client.ttl(marker_a)
        assert 0 < marker_ttl <= printer_bridge.JOB_ID_DEDUPLICATION_TTL

        changed_job = {
            **job,
            "message": [{"type": "text", "content": "changed"}],
        }
        assert printer_a.push(changed_job, 3) is False
        assert client.llen(queue_key) == 1

        assert printer_b.push(job, 3) is True
        assert printer_a.push({**job, "job_id": f"{namespace}-second"}, 3) is True
        assert client.llen(queue_key) == 3
    finally:
        client.delete(queue_key, marker_a, marker_b, second_marker)
