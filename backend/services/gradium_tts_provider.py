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

# Static catalog of standard Gradium pre-built voices
GRADIUM_VOICES = [
    {"name": "YTpq7expH9539ERJ", "short_name": "Emma (en)", "locale": "en", "gender": "Female"},
    {"name": "3jUdJyOi9pgbxBTK", "short_name": "Arthur (en)", "locale": "en", "gender": "Male"},
    {"name": "2H4HY2CBNyJHBCrP", "short_name": "Christina (en)", "locale": "en", "gender": "Female"},
    {"name": "KWJiFWu2O9nMPYcR", "short_name": "John (en)", "locale": "en", "gender": "Male"},
    {"name": "LFZvm12tW_z0xfGo", "short_name": "Kent (en)", "locale": "en", "gender": "Male"},
    {"name": "jtEKaLYNn6iif5PR", "short_name": "Sydney (en)", "locale": "en", "gender": "Female"},
    {"name": "Eu9iL_CYe8N-Gkx_", "short_name": "Tiffany (en)", "locale": "en", "gender": "Female"},
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
