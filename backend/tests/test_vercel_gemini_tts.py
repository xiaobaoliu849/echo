import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from routers.settings import VERCEL_TTS_MODEL_LIST_SUPPLEMENTS
from services.tts_service import TTSService, TTS_ENGINE_VERCEL_GEMINI
from services.vercel_gemini_tts_provider import (
    VERCEL_GEMINI_TTS_MODELS,
    _pace_instructions,
    _speech_url,
    vercel_gemini_tts_synthesize,
)


WAV = b"RIFF\x04\x00\x00\x00WAVEaudio"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", VERCEL_GEMINI_TTS_MODELS)
async def test_vercel_gemini_speech_request(model: str):
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {"audio": base64.b64encode(WAV).decode(), "warnings": []}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response) as post:
        audio = await vercel_gemini_tts_synthesize(
            " Hello, Echo. ", "kore", "gateway-key", "https://ai-gateway.vercel.sh/v1", model
        )
    assert audio == WAV
    assert post.call_args.args == ("https://ai-gateway.vercel.sh/v4/ai/speech-model",)
    headers = post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer gateway-key"
    assert headers["ai-gateway-protocol-version"] == "0.0.1"
    assert headers["ai-speech-model-specification-version"] == "4"
    assert headers["ai-model-id"] == model
    assert post.call_args.kwargs["json"] == {
        "text": "Hello, Echo.", "voice": "Kore", "outputFormat": "wav"
    }


@pytest.mark.asyncio
async def test_vercel_gemini_accepts_additional_prebuilt_voice():
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {"audio": base64.b64encode(WAV).decode()}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response) as post:
        await vercel_gemini_tts_synthesize("Hello", "sulafat", "gateway-key")
    assert post.call_args.kwargs["json"]["voice"] == "Sulafat"


def test_vercel_speech_url_accepts_configured_gateway_variants():
    assert _speech_url("https://example.com/v4/ai/speech-model") == "https://example.com/v4/ai/speech-model"
    assert _speech_url("https://example.com/v4") == "https://example.com/v4/ai/speech-model"


def test_vercel_rate_uses_supported_pacing_instructions():
    assert _pace_instructions("+0%") is None
    assert "20% faster" in _pace_instructions("+20%")
    assert "15% slower" in _pace_instructions("-15%")
    with pytest.raises(ValueError, match="rate"):
        _pace_instructions("very fast")


@pytest.mark.asyncio
async def test_vercel_gemini_sends_pacing_instructions():
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {"audio": base64.b64encode(WAV).decode()}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response) as post:
        await vercel_gemini_tts_synthesize("Hello", "Kore", "key", rate="-15%")
    assert "15% slower" in post.call_args.kwargs["json"]["instructions"]


@pytest.mark.asyncio
async def test_vercel_gemini_rejects_unsupported_inputs_before_request():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        with pytest.raises(ValueError, match="model"):
            await vercel_gemini_tts_synthesize("hello", "Kore", "key", model="google/gemini-3.8-live")
        with pytest.raises(ValueError, match="voice"):
            await vercel_gemini_tts_synthesize("hello", "voice_google_custom", "key")
        post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"audio": "%%%"}, {"audio": base64.b64encode(b"not wav").decode()}])
async def test_vercel_gemini_rejects_invalid_audio(payload: dict):
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = payload
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response):
        with pytest.raises(RuntimeError, match="audio|WAV"):
            await vercel_gemini_tts_synthesize("hello", "Kore", "key")


@pytest.mark.asyncio
async def test_vercel_gemini_reports_gateway_error_without_secret():
    response = MagicMock(spec=httpx.Response)
    response.status_code = 403
    response.json.return_value = {"error": {"message": "Access denied"}}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response):
        with pytest.raises(RuntimeError, match="Access denied") as error:
            await vercel_gemini_tts_synthesize("hello", "Kore", "secret-key")
    assert "secret-key" not in str(error.value)


@pytest.mark.asyncio
async def test_tts_service_vercel_dispatch_and_catalog(tmp_path: Path):
    service = TTSService(output_dir=tmp_path)
    assert set(VERCEL_TTS_MODEL_LIST_SUPPLEMENTS) == set(VERCEL_GEMINI_TTS_MODELS)
    voices = await service.list_voices(engine=TTS_ENGINE_VERCEL_GEMINI)
    assert any(item["name"] == "Kore" for item in voices)
    assert not any(item["name"].startswith("voice_") for item in voices)

    with patch.object(service, "_vercel_gemini_settings", return_value=("key", "https://ai-gateway.vercel.sh")):
        with patch("services.tts_service.vercel_gemini_tts_synthesize", new_callable=AsyncMock, return_value=WAV) as synth:
            result = await service.generate_audio(
                "Hello, Echo.", voice="Puck", engine=TTS_ENGINE_VERCEL_GEMINI,
                model="google/gemini-3.8-flash-lite-tts",
            )
    assert result.engine == TTS_ENGINE_VERCEL_GEMINI
    assert result.media_type == "audio/wav"
    assert Path(result.file_path).suffix == ".wav"
    assert Path(result.file_path).read_bytes() == WAV
    assert synth.call_args.kwargs["model"] == "google/gemini-3.8-flash-lite-tts"
    assert synth.call_args.kwargs["rate"] == "+0%"
