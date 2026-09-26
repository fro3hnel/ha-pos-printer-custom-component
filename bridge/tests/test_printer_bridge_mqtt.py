"""Tests for MQTT lifecycle and queue behavior in the bridge."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bridge import printer_bridge


class FakeClient:
    """Small paho client double."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str, int, bool]] = []
        self.subscribed: list[tuple[str, int]] = []
        self.will: tuple[str, str, int, bool] | None = None

    def username_pw_set(self, _user, _password):
        return None

    def message_callback_add(self, _topic, _callback):
        return None

    def will_set(self, topic, payload, qos, retain):
        self.will = (topic, payload, qos, retain)

    def subscribe(self, topic, qos):
        self.subscribed.append((topic, qos))

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return SimpleNamespace()


class FakePrinter:
    def __init__(self) -> None:
        self.execute_calls = 0

    def get_status(self):
        return 0

    def execute_job(self, _job):
        self.execute_calls += 1
        return []


class FakeSpool:
    def __init__(self) -> None:
        self.jobs = []
        self._accepted_job_ids: set[str] = set()
        self.last_job_payload = None

    def push(self, payload, priority):
        if payload["job_id"] in self._accepted_job_ids:
            return False
        self._accepted_job_ids.add(payload["job_id"])
        self.jobs.append((payload, priority))
        return True

    def length(self):
        return len(self.jobs)

    def successful_jobs(self):
        return 0

    def record_success(self):
        return 1

    def record_last_job(self, payload):
        self.last_job_payload = payload

    def last_job(self):
        return self.last_job_payload


def test_bridge_uses_lwt_and_cleans_legacy_discovery(monkeypatch):
    """The bridge should publish one native integration device without MQTT duplicates."""
    client = FakeClient()
    monkeypatch.setattr(printer_bridge.mqtt, "Client", lambda: client)
    bridge = printer_bridge.MQTTBridge(FakePrinter(), FakeSpool())

    assert client.will == (bridge.AVAILABILITY_TOPIC, "offline", 1, True)

    bridge._on_connect(client, None, None, 0)
    published = {topic: (payload, qos, retain) for topic, payload, qos, retain in client.published}

    assert published[bridge.AVAILABILITY_TOPIC] == ("online", 1, True)
    status_payload = json.loads(published[bridge.STATUS_TOPIC][0])
    assert status_payload["schema_version"] == 1
    assert status_payload["printer_name"] == printer_bridge.CFG.printer_name
    assert status_payload["bridge_version"] == printer_bridge.BRIDGE_VERSION
    assert status_payload["online"] is True
    assert isinstance(status_payload["timestamp"], int)
    assert status_payload["heartbeat_interval"] == printer_bridge.CFG.heartbeat_interval
    assert status_payload["queue_length"] == 0
    assert status_payload["printer_status"] == 0
    assert status_payload["successful_jobs"] == 0
    assert status_payload["last_job"] is None
    assert published[bridge.STATUS_TOPIC][1:] == (1, True)
    discovery_payload = json.loads(published[bridge.DISCOVERY_TOPIC][0])
    assert discovery_payload["printer_name"] == printer_bridge.CFG.printer_name
    assert published["pos_printer/discovery"] == ("", 1, True)
    assert (
        published[
            f"homeassistant/sensor/{printer_bridge.CFG.printer_name}/queue/config"
        ]
        == ("", 1, True)
    )
    assert not any(
        topic.startswith("homeassistant/") and payload
        for topic, payload, _qos, _retain in client.published
    )


def test_received_job_is_queued_and_acknowledged(monkeypatch):
    """A valid MQTT job should get a queued acknowledgement immediately."""
    client = FakeClient()
    spool = FakeSpool()
    monkeypatch.setattr(printer_bridge.mqtt, "Client", lambda: client)
    bridge = printer_bridge.MQTTBridge(FakePrinter(), spool)

    bridge._on_message(
        client,
        None,
        SimpleNamespace(
            topic=bridge.SUB_TOPIC,
            payload=json.dumps(
                {"job_id": "job-1", "priority": 3, "message": [{"type": "text"}]}
            ),
        ),
    )

    assert spool.jobs[0][1] == 3
    assert "_queued_at" in spool.jobs[0][0]
    ack = next(
        json.loads(payload)
        for topic, payload, _qos, _retain in client.published
        if topic == bridge.PUB_TOPIC
    )
    assert ack["job_id"] == "job-1"
    assert ack["status"] == "queued"
    assert ack["duplicate"] is False
    status = json.loads(client.published[-1][1])
    assert client.published[-1][0] == bridge.STATUS_TOPIC
    assert client.published[-1][3] is True
    assert status["queue_length"] == 1
    assert status["last_job"] == {
        "id": "job-1",
        "status": "queued",
        "detail": "",
        "duplicate": False,
        "timestamp": ack["timestamp"],
    }
    assert spool.last_job_payload == status["last_job"]


def test_duplicate_job_is_not_queued_or_printed(monkeypatch):
    """QoS 1 redelivery should report duplicate without a second queue entry."""
    client = FakeClient()
    printer = FakePrinter()
    spool = FakeSpool()
    monkeypatch.setattr(printer_bridge.mqtt, "Client", lambda: client)
    bridge = printer_bridge.MQTTBridge(printer, spool)
    first_payload = {
        "job_id": "stable-job-id",
        "priority": 4,
        "message": [{"type": "text", "content": "first"}],
    }
    changed_payload = {
        **first_payload,
        "message": [{"type": "text", "content": "changed"}],
    }

    for payload in (first_payload, changed_payload):
        bridge._on_message(
            client,
            None,
            SimpleNamespace(topic=bridge.SUB_TOPIC, payload=json.dumps(payload)),
        )

    assert len(spool.jobs) == 1
    assert spool.jobs[0][0]["message"][0]["content"] == "first"
    assert printer.execute_calls == 0
    acknowledgements = [
        json.loads(payload)
        for topic, payload, _qos, _retain in client.published
        if topic == bridge.PUB_TOPIC
    ]
    assert [ack["status"] for ack in acknowledgements] == ["queued", "duplicate"]
    assert acknowledgements[-1]["duplicate"] is True
    assert "not queued again" in acknowledgements[-1]["detail"]


@pytest.mark.parametrize("job_id", [None, "", "   ", "x" * 129, 123])
def test_invalid_job_id_is_rejected(monkeypatch, job_id):
    """Direct MQTT clients must use a non-empty bounded string job ID."""
    client = FakeClient()
    spool = FakeSpool()
    monkeypatch.setattr(printer_bridge.mqtt, "Client", lambda: client)
    bridge = printer_bridge.MQTTBridge(FakePrinter(), spool)

    bridge._on_message(
        client,
        None,
        SimpleNamespace(
            topic=bridge.SUB_TOPIC,
            payload=json.dumps(
                {"job_id": job_id, "message": [{"type": "text", "content": "x"}]}
            ),
        ),
    )

    assert spool.jobs == []
    assert all(topic != bridge.PUB_TOPIC for topic, *_rest in client.published)


def test_job_expiry_uses_bridge_queue_time():
    """Expiry should prevent stale physical printouts."""
    expired = {"expires": 30, "_queued_at": 100.0}
    fresh = {"expires": 30, "_queued_at": 100.0}

    assert printer_bridge._job_is_expired(expired, now=131.0) is True
    assert printer_bridge._job_is_expired(fresh, now=129.0) is False
