"""Deterministic monochrome pictograms for receipt printing."""

from __future__ import annotations

import base64
import io
from collections.abc import Callable, Sequence
from math import ceil

from PIL import Image, ImageDraw

from .const import DEFAULT_PAPER_WIDTH, PAPER_WIDTH_TO_PIXELS

MAX_PICTOGRAMS = 12

PICTOGRAM_NAMES = (
    "t_shirt",
    "long_sleeve",
    "shorts",
    "trousers",
    "sweater",
    "light_jacket",
    "winter_coat",
    "raincoat",
    "beanie",
    "gloves",
    "sneakers",
    "rain_boots",
    "winter_boots",
    "umbrella",
    "unknown",
)

_INK = 0
_PAPER = 255
_LOGICAL_SIZE = 100
_SHEET_MARGIN = 16
_CELL_GAP = 8


class _IconCanvas:
    """Draw normalized shapes on a square Pillow image."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.image = Image.new("L", (size, size), color=_PAPER)
        self.draw = ImageDraw.Draw(self.image)

    def _value(self, value: float) -> int:
        return round(value * self.size / _LOGICAL_SIZE)

    def _box(self, box: tuple[float, float, float, float]) -> tuple[int, ...]:
        return tuple(self._value(value) for value in box)

    def _points(self, points: Sequence[tuple[float, float]]) -> list[tuple[int, int]]:
        return [(self._value(x), self._value(y)) for x, y in points]

    @property
    def stroke(self) -> int:
        """Return a bold stroke that survives thermal-printer conversion."""
        return max(4, self._value(4))

    def polygon(
        self,
        points: Sequence[tuple[float, float]],
        *,
        fill: int = _PAPER,
        width: int | None = None,
    ) -> None:
        """Draw an outlined polygon."""
        self.draw.polygon(
            self._points(points),
            fill=fill,
            outline=_INK,
            width=width or self.stroke,
        )

    def line(
        self,
        points: Sequence[tuple[float, float]],
        *,
        width: int | None = None,
    ) -> None:
        """Draw a rounded polyline."""
        self.draw.line(
            self._points(points),
            fill=_INK,
            width=width or self.stroke,
            joint="curve",
        )

    def rectangle(
        self,
        box: tuple[float, float, float, float],
        *,
        fill: int = _PAPER,
        width: int | None = None,
    ) -> None:
        """Draw an outlined rectangle."""
        self.draw.rectangle(
            self._box(box),
            fill=fill,
            outline=_INK,
            width=width or self.stroke,
        )

    def rounded_rectangle(
        self,
        box: tuple[float, float, float, float],
        *,
        radius: float = 5,
        fill: int = _PAPER,
        width: int | None = None,
    ) -> None:
        """Draw an outlined rounded rectangle."""
        self.draw.rounded_rectangle(
            self._box(box),
            radius=self._value(radius),
            fill=fill,
            outline=_INK,
            width=width or self.stroke,
        )

    def ellipse(
        self,
        box: tuple[float, float, float, float],
        *,
        fill: int = _PAPER,
        width: int | None = None,
    ) -> None:
        """Draw an outlined ellipse."""
        self.draw.ellipse(
            self._box(box),
            fill=fill,
            outline=_INK,
            width=width or self.stroke,
        )

    def arc(
        self,
        box: tuple[float, float, float, float],
        start: int,
        end: int,
        *,
        width: int | None = None,
    ) -> None:
        """Draw an arc."""
        self.draw.arc(
            self._box(box),
            start=start,
            end=end,
            fill=_INK,
            width=width or self.stroke,
        )


def _draw_t_shirt(canvas: _IconCanvas) -> None:
    canvas.polygon(
        [
            (34, 18),
            (42, 14),
            (58, 14),
            (66, 18),
            (85, 30),
            (75, 45),
            (67, 40),
            (67, 86),
            (33, 86),
            (33, 40),
            (25, 45),
            (15, 30),
        ]
    )
    canvas.arc((40, 10, 60, 30), 0, 180)


def _draw_long_sleeve(canvas: _IconCanvas) -> None:
    canvas.polygon(
        [
            (35, 18),
            (43, 14),
            (57, 14),
            (65, 18),
            (77, 25),
            (92, 70),
            (79, 75),
            (67, 43),
            (67, 86),
            (33, 86),
            (33, 43),
            (21, 75),
            (8, 70),
            (23, 25),
        ]
    )
    canvas.arc((40, 10, 60, 30), 0, 180)
    canvas.line([(9, 66), (23, 70)])
    canvas.line([(77, 70), (91, 66)])


def _draw_shorts(canvas: _IconCanvas) -> None:
    canvas.polygon(
        [
            (23, 20),
            (77, 20),
            (74, 76),
            (54, 76),
            (50, 56),
            (46, 76),
            (26, 76),
        ]
    )
    canvas.line([(24, 31), (76, 31)])
    canvas.line([(50, 32), (50, 56)])
    canvas.line([(32, 39), (40, 44)])
    canvas.line([(68, 39), (60, 44)])


def _draw_trousers(canvas: _IconCanvas) -> None:
    canvas.polygon(
        [
            (25, 12),
            (75, 12),
            (70, 90),
            (52, 90),
            (50, 50),
            (48, 90),
            (30, 90),
        ]
    )
    canvas.line([(26, 24), (74, 24)])
    canvas.line([(50, 25), (50, 50)])
    canvas.line([(33, 32), (41, 37)])
    canvas.line([(67, 32), (59, 37)])


def _draw_sweater(canvas: _IconCanvas) -> None:
    _draw_long_sleeve(canvas)
    canvas.line([(34, 77), (66, 77)])
    canvas.line([(34, 83), (66, 83)], width=max(3, canvas.stroke - 1))
    canvas.line([(10, 63), (23, 68)], width=max(3, canvas.stroke - 1))
    canvas.line([(77, 68), (90, 63)], width=max(3, canvas.stroke - 1))


def _draw_light_jacket(canvas: _IconCanvas) -> None:
    _draw_long_sleeve(canvas)
    canvas.polygon([(40, 16), (50, 29), (60, 16), (57, 36), (50, 29), (43, 36)])
    canvas.line([(50, 29), (50, 86)])
    canvas.line([(38, 57), (46, 62)])
    canvas.line([(62, 57), (54, 62)])


def _draw_winter_coat(canvas: _IconCanvas) -> None:
    canvas.arc((35, 7, 65, 35), 180, 360)
    canvas.polygon(
        [
            (35, 20),
            (21, 27),
            (8, 69),
            (21, 74),
            (31, 45),
            (28, 91),
            (72, 91),
            (69, 45),
            (79, 74),
            (92, 69),
            (79, 27),
            (65, 20),
        ]
    )
    canvas.line([(50, 24), (50, 91)])
    for y in (43, 61, 78):
        canvas.line([(30, y), (70, y)], width=max(3, canvas.stroke - 1))


def _draw_raincoat(canvas: _IconCanvas) -> None:
    canvas.arc((35, 7, 65, 35), 180, 360)
    canvas.polygon(
        [
            (35, 21),
            (20, 27),
            (7, 67),
            (20, 73),
            (30, 45),
            (23, 89),
            (77, 89),
            (70, 45),
            (80, 73),
            (93, 67),
            (80, 27),
            (65, 21),
        ]
    )
    canvas.line([(50, 25), (50, 89)])
    canvas.line([(37, 58), (45, 64)])
    canvas.line([(63, 58), (55, 64)])


def _draw_beanie(canvas: _IconCanvas) -> None:
    canvas.ellipse((43, 8, 57, 22), fill=_INK)
    canvas.arc((20, 16, 80, 82), 180, 360, width=canvas.stroke + 2)
    canvas.rounded_rectangle((18, 49, 82, 73), radius=5)
    for x in (32, 44, 56, 68):
        canvas.line([(x, 52), (x, 70)], width=max(3, canvas.stroke - 1))


def _draw_gloves(canvas: _IconCanvas) -> None:
    canvas.polygon(
        [
            (16, 49),
            (20, 31),
            (27, 34),
            (27, 20),
            (34, 20),
            (35, 34),
            (40, 22),
            (46, 25),
            (43, 42),
            (50, 36),
            (55, 42),
            (45, 61),
            (25, 66),
        ]
    )
    canvas.polygon(
        [
            (84, 49),
            (80, 31),
            (73, 34),
            (73, 20),
            (66, 20),
            (65, 34),
            (60, 22),
            (54, 25),
            (57, 42),
            (50, 36),
            (45, 42),
            (55, 61),
            (75, 66),
        ]
    )
    canvas.line([(24, 66), (27, 78), (47, 73), (45, 61)])
    canvas.line([(76, 66), (73, 78), (53, 73), (55, 61)])


def _draw_sneakers(canvas: _IconCanvas) -> None:
    canvas.polygon(
        [
            (10, 57),
            (29, 53),
            (38, 31),
            (55, 41),
            (59, 55),
            (84, 64),
            (90, 76),
            (13, 76),
        ]
    )
    canvas.line([(14, 68), (87, 68)])
    canvas.line([(37, 43), (51, 48)])
    canvas.line([(34, 51), (53, 56)])


def _draw_rain_boots(canvas: _IconCanvas) -> None:
    canvas.polygon(
        [(18, 15), (48, 15), (45, 65), (55, 77), (54, 88), (12, 88), (18, 69)]
    )
    canvas.polygon(
        [(53, 15), (83, 15), (80, 65), (90, 77), (89, 88), (47, 88), (53, 69)]
    )
    canvas.line([(18, 29), (47, 29)])
    canvas.line([(53, 29), (82, 29)])


def _draw_winter_boots(canvas: _IconCanvas) -> None:
    _draw_rain_boots(canvas)
    canvas.line([(18, 23), (47, 23)], width=canvas.stroke + 2)
    canvas.line([(53, 23), (82, 23)], width=canvas.stroke + 2)
    for x in (25, 33, 40, 60, 67, 75):
        canvas.line([(x, 15), (x - 3, 25)], width=max(2, canvas.stroke - 2))


def _draw_umbrella(canvas: _IconCanvas) -> None:
    canvas.arc((10, 16, 90, 78), 180, 360, width=canvas.stroke + 2)
    canvas.line([(10, 47), (90, 47)])
    canvas.arc((10, 38, 38, 58), 180, 360)
    canvas.arc((36, 38, 64, 58), 180, 360)
    canvas.arc((62, 38, 90, 58), 180, 360)
    canvas.line([(50, 18), (50, 79)])
    canvas.arc((50, 66, 72, 91), 0, 180)


def _draw_unknown(canvas: _IconCanvas) -> None:
    canvas.ellipse((12, 12, 88, 88), width=canvas.stroke + 1)
    canvas.arc((32, 24, 68, 56), 190, 355, width=canvas.stroke + 2)
    canvas.line([(68, 40), (62, 50), (51, 58), (51, 66)], width=canvas.stroke + 2)
    canvas.ellipse((47, 72, 55, 80), fill=_INK, width=1)


_DRAWERS: dict[str, Callable[[_IconCanvas], None]] = {
    "t_shirt": _draw_t_shirt,
    "long_sleeve": _draw_long_sleeve,
    "shorts": _draw_shorts,
    "trousers": _draw_trousers,
    "sweater": _draw_sweater,
    "light_jacket": _draw_light_jacket,
    "winter_coat": _draw_winter_coat,
    "raincoat": _draw_raincoat,
    "beanie": _draw_beanie,
    "gloves": _draw_gloves,
    "sneakers": _draw_sneakers,
    "rain_boots": _draw_rain_boots,
    "winter_boots": _draw_winter_boots,
    "umbrella": _draw_umbrella,
    "unknown": _draw_unknown,
}


def render_pictogram(name: str, size: int = 160) -> Image.Image:
    """Render one registered pictogram as a one-bit square image."""
    try:
        drawer = _DRAWERS[name]
    except KeyError as err:
        raise ValueError(f"Unknown pictogram: {name}") from err

    canvas = _IconCanvas(size)
    drawer(canvas)
    return canvas.image.convert("1", dither=Image.Dither.NONE)


def render_pictogram_sheet(
    pictograms: Sequence[str], paper_width: int = DEFAULT_PAPER_WIDTH
) -> Image.Image:
    """Lay out pictograms in print order for a supported paper width."""
    if not pictograms:
        raise ValueError("At least one pictogram is required")
    if len(pictograms) > MAX_PICTOGRAMS:
        raise ValueError(f"At most {MAX_PICTOGRAMS} pictograms are supported")

    width = PAPER_WIDTH_TO_PIXELS.get(
        paper_width, PAPER_WIDTH_TO_PIXELS[DEFAULT_PAPER_WIDTH]
    )
    columns = 2 if paper_width == 53 else 3
    cell_size = (width - 2 * _SHEET_MARGIN - (columns - 1) * _CELL_GAP) // columns
    rows = ceil(len(pictograms) / columns)
    height = 2 * _SHEET_MARGIN + rows * cell_size + (rows - 1) * _CELL_GAP
    sheet = Image.new("1", (width, height), color=1)

    icon_size = cell_size - 12
    inset = (cell_size - icon_size) // 2
    for index, name in enumerate(pictograms):
        row, column = divmod(index, columns)
        left = _SHEET_MARGIN + column * (cell_size + _CELL_GAP) + inset
        top = _SHEET_MARGIN + row * (cell_size + _CELL_GAP) + inset
        sheet.paste(render_pictogram(name, icon_size), (left, top))

    return sheet


def render_pictogram_data_uri(
    pictograms: Sequence[str], paper_width: int = DEFAULT_PAPER_WIDTH
) -> str:
    """Render a pictogram sheet as a PNG data URI for the MQTT job."""
    sheet = render_pictogram_sheet(pictograms, paper_width)
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG", optimize=True)
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{payload}"
