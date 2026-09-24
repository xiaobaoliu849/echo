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


@pytest.mark.asyncio
async def test_base_url_v1beta_normalization(tmp_path: Path):
    # Tests that /v1beta at end of base_url is stripped so url doesn't become /v1beta/v1beta/voices
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "api_keys": {"google_api_key": "test-key"},
                "api_urls": {"Google": "https://generativelanguage.googleapis.com/v1beta"},
            }
        ),
        encoding="utf-8",
    )
    service = GeminiVoiceService(config=BackendConfig(config_path=config_file))

    called_urls = []

    async def mock_post(url, *args, **kwargs):
        called_urls.append(url)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {"id": "voice_123"}
        return resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        await service.create_voice_clone(
            audio_bytes=b"dummy-audio",
            mime_type="audio/wav",
            preferred_name="test_voice",
        )
        assert len(called_urls) == 1
        assert called_urls[0] == "https://generativelanguage.googleapis.com/v1beta/voices"
        assert "/v1beta/v1beta" not in called_urls[0]


@pytest.mark.asyncio
async def test_create_voice_clone_payload_structure(tmp_path: Path):
    service = _service_with_config(tmp_path)
    captured_payload = {}

    async def mock_post(url, *args, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {"id": "voice_cloned_abc"}
        return resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        res = await service.create_voice_clone(
            audio_bytes=b"hello-voice",
            mime_type="audio/wav",
            preferred_name="MyVoice",
        )
        assert res["voice"] == "voice_cloned_abc"
        assert captured_payload.get("store") is True
        voice_block = captured_payload.get("voice", {})
        assert voice_block.get("type") == "replicated"
        assert voice_block.get("display_name") == "MyVoice"
        replicated = voice_block.get("replicated", {})
        assert "source_audio" in replicated
        assert "consent_audio" in replicated
        assert replicated["source_audio"]["mime_type"] == "audio/wav"
        assert isinstance(replicated["source_audio"]["data"], str)


@pytest.mark.asyncio
async def test_extract_error_consent_flow(tmp_path: Path):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 500
    resp.json.return_value = {
        "error": {
            "code": 500,
            "message": "Error translating server response to JSON",
            "details": [
                {
                    "detail": "Consent flow failed. The recorded phrase didn't match the text on screen."
                }
            ],
        }
    }
    err = GeminiVoiceService._extract_error(resp)
    assert "Consent flow failed" in err
    assert "Please recite" in err


@pytest.mark.asyncio
async def test_create_voice_clone_normalizes_audio_to_wav(tmp_path: Path):
    service = _service_with_config(tmp_path)
    captured_payload = {}

    async def mock_post(url, *args, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {"id": "voice_cloned_wav"}
        return resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        res = await service.create_voice_clone(
            audio_bytes=b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00",
            mime_type="audio/webm;codecs=opus",
            preferred_name="NormalizedVoice",
        )
        assert res["voice"] == "voice_cloned_wav"
        replicated = captured_payload["voice"]["replicated"]
        # Must be audio/wav, not audio/webm
        assert replicated["source_audio"]["mime_type"] == "audio/wav"
        assert replicated["consent_audio"]["mime_type"] == "audio/wav"
