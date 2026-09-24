import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx
import pytest

from services.gemini_voice_service import GeminiVoiceService
from services.config_loader import BackendConfig


def _service_with_config(tmp_path: Path, *, api_key: str = "test-google-key") -> GeminiVoiceService:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "api_keys": {"google_api_key": api_key},
                "api_urls": {"Google": "https://generativelanguage.googleapis.com"},
            }
        ),
        encoding="utf-8",
    )
    return GeminiVoiceService(config=BackendConfig(config_path=config_file))


@pytest.mark.asyncio
async def test_create_voice_design_success(tmp_path: Path):
    service = _service_with_config(tmp_path)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "voice_id": "voice_gemini_astronomer",
        "sample_audio": "UkZGRg==",
    }

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        res = await service.create_voice_design(
            voice_prompt="A calm British astronomer",
            preview_text="The stars are bright tonight.",
            preferred_name="British Astronomer",
            language="en",
        )
        assert res["voice"] == "voice_gemini_astronomer"
        assert res["type"] == "voice_design"
        assert res["provider"] == "gemini"
        assert res["preferred_name"] == "British Astronomer"
        assert res["preview_audio_data"] == "UkZGRg=="


@pytest.mark.asyncio
async def test_create_voice_clone_success(tmp_path: Path):
    service = _service_with_config(tmp_path)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "voice_id": "voice_gemini_cloned_user",
    }

    fake_audio = b"RIFFfakeaudio"
    with patch("httpx.AsyncClient.post", return_value=mock_response):
        res = await service.create_voice_clone(
            audio_bytes=fake_audio,
            mime_type="audio/wav",
            preferred_name="My Cloned Voice",
        )
        assert res["voice"] == "voice_gemini_cloned_user"
        assert res["type"] == "voice_clone"
        assert res["provider"] == "gemini"
        assert res["preferred_name"] == "My Cloned Voice"


@pytest.mark.asyncio
async def test_list_voices_success(tmp_path: Path):
    service = _service_with_config(tmp_path)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "voices": [
            {
                "voice_id": "voice_designed_1",
                "type": "prompted",
                "display_name": "Warm Narrator",
                "description": "Warm voice",
                "model": "gemini-3.8-flash-tts",
            },
            {
                "voice_id": "voice_cloned_1",
                "type": "replicated",
                "display_name": "Cloned Speaker",
                "model": "gemini-3.8-flash-tts",
            },
        ]
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        res_design = await service.list_voices(voice_type="voice_design")
        assert res_design["count"] == 1
        assert res_design["voices"][0]["voice"] == "voice_designed_1"
        assert res_design["voice_provider"] == "gemini"

        res_clone = await service.list_voices(voice_type="voice_clone")
        assert res_clone["count"] == 1
        assert res_clone["voices"][0]["voice"] == "voice_cloned_1"


@pytest.mark.asyncio
async def test_delete_voice_success(tmp_path: Path):
    service = _service_with_config(tmp_path)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 204

    with patch("httpx.AsyncClient.delete", return_value=mock_response):
        res = await service.delete_voice(voice_name="voice_designed_1")
        assert res["voice"] == "voice_designed_1"
        assert res["deleted"] is True


@pytest.mark.asyncio
async def test_missing_api_key_raises(tmp_path: Path):
    service = _service_with_config(tmp_path, api_key="")
    with pytest.raises(ValueError, match="Missing Google / Gemini API key"):
        await service.list_voices()
