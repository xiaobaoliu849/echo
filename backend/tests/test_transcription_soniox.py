"""Unit tests for Soniox speech recognition (ASR) integration in TranscriptionService."""
from __future__ import annotations

import asyncio
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from services.transcription_service import (
    SONIOX_BASE_URL,
    SONIOX_DEFAULT_MODEL,
    TranscriptionService,
)


def _make_service() -> TranscriptionService:
    service = TranscriptionService.__new__(TranscriptionService)
    service.config = MagicMock()
    service.config.reload = MagicMock()
    service.config.peek_setting = MagicMock(return_value="")
    service.config.get_provider_settings = MagicMock(return_value={})
    return service


class _FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "https://api.soniox.com/v1")
            resp = httpx.Response(self.status_code, request=req, text=self.text)
            raise httpx.HTTPStatusError(self.text, request=req, response=resp)

    def json(self):
        return self._payload


@contextmanager
def _file_guards():
    with patch("services.transcription_service.Path.is_file", return_value=True), \
         patch("services.transcription_service.Path.stat", return_value=SimpleNamespace(st_size=1024)), \
         patch("services.transcription_service.Path.read_bytes", return_value=b"fake audio data"):
        yield


class SonioxTranscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_with_soniox_success(self):
        service = _make_service()
        file_path = Path("test_audio.mp3")

        mock_client = AsyncMock()
        # 1. upload -> file_id
        mock_client.post.side_effect = [
            _FakeResponse({"id": "file_test_123"}),  # /files
            _FakeResponse({"id": "trans_test_456", "status": "queued"}),  # /transcriptions
        ]
        # 2. poll -> completed
        # 3. get transcript -> text and tokens
        mock_client.get.side_effect = [
            _FakeResponse({"id": "trans_test_456", "status": "completed"}),  # /transcriptions/{id}
            _FakeResponse({
                "id": "trans_test_456",
                "text": "Hello world from Soniox",
                "tokens": [
                    {"text": "Hello", "start_ms": 100, "end_ms": 400, "confidence": 0.98},
                    {"text": "world", "start_ms": 420, "end_ms": 800, "confidence": 0.99},
                    {"text": "from", "start_ms": 820, "end_ms": 1000, "confidence": 0.95},
                    {"text": "Soniox", "start_ms": 1020, "end_ms": 1500, "confidence": 0.99},
                ]
            }),  # /transcriptions/{id}/transcript
        ]
        mock_client.delete.return_value = _FakeResponse({"status": "deleted"})

        with patch("services.transcription_service.httpx.AsyncClient") as mock_client_cls, \
             _file_guards():
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            result = await service._transcribe_with_soniox(file_path, "test-soniox-key")

            self.assertEqual(result["text"], "Hello world from Soniox")
            self.assertEqual(len(result["words"]), 4)
            self.assertEqual(result["words"][0], {"text": "Hello", "start": 0.1, "end": 0.4})
            self.assertEqual(result["words"][3], {"text": "Soniox", "start": 1.02, "end": 1.5})
            self.assertEqual(result["duration_seconds"], 1.5)

            # Ensure cleanup DELETE was called
            mock_client.delete.assert_called_once_with(
                f"{SONIOX_BASE_URL}/files/file_test_123",
                headers={"Authorization": "Bearer test-soniox-key"}
            )

    async def test_transcribe_with_soniox_upload_failure(self):
        service = _make_service()
        file_path = Path("test_audio.mp3")

        mock_client = AsyncMock()
        mock_client.post.return_value = _FakeResponse({}, status_code=401, text="Unauthorized: Invalid key")

        with patch("services.transcription_service.httpx.AsyncClient") as mock_client_cls, \
             _file_guards():
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with self.assertRaises(RuntimeError) as ctx:
                await service._transcribe_with_soniox(file_path, "invalid-key")
            self.assertIn("Soniox file upload failed", str(ctx.exception))

    async def test_transcribe_with_soniox_task_failure(self):
        service = _make_service()
        file_path = Path("test_audio.mp3")

        mock_client = AsyncMock()
        mock_client.post.side_effect = [
            _FakeResponse({"id": "file_test_789"}),
            _FakeResponse({"id": "trans_test_999", "status": "queued"}),
        ]
        mock_client.get.return_value = _FakeResponse({
            "id": "trans_test_999",
            "status": "failed",
            "error_message": "Audio format corrupted"
        })
        mock_client.delete.return_value = _FakeResponse({})

        with patch("services.transcription_service.httpx.AsyncClient") as mock_client_cls, \
             _file_guards():
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with self.assertRaises(RuntimeError) as ctx:
                await service._transcribe_with_soniox(file_path, "test-key")
            self.assertIn("Audio format corrupted", str(ctx.exception))

            # Cleanup DELETE should still be called even on failure
            mock_client.delete.assert_called_once()

    async def test_transcribe_file_soniox_missing_key_raises(self):
        service = _make_service()
        service.config.peek_setting.return_value = ""

        with _file_guards():
            with self.assertRaises(ValueError) as ctx:
                await service.transcribe_file("test.mp3", provider="soniox")
            self.assertIn("Soniox API key not configured", str(ctx.exception))

    async def test_transcribe_file_soniox_explicit_provider(self):
        service = _make_service()
        service.config.peek_setting.return_value = "configured-soniox-key"
        service._transcribe_with_soniox = AsyncMock(return_value={
            "text": "Soniox transcription test",
            "words": [{"text": "Soniox", "start": 0.0, "end": 0.5}],
            "duration_seconds": 0.5
        })

        with _file_guards():
            result = await service.transcribe_file("test.mp3", provider="soniox")
            self.assertEqual(result["provider"], "soniox")
            self.assertEqual(result["text"], "Soniox transcription test")
            service._transcribe_with_soniox.assert_called_once()


if __name__ == "__main__":
    unittest.main()
