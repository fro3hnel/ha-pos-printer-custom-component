"""Deterministic monochrome charts for receipt printing."""

from __future__ import annotations

import base64
import io
from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .const import DEFAULT_PAPER_WIDTH, PAPER_WIDTH_TO_PIXELS


def _font(size: int) -> ImageFont.ImageFont:
    """Return a portable font that is available in every HA container."""
    return ImageFont.load_default(size=size)


def _point(item: Mapping[str, Any]) -> tuple[str, float]:
    """Normalize one chart point supplied by a service call."""
    label = str(item.get("label", item.get("time", ""))).strip()
    value = item.get("price", item.get("value"))
    if not label or isinstance(value, bool):
        raise ValueError("Every chart point needs a label and numeric price")
    try:
        return label, float(value)
    except (TypeError, ValueError) as err:
        raise ValueError("Every chart point needs a numeric price") from err


def render_price_chart(
    points: Sequence[Mapping[str, Any]], paper_width: int = DEFAULT_PAPER_WIDTH
) -> Image.Image:
    """Render price points as a clear, one-bit line chart."""
    normalized = [_point(item) for item in points]
    if len(normalized) < 2:
        raise ValueError("At least two chart points are required")
    if len(normalized) > 192:
        raise ValueError("At most 192 chart points are supported")

    width = PAPER_WIDTH_TO_PIXELS.get(
        paper_width, PAPER_WIDTH_TO_PIXELS[DEFAULT_PAPER_WIDTH]
    )
    height = 400
    left, right, top, bottom = 64, 18, 20, 54
    plot_width = width - left - right
    plot_height = height - top - bottom
    values = [value for _, value in normalized]
    low, high = min(values), max(values)
    span = high - low
    padding = max(span * 0.12, 0.25)
    low, high = low - padding, high + padding
    span = high - low

    image = Image.new("1", (width, height), color=1)
    draw = ImageDraw.Draw(image)
    small, normal = _font(12), _font(16)

    for row in range(5):
        y = top + round(plot_height * row / 4)
        value = high - span * row / 4
        draw.line((left, y, width - right, y), fill=0, width=1)
        draw.text((4, y - 6), f"{value:.1f}", fill=0, font=small)

    draw.line((left, top, left, height - bottom), fill=0, width=2)
    draw.line((left, height - bottom, width - right, height - bottom), fill=0, width=2)

    count = len(normalized)
    xy: list[tuple[int, int]] = []
    for index, (_, value) in enumerate(normalized):
        x = left + round(plot_width * index / (count - 1))
        y = top + round((high - value) * plot_height / span)
        xy.append((x, y))
    draw.line(xy, fill=0, width=3, joint="curve")
    for x, y in xy:
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=0)

    tick_step = max(1, ceil(count / 7))
    for index in range(0, count, tick_step):
        x = xy[index][0]
        draw.line((x, height - bottom, x, height - bottom + 5), fill=0, width=1)
        draw.text((x - 12, height - bottom + 10), normalized[index][0], fill=0, font=small)
    draw.text((left, height - 18), "Stunde", fill=0, font=normal)
    draw.text((width - 92, 2), "ct/kWh", fill=0, font=small)
    return image


def render_price_chart_data_uri(
    points: Sequence[Mapping[str, Any]], paper_width: int = DEFAULT_PAPER_WIDTH
) -> str:
    """Return a rendered price chart as a PNG data URI."""
    image = render_price_chart(points, paper_width)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{payload}"
