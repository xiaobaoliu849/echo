"""ElevenLabs voice clone service.

Uses the official ElevenLabs REST API:
- Voice Clone: POST /v1/voices/add  (multipart: name + files → voice_id)
- List:        GET  /v1/voices
- Delete:      DELETE /v1/voices/{voice_id}
"""

from __future__ import annotations

from typing import Any

import httpx

from .config_loader import BackendConfig

# ElevenLabs accepts mp3/pdf?/wav audio for instant cloning; keep the
# browser-friendly subset the clone page already allows.
ELEVENLABS_CLONE_MIME_TYPES = (
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/x-flac",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/webm",
)

_MIME_TO_SUFFIX = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
}


class ElevenLabsVoiceService:
    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig()

    def _get_credentials(self) -> tuple[str, str]:
        self.config.reload()
        settings = self.config.get_provider_settings("ElevenLabs")
        api_key = str(settings.get("api_key", "")).strip()
        if not api_key:
            raise ValueError("Missing ElevenLabs API key.")
        base_url = str(settings.get("base_url", "")).strip().rstrip("/")
        if not base_url:
            base_url = "https://api.elevenlabs.io/v1"
        return api_key, base_url

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            return response.text[:500]
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("status")
            if message:
                return str(message)
        if detail:
            return str(detail)[:500]
        return response.text[:500]

    async def create_voice_clone(
        self,
        *,
        audio_bytes: bytes,
        mime_type: str,
        preferred_name: str,
    ) -> dict[str, Any]:
        """Upload an audio sample and create an instant voice clone.

        Returns a dict compatible with VoiceCreateResponse:
        voice (voice_id), type, preferred_name, provider.
        """
        preferred = preferred_name.strip()
        if not preferred:
            raise ValueError("preferred_name is required.")
        if not audio_bytes:
            raise ValueError("audio file is empty.")

        media_type = (mime_type or "").strip().lower()
        if media_type not in _MIME_TO_SUFFIX:
            media_type = "audio/mpeg"

        api_key, base_url = self._get_credentials()
        headers = {"xi-api-key": api_key}
        files = {
            "files": (
                f"sample{_MIME_TO_SUFFIX[media_type]}",
                audio_bytes,
                media_type,
            )
        }
        data = {"name": preferred}

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{base_url}/voices/add",
                    headers=headers,
                    files=files,
                    data=data,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"ElevenLabs voice clone request failed: {self._extract_error_detail(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs voice network error: {exc}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("ElevenLabs voice clone returned invalid response.")
        voice_id = str(payload.get("voice_id", "")).strip()
        if not voice_id:
            raise RuntimeError("ElevenLabs voice clone response missing voice_id.")

        return {
            "voice": voice_id,
            "type": "voice_clone",
            "preferred_name": preferred,
            "requires_verification": bool(payload.get("requires_verification", False)),
        }

    async def list_voices(self) -> dict[str, Any]:
        """List custom (cloned) voices, filtered to category "cloned"."""
        api_key, base_url = self._get_credentials()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{base_url}/voices",
                    headers={"xi-api-key": api_key},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"ElevenLabs voice list request failed: {self._extract_error_detail(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs voice network error: {exc}") from exc

        voices_payload = payload.get("voices", []) if isinstance(payload, dict) else []
        items: list[dict[str, Any]] = []
        for voice in voices_payload:
            if not isinstance(voice, dict):
                continue
            voice_id = str(voice.get("voice_id", "")).strip()
            if not voice_id:
                continue
            category = str(voice.get("category", "")).strip().lower()
            if category and category not in ("cloned", "generated"):
                # Skip stock/default voices; only show user-created clones.
                continue
            name = str(voice.get("name", "") or voice_id)
            labels = voice.get("labels") if isinstance(voice.get("labels"), dict) else {}
            items.append(
                {
                    "voice": voice_id,
                    "type": "voice_clone",
                    "target_model": category or "cloned",
                    "language": str(labels.get("language", "") or ""),
                    "name": name,
                    "gender": str(labels.get("gender", "") or "Clone"),
                }
            )

        return {
            "voice_type": "voice_clone",
            "count": len(items),
            "voices": items,
        }

    async def delete_voice(self, *, voice_name: str) -> dict[str, Any]:
        voice_id = voice_name.strip()
        if not voice_id:
            raise ValueError("voice_name is required.")

        api_key, base_url = self._get_credentials()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.delete(
                    f"{base_url}/voices/{voice_id}",
                    headers={"xi-api-key": api_key},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return {"voice": voice_id, "type": "voice_clone", "deleted": False}
            raise RuntimeError(
                f"ElevenLabs voice delete request failed: {self._extract_error_detail(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs voice network error: {exc}") from exc

        return {"voice": voice_id, "type": "voice_clone", "deleted": True}
