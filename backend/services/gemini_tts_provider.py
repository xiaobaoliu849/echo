"""Google Gemini TTS provider (HTTP generateContent with AUDIO modality).

Supports:
- gemini-3.8-flash-tts (high fidelity, expressive narration, acting direction)
- gemini-3.8-flash-lite-tts (low latency, high throughput)
"""
from __future__ import annotations

import base64
import re
from typing import Any

import httpx

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"

GEMINI_TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]
DEFAULT_GEMINI_TTS_MODEL = "gemini-3.8-flash-tts"

# Curated prebuilt voices for Gemini TTS
GEMINI_TTS_VOICES = [
    {"name": "Kore", "short_name": "Kore (Gemini, Female)", "locale": "multi", "gender": "Female", "description": "清澈宁静女声，适合解说、播客与长文"},
    {"name": "Puck", "short_name": "Puck (Gemini, Male)", "locale": "multi", "gender": "Male", "description": "热情灵动男声，表现力丰富"},
    {"name": "Charon", "short_name": "Charon (Gemini, Male)", "locale": "multi", "gender": "Male", "description": "深沉稳重男声，适合正式叙述与新闻"},
    {"name": "Fenrir", "short_name": "Fenrir (Gemini, Male)", "locale": "multi", "gender": "Male", "description": "浑厚有力男声，适合影视与游戏配音"},
    {"name": "Aoede", "short_name": "Aoede (Gemini, Female)", "locale": "multi", "gender": "Female", "description": "温婉细腻女声，适合故事与对话"},
    {"name": "Leda", "short_name": "Leda (Gemini, Female)", "locale": "multi", "gender": "Female", "description": "亲切知性女声，适合助理与教学"},
    {"name": "Orus", "short_name": "Orus (Gemini, Male)", "locale": "multi", "gender": "Male", "description": "干练清晰男声，节奏适中"},
    {"name": "Zephyr", "short_name": "Zephyr (Gemini, Neutral)", "locale": "multi", "gender": "Neutral", "description": "柔和自然中性声，日常对话通用"},
]

DEFAULT_GEMINI_TTS_VOICE = GEMINI_TTS_VOICES[0]["name"]
_KNOWN_GEMINI_VOICE_NAMES = {v["name"].lower() for v in GEMINI_TTS_VOICES}


def is_gemini_voice(voice: str) -> bool:
    """Check if voice identifier belongs to Gemini (prebuilt or custom voice ID)."""
    if not voice:
        return False
    v = voice.strip()
    if not v:
        return False
    if v.lower() in _KNOWN_GEMINI_VOICE_NAMES:
        return True
    if v.startswith("voice_") or v.startswith("voicekey_"):
        return True
    return False


def gemini_headers(api_key: str) -> dict[str, str]:
    return {
        "x-goog-api-key": api_key.strip(),
        "Content-Type": "application/json",
    }


def _build_speech_config(voice: str) -> dict[str, Any]:
    v = voice.strip()
    if v.startswith("voice_") or v.startswith("voicekey_"):
        return {"voiceConfig": {"voice": v}}
    # Prebuilt voice
    matched_name = next(
        (cand["name"] for cand in GEMINI_TTS_VOICES if cand["name"].lower() == v.lower()),
        v or DEFAULT_GEMINI_TTS_VOICE,
    )
    return {
        "voiceConfig": {
            "prebuiltVoiceConfig": {
                "voiceName": matched_name
            }
        }
    }


async def gemini_tts_synthesize(
    text: str,
    voice: str,
    api_key: str,
    base_url: str = DEFAULT_GEMINI_BASE_URL,
    model: str = DEFAULT_GEMINI_TTS_MODEL,
    style: str | None = None,
) -> bytes:
    """Synthesize text into audio WAV bytes via Gemini generateContent."""
    if not api_key:
        raise ValueError("Missing Google Gemini API key.")
    if not text or not text.strip():
        raise ValueError("Input text is empty.")

    target_model = (model or DEFAULT_GEMINI_TTS_MODEL).strip()
    clean_voice = (voice or DEFAULT_GEMINI_TTS_VOICE).strip()

    part_obj: dict[str, Any] = {"text": text.strip()}
    if style and style.strip():
        part_obj["speech_metadata"] = {"style": style.strip()}

    payload: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [part_obj],
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": _build_speech_config(clean_voice),
        },
    }

    clean_base = base_url.rstrip("/")
    if clean_base.endswith("/v1beta"):
        clean_base = clean_base[:-7]
    elif clean_base.endswith("/v1"):
        clean_base = clean_base[:-3]
    clean_base = clean_base.rstrip("/")
    url = f"{clean_base}/v1beta/models/{target_model}:generateContent"
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=gemini_headers(api_key), json=payload)

    if response.status_code != 200:
        error_msg = response.text[:600]
        try:
            err_json = response.json()
            if isinstance(err_json, dict) and "error" in err_json:
                error_msg = err_json["error"].get("message") or error_msg
        except Exception:
            pass
        raise RuntimeError(f"Gemini TTS API error ({response.status_code}): {error_msg}")

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError("Gemini TTS returned invalid non-JSON response.") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini TTS response contained no candidates.")

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    for part in parts:
        inline = part.get("inline_data") or part.get("inlineData")
        if isinstance(inline, dict) and inline.get("data"):
            raw_b64 = inline["data"]
            return base64.b64decode(raw_b64)

    raise RuntimeError("Gemini TTS response did not contain inline audio data.")
