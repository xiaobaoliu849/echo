"""Gemini 3.8 speech through Vercel AI Gateway's speech-model endpoint."""

from __future__ import annotations

import base64
import binascii
import re

import httpx

from .gemini_tts_provider import DEFAULT_GEMINI_TTS_VOICE, GEMINI_TTS_VOICES

DEFAULT_VERCEL_GEMINI_TTS_MODEL = "google/gemini-3.8-flash-tts"
VERCEL_GEMINI_TTS_MODELS = (
    DEFAULT_VERCEL_GEMINI_TTS_MODEL,
    "google/gemini-3.8-flash-lite-tts",
)
DEFAULT_VERCEL_GEMINI_TTS_BASE_URL = "https://ai-gateway.vercel.sh"


def _speech_url(base_url: str) -> str:
    base = (base_url or DEFAULT_VERCEL_GEMINI_TTS_BASE_URL).strip().rstrip("/")
    for suffix in ("/v4/ai/speech-model", "/v4/ai", "/v4", "/v1"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if not base.startswith(("https://", "http://")):
        raise ValueError("Invalid Vercel AI Gateway base URL.")
    return f"{base}/v4/ai/speech-model"


def _pace_instructions(rate: str) -> str | None:
    """Translate Echo's percent rate into the gateway's supported instructions."""
    match = re.fullmatch(r"([+-]?)(\d{1,3})%", rate.strip())
    if not match:
        raise ValueError("Invalid TTS rate. Use a percentage such as +20% or -10%.")
    magnitude = int(match.group(2))
    direction = match.group(1) or "+"
    if magnitude > 90:
        raise ValueError("Vercel Gemini TTS rate must be between -90% and +90%.")
    if not magnitude:
        return None
    adjective = "faster" if direction == "+" else "slower"
    return f"Speak approximately {magnitude}% {adjective} than a normal conversational pace."


async def vercel_gemini_tts_synthesize(
    text: str,
    voice: str,
    api_key: str,
    base_url: str = DEFAULT_VERCEL_GEMINI_TTS_BASE_URL,
    model: str = DEFAULT_VERCEL_GEMINI_TTS_MODEL,
    rate: str = "+0%",
) -> bytes:
    """Return a complete WAV file; the gateway includes the RIFF header."""
    if not api_key or not api_key.strip():
        raise ValueError("Missing Vercel AI Gateway API key.")
    if not text or not text.strip():
        raise ValueError("Input text is empty.")
    if model not in VERCEL_GEMINI_TTS_MODELS:
        raise ValueError(f"Unsupported Vercel Gemini TTS model: {model}")

    voice_names = {item["name"].lower(): item["name"] for item in GEMINI_TTS_VOICES}
    selected_voice = voice_names.get((voice or DEFAULT_GEMINI_TTS_VOICE).strip().lower())
    if selected_voice is None:
        raise ValueError(f"Unsupported Vercel Gemini TTS voice: {voice}")

    instructions = _pace_instructions(rate)
    payload = {"text": text.strip(), "voice": selected_voice, "outputFormat": "wav"}
    if instructions:
        payload["instructions"] = instructions

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "ai-gateway-protocol-version": "0.0.1",
        "ai-speech-model-specification-version": "4",
        "ai-model-id": model,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            _speech_url(base_url),
            headers=headers,
            json=payload,
        )

    if response.status_code != 200:
        try:
            error = response.json()
            detail = error.get("error", error) if isinstance(error, dict) else None
            message = detail.get("message") if isinstance(detail, dict) else None
        except ValueError:
            message = None
        raise RuntimeError(f"Vercel Gemini TTS failed ({response.status_code}): {message or response.reason_phrase}")

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Vercel Gemini TTS returned invalid JSON.") from exc
    encoded = data.get("audio") if isinstance(data, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("Vercel Gemini TTS returned no audio.")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("Vercel Gemini TTS returned invalid audio encoding.") from exc
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise RuntimeError("Vercel Gemini TTS returned invalid WAV audio.")
    return audio
