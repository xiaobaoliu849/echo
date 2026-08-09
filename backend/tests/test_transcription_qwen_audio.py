"""Tests for the Qwen-Audio-3.0-ASR-Flash (Fun-ASR Flash) transcription provider.

Covers:
  - request payload / headers against the multimodal-generation API contract
  - response parsing (text, word-level timestamps ms->s, usage duration)
  - provider aliases in transcribe_file (dashscope/qwen/funasr -> new model,
    qwen-legacy -> old compatible-mode model)
  - auto-select prefers Qwen-Audio (word timestamps) over MiMo
  - base64 size guard and language_hints cap
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.transcription_service import (
    QWEN_AUDIO_ASR_MAX_BASE64_BYTES,
    QWEN_AUDIO_ASR_MODEL,
    QWEN_AUDIO_ASR_PATH,
    TranscriptionService,
)


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("POST", "https://example.invalid")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(self.text, request=request, response=response)

    def json(self):
        return self._payload


class _FakeClient:
    """Captures the last POST request and returns a canned response."""

    def __init__(self, response: _FakeResponse):
        self.response = response
        self.requests: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None, **kwargs):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return self.response


DOC_EXAMPLE_PAYLOAD = {
    "output": {
        "sentence": {
            "begin_time": 760,
            "channel_id": 0,
            "end_time": 3800,
            "sentence_end": True,
            "sentence_id": 1,
            "text": "Hello World，这里是阿里巴巴语音实验室。",
            "words": [
                {"begin_time": 760, "end_time": 1040, "fixed": True, "punctuation": "", "text": "Hello"},
                {"begin_time": 1040, "end_time": 1240, "fixed": True, "punctuation": "，", "text": " World"},
                {"begin_time": 1360, "end_time": 1880, "fixed": True, "punctuation": "", "text": "这里是"},
                {"begin_time": 1880, "end_time": 2520, "fixed": True, "punctuation": "", "text": "阿里巴巴"},
                {"begin_time": 2520, "end_time": 2840, "fixed": True, "punctuation": "", "text": "语音"},
                {"begin_time": 2840, "end_time": 3800, "fixed": True, "punctuation": "。", "text": "实验室"},
            ],
        },
        "text": "Hello World，这里是阿里巴巴语音实验室。",
    },
    "usage": {"duration": 4},
    "request_id": "40e0734d-096f-9ae3-86c1-a8c013287561",
}


def _make_service() -> TranscriptionService:
    service = TranscriptionService.__new__(TranscriptionService)
    # Bypass __init__ (config / filesystem) — tests stub what they need.
    return service


class QwenAudioAsrRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_headers_and_response_parsing(self):
        service = _make_service()
        fake_client = _FakeClient(_FakeResponse(DOC_EXAMPLE_PAYLOAD))
        audio_path = Path("sample.wav")

        with (
            patch.object(Path, "read_bytes", return_value=b"fake-audio-bytes"),
            patch.object(service, "_dashscope_async_base_url", return_value="https://dashscope.aliyuncs.com/api/v1"),
            patch("services.transcription_service.httpx.AsyncClient", return_value=fake_client),
        ):
            result = await service._transcribe_with_qwen_audio_asr(
                audio_path,
                "sk-test-key",
                language_hints=["zh", "en", "ja", "ko", "vi"],  # 5 -> capped at 4
                vocabulary={"通义千问": 5},
            )

        self.assertEqual(len(fake_client.requests), 1)
        request = fake_client.requests[0]

        self.assertEqual(
            request["url"],
            f"https://dashscope.aliyuncs.com/api/v1{QWEN_AUDIO_ASR_PATH}",
        )
        headers = request["headers"]
        self.assertEqual(headers["Authorization"], "Bearer sk-test-key")
        self.assertEqual(headers["X-DashScope-SSE"], "disable")

        payload = request["json"]
        self.assertEqual(payload["model"], QWEN_AUDIO_ASR_MODEL)
        parameters = payload["parameters"]
        self.assertEqual(parameters["format"], "wav")
        self.assertEqual(parameters["language_hints"], ["zh", "en", "ja", "ko"])
        self.assertEqual(parameters["vocabulary"], {"通义千问": 5})

        messages = payload["input"]["messages"]
        self.assertEqual(len(messages), 1)
        content = messages[0]["content"][0]
        self.assertEqual(content["type"], "input_audio")
        self.assertTrue(content["input_audio"]["data"].startswith("data:audio/wav;base64,"))

        self.assertEqual(result["text"], "Hello World，这里是阿里巴巴语音实验室。")
        self.assertEqual(result["duration_seconds"], 4.0)
        self.assertIsNotNone(result["words"])
        self.assertEqual(len(result["words"]), 6)
        self.assertEqual(result["words"][0], {"text": "Hello", "start": 0.76, "end": 1.04})
        self.assertEqual(result["words"][-1]["end"], 3.8)

    async def test_mp3_uses_mpeg_mime(self):
        service = _make_service()
        fake_client = _FakeClient(_FakeResponse(DOC_EXAMPLE_PAYLOAD))
        with (
            patch.object(Path, "read_bytes", return_value=b"x"),
            patch.object(service, "_dashscope_async_base_url", return_value="https://dashscope.aliyuncs.com/api/v1"),
            patch("services.transcription_service.httpx.AsyncClient", return_value=fake_client),
        ):
            await service._transcribe_with_qwen_audio_asr(Path("clip.mp3"), "sk-key")

        content = fake_client.requests[0]["json"]["input"]["messages"][0]["content"][0]
        self.assertTrue(content["input_audio"]["data"].startswith("data:audio/mpeg;base64,"))
        self.assertEqual(fake_client.requests[0]["json"]["parameters"]["format"], "mp3")

    async def test_rejects_audio_above_base64_limit(self):
        service = _make_service()
        oversized = b"x" * (QWEN_AUDIO_ASR_MAX_BASE64_BYTES + 1)
        with patch.object(Path, "read_bytes", return_value=oversized):
            with self.assertRaises(ValueError):
                await service._transcribe_with_qwen_audio_asr(Path("big.wav"), "sk-key")

    async def test_empty_transcript_raises(self):
        service = _make_service()
        fake_client = _FakeClient(_FakeResponse({"output": {"text": ""}, "usage": {}}))
        with (
            patch.object(Path, "read_bytes", return_value=b"x"),
            patch.object(service, "_dashscope_async_base_url", return_value="https://dashscope.aliyuncs.com/api/v1"),
            patch("services.transcription_service.httpx.AsyncClient", return_value=fake_client),
        ):
            with self.assertRaises(RuntimeError):
                await service._transcribe_with_qwen_audio_asr(Path("a.wav"), "sk-key")

    async def test_http_error_wrapped_with_provider_name(self):
        service = _make_service()
        fake_client = _FakeClient(_FakeResponse({}, status_code=401, text="Invalid API-key"))
        with (
            patch.object(Path, "read_bytes", return_value=b"x"),
            patch.object(service, "_dashscope_async_base_url", return_value="https://dashscope.aliyuncs.com/api/v1"),
            patch("services.transcription_service.httpx.AsyncClient", return_value=fake_client),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await service._transcribe_with_qwen_audio_asr(Path("a.wav"), "sk-key")
        self.assertIn("Qwen-Audio ASR request failed", str(ctx.exception))


class WordExtractionTests(unittest.TestCase):
    def test_extracts_words_from_sentence(self):
        words = TranscriptionService._extract_qwen_audio_words(DOC_EXAMPLE_PAYLOAD["output"])
        self.assertIsNotNone(words)
        self.assertEqual(words[0]["start"], 0.76)
        self.assertEqual(words[-1]["end"], 3.8)

    def test_extracts_words_from_sentences_list(self):
        output = {
            "sentences": [
                {"words": [{"text": "你好", "begin_time": 0, "end_time": 500}]},
                {"words": [{"text": "世界", "begin_time": 600, "end_time": 1200}]},
            ]
        }
        words = TranscriptionService._extract_qwen_audio_words(output)
        self.assertEqual(
            words,
            [
                {"text": "你好", "start": 0.0, "end": 0.5},
                {"text": "世界", "start": 0.6, "end": 1.2},
            ],
        )

    def test_returns_none_when_no_words(self):
        self.assertIsNone(TranscriptionService._extract_qwen_audio_words({}))
        self.assertIsNone(TranscriptionService._extract_qwen_audio_words({"sentence": {"text": "hi"}}))


class ProviderRoutingTests(unittest.IsolatedAsyncioTestCase):
    def _service_with_keys(self, keys: dict[str, str]) -> TranscriptionService:
        service = _make_service()
        for name in ("deepgram", "openai", "assemblyai", "doubao", "xiaomi", "dashscope"):
            key = keys.get(name, "")
            setattr(service, f"_{name}_key", lambda k=key: k)
        return service

    async def test_qwen_aliases_route_to_qwen_audio_asr(self):
        for alias in ("dashscope", "qwen", "qwen-audio", "qwen-audio-asr", "funasr", "fun-asr"):
            service = self._service_with_keys({"dashscope": "sk"})
            service._transcribe_with_qwen_audio_asr = AsyncMock(return_value={"text": "ok", "duration_seconds": None, "words": None})
            with (
                patch("services.transcription_service.Path.is_file", return_value=True),
                patch("services.transcription_service.Path.stat", return_value=SimpleNamespace(st_size=10)),
            ):
                result = await service.transcribe_file("a.wav", provider=alias)
            self.assertEqual(result["text"], "ok", alias)
            service._transcribe_with_qwen_audio_asr.assert_awaited_once()

    async def test_qwen_legacy_routes_to_compatible_mode(self):
        service = self._service_with_keys({"dashscope": "sk"})
        service._transcribe_with_openai_asr = AsyncMock(return_value={"text": "legacy", "duration_seconds": None, "words": None})
        service._transcribe_with_qwen_audio_asr = AsyncMock()
        with (
            patch("services.transcription_service.Path.is_file", return_value=True),
            patch("services.transcription_service.Path.stat", return_value=SimpleNamespace(st_size=10)),
        ):
            result = await service.transcribe_file("a.wav", provider="qwen-legacy")
        self.assertEqual(result["text"], "legacy")
        service._transcribe_with_openai_asr.assert_awaited_once()
        service._transcribe_with_qwen_audio_asr.assert_not_awaited()

    async def test_auto_select_prefers_qwen_audio_over_mimo(self):
        # With only dashscope + xiaomi keys, auto-select must pick Qwen-Audio
        # because it returns word-level timestamps (MiMo does not).
        service = self._service_with_keys({"dashscope": "sk", "xiaomi": "sk2"})
        service._transcribe_with_qwen_audio_asr = AsyncMock(return_value={"text": "qwen", "duration_seconds": None, "words": []})
        service._transcribe_with_openai_asr = AsyncMock()
        with (
            patch("services.transcription_service.Path.is_file", return_value=True),
            patch("services.transcription_service.Path.stat", return_value=SimpleNamespace(st_size=10)),
        ):
            result = await service.transcribe_file("a.wav")
        self.assertEqual(result["text"], "qwen")
        service._transcribe_with_openai_asr.assert_not_awaited()

    async def test_missing_dashscope_key_rejected(self):
        service = self._service_with_keys({})
        with (
            patch("services.transcription_service.Path.is_file", return_value=True),
            patch("services.transcription_service.Path.stat", return_value=SimpleNamespace(st_size=10)),
        ):
            with self.assertRaises(ValueError):
                await service.transcribe_file("a.wav", provider="qwen-audio")


if __name__ == "__main__":
    unittest.main()
