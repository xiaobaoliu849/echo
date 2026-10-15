"""Regenerate the shared in-app, Electron, and Windows installer icon.

The brand gradient and glyph geometry below define the single icon used by
the frontend, Electron, the Windows executable, and the installer.

Run with Python 3.12, NumPy, and Pillow, for example:
    .packaging-venv/Scripts/python.exe scripts/generate_icon.py

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
FRONTEND_ICON_PATH = ROOT / "frontend" / "src" / "assets" / "echo-icon.png"
ELECTRON_ICON_PATH = ROOT / "electron" / "icon.png"

# Deep sage-green tile: saturated enough to hold up on a dark taskbar, a
# light wallpaper, and the cream app shell alike (the old #75897E→#5C6E64
# looked washed out next to the desktop).
GRADIENT_TOP = (0x3B, 0x80, 0x6A)
GRADIENT_BOTTOM = (0x1F, 0x4E, 0x40)
# White speech bubble holding a soundwave; the centre bar is warm amber.
BUBBLE = (255, 255, 255)
WAVE = GRADIENT_BOTTOM
ACCENT = (0xF2, 0xA0, 0x5A)
CORNER_RADIUS_RATIO = 14 / 40
# Geometry in units of the tile size.
BUBBLE_BOX = (0.17, 0.20, 0.83, 0.70)
BUBBLE_RADIUS = 0.32  # of the bubble height
# (x as a fraction of bubble width, y below the bubble edge as a fraction of
# the tile); the root starts inside the body so it meets the rounded corner
# without a notch.
TAIL = ((0.17, -0.09), (0.10, 0.117), (0.42, -0.02))
WAVE_CENTER_Y = 0.45
# (x offset, height) per bar; the full set and a bolder three-bar set for
# frames of 32px and below, where five thin bars blur together.
BARS = ((-0.166, 0.068), (-0.083, 0.156), (0.0, 0.234), (0.083, 0.156), (0.166, 0.068))
BAR_WIDTH = 0.049
SMALL_BARS = ((-0.12, 0.12), (0.0, 0.25), (0.12, 0.12))
SMALL_BAR_WIDTH = 0.085
SMALL_MAX = 32
# CSS linear-gradient(160deg): 0deg points up, clockwise; the axis unit
# vector in screen coordinates (x right, y down).
AXIS = (math.sin(math.radians(160)), -math.cos(math.radians(160)))

SUPERSAMPLE = 4096
ICO_SIZES = (16, 32, 48, 64, 128, 256)

# NSIS assisted-installer sidebar (electron-builder `installerSidebar`).
SIDEBAR_SIZE = (164, 314)
SIDEBAR_PATH = ROOT / "resources" / "installer" / "sidebar.bmp"
SIDEBAR_BOTTOM = GRADIENT_BOTTOM


def draw_mark(draw: ImageDraw.ImageDraw, x0: float, y0: float, size: float, small: bool = False) -> None:
    """Draw the bubble + soundwave into the square at (x0, y0) of side `size`."""
    bx0, by0, bx1, by1 = (v * size for v in BUBBLE_BOX)
    bx0, bx1, by0, by1 = bx0 + x0, bx1 + x0, by0 + y0, by1 + y0
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=(by1 - by0) * BUBBLE_RADIUS, fill=BUBBLE)
    width = bx1 - bx0
    draw.polygon([(bx0 + tx * width, by1 - 1 + ty * size) for tx, ty in TAIL], fill=BUBBLE)
    bars, bar_w = (SMALL_BARS, SMALL_BAR_WIDTH) if small else (BARS, BAR_WIDTH)
    cx, cy, w = x0 + size / 2, y0 + size * WAVE_CENTER_Y, bar_w * size
    for dx, h in bars:
        x, hh = cx + dx * size, h * size
        draw.rounded_rectangle(
            [x - w / 2, cy - hh / 2, x + w / 2, cy + hh / 2],
            radius=w / 2,
            fill=ACCENT if dx == 0 else WAVE,
        )


def render_sidebar() -> Image.Image:
    """Branded NSIS sidebar: vertical sage gradient, the mark, app name."""
    width, height = SIDEBAR_SIZE
    scale = 4
    w, h = width * scale, height * scale
    top = np.array(GRADIENT_TOP, dtype=float)
    bottom = np.array(SIDEBAR_BOTTOM, dtype=float)
    t = np.linspace(0.0, 1.0, h)[:, None, None]
    rgb = np.round(top + (bottom - top) * t).astype(np.uint8)
    img = Image.fromarray(np.broadcast_to(rgb, (h, w, 3)).copy(), "RGB")
    draw = ImageDraw.Draw(img)
    # Mark box: 70% of the panel width, centered at a quarter of the height.
    mark = w * 0.7
    draw_mark(draw, (w - mark) / 2, h * 0.25 - mark / 2, mark)
    try:
        from PIL import ImageFont

        name_font = ImageFont.truetype("segoeuib.ttf", int(h * 0.105))
        tag_font = ImageFont.truetype("msyh.ttc", int(h * 0.048))
    except OSError:  # fonts missing on a non-Windows builder: skip text
        return img.resize(SIDEBAR_SIZE, Image.LANCZOS)
    for text, font, y in (("Echo", name_font, h * 0.44), ("英语口语陪练", tag_font, h * 0.58)):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((w - (box[2] - box[0])) / 2 - box[0], y), text, font=font, fill=BUBBLE)
    return img.resize(SIDEBAR_SIZE, Image.LANCZOS)


def render(size: int, small: bool = False) -> Image.Image:
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
    draw_mark(ImageDraw.Draw(img), 0, 0, size, small)
    return img


def main() -> None:
    master = render(SUPERSAMPLE)
    png = master.resize((512, 512), Image.LANCZOS)
    for path in (OUT_DIR / "logo.png", FRONTEND_ICON_PATH, ELECTRON_ICON_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        png.save(path)
    # Pillow's ICO writer uses an appended image whose size matches a
    # requested frame instead of downscaling the first one; small frames get
    # the bolder three-bar glyph.
    small = render(SUPERSAMPLE, small=True)
    frames = [(small if s <= SMALL_MAX else master).resize((s, s), Image.LANCZOS) for s in ICO_SIZES]
    frames[-1].save(
        OUT_DIR / "logo.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )
    SIDEBAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    render_sidebar().save(SIDEBAR_PATH)
    print(f"Wrote {SIDEBAR_PATH} for the NSIS assisted installer")
    print(f"Wrote matching frontend, Electron, and Windows icons {ICO_SIZES}")


if __name__ == "__main__":
    main()
