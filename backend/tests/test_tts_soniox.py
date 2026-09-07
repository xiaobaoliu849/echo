import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from services.tts_service import (
    TTSService,
    TTS_ENGINE_SONIOX,
    TTSAudioResult,
)
from services.soniox_tts_provider import (
    DEFAULT_SONIOX_TTS_MODEL,
    DEFAULT_SONIOX_TTS_VOICE,
    SONIOX_TTS_VOICES,
    is_soniox_voice,
)


@pytest.fixture
def tts_service(tmp_path):
    service = TTSService()
    service.output_dir = tmp_path
    return service


def test_is_soniox_voice():
    assert is_soniox_voice("Adrian") is True
    assert is_soniox_voice("Mina") is True
    assert is_soniox_voice("NonExistentVoice") is False
    assert is_soniox_voice("") is False


@pytest.mark.asyncio
async def test_detect_engine_by_voice_soniox(tts_service):
    assert tts_service.detect_engine_by_voice("Adrian") == TTS_ENGINE_SONIOX
    assert tts_service.detect_engine_by_voice("Daniel") == TTS_ENGINE_SONIOX


@pytest.mark.asyncio
async def test_list_voices_soniox_fallback(tts_service):
    with patch.object(tts_service, "_soniox_settings", return_value=("", "https://tts-rt.soniox.com", "https://api.soniox.com/v1")):
        voices = await tts_service.list_voices(engine=TTS_ENGINE_SONIOX)
        assert len(voices) >= len(SONIOX_TTS_VOICES)
        names = [v["name"] for v in voices]
        assert "Adrian" in names
        assert "Mina" in names


@pytest.mark.asyncio
async def test_list_voices_soniox_remote(tts_service):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {
                "id": "tts-rt-v2",
                "voices": [
                    {"id": "TestVoice1", "gender": "female", "description": "test voice"},
                ],
            }
        ]
    }

    with patch.object(tts_service, "_soniox_settings", return_value=("test_key", "https://tts-rt.soniox.com", "https://api.soniox.com/v1")):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            voices = await tts_service.list_voices(engine=TTS_ENGINE_SONIOX)
            names = [v["name"] for v in voices]
            assert "TestVoice1" in names


@pytest.mark.asyncio
async def test_generate_audio_soniox_success(tts_service, tmp_path):
    with patch.object(tts_service, "_soniox_settings", return_value=("test_key", "https://tts-rt.soniox.com", "https://api.soniox.com/v1")):
        with patch("services.tts_service.soniox_tts_synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.return_value = b"\xff\xfb\x90\x44fake_mp3_data"
            result = await tts_service.generate_audio(
                text="Hello from Soniox",
                voice="Adrian",
                engine=TTS_ENGINE_SONIOX,
            )
            assert isinstance(result, TTSAudioResult)
            assert result.engine == TTS_ENGINE_SONIOX
            assert result.voice == "Adrian"
            assert Path(result.file_path).exists()
            assert Path(result.file_path).read_bytes() == b"\xff\xfb\x90\x44fake_mp3_data"


@pytest.mark.asyncio
async def test_generate_audio_soniox_missing_key(tts_service):
    with patch.object(tts_service, "_soniox_settings", return_value=("", "https://tts-rt.soniox.com", "https://api.soniox.com/v1")):
        with pytest.raises(RuntimeError, match="Soniox API Key is not configured"):
            await tts_service.generate_audio(
                text="Hello from Soniox",
                voice="Adrian",
                engine=TTS_ENGINE_SONIOX,
            )
