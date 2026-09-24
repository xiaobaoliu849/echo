"""Google Gemini voice design and voice replication (cloning) service.

API reference:
- Voice design: POST /v1beta/voices (type="prompted")
- Voice clone / replication: POST /v1beta/voices (type="replicated")
- List voices: GET /v1beta/voices
- Delete voice: DELETE /v1beta/voices/{voice_id}
"""
from __future__ import annotations

import base64
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

VoiceType = Literal["voice_design", "voice_clone"]


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
        return api_key, base_url

    @staticmethod
    def _extract_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict) and "error" in payload:
                err = payload["error"]
                if isinstance(err, dict) and "message" in err:
                    return str(err["message"])
                return str(err)
            if isinstance(payload, dict) and "detail" in payload:
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
                "description": prompt,
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
            data.get("voice_id")
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
        if isinstance(sample_audio, str) and sample_audio.strip():
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
    ) -> dict[str, Any]:
        preferred = preferred_name.strip()
        if not preferred:
            raise ValueError("preferred_name is required.")
        if not audio_bytes:
            raise ValueError("audio file is empty.")

        api_key, base_url = self._get_credentials()
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        url = f"{base_url}/v1beta/voices"

        payload = {
            "type": "replicated",
            "store": True,
            "replicated": {
                "source_audio": audio_b64,
                "consent_audio": audio_b64,
            },
            "voice": {
                "display_name": preferred,
                "model": DEFAULT_GEMINI_TTS_MODEL,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=gemini_headers(api_key), json=payload)
            if response.status_code not in (200, 201):
                raise RuntimeError(
                    f"Gemini voice clone failed ({response.status_code}): {self._extract_error(response)}"
                )
            data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Gemini voice network error: {exc}") from exc

        if not isinstance(data, dict):
            raise RuntimeError("Gemini voice clone returned invalid non-JSON response.")

        voice_id = (
            data.get("voice_id")
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
            v_id = str(v.get("voice_id") or v.get("name") or "").strip()
            if not v_id:
                continue
            v_type = str(v.get("type", "")).strip().lower()
            # If type matches or if not specified
            if v_type and v_type != expected_type:
                continue

            display_name = str(v.get("display_name", "") or v_id)
            description = str(v.get("description", "") or "")
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
