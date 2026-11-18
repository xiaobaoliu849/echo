from __future__ import annotations

import base64
from typing import Any, Literal

import httpx

from .config_loader import BackendConfig

VoiceType = Literal["voice_design", "voice_clone"]

QWEN_TTS_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
QWEN_VOICE_DESIGN_MODEL = "qwen-voice-design"
QWEN_VOICE_DESIGN_TARGET = "qwen3-tts-vd-realtime-2025-12-16"
QWEN_VOICE_CLONE_MODEL = "qwen-voice-enrollment"
QWEN_VOICE_CLONE_TARGET = "qwen3-tts-vc-realtime-2025-11-27"


class QwenModelUnavailable(RuntimeError):
    pass


class QwenVoiceService:
    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig()

    @staticmethod
    def _resolve_model(voice_type: VoiceType) -> tuple[str, str]:
        if voice_type == "voice_design":
            return QWEN_VOICE_DESIGN_MODEL, QWEN_VOICE_DESIGN_TARGET
        return QWEN_VOICE_CLONE_MODEL, QWEN_VOICE_CLONE_TARGET

    def _get_api_key(self) -> str:
        self.config.reload()
        settings = self.config.get_provider_settings("DashScope")
        api_key = str(settings.get("api_key", "")).strip()
        if not api_key:
            raise ValueError("Missing DashScope API key.")
        return api_key

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = self._get_api_key()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(QWEN_TTS_API_URL, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            try:
                error = exc.response.json()
            except ValueError:
                error = {}
            if isinstance(error, dict) and error.get("code") == "InvalidParameter" and error.get("message") == "Model not exist.":
                raise QwenModelUnavailable(f"Qwen voice request failed: {detail}") from exc
            raise RuntimeError(f"Qwen voice request failed: {detail}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Qwen voice network error: {exc}") from exc

        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Qwen voice API returned invalid response.")
        return data

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

        model, target_model = self._resolve_model("voice_design")
        payload = {
            "model": model,
            "input": {
                "action": "create",
                "target_model": target_model,
                "voice_prompt": prompt,
                "preview_text": preview,
                "preferred_name": preferred,
                "language": lang,
            },
            "parameters": {
                "sample_rate": 24000,
                "response_format": "wav",
            },
        }
        result = await self._request(payload)
        output = result.get("output", {})
        voice_name = output.get("voice")
        if not isinstance(voice_name, str) or not voice_name.strip():
            raise RuntimeError("Qwen voice design response missing voice field.")

        preview_audio_data = ""
        preview_audio = output.get("preview_audio")
        if isinstance(preview_audio, dict):
            value = preview_audio.get("data")
            if isinstance(value, str):
                preview_audio_data = value

        return {
            "voice": voice_name.strip(),
            "type": "voice_design",
            "target_model": target_model,
            "preferred_name": preferred,
            "language": lang,
            "preview_audio_data": preview_audio_data,
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

        model, target_model = self._resolve_model("voice_clone")
        encoded = base64.b64encode(audio_bytes).decode("ascii")
        media_type = (mime_type or "").strip() or "audio/mpeg"
        payload = {
            "model": model,
            "input": {
                "action": "create",
                "target_model": target_model,
                "preferred_name": preferred,
                "audio": {
                    "data": f"data:{media_type};base64,{encoded}",
                },
            },
        }
        result = await self._request(payload)
        output = result.get("output", {})
        voice_name = output.get("voice")
        if not isinstance(voice_name, str) or not voice_name.strip():
            raise RuntimeError("Qwen voice clone response missing voice field.")

        return {
            "voice": voice_name.strip(),
            "type": "voice_clone",
            "target_model": target_model,
            "preferred_name": preferred,
        }

    async def list_voices(
        self,
        *,
        voice_type: VoiceType = "voice_design",
        page_index: int = 0,
        page_size: int = 100,
    ) -> dict[str, Any]:
        if page_index < 0:
            raise ValueError("page_index must be >= 0.")
        if page_size < 1 or page_size > 200:
            raise ValueError("page_size must be between 1 and 200.")

        model, target_model = self._resolve_model(voice_type)
        payload = {
            "model": model,
            "input": {
                "action": "list",
                "page_index": page_index,
                "page_size": page_size,
            },
        }
        try:
            result = await self._request(payload)
        except QwenModelUnavailable:
            if voice_type != "voice_design":
                raise
            # Workspaces without the legacy VD model use the unified catalog.
            result = await self._request({
                "model": "voice-enrollment",
                "input": {"action": "list_voice", "page_index": page_index, "page_size": page_size},
            })
            items = []
            for row in result.get("output", {}).get("voice_list", []):
                voice_id = row.get("voice_id") if isinstance(row, dict) else None
                if not isinstance(voice_id, str) or "-vd-" not in voice_id:
                    continue
                items.append({
                    "voice": voice_id, "type": voice_type, "name": voice_id, "gender": "AI",
                    "target_model": voice_id.split("-vd-", 1)[0], "language": row.get("language") or "multi",
                })
            return {"voice_type": voice_type, "count": len(items), "voices": items}
        output = result.get("output", {})
        expected_target_prefix = "qwen3-tts-vd" if voice_type == "voice_design" else "qwen3-tts-vc"

        items: list[dict[str, Any]] = []
        for voice in output.get("voice_list", []):
            if not isinstance(voice, dict):
                continue
            voice_id = voice.get("voice")
            if not isinstance(voice_id, str) or not voice_id:
                continue
            voice_target_model = str(voice.get("target_model", ""))
            if expected_target_prefix not in voice_target_model:
                continue
            language = str(voice.get("language", "zh-CN"))
            items.append(
                {
                    "voice": voice_id,
                    "type": voice_type,
                    "target_model": voice_target_model or target_model,
                    "language": language,
                    "name": voice_id,
                    "gender": "AI" if voice_type == "voice_design" else "Clone",
                }
            )

        return {
            "voice_type": voice_type,
            "count": len(items),
            "voices": items,
        }

    async def delete_voice(self, *, voice_name: str, voice_type: VoiceType) -> dict[str, Any]:
        target_voice = voice_name.strip()
        if not target_voice:
            raise ValueError("voice_name is required.")

        model, _ = self._resolve_model(voice_type)
        payload = {
            "model": model,
            "input": {
                "action": "delete",
                "voice": target_voice,
            },
        }
        if voice_type == "voice_design" and target_voice.startswith(("qwen-audio-", "cosyvoice-")) and "-vd-" in target_voice:
            payload = {"model": "voice-enrollment", "input": {"action": "delete_voice", "voice_id": target_voice}}
        await self._request(payload)
        return {
            "voice": target_voice,
            "type": voice_type,
            "deleted": True,
        }
