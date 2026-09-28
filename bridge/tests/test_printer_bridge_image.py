"""Tests for the bridge's direct Bixolon image-printing path."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from bridge import printer_bridge


class FakeCFunction:
    """Callable ctypes-function stand-in that records assigned signatures."""

    def __init__(self, return_value: int = 0, *, capture_image: bool = False) -> None:
        self.return_value = return_value
        self.capture_image = capture_image
        self.calls: list[tuple[object, ...]] = []
        self.image_metadata: list[tuple[str | None, str, tuple[int, int]]] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        if self.capture_image:
            with Image.open(args[0].decode()) as image:
                self.image_metadata.append((image.format, image.mode, image.size))
        return self.return_value


class FakeBixolonLibrary:
    """Minimal SDK double used for image-path binding and execution tests."""

    def __init__(self, print_image_result: int = 0) -> None:
        self.ConnectToPrinter = FakeCFunction()
        self.DisconnectPrinter = FakeCFunction()
        self.PrintText = FakeCFunction()
        self.LineFeed = FakeCFunction()
        self.PartialCut = FakeCFunction()
        self.SetLeftMargin = FakeCFunction()
        self.SetCharSet = FakeCFunction()
        self.PrintBarcode = FakeCFunction()
        self.PrintImage = FakeCFunction(print_image_result, capture_image=True)


@pytest.fixture
def printer(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[printer_bridge.BixolonPrinter, FakeBixolonLibrary]:
    """Create a bridge printer with an in-memory native SDK double."""
    library = FakeBixolonLibrary()
    monkeypatch.setattr(printer_bridge, "CDLL", lambda *_args, **_kwargs: library)
    return printer_bridge.BixolonPrinter(), library


def _png_content() -> str:
    """Build a tiny PNG as a raw Base64 payload."""
    image = Image.new("RGB", (3, 2), color="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_print_image_binds_the_direct_sdk_function(printer):
    """PrintImage must use the types declared by the Bixolon Linux SDK."""
    _printer, library = printer

    assert library.PrintImage.argtypes == [
        printer_bridge.c_char_p,
        printer_bridge.c_bool,
        printer_bridge.c_uint,
    ]
    assert library.PrintImage.restype is printer_bridge.c_int


def test_connect_configures_the_printer_for_windows_1252(printer):
    """The printer and outgoing text bytes must use the same code page."""
    bridge_printer, library = printer

    bridge_printer.connect()

    assert library.SetCharSet.argtypes == [printer_bridge.c_uint]
    assert library.SetCharSet.restype is printer_bridge.c_int
    assert library.SetCharSet.calls == [(bridge_printer._CHARSET_WPC1252,)]


def test_text_uses_windows_1252_and_omits_unsupported_characters(printer):
    """Western European punctuation prints correctly while emoji are skipped."""
    bridge_printer, library = printer

    bridge_printer._txt("Grüße ·🙂©️1️⃣")

    assert library.PrintText.calls[0][0] == b"Gr\xfc\xdfe \xb7"


def test_print_image_uses_a_temporary_bmp_and_requested_alignment(printer):
    """The direct SDK call receives a readable BMP and Bixolon alignment value."""
    bridge_printer, library = printer

    bridge_printer._print_image(
        {"content": _png_content(), "alignment": "right"}, paper_w=80
    )

    assert len(library.PrintImage.calls) == 1
    image_path, compress, alignment = library.PrintImage.calls[0]
    assert compress is False
    assert alignment.value == bridge_printer._ALIGN["right"]
    assert library.PrintImage.image_metadata == [("BMP", "RGB", (3, 2))]
    assert not Path(image_path.decode()).exists()


def test_print_image_includes_the_sdk_error_code(printer):
    """SDK errors must remain actionable in the bridge acknowledgement and log."""
    bridge_printer, library = printer
    library.PrintImage.return_value = -118

    with pytest.raises(
        RuntimeError,
        match=r"PrintImage failed: IMAGE_OPEN_ERROR \(code -118\)",
    ):
        bridge_printer._print_image({"content": _png_content()}, paper_w=80)

    assert len(library.PrintImage.calls) == 1
    image_path = library.PrintImage.calls[0][0]
    assert not Path(image_path.decode()).exists()


def test_text_is_flushed_before_a_following_image(printer):
    """Direct image rendering must not discard text buffered by the SDK."""
    bridge_printer, library = printer

    failures = bridge_printer.execute_job(
        {
            "message": [
                {"type": "text", "content": "before image"},
                {"type": "image", "content": _png_content()},
            ],
            "feed_after": 0,
        }
    )

    assert failures == []
    assert [call[0].value for call in library.LineFeed.calls] == [1, 0]
    assert len(library.PrintImage.calls) == 1
