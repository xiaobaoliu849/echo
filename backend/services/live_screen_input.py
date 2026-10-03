"""Bounded transient JPEG input; screen frames never enter the timeline store."""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
from typing import Any

from PIL import Image

MAX_SCREEN_FRAME_BYTES = 96 * 1024
MAX_SCREEN_FRAME_DIMENSION = 768


def decode_screen_frame(payload: dict[str, Any]) -> bytes:
    if payload.get("mime_type") != "image/jpeg":
        raise ValueError("Screen frames must be JPEG / 屏幕帧必须为 JPEG。")
    data = payload.get("data")
    if not isinstance(data, str) or not data or len(data) > MAX_SCREEN_FRAME_BYTES * 4 // 3:
        raise ValueError("Screen frame exceeds size limit or is empty / 屏幕帧过大或为空。")
    try:
        raw = base64.b64decode(data, validate=True)
        if len(raw) > MAX_SCREEN_FRAME_BYTES:
            raise ValueError("Screen frame exceeds size limit / 屏幕帧过大。")
        with Image.open(BytesIO(raw)) as image:
            if image.format != "JPEG" or max(image.size) > MAX_SCREEN_FRAME_DIMENSION:
                raise ValueError("Screen frames must be JPEG, at most 768 pixels per side / 屏幕帧必须为 JPEG，每边不超过 768 像素。")
            image.load()  # Decode only after dimensions are bounded; reject truncated JPEGs.
    except (binascii.Error, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid screen frame / 屏幕帧无效。") from exc
    return raw
