#!/usr/bin/env python3
import argparse
import base64
import io
from PIL import Image

def main():
    parser = argparse.ArgumentParser(
        description="Load an image, convert to black & white (Floyd–Steinberg dithering), and output as Base64-encoded PNG."
    )
    parser.add_argument(
        "input_path", 
        help="Path to the input image file (any format supported by Pillow)."
    )
    parser.add_argument(
        "--max-width", "-w",
        type=int,
        default=512,
        help="Maximum width in pixels; image will be resized proportionally."
    )
    args = parser.parse_args()

    # Open and convert to grayscale
    with Image.open(args.input_path) as img:
        # resize if exceeding max width
        if args.max_width is not None:
            orig_w, orig_h = img.size
            if orig_w > args.max_width:
                ratio = args.max_width / orig_w
                new_h = int(orig_h * ratio)
                img = img.resize((args.max_width, new_h), Image.LANCZOS)

        # convert to grayscale
        gray = img.convert("L")
        # Convert to 1-bit black & white using Floyd–Steinberg dithering
        bw = gray.convert("1", dither=Image.FLOYDSTEINBERG)

    # Save to PNG in-memory
    buf = io.BytesIO()
    bw.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    # Print data URI
    print(f"data:image/png;base64,{b64}")

if __name__ == "__main__":
    main()