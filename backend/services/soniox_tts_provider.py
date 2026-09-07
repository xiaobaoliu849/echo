"""Soniox TTS provider (HTTP synthesis endpoint + voices catalog).

API reference:
- REST generation: https://tts-rt.soniox.com/tts
- Model & Voices catalog: https://api.soniox.com/v1/tts-models
- Custom Voices: https://api.soniox.com/v1/voices
Auth: `Authorization: Bearer <key>` header.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

DEFAULT_SONIOX_TTS_BASE_URL = "https://tts-rt.soniox.com"
DEFAULT_SONIOX_API_BASE_URL = "https://api.soniox.com/v1"

SONIOX_TTS_MODELS = ["tts-rt-v2"]
DEFAULT_SONIOX_TTS_MODEL = "tts-rt-v2"

# Static built-in catalog for Soniox tts-rt-v2 (curated flagship voices)
SONIOX_TTS_VOICES = [
    {"name": "Adrian", "short_name": "Adrian (Soniox, Male)", "locale": "multi", "gender": "Male", "description": "标准深沉男声，通用多语言"},
    {"name": "Daniel", "short_name": "Daniel (Soniox, Male)", "locale": "multi", "gender": "Male", "description": "亲切专业男声，适合播客与助手"},
    {"name": "Mina", "short_name": "Mina (Soniox, Female)", "locale": "multi", "gender": "Female", "description": "清亮自然女声，表现力丰富"},
    {"name": "Elena", "short_name": "Elena (Soniox, Female)", "locale": "multi", "gender": "Female", "description": "温和典雅女声，适合长文本朗读"},
    {"name": "Alex", "short_name": "Alex (Soniox, Neutral)", "locale": "multi", "gender": "Neutral", "description": "中性平稳，适合新闻与旁白"},
    {"name": "Sophia", "short_name": "Sophia (Soniox, Female)", "locale": "multi", "gender": "Female", "description": "活力明亮年轻女声"},
    {"name": "Marcus", "short_name": "Marcus (Soniox, Male)", "locale": "multi", "gender": "Male", "description": "饱满共鸣男声"},
    {"name": "Chloe", "short_name": "Chloe (Soniox, Female)", "locale": "multi", "gender": "Female", "description": "细腻温润女声"},
]

DEFAULT_SONIOX_TTS_VOICE = SONIOX_TTS_VOICES[0]["name"]

_KNOWN_SONIOX_VOICE_NAMES = {v["name"] for v in SONIOX_TTS_VOICES}


def is_soniox_voice(voice: str) -> bool:
    """Check if a voice identifier belongs to Soniox."""
    if not voice:
        return False
    v = voice.strip()
    if not v:
        return False
    if v in _KNOWN_SONIOX_VOICE_NAMES:
        return True
    return False


def soniox_tts_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def soniox_tts_synthesize(
    text: str,
    voice: str,
    api_key: str,
    base_url: str = DEFAULT_SONIOX_TTS_BASE_URL,
    model: str = DEFAULT_SONIOX_TTS_MODEL,
    speed: float = 1.0,
    audio_format: str = "mp3",
) -> bytes:
    """Non-streaming synthesis via POST https://tts-rt.soniox.com/tts (raw audio bytes)."""
    payload: dict[str, Any] = {
        "text": text,
        "voice": voice or DEFAULT_SONIOX_TTS_VOICE,
        "model": model or DEFAULT_SONIOX_TTS_MODEL,
        "speed": speed,
        "audio_format": audio_format,
    }
    url = f"{base_url.rstrip('/')}/tts"
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        response = await client.post(url, headers=soniox_tts_headers(api_key), json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Soniox TTS API error: {response.status_code} - {response.text}")
    if not response.content:
        raise RuntimeError("Soniox TTS returned no audio data.")
    return response.content


async def fetch_soniox_voices(
    api_key: str,
    api_base_url: str = DEFAULT_SONIOX_API_BASE_URL,
) -> list[dict[str, Any]]:
    """Fetch voices catalog from Soniox GET /tts-models and GET /voices."""
    voices: list[dict[str, Any]] = []
    seen_names = set()

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    # 1. Try querying /tts-models
    models_url = f"{api_base_url.rstrip('/')}/tts-models"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(models_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                models_list = data if isinstance(data, list) else data.get("models", [])
                for m in models_list:
                    model_voices = m.get("voices", [])
                    for v in model_voices:
                        v_id = str(v.get("id") or v.get("name") or "").strip()
                        if not v_id or v_id in seen_names:
                            continue
                        seen_names.add(v_id)
                        gender = str(v.get("gender") or "Neutral").capitalize()
                        desc = str(v.get("description") or "")
                        voices.append({
                            "name": v_id,
                            "short_name": f"{v_id} (Soniox, {gender})",
                            "locale": "multi",
                            "gender": gender,
                            "description": desc,
                        })
    except Exception:
        pass

    # 2. Try querying /voices (custom cloned voices)
    custom_url = f"{api_base_url.rstrip('/')}/voices"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(custom_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                v_list = data if isinstance(data, list) else data.get("voices", data.get("data", []))
                for v in v_list:
                    v_id = str(v.get("id") or v.get("name") or "").strip()
                    if not v_id or v_id in seen_names:
                        continue
                    seen_names.add(v_id)
                    gender = str(v.get("gender") or "Neutral").capitalize()
                    name = str(v.get("name") or v_id)
                    voices.append({
                        "name": v_id,
                        "short_name": f"{name} (Soniox Clone)",
                        "locale": "multi",
                        "gender": gender,
                        "description": "Soniox 自定义克隆音色",
                    })
    except Exception:
        pass

    if voices:
        for sv in SONIOX_TTS_VOICES:
            if sv["name"] not in seen_names:
                voices.append(dict(sv))
        return voices

    return [dict(v) for v in SONIOX_TTS_VOICES]
