"""Tests for the save-text endpoint persisting word-level timestamps.

Covers the realtime-saved-job path (Gap C):
  - POST /api/transcription/jobs/save-text with words persists them
  - the persisted words are recoverable via GET /api/transcription/jobs/{id}/words
  - the existing no-words behaviour (404 on GET /words) is preserved
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from main import create_app
from routers import transcription as transcription_router
from services.transcription_service import TranscriptionService


class SaveTextWordsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_env_patcher = patch.dict(
            os.environ,
            {
                "VOICESPIRIT_API_TOKEN": "test-api-token",
                "VOICESPIRIT_ADMIN_TOKEN": "test-admin-token",
            },
            clear=False,
        )
        self._auth_env_patcher.start()
        self.app = create_app()

        self._tmp = tempfile.TemporaryDirectory()
        service = TranscriptionService()
        service.jobs_dir = Path(self._tmp.name)
        service.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._original_service = transcription_router.transcription_service
        transcription_router.transcription_service = service

    def tearDown(self) -> None:
        transcription_router.transcription_service = self._original_service
        self._tmp.cleanup()
        self._auth_env_patcher.stop()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = dict(kwargs.get("headers") or {})
        if path.startswith("/api/") and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers.setdefault("Authorization", f"Bearer {os.getenv('VOICESPIRIT_API_TOKEN', 'test-api-token')}")
            kwargs["headers"] = headers

        async def runner():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(runner())

    def test_save_text_persists_words(self) -> None:
        words = [
            {"text": "好", "start": 0.17, "end": 0.295},
            {"text": "知道了", "start": 0.295, "end": 0.92},
        ]
        save_resp = self._request(
            "POST",
            "/api/transcription/jobs/save-text",
            json={"transcript": "好，知道了", "file_name": "实时转写", "words": words},
        )
        self.assertEqual(save_resp.status_code, 200, save_resp.text)
        body = save_resp.json()
        job_id = body.get("job_id")
        self.assertTrue(job_id)

        words_resp = self._request("GET", f"/api/transcription/jobs/{job_id}/words")
        self.assertEqual(words_resp.status_code, 200, words_resp.text)
        self.assertEqual(words_resp.json(), words)

    def test_save_text_without_words_preserves_404(self) -> None:
        save_resp = self._request(
            "POST",
            "/api/transcription/jobs/save-text",
            json={"transcript": "只有文本", "file_name": "实时转写"},
        )
        self.assertEqual(save_resp.status_code, 200, save_resp.text)
        job_id = save_resp.json().get("job_id")
        self.assertTrue(job_id)

        words_resp = self._request("GET", f"/api/transcription/jobs/{job_id}/words")
        self.assertEqual(words_resp.status_code, 404)

    def test_save_text_rejects_nonempty_transcript(self) -> None:
        # Guard against regressing the existing validation.
        resp = self._request("POST", "/api/transcription/jobs/save-text", json={"transcript": "   "})
        self.assertGreaterEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()