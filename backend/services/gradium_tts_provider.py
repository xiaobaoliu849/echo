"""Gradium TTS provider (HTTP bytes endpoint + voice catalog).

API reference: https://docs.gradium.ai/
Auth: `x-api-key: <key>` header.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

DEFAULT_GRADIUM_BASE_URL = "https://api.gradium.ai"

GRADIUM_MODELS = ["default"]
DEFAULT_GRADIUM_MODEL = "default"

# Static catalog of standard Gradium pre-built flagship voices
GRADIUM_VOICES = [
    {"name": "YTpq7expH9539ERJ", "short_name": "Emma (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "标准温和女声"},
    {"name": "3jUdJyOi9pgbxBTK", "short_name": "Arthur (en-US, Male)", "locale": "en-US", "gender": "Male", "description": "磁性成熟男声"},
    {"name": "2H4HY2CBNyJHBCrP", "short_name": "Christina (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "表现力充沛女声"},
    {"name": "KWJiFWu2O9nMPYcR", "short_name": "John (en-US, Male)", "locale": "en-US", "gender": "Male", "description": "沉稳专业男声"},
    {"name": "LFZvm12tW_z0xfGo", "short_name": "Kent (en-US, Male)", "locale": "en-US", "gender": "Male", "description": "青年活力男声"},
    {"name": "jtEKaLYNn6iif5PR", "short_name": "Sydney (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "清澈亲切女声"},
    {"name": "Eu9iL_CYe8N-Gkx_", "short_name": "Tiffany (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "热情灵动女声"},
    {"name": "NbpkqMVS3CJeq2j8", "short_name": "Zoey (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "活泼自信女声 (Gen Z)"},
    {"name": "YVzbrdWnnu9FgRn5", "short_name": "Sunnie (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "阳光明亮女声"},
    {"name": "Bla6SbVMczYnOhfK", "short_name": "Marlowe (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "热情爱笑女声"},
    {"name": "4SZHfMpw-p46Ywgs", "short_name": "Harper (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "现代干练女声"},
    {"name": "D6COLz20Hw7uh3UK", "short_name": "Brooklyn (en-US, Female)", "locale": "en-US", "gender": "Female", "description": "开朗亲和女声"},
    {"name": "6MFfc37kq0sBjBjy", "short_name": "Sterling (en-US, Male)", "locale": "en-US", "gender": "Male", "description": "戏剧感男声"},
    {"name": "_6Aslh2DxfmnRLmP", "short_name": "Russell (en-US, Male)", "locale": "en-US", "gender": "Male", "description": "高能量说服力男声"},
    {"name": "r2sIQdqqoqgRJuXw", "short_name": "Marcus (en-US, Male)", "locale": "en-US", "gender": "Male", "description": "高能量共鸣男声"},
]

DEFAULT_GRADIUM_VOICE = GRADIUM_VOICES[0]["name"]

_KNOWN_GRADIUM_VOICE_IDS = {v["name"] for v in GRADIUM_VOICES}
_GRADIUM_VOICE_ID_RE = re.compile(r"^[0-9a-zA-Z_\-]{14,24}$")


def is_gradium_voice(voice: str) -> bool:
    """Check if a voice identifier belongs to Gradium."""
    if not voice:
        return False
    v = voice.strip()
    return v in _KNOWN_GRADIUM_VOICE_IDS or bool(_GRADIUM_VOICE_ID_RE.match(v))


def gradium_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }


async def gradium_tts_synthesize(
    text: str,
    voice_id: str,
    api_key: str,
    base_url: str = DEFAULT_GRADIUM_BASE_URL,
    model: str = DEFAULT_GRADIUM_MODEL,
    output_format: str = "wav",
) -> bytes:
    """Non-streaming synthesis via POST /api/post/speech/tts (raw audio bytes)."""
    payload: dict[str, Any] = {
        "text": text,
        "voice_id": voice_id or DEFAULT_GRADIUM_VOICE,
        "model_name": model or DEFAULT_GRADIUM_MODEL,
        "output_format": output_format,
        "only_audio": True,
    }
    url = f"{base_url.rstrip('/')}/api/post/speech/tts"
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        response = await client.post(url, headers=gradium_headers(api_key), json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Gradium TTS API error: {response.status_code} - {response.text}")
    if not response.content:
        raise RuntimeError("Gradium TTS returned no audio data.")
    return response.content


async def fetch_gradium_voices(
    api_key: str,
    base_url: str = DEFAULT_GRADIUM_BASE_URL,
) -> list[dict[str, Any]]:
    """Fetch custom cloned voices from Gradium /api/voices and combine with built-ins."""
    url = f"{base_url.rstrip('/')}/api/voices"
    headers = gradium_headers(api_key)
    headers.pop("Content-Type", None)

    voices: list[dict[str, Any]] = []
    # Start with standard built-ins
    seen_ids = set()
    for v in GRADIUM_VOICES:
        voices.append(dict(v))
        seen_ids.add(v["name"])

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        voice_id = str(item.get("voice_id") or item.get("id") or "").strip()
                        if not voice_id or voice_id in seen_ids:
                            continue
                        name = str(item.get("name") or voice_id[:8])
                        gender = str(item.get("gender") or "Neutral")
                        language = str(item.get("language") or "en")
                        voices.append({
                            "name": voice_id,
                            "short_name": f"{name} (Gradium)",
                            "locale": language,
                            "gender": gender,
                        })
                        seen_ids.add(voice_id)
    except Exception:
        pass

    return voices
