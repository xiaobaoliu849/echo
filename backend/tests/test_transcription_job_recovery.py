"""Tests for transcription job-store self-healing.

Covers:
  - reap_stale_active_job: locally-interrupted transient records flip to
    failed; fresh, remote-managed and completed records pass through.
  - list_jobs reaps stale records before filtering (no eternal "排队中" rows).
  - _evict_old_jobs ignores translation sidecars when counting jobs.
  - delete_job removes translation/burn/subtitle sidecars with the record.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.transcription_service import (
    INTERRUPTED_JOB_STALE_SECONDS,
    JOB_INTERRUPTED_MESSAGE,
    TranscriptionService,
)


def _make_service() -> TranscriptionService:
    service = TranscriptionService.__new__(TranscriptionService)
    service.jobs_dir = Path(tempfile.mkdtemp(prefix="vs_asr_recovery_test_"))
    return service


class JobStoreRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _make_service()

    def _write_record(
        self,
        job_id: str,
        status: str,
        *,
        mode: str = "async",
        remote_job_id: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        payload = {
            "job_id": job_id,
            "file_path": "",
            "mode": mode,
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
            "transcript_path": None,
            "error": None,
            "remote_job_id": remote_job_id,
            "source_url": None,
            "memory_saved": False,
            "original_filename": f"{job_id}.mp4",
            "provider": None,
            "progress": None,
        }
        (self.service.jobs_dir / f"{job_id}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    @staticmethod
    def _stale_iso() -> str:
        stale_ts = datetime.now(timezone.utc) - timedelta(
            seconds=INTERRUPTED_JOB_STALE_SECONDS + 60
        )
        return stale_ts.isoformat()

    def test_reaps_stale_local_queued_job(self):
        self._write_record("tx_old_local", "queued", updated_at=self._stale_iso())

        job = self.service.get_job("tx_old_local")
        assert job is not None
        reaped = self.service.reap_stale_active_job(job)

        self.assertEqual(reaped.status, "failed")
        self.assertIn("重试", str(reaped.error))
        self.assertIsNotNone(reaped.error)
        # Persisted, not just mutated in memory.
        reread = self.service.get_job("tx_old_local")
        assert reread is not None
        self.assertEqual(reread.status, "failed")

    def test_leaves_fresh_active_job_alone(self):
        self._write_record("tx_fresh", "running", updated_at=datetime.now(timezone.utc).isoformat())

        job = self.service.get_job("tx_fresh")
        assert job is not None
        untouched = self.service.reap_stale_active_job(job)

        self.assertEqual(untouched.status, "running")
        self.assertIsNone(untouched.error)

    def test_never_reaps_remote_managed_or_terminal_records(self):
        self._write_record(
            "tx_remote",
            "submitted",
            remote_job_id="dashscope-task-1",
            updated_at=self._stale_iso(),
        )
        self._write_record("tx_done", "completed", updated_at=self._stale_iso())
        self._write_record(
            "tx_sync_done", "completed", mode="sync", updated_at=self._stale_iso()
        )

        expectations = {"tx_remote": "submitted", "tx_done": "completed", "tx_sync_done": "completed"}
        for job_id, expected_status in expectations.items():
            job = self.service.get_job(job_id)
            assert job is not None
            passed = self.service.reap_stale_active_job(job)
            self.assertEqual(passed.status, expected_status)

    def test_list_jobs_reaps_before_filtering(self):
        self._write_record("tx_stale_row", "queued", updated_at=self._stale_iso())

        rows = {job.job_id: job for job in self.service.list_jobs()}
        self.assertEqual(rows["tx_stale_row"].status, "failed")
        self.assertIn(JOB_INTERRUPTED_MESSAGE, str(rows["tx_stale_row"].error))

        # The failed filter now matches the reaped row...
        failed_only = self.service.list_jobs(statuses={"failed"})
        self.assertEqual([job.job_id for job in failed_only], ["tx_stale_row"])
        # ...and it no longer shows up as a queued task.
        queued_only = self.service.list_jobs(statuses={"queued"})
        self.assertEqual(queued_only, [])

    def test_eviction_ignores_translation_sidecars_when_counting(self):
        old_job = self.service.jobs_dir / "tx_aaa.json"
        new_job = self.service.jobs_dir / "tx_bbb.json"
        sidecar = self.service.jobs_dir / "tx_bbb_translation.json"
        old_job.write_text("{}", encoding="utf-8")
        new_job.write_text("{}", encoding="utf-8")
        sidecar.write_text("{}", encoding="utf-8")

        now = time.time()
        os.utime(sidecar, (now - 10_000, now - 10_000))  # oldest file overall
        os.utime(old_job, (now - 100, now - 100))
        os.utime(new_job, (now - 10, now - 10))

        # Cap of 2 real jobs: nothing should be evicted even though the
        # directory holds three tx_*.json files — sidecars are not jobs.
        self.service._evict_old_jobs(max_jobs=2)
        self.assertTrue(old_job.is_file())
        self.assertTrue(new_job.is_file())
        self.assertTrue(sidecar.is_file())

        # Cap of 1: the oldest REAL job goes, sidecars remain untouched.
        self.service._evict_old_jobs(max_jobs=1)
        self.assertFalse(old_job.is_file())
        self.assertTrue(new_job.is_file())
        self.assertTrue(sidecar.is_file())

    def test_delete_job_removes_translation_and_burn_sidecars(self):
        job_id = "tx_sidecar_full"
        self._write_record(job_id, "queued", updated_at=self._stale_iso())
        names = [
            f"{job_id}_translation.json",
            f"{job_id}_burn.srt",
            f"{job_id}_subtitled.mp4",
        ]
        paths = [self.service.jobs_dir / name for name in names]
        for path in paths:
            path.write_text("x", encoding="utf-8")

        self.assertTrue(self.service.delete_job(job_id))
        for path in [self.service.jobs_dir / f"{job_id}.json", *paths]:
            self.assertFalse(path.exists(), path.name)


if __name__ == "__main__":
    unittest.main()
