"""Unit tests for Google Gemini 3.5 Transcribe integration in TranscriptionService."""
from __future__ import annotations

import unittest
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


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, **kw):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return self.response


def _file_guards():
    return (
        patch("services.transcription_service.Path.is_file", return_value=True),
        patch("services.transcription_service.Path.stat", return_value=SimpleNamespace(st_size=10)),
        patch("services.transcription_service._read_file_base64", return_value="bW9jayBhZGlv"),
    )


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

    async def test_transcribe_with_google_gemini_interactions_success(self):
        service = _make_service()
        service.config = SimpleNamespace(
            get_provider_settings=lambda name: {"base_url": "https://generativelanguage.googleapis.com/v1beta"}
        )
        fake_response = _FakeResponse({
            "output_text": "Hello Gemini transcribe.",
            "duration": 5.5,
            "words": [
                {"text": "Hello", "start_time": 0.0, "end_time": 0.4},
                {"text": "Gemini", "start_time": 0.5, "end_time": 1.2},
                {"text": "transcribe.", "start_time": 1.3, "end_time": 2.0},
            ],
        })
        fake_client = _FakeClient(fake_response)
        with patch("services.transcription_service.httpx.AsyncClient", return_value=fake_client), \
             _file_guards()[0], _file_guards()[1], _file_guards()[2]:
            result = await service._transcribe_with_google_gemini(Path("sample.wav"), api_key="sk-goog")

        self.assertEqual(result["text"], "Hello Gemini transcribe.")
        self.assertEqual(result["duration_seconds"], 5.5)
        self.assertEqual(len(result["words"]), 3)
        self.assertEqual(result["words"][0]["text"], "Hello")
        self.assertEqual(result["words"][0]["start"], 0.0)

        # Check payload
        self.assertEqual(len(fake_client.requests), 1)
        req = fake_client.requests[0]
        self.assertIn("interactions", req["url"])
        self.assertEqual(req["json"]["model"], GEMINI_TRANSCRIBE_MODEL)
        self.assertEqual(req["headers"]["x-goog-api-key"], "sk-goog")

    async def test_transcribe_with_google_gemini_generate_content_fallback(self):
        service = _make_service()
        service.config = SimpleNamespace(
            get_provider_settings=lambda name: {}
        )
        # First call (interactions) returns 404, second (generateContent) succeeds
        class FallbackClient:
            def __init__(self):
                self.calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None, **kw):
                self.calls += 1
                if "interactions" in url:
                    return _FakeResponse({}, status_code=404, text="Not Found")
                return _FakeResponse({
                    "candidates": [
                        {"content": {"parts": [{"text": "Transcribed fallback text"}]}}
                    ],
                    "usage": {"duration_seconds": 3.0},
                })

        with patch("services.transcription_service.httpx.AsyncClient", return_value=FallbackClient()), \
             _file_guards()[0], _file_guards()[1], _file_guards()[2]:
            result = await service._transcribe_with_google_gemini(Path("sample.mp3"), api_key="sk-goog")

        self.assertEqual(result["text"], "Transcribed fallback text")
        self.assertEqual(result["duration_seconds"], 3.0)

    async def test_transcribe_file_explicit_google_provider(self):
        service = _make_service()
        service._google_key = lambda: "sk-goog"
        service._transcribe_with_google_gemini = AsyncMock(
            return_value={"text": "Google STT", "duration_seconds": 4.2, "words": None}
        )

        with _file_guards()[0], _file_guards()[1]:
            for p in ["google", "gemini", "gemini-3.5-transcribe", "google-transcribe"]:
                res = await service.transcribe_file("audio.wav", provider=p)
                self.assertEqual(res["provider"], "google")
                self.assertEqual(res["text"], "Google STT")

    async def test_transcribe_file_missing_google_key_raises(self):
        service = _make_service()
        service._google_key = lambda: ""

        with _file_guards()[0], _file_guards()[1]:
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

        with _file_guards()[0], _file_guards()[1]:
            res = await service.transcribe_file("audio.wav")
            self.assertEqual(res["provider"], "google")
            self.assertEqual(res["text"], "Auto Google STT")


if __name__ == "__main__":
    unittest.main()
