"""Unit tests for Google Gemini 3.5 Transcribe integration in TranscriptionService."""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.transcription_service import (
    GEMINI_TRANSCRIBE_MODEL,
    TranscriptionService,
)


def _make_service() -> TranscriptionService:
    return TranscriptionService.__new__(TranscriptionService)


class _FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            req = httpx.Request("POST", "https://example.invalid")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError(self.text, request=req, response=resp)

    def json(self):
        return self._payload


@contextmanager
def _file_guards():
    with patch("services.transcription_service.Path.is_file", return_value=True), \
         patch("services.transcription_service.Path.stat", return_value=SimpleNamespace(st_size=10)), \
         patch("services.transcription_service.Path.read_bytes", return_value=b"mock audio bytes"), \
         patch("services.transcription_service._read_file_base64", return_value="bW9jayBhZGlv"):
        yield


class GoogleGeminiTranscribeTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_time_offset(self):
        self.assertIsNone(TranscriptionService._parse_time_offset(None))
        self.assertEqual(TranscriptionService._parse_time_offset(12.5), 12.5)
        self.assertEqual(TranscriptionService._parse_time_offset("1.25s"), 1.25)
        self.assertEqual(TranscriptionService._parse_time_offset("3.5"), 3.5)
        self.assertIsNone(TranscriptionService._parse_time_offset("invalid"))

    def test_extract_google_words(self):
        data = {
            "output": {
                "words": [
                    {"word": "Hello", "start_time": "0.1s", "end_time": "0.5s"},
                    {"word": "world", "start_time": "0.6s", "end_time": "1.0s"},
                ]
            }
        }
        words = TranscriptionService._extract_google_words(data)
        self.assertEqual(
            words,
            [
                {"text": "Hello", "start": 0.1, "end": 0.5},
                {"text": "world", "start": 0.6, "end": 1.0},
            ],
        )

    async def test_transcribe_with_google_gemini_sdk_success(self):
        service = _make_service()
        service.config = SimpleNamespace(
            get_provider_settings=lambda name: {"base_url": "https://generativelanguage.googleapis.com/v1beta"}
        )

        mock_audio_file = SimpleNamespace(
            uri="https://generativelanguage.googleapis.com/v1beta/files/test1234",
            mime_type="audio/wav",
            name="files/test1234",
        )
        mock_step = SimpleNamespace(
            type="model_output",
            content="Hello Gemini transcribe via SDK.",
        )
        mock_interaction = SimpleNamespace(
            output_text="Hello Gemini transcribe via SDK.",
            steps=[mock_step],
            to_dict=lambda: {
                "output": {
                    "words": [
                        {"text": "Hello", "start_time": 0.0, "end_time": 0.4},
                        {"text": "Gemini", "start_time": 0.5, "end_time": 1.2},
                    ]
                },
                "usage": {"duration_seconds": 2.5},
            },
        )

        mock_client = SimpleNamespace(
            files=SimpleNamespace(
                upload=lambda file: mock_audio_file,
                delete=lambda name: True,
            ),
            interactions=SimpleNamespace(
                create=lambda **kw: mock_interaction,
            ),
        )

        with patch("services.transcription_service.genai", SimpleNamespace(Client=lambda **kw: mock_client)), \
             _file_guards():
            result = await service._transcribe_with_google_gemini(Path("sample.wav"), api_key="sk-goog")

        self.assertEqual(result["text"], "Hello Gemini transcribe via SDK.")
        self.assertEqual(result["duration_seconds"], 2.5)
        self.assertEqual(len(result["words"]), 2)
        self.assertEqual(result["words"][0]["text"], "Hello")
        self.assertEqual(result["words"][0]["start"], 0.0)

    async def test_transcribe_with_google_gemini_rest_fallback(self):
        service = _make_service()
        service.config = SimpleNamespace(
            get_provider_settings=lambda name: {"base_url": "https://generativelanguage.googleapis.com/v1beta"}
        )

        class RestClient:
            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None, files=None, **kw):
                self.calls.append(url)
                if "/upload/" in url:
                    return _FakeResponse({"file": {"name": "files/rest123", "uri": "https://gen/files/rest123"}})
                if "/interactions" in url:
                    return _FakeResponse({
                        "output_text": "Transcribed via REST fallback",
                        "duration": 4.0,
                        "words": [{"text": "Transcribed", "start_time": 0.0, "end_time": 1.0}],
                    })
                return _FakeResponse({}, status_code=404)

            async def delete(self, url, headers=None, **kw):
                self.calls.append(url)
                return _FakeResponse({})

        with patch("services.transcription_service.genai", None), \
             patch("services.transcription_service.httpx.AsyncClient", return_value=RestClient()), \
             _file_guards():
            result = await service._transcribe_with_google_gemini(Path("sample.mp3"), api_key="sk-goog")

        self.assertEqual(result["text"], "Transcribed via REST fallback")
        self.assertEqual(result["duration_seconds"], 4.0)

    async def test_transcribe_file_explicit_google_provider(self):
        service = _make_service()
        service._google_key = lambda: "sk-goog"
        service._transcribe_with_google_gemini = AsyncMock(
            return_value={"text": "Google STT", "duration_seconds": 4.2, "words": None}
        )

        with _file_guards():
            for p in ["google", "gemini", "gemini-3.5-transcribe", "google-transcribe"]:
                res = await service.transcribe_file("audio.wav", provider=p)
                self.assertEqual(res["provider"], "google")
                self.assertEqual(res["text"], "Google STT")

    async def test_transcribe_file_missing_google_key_raises(self):
        service = _make_service()
        service._google_key = lambda: ""

        with _file_guards():
            with self.assertRaises(ValueError) as ctx:
                await service.transcribe_file("audio.wav", provider="google")
            self.assertIn("Google API key not configured", str(ctx.exception))

    async def test_transcribe_file_auto_selects_google_when_available(self):
        service = _make_service()
        service._deepgram_key = lambda: ""
        service._google_key = lambda: "sk-goog"
        service._openai_key = lambda: "sk-openai"
        service._transcribe_with_google_gemini = AsyncMock(
            return_value={"text": "Auto Google STT", "duration_seconds": 2.0, "words": None}
        )

        with _file_guards():
            res = await service.transcribe_file("audio.wav")
            self.assertEqual(res["provider"], "google")
            self.assertEqual(res["text"], "Auto Google STT")


if __name__ == "__main__":
    unittest.main()
