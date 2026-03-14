"""Image loading and host-side preprocessing for POS printing."""

from __future__ import annotations

import base64
import binascii
import io
from pathlib import Path
from typing import Any
from urllib.parse import unquote, unquote_to_bytes, urlparse

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from PIL import Image, ImageOps

from .const import (
    DEFAULT_IMAGE_DITHER,
    DEFAULT_IMAGE_FETCH_TIMEOUT,
    DEFAULT_IMAGE_THRESHOLD,
    DEFAULT_PAPER_WIDTH,
    PAPER_WIDTH_TO_PIXELS,
)

_MEDIA_SOURCE_PREFIX = "media-source://media_source/local/"
_IMAGE_USER_AGENT = "ha-pos-printer/0.2.0"
_ALLOWED_RELATIVE_ROOTS = ("media", "www")


def _decode_data_uri(content: str) -> bytes:
    """Decode a data URI into raw bytes."""
    if "," not in content:
        raise HomeAssistantError("Image data URI is missing the comma separator.")

    header, payload = content.split(",", 1)
    if ";base64" in header.lower():
        try:
            return base64.b64decode(payload, validate=True)
        except binascii.Error as err:
            raise HomeAssistantError("Image data URI contains invalid base64.") from err

    return unquote_to_bytes(payload)


