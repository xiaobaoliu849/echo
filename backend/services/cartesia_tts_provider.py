"""Cartesia Sonic TTS provider (HTTP bytes endpoint + voice catalog).

API reference: https://docs.cartesia.ai/api-reference/tts/bytes
Auth: `Authorization: Bearer <key>` + `Cartesia-Version` header.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

CARTESIA_VERSION = "2026-08-14"
DEFAULT_CARTESIA_BASE_URL = "https://api.cartesia.ai"

# sonic-preview is the Sonic 3.6 beta track (44 languages incl. zh);
# sonic-3.5 is the current stable model.
CARTESIA_MODELS = ["sonic-preview", "sonic-3.5", "sonic-3"]
DEFAULT_CARTESIA_MODEL = "sonic-preview"

# Static fallback catalog (recommended voice-agent voices from the docs).
# The live catalog is fetched from GET /voices when an API key is configured.
CARTESIA_VOICES = [
    {"name": "f786b574-daa5-4673-aa0c-cbe3e8534c02", "short_name": "Katie (en-US)", "locale": "en-US", "gender": "Female"},
    {"name": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4", "short_name": "Skylar (en-US)", "locale": "en-US", "gender": "Female"},
    {"name": "a5136bf9-224c-4d76-b823-52bd5efcffcc", "short_name": "Jameson (en-US)", "locale": "en-US", "gender": "Male"},
    {"name": "62ae83ad-4f6a-430b-af41-a9bede9286ca", "short_name": "Gemma (en-GB)", "locale": "en-GB", "gender": "Female"},
    {"name": "ef191366-f52f-447a-a398-ed8c0f2943a1", "short_name": "Archie (en-GB)", "locale": "en-GB", "gender": "Male"},
]

DEFAULT_CARTESIA_VOICE = CARTESIA_VOICES[0]["name"]

_CARTESIA_VOICE_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_CARTESIA_GENDER_MAP = {
    "masculine": "Male",
    "feminine": "Female",
    "gender_neutral": "Neutral",
}


def is_cartesia_voice(voice: str) -> bool:
    """Cartesia voice IDs are UUIDs."""
    return bool(voice) and bool(_CARTESIA_VOICE_ID_RE.match(voice.strip()))


def infer_cartesia_language(text: str) -> str:
    """Pick the base ISO language code for a transcript (zh for CJK, else en)."""
    if re.search(r"[一-鿿]", text):
        return "zh"
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    if re.search(r"[가-힯]", text):
        return "ko"
    return "en"


def cartesia_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Cartesia-Version": CARTESIA_VERSION,
        "Content-Type": "application/json",
    }


async def cartesia_tts_synthesize(
    text: str,
    voice_id: str,
    api_key: str,
    base_url: str = DEFAULT_CARTESIA_BASE_URL,
    model: str = DEFAULT_CARTESIA_MODEL,
    language: str | None = None,
) -> bytes:
    """Non-streaming synthesis via POST /tts/bytes (mp3 container)."""
    payload: dict[str, Any] = {
        "model_id": model,
        "transcript": text,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {
            "container": "mp3",
            "encoding": "pcm_s16le",
            "sample_rate": 44100,
        },
        "language": language or infer_cartesia_language(text),
    }
    url = f"{base_url.rstrip('/')}/tts/bytes"
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=cartesia_headers(api_key), json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Cartesia TTS API error: {response.status_code} - {response.text}")
    if not response.content:
        raise RuntimeError("Cartesia TTS returned no audio data.")
    return response.content


async def fetch_cartesia_voices(
    api_key: str,
    base_url: str = DEFAULT_CARTESIA_BASE_URL,
) -> list[dict[str, Any]]:
    """Fetch the full voice catalog (paginated) and normalize to VoiceSpirit shape."""
    url = f"{base_url.rstrip('/')}/voices"
    headers = cartesia_headers(api_key)
    headers.pop("Content-Type", None)

    voices: list[dict[str, Any]] = []
    params: dict[str, Any] = {"limit": 100}
    async with httpx.AsyncClient(timeout=15.0) as client:
        for _ in range(10):  # hard cap on pagination loops
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                break
            data = response.json()
            for v in data.get("data", []):
                voice_id = str(v.get("id", "")).strip()
                if not voice_id:
                    continue
                gender = _CARTESIA_GENDER_MAP.get(str(v.get("gender", "")).lower(), "Neutral")
                language = str(v.get("language", "") or "multi")
                name = str(v.get("name", "") or voice_id[:8])
                voices.append({
                    "name": voice_id,
                    "short_name": f"{name} (Cartesia)",
                    "locale": language,
                    "gender": gender,
                })
            if not data.get("has_more") or not data.get("next_page"):
                break
            params["starting_after"] = data["next_page"]
    return voices
