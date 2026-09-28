"""Tests for receipt chart rendering."""

from PIL import Image

from custom_components.pos_printer.charts import render_price_chart


def test_price_chart_uses_one_row_per_interval() -> None:
    """Future quarter-hour prices render as a tall, monochrome bar chart."""
    points = [
        {"label": "12:15", "price": 1.2},
        {"label": "12:30", "price": 2.4},
        {"label": "12:45", "price": 0.8},
    ]

    image = render_price_chart(points, paper_width=80)

    assert isinstance(image, Image.Image)
    assert image.mode == "1"
    assert image.width == 576
    assert image.height == 99


def test_price_chart_supports_negative_prices() -> None:
    """The zero baseline makes both negative and positive prices printable."""
    image = render_price_chart(
        [{"label": "12:15", "price": -0.2}, {"label": "12:30", "price": 0.4}]
    )

    assert image.getbbox() is not None