def _extract_media_source_id(value: Any) -> str | None:
    """Normalize media-selector output to a media-source identifier."""
    if value in (None, ""):
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ("media_content_id", "media-source", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate

    raise HomeAssistantError(
        "Field 'image_media_source' must be a media-source string or selector object."
    )


def _resolve_local_media_path(hass: HomeAssistant, media_source_id: str) -> Path:
    """Resolve a local ``media-source://`` URI to a file path."""
    if not media_source_id.startswith(_MEDIA_SOURCE_PREFIX):
        raise HomeAssistantError(
            "Only local media-source images are supported by this integration."
        )

    relative_path = unquote(media_source_id[len(_MEDIA_SOURCE_PREFIX) :]).lstrip("/")
    media_dirs = getattr(hass.config, "media_dirs", {})
    base_path = Path(media_dirs.get("local", hass.config.path("media"))).resolve()
    target_path = (base_path / relative_path).resolve()

    if target_path != base_path and base_path not in target_path.parents:
        raise HomeAssistantError("Media-source image path escapes the media directory.")

    return target_path


def _resolve_local_path(hass: HomeAssistant, raw_path: str) -> Path:
    """Resolve a user-provided path inside Home Assistant managed folders."""
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        parts = candidate.parts
        if parts and parts[0] in _ALLOWED_RELATIVE_ROOTS:
            candidate = Path(hass.config.path(*parts))
        else:
            candidate = Path(hass.config.path(raw_path))

    resolved = candidate.resolve()
    allowed_roots = [
        Path(hass.config.path()).resolve(),
        Path(hass.config.path("www")).resolve(),
    ]
    allowed_roots.extend(
        Path(path).resolve()
        for path in getattr(hass.config, "media_dirs", {}).values()
    )
    allowed_roots.append(Path(hass.config.path("media")).resolve())

    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise HomeAssistantError(
            "Local image paths must stay inside the Home Assistant config, media, or www directory."
        )

    return resolved


async def _async_fetch_remote_image(
    hass: HomeAssistant,
    uri: str,
    timeout: int,
) -> bytes:
    """Fetch an image over HTTP(S) on the Home Assistant host."""
    session = async_get_clientsession(hass)
    async with session.get(
        uri,
        timeout=timeout,
        headers={"User-Agent": _IMAGE_USER_AGENT},
    ) as response:
        response.raise_for_status()
        payload = await response.read()

    if not payload:
        raise HomeAssistantError("Remote image returned an empty payload.")

    return payload


async def _async_load_local_image(
    hass: HomeAssistant,
    path: Path,
) -> bytes:
    """Read local image bytes in the executor."""
    try:
        return await hass.async_add_executor_job(path.read_bytes)
    except FileNotFoundError as err:
        raise HomeAssistantError(f"Image file not found: {path}") from err


def _decode_image_content(content: str) -> bytes:
    """Decode base64 or data-URI image payloads."""
    source = content.strip()
    if not source:
        raise HomeAssistantError("Image content is empty.")

    if source.startswith("data:"):
        return _decode_data_uri(source)

    try:
        return base64.b64decode(source, validate=True)
    except binascii.Error as err:
        raise HomeAssistantError(
            "Field 'image_content' must contain base64 or a valid data URI."
        ) from err


async def _async_load_camera_image(
    hass: HomeAssistant,
    camera_entity_id: str,
    timeout: int,
) -> bytes:
    """Retrieve a still image from a Home Assistant camera entity."""
    from homeassistant.components.camera import async_get_image

    image = await async_get_image(hass, camera_entity_id, timeout=timeout)
    return image.content


async def async_resolve_image_bytes(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> bytes:
    """Resolve a single image source into bytes."""
    timeout = int(data.get("image_fetch_timeout", DEFAULT_IMAGE_FETCH_TIMEOUT))
    image_content = data.get("image_content")
    image_url = data.get("image_url")
    image_path = data.get("image_path")
    image_media_source = _extract_media_source_id(data.get("image_media_source"))
    camera_entity_id = data.get("camera_entity_id")

    sources = [
        ("image_content", image_content),
        ("image_url", image_url),
        ("image_path", image_path),
        ("image_media_source", image_media_source),
        ("camera_entity_id", camera_entity_id),
    ]
    active_sources = [name for name, value in sources if value not in (None, "")]

    if not active_sources:
        raise HomeAssistantError("No image source provided.")

    if len(active_sources) > 1:
        raise HomeAssistantError(
            "Use only one image source at a time: "
            "image_content, image_url, image_path, image_media_source, or camera_entity_id."
        )

    if image_content not in (None, ""):
        return _decode_image_content(str(image_content))

    if image_url not in (None, ""):
        parsed = urlparse(str(image_url))
        if parsed.scheme in {"http", "https"}:
            return await _async_fetch_remote_image(hass, str(image_url), timeout)
        if parsed.scheme == "file":
            path = _resolve_local_path(hass, unquote(parsed.path))
            return await _async_load_local_image(hass, path)
        raise HomeAssistantError(
            "Field 'image_url' must use http://, https://, or file://."
        )

    if image_path not in (None, ""):
        path = _resolve_local_path(hass, str(image_path))
        return await _async_load_local_image(hass, path)

    if image_media_source is not None:
        path = _resolve_local_media_path(hass, image_media_source)
        return await _async_load_local_image(hass, path)

    return await _async_load_camera_image(hass, str(camera_entity_id), timeout)


def _encode_processed_image(
    image_bytes: bytes,
    paper_width: int,
    max_width: int | None,
    rotation: int,
    dither: bool,
    invert: bool,
    threshold: int | None,
) -> str:
    """Convert image bytes into a printer-friendly data URI."""
    target_width = max_width or PAPER_WIDTH_TO_PIXELS.get(
        paper_width,
        PAPER_WIDTH_TO_PIXELS[DEFAULT_PAPER_WIDTH],
    )
    bw_threshold = threshold if threshold is not None else DEFAULT_IMAGE_THRESHOLD

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            processed = ImageOps.exif_transpose(image).convert("L")

            if rotation:
                processed = processed.rotate(-rotation, expand=True)

            if processed.width > target_width:
                ratio = target_width / processed.width
                processed = processed.resize(
                    (target_width, max(1, int(processed.height * ratio))),
                    Image.LANCZOS,
                )

            if invert:
                processed = ImageOps.invert(processed)

            if dither:
                processed = processed.convert("1", dither=Image.FLOYDSTEINBERG)
            else:
                processed = processed.point(
                    lambda value: 255 if value > bw_threshold else 0,
                    mode="1",
                )

            buffer = io.BytesIO()
            processed.save(buffer, format="PNG", optimize=True)
    except OSError as err:
        raise HomeAssistantError("Unable to load or process the selected image.") from err

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


async def async_prepare_image_content(
    hass: HomeAssistant,
    data: dict[str, Any],
    paper_width: int,
) -> str:
    """Resolve and preprocess image data on the Home Assistant host."""
    image_bytes = await async_resolve_image_bytes(hass, data)
    max_width = data.get("image_max_width")
    rotation = int(data.get("image_rotation", 0) or 0)
    dither = bool(data.get("image_dither", DEFAULT_IMAGE_DITHER))
    invert = bool(data.get("image_invert", False))
    threshold = data.get("image_threshold")

    return await hass.async_add_executor_job(
        _encode_processed_image,
        image_bytes,
        paper_width,
        int(max_width) if max_width is not None else None,
        rotation,
        dither,
        invert,
        int(threshold) if threshold is not None else None,
    )
