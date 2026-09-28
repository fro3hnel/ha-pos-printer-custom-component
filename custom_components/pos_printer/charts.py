"""Deterministic monochrome charts for receipt printing."""

from __future__ import annotations

import base64
import io
from collections.abc import Mapping, Sequence
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
    """Render future price points as a tall, one-bit horizontal bar chart."""
    normalized = [_point(item) for item in points]
    if len(normalized) < 2:
        raise ValueError("At least two chart points are required")
    if len(normalized) > 192:
        raise ValueError("At most 192 chart points are supported")

    width = PAPER_WIDTH_TO_PIXELS.get(
        paper_width, PAPER_WIDTH_TO_PIXELS[DEFAULT_PAPER_WIDTH]
    )
    # Receipt paper has effectively unlimited length.  Put time on the long
    # axis so that every 15-minute price interval gets its own readable row.
    row_height = 13
    left, right, top, bottom = 78, 18, 30, 30
    height = top + bottom + len(normalized) * row_height
    plot_width = width - left - right
    values = [value for _, value in normalized]
    low, high = min(0.0, min(values)), max(0.0, max(values))
    span = high - low or 1.0

    image = Image.new("1", (width, height), color=1)
    draw = ImageDraw.Draw(image)
    small, normal = _font(12), _font(16)

    def x_for(value: float) -> int:
        return left + round((value - low) * plot_width / span)

    # Price grid runs across the paper; labels only need a few decimal values.
    for column in range(5):
        value = low + span * column / 4
        x = x_for(value)
        draw.line((x, top, x, height - bottom), fill=0, width=1)
        label = f"{value:.1f}"
        label_box = draw.textbbox((0, 0), label, font=small)
        draw.text((x - (label_box[2] - label_box[0]) // 2, 4), label, fill=0, font=small)

    zero_x = x_for(0.0)
    draw.line((zero_x, top, zero_x, height - bottom), fill=0, width=2)
    draw.text((left, 18), "ct/kWh", fill=0, font=normal)

    for index, (label, value) in enumerate(normalized):
        y = top + index * row_height
        bar_end = x_for(value)
        draw.rectangle(
            (min(zero_x, bar_end), y + 2, max(zero_x, bar_end), y + row_height - 3),
            fill=0,
        )
        # Hour labels are retained, quarter-hour labels fill the remaining rows.
        draw.text((2, y + 1), label, fill=0, font=small)

    draw.line((left, top, left, height - bottom), fill=0, width=1)
    draw.line((left, height - bottom, width - right, height - bottom), fill=0, width=1)
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
