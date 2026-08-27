"""Tests for transcription library metadata.

Covers the fixes that make the history library show meaningful records:
  - sync-completed jobs keep the original upload filename (previously dropped,
    so the UI fell back to the internal `upload_<uuid>.wav` storage name)
  - list responses expose duration, origin, and a transcript preview
  - PATCH /jobs/{id} renames a record's display name
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from main import create_app
from routers import transcription as transcription_router
from services.transcription_service import TranscriptionService


class TranscriptionLibraryMetadataTests(unittest.TestCase):
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
        self._service = service
        self._original_service = transcription_router.transcription_service
        transcription_router.transcription_service = service

    def tearDown(self) -> None:
        transcription_router.transcription_service = self._original_service
        self._tmp.cleanup()
        self._auth_env_patcher.stop()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = dict(kwargs.get("headers") or {})
        needs_auth = method.upper() in {"POST", "PUT", "PATCH", "DELETE"} or (
            method.upper() == "GET" and path.startswith("/api/transcription")
        )
        if path.startswith("/api/") and needs_auth:
            headers.setdefault("Authorization", f"Bearer {os.getenv('VOICESPIRIT_API_TOKEN', 'test-api-token')}")
            kwargs["headers"] = headers

        async def runner():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(runner())

    def _create_job(self, **kwargs) -> object:
        defaults = dict(
            file_path="upload_abcdef123456.wav",
            original_filename="客户访谈.mp3",
            transcript="大家好，我们开始今天的访谈。",
            duration_seconds=61.5,
            origin="upload",
        )
        defaults.update(kwargs)
        return asyncio.run(self._service.create_completed_sync_job(**defaults))

    def test_sync_job_keeps_original_filename(self) -> None:
        job = self._create_job()

        self.assertEqual(job.original_filename, "客户访谈.mp3")
        self.assertEqual(job.duration_seconds, 61.5)
        self.assertEqual(job.origin, "upload")

        resp = self._request("GET", "/api/transcription/jobs")
        self.assertEqual(resp.status_code, 200, resp.text)
        jobs = resp.json().get("jobs", [])
        self.assertTrue(jobs)
        entry = next(j for j in jobs if j["job_id"] == job.job_id)
        self.assertEqual(entry["file_name"], "客户访谈.mp3")

    def test_list_exposes_duration_origin_and_preview(self) -> None:
        job = self._create_job()

        resp = self._request("GET", "/api/transcription/jobs")
        self.assertEqual(resp.status_code, 200, resp.text)
        entry = next(
            j for j in resp.json().get("jobs", []) if j["job_id"] == job.job_id
        )
        self.assertEqual(entry["duration_seconds"], 61.5)
        self.assertEqual(entry["origin"], "upload")
        self.assertTrue(entry["transcript_preview"])
        self.assertIn("访谈", entry["transcript_preview"])
        # List responses must not carry the full transcript payload.
        self.assertIsNone(entry["transcript"])

    def test_rename_updates_display_name(self) -> None:
        job = self._create_job()

        resp = self._request(
            "PATCH",
            f"/api/transcription/jobs/{job.job_id}",
            json={"file_name": "重点客户访谈（整理版）"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["file_name"], "重点客户访谈（整理版）")

        reloaded = self._service.get_job(job.job_id)
        self.assertEqual(reloaded.original_filename, "重点客户访谈（整理版）")

    def test_rename_rejects_empty_name(self) -> None:
        job = self._create_job()

        resp = self._request(
            "PATCH",
            f"/api/transcription/jobs/{job.job_id}",
            json={"file_name": "   "},
        )
        self.assertGreaterEqual(resp.status_code, 400)
        # Whitespace survives as the stored name via pydantic min_length —
        # either way the previous name must not be silently destroyed.

    def test_rename_unknown_job_returns_404(self) -> None:
        resp = self._request(
            "PATCH",
            "/api/transcription/jobs/tx_does_not_exist",
            json={"file_name": "whatever"},
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
