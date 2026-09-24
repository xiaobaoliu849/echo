import base64
import pytest
import httpx
from unittest.mock import patch, MagicMock

from services.gemini_tts_provider import (
    GEMINI_TTS_MODELS,
    DEFAULT_GEMINI_TTS_MODEL,
    DEFAULT_GEMINI_TTS_VOICE,
    is_gemini_voice,
    _build_speech_config,
    gemini_tts_synthesize,
)


def test_gemini_tts_models_and_defaults():
    assert "gemini-3.8-flash-tts" in GEMINI_TTS_MODELS
    assert "gemini-3.8-flash-lite-tts" in GEMINI_TTS_MODELS
    assert DEFAULT_GEMINI_TTS_MODEL == "gemini-3.8-flash-tts"
    assert DEFAULT_GEMINI_TTS_VOICE == "Kore"


def test_is_gemini_voice():
    assert is_gemini_voice("Kore") is True
    assert is_gemini_voice("puck") is True
    assert is_gemini_voice("Charon") is True
    assert is_gemini_voice("voice_gemini_test123") is True
    assert is_gemini_voice("voicekey_encrypted_key") is True
    assert is_gemini_voice("zh-CN-XiaoxiaoNeural") is False
    assert is_gemini_voice("") is False
    assert is_gemini_voice(None) is False


def test_build_speech_config():
    prebuilt_cfg = _build_speech_config("Puck")
    assert prebuilt_cfg == {
        "voiceConfig": {
            "prebuiltVoiceConfig": {
                "voiceName": "Puck"
            }
        }
    }

    custom_cfg = _build_speech_config("voice_custom_abc")
    assert custom_cfg == {
        "voiceConfig": {
            "voice": "voice_custom_abc"
        }
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("voice", "style"),
    [("Kore", None), ("voice_pzimzi1rhjx3", "warm and friendly")],
)
async def test_gemini_tts_synthesize_success(voice: str, style: str | None):
    fake_wav_bytes = b"RIFF....WAVEfmt ...."
    fake_b64 = base64.b64encode(fake_wav_bytes).decode("ascii")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": fake_b64,
                            }
                        }
                    ]
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", return_value=mock_response) as post:
        audio_out = await gemini_tts_synthesize(
            text="Hello from Gemini 3.8 Flash TTS!",
            voice=voice,
            api_key="fake-gemini-key",
            model="gemini-3.8-flash-tts",
            style=style,
        )
        assert audio_out == fake_wav_bytes
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        assert url == (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.8-flash-tts:generateContent"
        )
        assert "config" not in payload
        assert payload["generationConfig"] == {
            "responseModalities": ["AUDIO"],
            "speechConfig": _build_speech_config(voice),
        }
        expected_part = {"text": "Hello from Gemini 3.8 Flash TTS!"}
        if style:
            expected_part["speech_metadata"] = {"style": style}
        assert payload["contents"][0]["parts"] == [expected_part]


@pytest.mark.asyncio
async def test_gemini_tts_synthesize_error_handling():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 400
    mock_response.text = '{"error": {"message": "Invalid API key provided"}}'
    mock_response.json.return_value = {"error": {"message": "Invalid API key provided"}}

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        with pytest.raises(RuntimeError) as exc_info:
            await gemini_tts_synthesize(
                text="Test error",
                voice="Kore",
                api_key="fake-key",
            )
        assert "Invalid API key provided" in str(exc_info.value)
