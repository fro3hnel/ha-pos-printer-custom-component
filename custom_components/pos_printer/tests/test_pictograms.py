"""Tests for deterministic receipt pictograms."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, ImageOps

from custom_components.pos_printer.const import PAPER_WIDTH_TO_PIXELS
from custom_components.pos_printer.pictograms import (
    MAX_PICTOGRAMS,
    PICTOGRAM_NAMES,
    render_pictogram,
    render_pictogram_data_uri,
    render_pictogram_sheet,
)


@pytest.mark.parametrize("name", PICTOGRAM_NAMES)
def test_every_pictogram_is_visible_and_bounded(name):
    """Every symbol should produce black pixels without touching its canvas edge."""
    image = render_pictogram(name)

    assert image.mode == "1"
    assert image.getextrema() == (0, 255)
    ink_bounds = ImageOps.invert(image.convert("L")).getbbox()
    assert ink_bounds is not None
    assert ink_bounds[0] > 0
    assert ink_bounds[1] > 0
    assert ink_bounds[2] < image.width
    assert ink_bounds[3] < image.height


@pytest.mark.parametrize(
    ("paper_width", "pictograms", "expected_rows"),
    [
        (53, ["t_shirt", "shorts", "sneakers"], 2),
        (80, ["long_sleeve", "trousers", "sweater", "light_jacket"], 2),
    ],
)
def test_sheet_uses_paper_width_grid(paper_width, pictograms, expected_rows):
    """Narrow paper should use two columns and wide paper three columns."""
    sheet = render_pictogram_sheet(pictograms, paper_width)

    assert sheet.mode == "1"
    assert sheet.width == PAPER_WIDTH_TO_PIXELS[paper_width]
    assert sheet.height > expected_rows * 100
    assert sheet.getextrema() == (0, 255)


def test_data_uri_contains_one_bit_png():
    """MQTT output should be a compact, decodable monochrome PNG."""
    data_uri = render_pictogram_data_uri(["raincoat", "rain_boots"], 80)
    header, encoded = data_uri.split(",", 1)

    assert header == "data:image/png;base64"
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        image.load()
        assert image.format == "PNG"
        assert image.mode == "1"
        assert image.width == PAPER_WIDTH_TO_PIXELS[80]


@pytest.mark.parametrize(
    "pictograms",
    [[], ["t_shirt"] * (MAX_PICTOGRAMS + 1)],
)
def test_sheet_rejects_invalid_item_counts(pictograms):
    """The renderer should retain the same count bounds as the action schema."""
    with pytest.raises(ValueError):
        render_pictogram_sheet(pictograms)


def test_renderer_rejects_unknown_name():
    """An unknown registry key should fail before a blank receipt is published."""
    with pytest.raises(ValueError, match="Unknown pictogram"):
        render_pictogram("not_registered")
