"""Image loading and host-side preprocessing for POS printing."""

from __future__ import annotations

import base64
import binascii
import io
from pathlib import Path
from typing import Any
from urllib.parse import unquote, unquote_to_bytes, urlparse

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from PIL import Image, ImageOps

from .const import (
    DEFAULT_IMAGE_DITHER,
    DEFAULT_IMAGE_FETCH_TIMEOUT,
    DEFAULT_IMAGE_THRESHOLD,
    DEFAULT_PAPER_WIDTH,
    PAPER_WIDTH_TO_PIXELS,
    VERSION,
)
from .exceptions import integration_error, service_validation_error

_MEDIA_SOURCE_PREFIX = "media-source://media_source/local/"
_IMAGE_USER_AGENT = f"ha-pos-printer/{VERSION}"
_ALLOWED_RELATIVE_ROOTS = ("media", "www")
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000


def _validate_image_size(payload: bytes) -> bytes:
    """Reject image payloads that are too large for a service action."""
    if len(payload) > _MAX_IMAGE_BYTES:
        raise service_validation_error(
            "Image payload exceeds the 10 MiB limit.",
            "image_too_large",
            maximum_mib=10,
        )
    return payload


def _decode_data_uri(content: str) -> bytes:
    """Decode a data URI into raw bytes."""
    if "," not in content:
        raise service_validation_error(
            "Image data URI is missing the comma separator.",
            "data_uri_separator_missing",
        )

    header, payload = content.split(",", 1)
    if ";base64" in header.lower():
        try:
            return base64.b64decode(payload, validate=True)
        except binascii.Error as err:
            raise service_validation_error(
                "Image data URI contains invalid base64.",
                "invalid_data_uri_base64",
            ) from err

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

    raise service_validation_error(
        "Field 'image_media_source' must be a media-source string or selector object.",
        "invalid_media_source_selector",
    )


def _resolve_local_media_path(hass: HomeAssistant, media_source_id: str) -> Path:
    """Resolve a local ``media-source://`` URI to a file path."""
    if not media_source_id.startswith(_MEDIA_SOURCE_PREFIX):
        raise service_validation_error(
            "Only local media-source images are supported by this integration.",
            "local_media_source_only",
        )

    relative_path = unquote(media_source_id[len(_MEDIA_SOURCE_PREFIX) :]).lstrip("/")
    media_dirs = getattr(hass.config, "media_dirs", {})
    base_path = Path(media_dirs.get("local", hass.config.path("media"))).resolve()
    target_path = (base_path / relative_path).resolve()

    if target_path != base_path and base_path not in target_path.parents:
        raise service_validation_error(
            "Media-source image path escapes the media directory.",
            "media_path_escape",
        )

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
        raise service_validation_error(
            "Local image paths must stay inside the Home Assistant config, "
            "media, or www directory.",
            "local_path_not_allowed",
        )

    return resolved


async def _async_fetch_remote_image(
    hass: HomeAssistant,
    uri: str,
    timeout: int,
) -> bytes:
    """Fetch an image over HTTP(S) on the Home Assistant host."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            uri,
            timeout=timeout,
            headers={"User-Agent": _IMAGE_USER_AGENT},
        ) as response:
            response.raise_for_status()
            if (
                response.content_length is not None
                and response.content_length > _MAX_IMAGE_BYTES
            ):
                raise service_validation_error(
                    "Image payload exceeds the 10 MiB limit.",
                    "image_too_large",
                    maximum_mib=10,
                )
            payload = await response.content.read(_MAX_IMAGE_BYTES + 1)
    except (ClientError, TimeoutError) as err:
        raise integration_error(
            f"Unable to fetch the remote image: {err}",
            "remote_image_fetch_failed",
            error=err,
        ) from err

    if not payload:
        raise integration_error(
            "Remote image returned an empty payload.", "remote_image_empty"
        )

    return _validate_image_size(payload)


async def _async_load_local_image(
    hass: HomeAssistant,
    path: Path,
) -> bytes:
    """Read local image bytes in the executor."""
    try:
        payload = await hass.async_add_executor_job(path.read_bytes)
    except FileNotFoundError as err:
        raise service_validation_error(
            f"Image file not found: {path}",
            "image_file_not_found",
            path=path,
        ) from err
    except OSError as err:
        raise integration_error(
            f"Unable to read image file: {err}",
            "image_file_read_failed",
            error=err,
        ) from err
    return _validate_image_size(payload)


def _decode_image_content(content: str) -> bytes:
    """Decode base64 or data-URI image payloads."""
    source = content.strip()
    if not source:
        raise service_validation_error(
            "Image content is empty.", "image_content_empty"
        )

    if source.startswith("data:"):
        return _decode_data_uri(source)

    try:
        return base64.b64decode(source, validate=True)
    except binascii.Error as err:
        raise service_validation_error(
            "Field 'image_content' must contain base64 or a valid data URI.",
            "invalid_image_content",
        ) from err


async def _async_load_camera_image(
    hass: HomeAssistant,
    camera_entity_id: str,
    timeout: int,
) -> bytes:
    """Retrieve a still image from a Home Assistant camera entity."""
    from homeassistant.components.camera import async_get_image

    image = await async_get_image(hass, camera_entity_id, timeout=timeout)
    return _validate_image_size(image.content)


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
        raise service_validation_error(
            "No image source provided.", "no_image_source"
        )

    if len(active_sources) > 1:
        raise service_validation_error(
            "Use only one image source at a time: "
            "image_content, image_url, image_path, image_media_source, or camera_entity_id.",
            "multiple_image_sources",
        )

    if image_content not in (None, ""):
        return _validate_image_size(_decode_image_content(str(image_content)))

    if image_url not in (None, ""):
        parsed = urlparse(str(image_url))
        if parsed.scheme in {"http", "https"}:
            return await _async_fetch_remote_image(hass, str(image_url), timeout)
        if parsed.scheme == "file":
            path = _resolve_local_path(hass, unquote(parsed.path))
            return await _async_load_local_image(hass, path)
        raise service_validation_error(
            "Field 'image_url' must use http://, https://, or file://.",
            "invalid_image_url_scheme",
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
            if image.width * image.height > _MAX_IMAGE_PIXELS:
                raise service_validation_error(
                    "Image dimensions exceed the 40 megapixel limit.",
                    "image_dimensions_too_large",
                    maximum_megapixels=40,
                )
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
        raise integration_error(
            "Unable to load or process the selected image.",
            "image_processing_failed",
        ) from err

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
