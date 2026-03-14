"""Tests for host-side image processing."""

from __future__ import annotations

import base64
import io
import sys
from types import ModuleType
from pathlib import Path

import pytest
from homeassistant.exceptions import HomeAssistantError
from PIL import Image

from custom_components.pos_printer.const import VERSION
from custom_components.pos_printer.image_processing import (
    _decode_data_uri,
    _decode_image_content,
    _encode_processed_image,
    _extract_media_source_id,
    async_prepare_image_content,
    async_resolve_image_bytes,
)


class FakeConfig:
    """Minimal Home Assistant config object."""

    def __init__(self, config_dir: Path, media_dir: Path) -> None:
        self._config_dir = config_dir
        self.media_dirs = {"local": str(media_dir)}

    def path(self, *parts: str) -> str:
        return str(self._config_dir.joinpath(*parts))


class FakeHass:
    """Minimal hass object for image helpers."""

    def __init__(self, config_dir: Path, media_dir: Path) -> None:
        self.config = FakeConfig(config_dir, media_dir)

    async def async_add_executor_job(self, target, *args):
        return target(*args)


def _write_test_image(path: Path, size: tuple[int, int] = (64, 32)) -> bytes:
    """Create a simple RGB PNG for tests."""
    image = Image.new("RGB", size, color="white")
    image.putpixel((0, 0), (0, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path.read_bytes()


@pytest.mark.asyncio
async def test_prepare_image_content_from_local_path(tmp_path):
    """Images should be loaded from disk and converted to data URIs."""
    config_dir = tmp_path / "config"
    media_dir = tmp_path / "media"
    image_path = config_dir / "media" / "sample.png"
    _write_test_image(image_path)
    hass = FakeHass(config_dir, media_dir)

    result = await async_prepare_image_content(
        hass,
        {
            "image_path": "media/sample.png",
            "image_dither": False,
            "image_threshold": 32,
            "image_rotation": 90,
        },
        paper_width=80,
    )

    assert result.startswith("data:image/png;base64,")
    decoded = base64.b64decode(result.split(",", 1)[1])
    with Image.open(io.BytesIO(decoded)) as processed:
        assert processed.width <= 576


@pytest.mark.asyncio
async def test_resolve_image_bytes_supports_media_selector_object(tmp_path):
    """The helper should resolve media-selector output from the local media dir."""
    config_dir = tmp_path / "config"
    media_dir = tmp_path / "real_media"
    image_path = media_dir / "receipts" / "logo.png"
    expected = _write_test_image(image_path)
    hass = FakeHass(config_dir, media_dir)

    result = await async_resolve_image_bytes(
        hass,
        {
            "image_media_source": {
                "media_content_id": "media-source://media_source/local/receipts/logo.png"
            }
        },
    )
    assert result == expected


@pytest.mark.asyncio
async def test_resolve_image_bytes_rejects_media_path_escape(tmp_path):
    """Media-source paths must not escape the configured media directory."""
    config_dir = tmp_path / "config"
    media_dir = tmp_path / "media"
    hass = FakeHass(config_dir, media_dir)

    with pytest.raises(HomeAssistantError, match="escapes the media directory"):
        await async_resolve_image_bytes(
            hass,
            {"image_media_source": "media-source://media_source/local/../secret.png"},
        )


@pytest.mark.asyncio
async def test_resolve_image_bytes_rejects_multiple_sources(tmp_path):
    """Exactly one image source is allowed."""
    hass = FakeHass(tmp_path / "config", tmp_path / "media")

    with pytest.raises(HomeAssistantError, match="Use only one image source"):
        await async_resolve_image_bytes(
            hass,
            {"image_content": "aGVsbG8=", "image_url": "https://example.com/logo.png"},
        )


@pytest.mark.asyncio
async def test_resolve_image_bytes_rejects_path_escape(tmp_path):
    """Path traversal should be blocked."""
    config_dir = tmp_path / "config"
    media_dir = tmp_path / "media"
    hass = FakeHass(config_dir, media_dir)

    with pytest.raises(HomeAssistantError, match="must stay inside"):
        await async_resolve_image_bytes(hass, {"image_path": "../secret.png"})


@pytest.mark.asyncio
async def test_resolve_image_bytes_supports_camera_entities(tmp_path, monkeypatch):
    """Camera entities should be resolved through Home Assistant."""
    hass = FakeHass(tmp_path / "config", tmp_path / "media")

    async def fake_get_image(hass, entity_id, timeout):
        assert entity_id == "camera.front"
        assert timeout == 15
        return b"camera-bytes"

    monkeypatch.setattr(
        "custom_components.pos_printer.image_processing._async_load_camera_image",
        fake_get_image,
    )

    result = await async_resolve_image_bytes(hass, {"camera_entity_id": "camera.front"})
    assert result == b"camera-bytes"


def test_decode_data_uri_and_media_source_helpers():
    """Low-level helpers should decode and normalize inputs."""
    payload = base64.b64encode(b"hello").decode()
    assert _decode_data_uri(f"data:image/png;base64,{payload}") == b"hello"
    assert _decode_data_uri("data:image/png,hello%20world") == b"hello world"
    assert _extract_media_source_id({"media_content_id": "media-source://x"}) == "media-source://x"
    assert _decode_image_content(payload) == b"hello"

    with pytest.raises(HomeAssistantError, match="comma separator"):
        _decode_data_uri("data:image/png;base64")

    with pytest.raises(HomeAssistantError, match="invalid base64"):
        _decode_data_uri("data:image/png;base64,%%%")

    with pytest.raises(HomeAssistantError, match="Image content is empty"):
        _decode_image_content("   ")

    with pytest.raises(HomeAssistantError, match="base64 or a valid data URI"):
        _decode_image_content("not base64!")

    with pytest.raises(HomeAssistantError, match="media-source"):
        _extract_media_source_id(123)


@pytest.mark.asyncio
async def test_remote_fetch_and_missing_payload_branches(tmp_path, monkeypatch):
    """HTTP image loading should work and reject empty payloads."""
    hass = FakeHass(tmp_path / "config", tmp_path / "media")
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        async def read(self):
            return self._payload

    class FakeSession:
        def __init__(self, payload):
            self._payload = payload

        def get(self, uri, timeout, headers):
            calls.append((uri, timeout, headers["User-Agent"]))
            return FakeResponse(self._payload)

    monkeypatch.setattr(
        "custom_components.pos_printer.image_processing.async_get_clientsession",
        lambda hass: FakeSession(b"remote-bytes"),
    )
    result = await async_resolve_image_bytes(
        hass,
        {"image_url": "https://example.com/logo.png", "image_fetch_timeout": 5},
    )
    assert result == b"remote-bytes"
    assert calls == [("https://example.com/logo.png", 5, f"ha-pos-printer/{VERSION}")]

    monkeypatch.setattr(
        "custom_components.pos_printer.image_processing.async_get_clientsession",
        lambda hass: FakeSession(b""),
    )
    with pytest.raises(HomeAssistantError, match="empty payload"):
        await async_resolve_image_bytes(hass, {"image_url": "https://example.com/logo.png"})


@pytest.mark.asyncio
async def test_file_url_and_missing_file_branches(tmp_path):
    """file:// URLs should resolve locally and missing files should raise a HA error."""
    config_dir = tmp_path / "config"
    media_dir = tmp_path / "media"
    image_path = config_dir / "www" / "photo.png"
    expected = _write_test_image(image_path)
    hass = FakeHass(config_dir, media_dir)

    result = await async_resolve_image_bytes(hass, {"image_url": image_path.as_uri()})
    assert result == expected

    with pytest.raises(HomeAssistantError, match="Image file not found"):
        await async_resolve_image_bytes(hass, {"image_path": "www/missing.png"})


@pytest.mark.asyncio
async def test_image_source_validation_errors(tmp_path):
    """Missing and unsupported image sources should be rejected."""
    hass = FakeHass(tmp_path / "config", tmp_path / "media")

    with pytest.raises(HomeAssistantError, match="No image source provided"):
        await async_resolve_image_bytes(hass, {})

    with pytest.raises(HomeAssistantError, match="Only local media-source"):
        await async_resolve_image_bytes(
            hass,
            {"image_media_source": "media-source://camera/front_door"},
        )

    with pytest.raises(HomeAssistantError, match="must use http://, https://, or file://"):
        await async_resolve_image_bytes(hass, {"image_url": "ftp://example.com/image.png"})


@pytest.mark.asyncio
async def test_camera_helper_import_branch(tmp_path, monkeypatch):
    """The camera helper should import Home Assistant's camera helper lazily."""
    hass = FakeHass(tmp_path / "config", tmp_path / "media")
    fake_camera = ModuleType("homeassistant.components.camera")

    class FakeImage:
        content = b"camera-bytes"

    async def fake_get_image(hass, entity_id, timeout):
        assert entity_id == "camera.side"
        assert timeout == 15
        return FakeImage()

    fake_camera.async_get_image = fake_get_image
    monkeypatch.setitem(sys.modules, "homeassistant.components.camera", fake_camera)

    result = await async_resolve_image_bytes(hass, {"camera_entity_id": "camera.side"})
    assert result == b"camera-bytes"


@pytest.mark.asyncio
async def test_image_content_branches_cover_data_uri_and_base64(tmp_path):
    """Raw image content should accept both data URIs and plain base64."""
    hass = FakeHass(tmp_path / "config", tmp_path / "media")
    payload = base64.b64encode(b"hello").decode()

    assert await async_resolve_image_bytes(hass, {"image_content": payload}) == b"hello"
    assert (
        await async_resolve_image_bytes(
            hass,
            {"image_content": f"data:image/png;base64,{payload}"},
        )
        == b"hello"
    )


def test_encode_processed_image_covers_resize_invert_and_errors():
    """Encoding should resize, invert, dither, and reject invalid image bytes."""
    image = Image.new("RGB", (1200, 20), color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = _encode_processed_image(
        buffer.getvalue(),
        paper_width=53,
        max_width=100,
        rotation=0,
        dither=True,
        invert=True,
        threshold=None,
    )
    decoded = base64.b64decode(result.split(",", 1)[1])
    with Image.open(io.BytesIO(decoded)) as processed:
        assert processed.width == 100

    with pytest.raises(HomeAssistantError, match="Unable to load or process"):
        _encode_processed_image(b"not-an-image", 80, None, 0, False, False, 10)
