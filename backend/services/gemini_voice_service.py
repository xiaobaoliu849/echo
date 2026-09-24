"""Google Gemini voice design and voice replication (cloning) service.

API reference:
- Voice design: POST /v1beta/voices (type="prompted")
- Voice clone / replication: POST /v1beta/voices (type="replicated")
- List voices: GET /v1beta/voices
- Delete voice: DELETE /v1beta/voices/{voice_id}
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Literal

import httpx

from .config_loader import BackendConfig
from .gemini_tts_provider import (
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_TTS_MODEL,
    gemini_headers,
    gemini_tts_synthesize,
)

logger = logging.getLogger(__name__)

VoiceType = Literal["voice_design", "voice_clone"]

# Maximum number of retries for transient Gemini 500 errors.
_MAX_RETRIES = 2
_RETRY_DELAY_SECONDS = 1.5


def _normalize_to_gemini_wav(audio_bytes: bytes) -> tuple[bytes, str]:
    """Convert input audio to 24kHz 16-bit mono PCM WAV for Google Gemini voice replication.

    Raises ValueError on failure instead of silently returning un-normalized
    bytes, because sending non-WAV data with ``mime_type: audio/wav`` causes
    Google to return a cryptic 500 Internal Error.
    """
    if not audio_bytes:
        raise ValueError("Audio data is empty — nothing to normalize.")
    try:
        from pydub import AudioSegment
        import io
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
        seg = seg.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        out = io.BytesIO()
        seg.export(out, format="wav")
        return out.getvalue(), "audio/wav"
    except ImportError:
        raise ValueError(
            "pydub is not installed.  Audio normalization requires pydub and ffmpeg."
        )
    except Exception as exc:
        raise ValueError(
            f"Failed to normalize audio to 24 kHz WAV.  "
            f"Make sure ffmpeg is installed and the audio file is valid.  Detail: {exc}"
        ) from exc


class GeminiVoiceService:
    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig()

    def _get_credentials(self) -> tuple[str, str]:
        self.config.reload()
        settings = self.config.get_provider_settings("Google")
        api_key = (
            str(settings.get("api_key", "")).strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
            or os.environ.get("GEMINI_API_KEY", "").strip()
        )
        if not api_key:
            raise ValueError("Missing Google / Gemini API key. Please configure it in Settings.")
        base_url = str(settings.get("base_url", "")).strip().rstrip("/")
        if not base_url:
            base_url = DEFAULT_GEMINI_BASE_URL
        if base_url.endswith("/v1beta"):
            base_url = base_url[:-7]
        elif base_url.endswith("/v1"):
            base_url = base_url[:-3]
        base_url = base_url.rstrip("/")
        return api_key, base_url

    @staticmethod
    def _extract_error(response: httpx.Response) -> str:
        """Extract a human-readable error message from a Gemini API error response.

        The method tries to surface the most specific details available so users
        and server logs can identify the root cause instead of seeing a generic
        "Internal error encountered." message.
        """
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error_obj = payload.get("error", {})
                if isinstance(error_obj, dict):
                    msg = str(error_obj.get("message", "")).strip()
                    error_code = error_obj.get("code", "")
                    status = error_obj.get("status", "")
                    details = error_obj.get("details", [])
                    for d in details:
                        if isinstance(d, dict):
                            detail_str = str(d.get("detail", ""))
                            if "Consent flow failed" in detail_str:
                                return (
                                    "Consent flow failed: The consent audio did not match the required statement. "
                                    "Please recite: 'I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model.'"
                                )
                            if "Original error:" in detail_str:
                                orig = detail_str.split("Original error:")[1].strip().split("\n")[0]
                                if orig:
                                    return orig
                            # Surface INTERNAL: messages too — they contain useful detail.
                            if detail_str.strip():
                                return detail_str.strip().split("\n")[0]
                    # Build an enriched message from code + status + message.
                    parts = []
                    if status:
                        parts.append(f"[{status}]")
                    if msg:
                        parts.append(msg)
                    if parts:
                        return " ".join(parts)
                elif isinstance(error_obj, str) and error_obj.strip():
                    return error_obj.strip()
                if "detail" in payload:
                    return str(payload["detail"])
        except Exception:
            pass
        return response.text[:500]

    async def create_voice_design(
        self,
        *,
        voice_prompt: str,
        preview_text: str,
        preferred_name: str,
        language: str = "zh",
    ) -> dict[str, Any]:
        prompt = voice_prompt.strip()
        preview = preview_text.strip()
        preferred = preferred_name.strip()
        lang = language.strip() or "zh"

        if not prompt:
            raise ValueError("voice_prompt is required.")
        if not preview:
            raise ValueError("preview_text is required.")
        if not preferred:
            raise ValueError("preferred_name is required.")

        api_key, base_url = self._get_credentials()
        url = f"{base_url}/v1beta/voices"

        payload = {
            "store": True,
            "voice": {
                "model": DEFAULT_GEMINI_TTS_MODEL,
                "type": "prompted",
                "display_name": preferred,
                "prompted": {
                    "input": prompt,
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=gemini_headers(api_key), json=payload)
            if response.status_code not in (200, 201):
                raise RuntimeError(
                    f"Gemini voice design failed ({response.status_code}): {self._extract_error(response)}"
                )
            data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Gemini voice network error: {exc}") from exc

        if not isinstance(data, dict):
            raise RuntimeError("Gemini voice design returned invalid non-JSON response.")

        voice_id = (
            data.get("id")
            or data.get("voice_id")
            or (data.get("voice", {}).get("name") if isinstance(data.get("voice"), dict) else None)
            or data.get("name")
        )
        if not voice_id or not isinstance(voice_id, str):
            raise RuntimeError("Gemini voice design response missing voice identifier.")

        preview_audio_data = ""
        # Check if sample audio was provided in response
        sample_audio = data.get("sample_audio") or (
            data.get("voice", {}).get("sample_audio") if isinstance(data.get("voice"), dict) else None
        )
        if isinstance(sample_audio, dict) and sample_audio.get("data"):
            preview_audio_data = str(sample_audio["data"]).strip()
        elif isinstance(sample_audio, str) and sample_audio.strip():
            preview_audio_data = sample_audio.strip()
        else:
            # Generate preview audio on-the-fly using the created voice ID
            try:
                audio_bytes = await gemini_tts_synthesize(
                    text=preview,
                    voice=voice_id,
                    api_key=api_key,
                    base_url=base_url,
                    model=DEFAULT_GEMINI_TTS_MODEL,
                )
                preview_audio_data = base64.b64encode(audio_bytes).decode("ascii")
            except Exception:
                preview_audio_data = ""

        return {
            "voice": voice_id,
            "type": "voice_design",
            "target_model": DEFAULT_GEMINI_TTS_MODEL,
            "preferred_name": preferred,
            "language": lang,
            "preview_audio_data": preview_audio_data,
            "provider": "gemini",
        }

    async def create_voice_clone(
        self,
        *,
        audio_bytes: bytes,
        mime_type: str,
        preferred_name: str,
        consent_bytes: bytes | None = None,
        consent_mime_type: str | None = None,
    ) -> dict[str, Any]:
        import asyncio

        preferred = preferred_name.strip()
        if not preferred:
            raise ValueError("preferred_name is required.")
        if not audio_bytes:
            raise ValueError("audio file is empty.")

        api_key, base_url = self._get_credentials()

        # Google Gemini Voice Replication strictly requires 24kHz mono 16-bit PCM WAV.
        # _normalize_to_gemini_wav now raises ValueError on failure instead of
        # silently returning un-normalized bytes (which caused cryptic Google 500s).
        norm_source, _ = _normalize_to_gemini_wav(audio_bytes)
        source_b64 = base64.b64encode(norm_source).decode("ascii")

        # Normalize consent audio if provided separately, otherwise reuse source audio.
        # Note: Google requires the consent audio to clearly contain the verbal consent
        # phrase.  When a single recording contains both sample speech and the consent
        # statement, using the same audio for both fields is acceptable.
        if consent_bytes:
            norm_consent, _ = _normalize_to_gemini_wav(consent_bytes)
            consent_b64 = base64.b64encode(norm_consent).decode("ascii")
        else:
            consent_b64 = source_b64

        url = f"{base_url}/v1beta/voices"

        payload = {
            "store": True,
            "voice": {
                "type": "replicated",
                "display_name": preferred,
                "model": DEFAULT_GEMINI_TTS_MODEL,
                "replicated": {
                    "source_audio": {
                        "mime_type": "audio/wav",
                        "data": source_b64,
                    },
                    "consent_audio": {
                        "mime_type": "audio/wav",
                        "data": consent_b64,
                    },
                },
            },
        }

        # Retry transient 500 errors with exponential backoff.
        last_error: RuntimeError | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(url, headers=gemini_headers(api_key), json=payload)

                if response.status_code in (200, 201):
                    data = response.json()
                    break

                error_detail = self._extract_error(response)
                logger.warning(
                    "Gemini voice clone attempt %d/%d failed (HTTP %d): %s | raw=%s",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    response.status_code,
                    error_detail,
                    response.text[:800],
                )

                # Only retry on 5xx (server) errors; 4xx are client errors and won't resolve.
                if response.status_code < 500:
                    raise RuntimeError(
                        f"Gemini voice clone failed ({response.status_code}): {error_detail}"
                    )

                last_error = RuntimeError(
                    f"Gemini voice clone failed ({response.status_code}): {error_detail}"
                )
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAY_SECONDS * (2 ** attempt)
                    logger.info("Retrying Gemini voice clone in %.1fs…", delay)
                    await asyncio.sleep(delay)

            except httpx.HTTPError as exc:
                last_error = RuntimeError(f"Gemini voice network error: {exc}")
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAY_SECONDS * (2 ** attempt)
                    logger.info("Retrying after network error in %.1fs…", delay)
                    await asyncio.sleep(delay)
                else:
                    raise last_error from exc
        else:
            # All retries exhausted
            raise last_error  # type: ignore[misc]

        if not isinstance(data, dict):
            raise RuntimeError("Gemini voice clone returned invalid non-JSON response.")

        voice_id = (
            data.get("id")
            or data.get("voice_id")
            or (data.get("voice", {}).get("name") if isinstance(data.get("voice"), dict) else None)
            or data.get("name")
            or data.get("voice_key")
        )
        if not voice_id or not isinstance(voice_id, str):
            raise RuntimeError("Gemini voice clone response missing voice identifier.")

        return {
            "voice": voice_id,
            "type": "voice_clone",
            "target_model": DEFAULT_GEMINI_TTS_MODEL,
            "preferred_name": preferred,
            "provider": "gemini",
        }

    async def list_voices(
        self,
        voice_type: VoiceType = "voice_design",
        page_index: int = 0,
        page_size: int = 100,
    ) -> dict[str, Any]:
        api_key, base_url = self._get_credentials()
        url = f"{base_url}/v1beta/voices"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url, headers=gemini_headers(api_key))
            if response.status_code != 200:
                raise RuntimeError(
                    f"Gemini voice list failed ({response.status_code}): {self._extract_error(response)}"
                )
            data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Gemini voice network error: {exc}") from exc

        voices_raw = data.get("voices", []) if isinstance(data, dict) else []
        items: list[dict[str, Any]] = []

        expected_type = "prompted" if voice_type == "voice_design" else "replicated"

        for v in voices_raw:
            if not isinstance(v, dict):
                continue
            v_id = str(v.get("id") or v.get("voice_id") or v.get("name") or "").strip()
            if not v_id:
                continue
            v_type = str(v.get("type", "")).strip().lower()
            # If type matches or if not specified
            if v_type and v_type != expected_type:
                continue

            display_name = str(v.get("display_name", "") or v_id)
            prompted_info = v.get("prompted", {}) if isinstance(v.get("prompted"), dict) else {}
            description = str(v.get("description", "") or prompted_info.get("input", "") or "")
            target_model = str(v.get("model", "") or DEFAULT_GEMINI_TTS_MODEL)

            items.append(
                {
                    "voice": v_id,
                    "type": voice_type,
                    "target_model": target_model,
                    "language": "multi",
                    "name": display_name,
                    "gender": "AI" if voice_type == "voice_design" else "Clone",
                    "description": description,
                }
            )

        return {
            "voice_type": voice_type,
            "count": len(items),
            "voices": items,
            "voice_provider": "gemini",
        }

    async def delete_voice(
        self,
        *,
        voice_name: str,
        voice_type: VoiceType = "voice_design",
    ) -> dict[str, Any]:
        target_voice = voice_name.strip()
        if not target_voice:
            raise ValueError("voice_name is required.")

        api_key, base_url = self._get_credentials()
        url = f"{base_url}/v1beta/voices/{target_voice}"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.delete(url, headers=gemini_headers(api_key))
            if response.status_code not in (200, 204):
                raise RuntimeError(
                    f"Gemini voice delete failed ({response.status_code}): {self._extract_error(response)}"
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Gemini voice network error: {exc}") from exc

        return {
            "voice": target_voice,
            "type": voice_type,
            "deleted": True,
        }
