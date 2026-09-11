"""Regenerate resources/icons/logo.png and logo.ico from the in-app brand spec.

The desktop icon and the sidebar brand tile must be pixel-identical in
color, so both derive from one source: the gradient of `.vsBrandIcon` in
frontend/src/styles.css and the soundwave glyph of `brandMark` in
frontend/src/components/AppSidebar.tsx. Keep the constants below in sync
with those two places when the brand changes.

Run with the packaging environment: python scripts/generate_icon.py

The NSIS sidebar BMP is wired in electron/electron-builder.yml as
nsis.installerSidebar / uninstallerSidebar.
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

# NSIS assisted-installer sidebar (electron-builder `installerSidebar`).
SIDEBAR_SIZE = (164, 314)
SIDEBAR_PATH = ROOT / "resources" / "installer" / "sidebar.bmp"
SIDEBAR_BOTTOM = (0x4B, 0x5D, 0x53)  # slightly deeper than the icon for depth


def render_sidebar() -> Image.Image:
    """Branded NSIS sidebar: vertical sage gradient, white glyph, app name."""
    width, height = SIDEBAR_SIZE
    scale = 4
    w, h = width * scale, height * scale
    top = np.array(GRADIENT_TOP, dtype=float)
    bottom = np.array(SIDEBAR_BOTTOM, dtype=float)
    t = np.linspace(0.0, 1.0, h)[:, None, None]
    rgb = np.round(top + (bottom - top) * t).astype(np.uint8)
    img = Image.fromarray(np.broadcast_to(rgb, (h, w, 3)).copy(), "RGB")
    draw = ImageDraw.Draw(img)
    # Glyph box: 60% of the panel width, centered at a quarter of the height.
    glyph = w * 0.6
    stroke = STROKE_WIDTH / VIEWBOX * glyph
    cx0, cy0 = w / 2, h * 0.25
    for cx, bar_h in BARS:
        x = cx0 + (cx - 12) / VIEWBOX * glyph
        hh = bar_h / VIEWBOX * glyph
        draw.rounded_rectangle(
            [x - stroke / 2, cy0 - hh / 2, x + stroke / 2, cy0 + hh / 2],
            radius=stroke / 2,
            fill=GLYPH,
        )
    try:
        from PIL import ImageFont

        name_font = ImageFont.truetype("segoeuib.ttf", int(h * 0.105))
        tag_font = ImageFont.truetype("msyh.ttc", int(h * 0.048))
    except OSError:  # fonts missing on a non-Windows builder: skip text
        return img.resize(SIDEBAR_SIZE, Image.LANCZOS)
    for text, font, y in (("Echo", name_font, h * 0.44), ("AI 语音助手", tag_font, h * 0.58)):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((w - (box[2] - box[0])) / 2 - box[0], y), text, font=font, fill=GLYPH)
    return img.resize(SIDEBAR_SIZE, Image.LANCZOS)



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
    SIDEBAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    render_sidebar().save(SIDEBAR_PATH)
    print(f"Wrote {SIDEBAR_PATH} for the NSIS assisted installer")
    print(f"Wrote {OUT_DIR / 'logo.png'} and logo.ico {ICO_SIZES} from the in-app brand spec")


if __name__ == "__main__":
    main()
