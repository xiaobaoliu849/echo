"""Tests for ASR engine/provider selection and actual-engine echo.

Covers:
  - transcribe_file annotates the actual provider used (explicit + auto-select)
  - async ("链式") provider->model mapping, defaults, and submission payload
  - realtime streaming model pass-through and per-model language-hint capping
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from routers.transcription import _parse_realtime_config
from services.realtime_asr_service import (
    FUN_ASR_REALTIME_MODEL,
    QWEN_AUDIO_ASR_STREAMING_MODEL,
    build_streaming_asr_session,
)
from services.transcription_service import (
    ASYNC_MODEL_BY_PROVIDER,
    QWEN_ASR_ASYNC_MODEL,
    QWEN_AUDIO_ASR_ASYNC_MODEL,
    TranscriptionJob,
    TranscriptionService,
)


def _make_service() -> TranscriptionService:
    return TranscriptionService.__new__(TranscriptionService)


def _service_with_keys(keys: dict[str, str]) -> TranscriptionService:
    service = _make_service()
    for name in ("deepgram", "google", "openai", "assemblyai", "doubao", "xiaomi", "dashscope"):
        key = keys.get(name, "")
        setattr(service, f"_{name}_key", lambda k=key: k)
    return service


class _Cfg:
    def reload(self):
        return None

    def get_all(self):
        return {"api_keys": {"dashscope_api_key": "sk"}}

    def get_provider_settings(self, name):
        return {}


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
    )


class ProviderEchoTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, provider, mocks, keys):
        service = _service_with_keys(keys)
        for attr, ret in mocks.items():
            setattr(service, attr, AsyncMock(return_value=ret))
        with _file_guards()[0], _file_guards()[1]:
            return await service.transcribe_file("a.wav", provider=provider)

    async def test_explicit_qwen_echoes_dashscope(self):
        result = await self._run(
            "dashscope",
            {"_transcribe_with_qwen_audio_asr": {"text": "ok", "duration_seconds": None, "words": None}},
            {"dashscope": "sk"},
        )
        self.assertEqual(result["provider"], "dashscope")

    async def test_explicit_deepgram_echoes_deepgram(self):
        result = await self._run(
            "deepgram",
            {"_transcribe_with_deepgram": {"text": "ok", "duration_seconds": None, "words": None}},
            {"deepgram": "sk"},
        )
        self.assertEqual(result["provider"], "deepgram")

    async def test_explicit_whisper_normalizes_to_openai(self):
        result = await self._run(
            "whisper",
            {"_transcribe_with_openai_whisper": {"text": "ok", "duration_seconds": None, "words": None}},
            {"openai": "sk"},
        )
        self.assertEqual(result["provider"], "openai")

    async def test_explicit_google_echoes_google(self):
        result = await self._run(
            "google",
            {"_transcribe_with_google_gemini": {"text": "ok", "duration_seconds": None, "words": None}},
            {"google": "sk"},
        )
        self.assertEqual(result["provider"], "google")

    async def test_auto_xiaomi_only_echoes_xiaomi(self):
        service = _service_with_keys({"xiaomi": "sk"})
        service._mimo_chat_url = lambda: "https://example.invalid"
        service._transcribe_with_openai_asr = AsyncMock(
            return_value={"text": "ok", "duration_seconds": None, "words": None}
        )
        with _file_guards()[0], _file_guards()[1]:
            result = await service.transcribe_file("a.wav")
        self.assertEqual(result["provider"], "xiaomi")


class JobProviderPersistenceTests(unittest.TestCase):
    """update_job must persist provider independently of memory_saved (a past
    nesting bug only wrote provider when memory_saved was also being set)."""

    def test_update_provider_without_memory_saved(self):
        service = _make_service()
        job = TranscriptionJob(
            job_id="tx_test1", file_path="/x", mode="sync", status="completed"
        )
        service.get_job = lambda _job_id: job
        service._write_job = lambda j: j

        updated = service.update_job("tx_test1", provider="deepgram")
        self.assertEqual(updated.provider, "deepgram")

    def test_update_provider_is_persisted(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            svc = _make_service()
            svc.jobs_dir = Path(tmp)
            svc._now_iso = lambda: "2026-08-02T00:00:00Z"
            job = svc._write_job(
                TranscriptionJob(
                    job_id="tx_p1", file_path="/x", mode="sync", status="completed"
                )
            )
            svc.update_job("tx_p1", provider="assemblyai")
            stored = svc.get_job("tx_p1")
            self.assertEqual(stored.provider, "assemblyai")


class AsyncModelSelectionTests(unittest.IsolatedAsyncioTestCase):
    def test_provider_model_mapping(self):
        self.assertEqual(ASYNC_MODEL_BY_PROVIDER["qwen-filetrans"], QWEN_ASR_ASYNC_MODEL)
        self.assertEqual(ASYNC_MODEL_BY_PROVIDER["qwen-audio-filetrans"], QWEN_AUDIO_ASR_ASYNC_MODEL)
        self.assertNotEqual(QWEN_ASR_ASYNC_MODEL, QWEN_AUDIO_ASR_ASYNC_MODEL)

    async def _submit_model(self, provider):
        service = _make_service()
        service._dashscope_key = lambda: "sk"
        service._dashscope_async_base_url = lambda: "https://dashscope.aliyuncs.com/api/v1"
        fake_client = _FakeClient(_FakeResponse({"output": {"task_id": "t1"}}))
        with patch("services.transcription_service.httpx.AsyncClient", return_value=fake_client):
            await service._submit_remote_job_from_url("https://example.com/a.wav", provider=provider)
        return fake_client.requests[0]["json"]["model"]

    async def test_submit_maps_new_filetrans_model(self):
        self.assertEqual(await self._submit_model("qwen-audio-filetrans"), QWEN_AUDIO_ASR_ASYNC_MODEL)

    async def test_submit_maps_legacy_filetrans_model(self):
        self.assertEqual(await self._submit_model("qwen-filetrans"), QWEN_ASR_ASYNC_MODEL)

    async def test_submit_defaults_to_legacy_when_provider_none(self):
        self.assertEqual(await self._submit_model(None), QWEN_ASR_ASYNC_MODEL)


class RealtimeModelTests(unittest.TestCase):
    def test_parse_config_accepts_valid_streaming_model(self):
        config = _parse_realtime_config({"model": FUN_ASR_REALTIME_MODEL})
        self.assertEqual(config["model"], FUN_ASR_REALTIME_MODEL)

    def test_parse_config_rejects_unknown_model(self):
        self.assertNotIn("model", _parse_realtime_config({"model": "not-a-model"}))

    def test_build_session_defaults_to_qwen_streaming(self):
        session = build_streaming_asr_session(_Cfg())
        self.assertEqual(session._model, QWEN_AUDIO_ASR_STREAMING_MODEL)

    def test_build_session_caps_hints_for_fun_asr(self):
        session = build_streaming_asr_session(
            _Cfg(), language_hints=["zh", "en", "ja"], model=FUN_ASR_REALTIME_MODEL
        )
        self.assertEqual(session._model, FUN_ASR_REALTIME_MODEL)
        self.assertEqual(session._language_hints, ["zh"])


if __name__ == "__main__":
    unittest.main()
