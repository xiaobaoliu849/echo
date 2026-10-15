"""Operator-set renewal instructions shown on the hosted "My account" page.

Stored as a small JSON file in the data directory: free text (prices,
WeChat ID, ...) plus an optional payment QR code as a ``data:`` URL, so the
whole thing travels as JSON to the browser and to community clients.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .config_loader import get_data_file_path

MAX_TEXT_LENGTH = 1000
MAX_QR_BYTES = 1_500_000  # length of the data URL, ~1.1 MB image
_QR_RE = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$")

FILENAME = "hosted_renewal.json"


def _path() -> Path:
    return get_data_file_path(FILENAME)


def load() -> dict[str, str]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"text": "", "qr": ""}
    if not isinstance(data, dict):
        return {"text": "", "qr": ""}
    return {"text": str(data.get("text") or ""), "qr": str(data.get("qr") or "")}


def save(*, text: str, qr: str) -> dict[str, str]:
    text = str(text or "").strip()
    qr = str(qr or "").strip()
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"说明文字最多 {MAX_TEXT_LENGTH} 字。")
    if qr and (len(qr) > MAX_QR_BYTES or not _QR_RE.match(qr)):
        raise ValueError("收款码必须是 1MB 以内的 PNG/JPG/WebP/GIF 图片。")
    value: dict[str, Any] = {"text": text, "qr": qr}
    target = _path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return {"text": text, "qr": qr}
