"""Regenerate resources/icons/logo.png and logo.ico from the in-app brand spec.

The desktop icon and the sidebar brand tile must be pixel-identical in
color, so both derive from one source: the gradient of `.vsBrandIcon` in
frontend/src/styles.css and the soundwave glyph of `brandMark` in
frontend/src/components/AppSidebar.tsx. Keep the constants below in sync
with those two places when the brand changes.

Run with the packaging environment: python scripts/generate_icon.py
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "resources" / "icons"

# .vsBrandIcon background: linear-gradient(160deg, oklch(0.611 0.028 161), oklch(0.52 0.027 161))
GRADIENT_TOP = (0x75, 0x89, 0x7E)
GRADIENT_BOTTOM = (0x5C, 0x6E, 0x64)
# .vsBrandIcon color: white (soundwave glyph)
GLYPH = (255, 255, 255)
# .vsBrandIcon border-radius: 14px on a 40px tile; the glyph geometry is
# brandMark's 24x24 viewBox: bars at x=4/8/12/16/20, heights 4/12/18/12/4,
# stroke-width 2.4 with round caps.
CORNER_RADIUS_RATIO = 14 / 40
BARS = ((4, 4), (8, 12), (12, 18), (16, 12), (20, 4))
STROKE_WIDTH = 2.4
VIEWBOX = 24
# CSS linear-gradient(160deg): 0deg points up, clockwise; the axis unit
# vector in screen coordinates (x right, y down).
AXIS = (math.sin(math.radians(160)), -math.cos(math.radians(160)))

SUPERSAMPLE = 4096
ICO_SIZES = (16, 32, 48, 64, 128, 256)


def render(size: int) -> Image.Image:
    ux, uy = AXIS
    corners = [x * ux + y * uy for x in (0.0, size) for y in (0.0, size)]
    lo, hi = min(corners), max(corners)
    xs, ys = np.meshgrid(np.arange(size), np.arange(size))
    t = (xs * ux + ys * uy - lo) / (hi - lo)
    top = np.array(GRADIENT_TOP, dtype=float)
    bottom = np.array(GRADIENT_BOTTOM, dtype=float)
    rgb = np.round(top + (bottom - top) * t[..., None]).astype(np.uint8)
    img = Image.fromarray(np.dstack([rgb, np.full((size, size), 255, np.uint8)]), "RGBA")
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size * CORNER_RADIUS_RATIO, fill=255)
    img.putalpha(mask)
    draw = ImageDraw.Draw(img)
    stroke = STROKE_WIDTH / VIEWBOX * size
    for cx, height in BARS:
        x = cx / VIEWBOX * size
        h = height / VIEWBOX * size
        draw.rounded_rectangle(
            [x - stroke / 2, size / 2 - h / 2, x + stroke / 2, size / 2 + h / 2],
            radius=stroke / 2,
            fill=GLYPH + (255,),
        )
    return img


def main() -> None:
    master = render(SUPERSAMPLE)
    png = master.resize((512, 512), Image.LANCZOS)
    png.save(OUT_DIR / "logo.png")
    # ICO frames are produced via `sizes`; append_images is silently
    # ignored by Pillow's ICO writer.
    master.resize((256, 256), Image.LANCZOS).save(
        OUT_DIR / "logo.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES]
    )
    print(f"Wrote {OUT_DIR / 'logo.png'} and logo.ico {ICO_SIZES} from the in-app brand spec")


if __name__ == "__main__":
    main()
