"""Tests for the long-audio / video transcription pipeline.

Covers:
  - chunk result merging (text join, word-timestamp offsets, durations)
  - transcribe_media routing: direct path vs ffmpeg preprocessing
  - video audio-track extraction and long-audio chunking flows
  - graceful fallback when ffmpeg is unavailable
  - background local chunked job lifecycle (completed / failed)
  - video container suffixes accepted by _validate_file
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services import audio_tools
from services.audio_tools import MediaProbe
from services.transcription_service import (
    CHUNK_TARGET_SECONDS,
    SYNC_MAX_DURATION_SECONDS,
    TranscriptionService,
)


def _make_service() -> TranscriptionService:
    service = TranscriptionService.__new__(TranscriptionService)
    service.jobs_dir = Path(tempfile.mkdtemp(prefix="vs_asr_test_"))
    return service


def _probe(duration: float, *, video: bool = False, audio: bool = True, size: int = 1000) -> MediaProbe:
    return MediaProbe(
        duration_seconds=duration,
        size_bytes=size,
        has_video_stream=video,
        has_audio_stream=audio,
    )


class MergeChunkResultsTests(unittest.TestCase):
    def test_merges_text_words_and_durations_with_offsets(self):
        results = [
            {
                "text": "第一段内容",
                "duration_seconds": 240.0,
                "words": [
                    {"text": "第一", "start": 0.5, "end": 1.0},
                    {"text": "段", "start": 1.0, "end": 1.4},
                ],
            },
            {
                "text": "第二段内容",
                "duration_seconds": 120.0,
                "words": [{"text": "第二", "start": 2.0, "end": 2.6}],
            },
        ]
        offsets = [0.0, 240.0]
        merged = TranscriptionService._merge_chunk_results(results, offsets)

        self.assertEqual(merged["text"], "第一段内容\n第二段内容")
        self.assertEqual(merged["duration_seconds"], 360.0)
        self.assertIsNotNone(merged["words"])
        self.assertEqual(len(merged["words"]), 3)
        # First-chunk words keep their positions…
        self.assertEqual(merged["words"][0], {"text": "第一", "start": 0.5, "end": 1.0})
        # …second-chunk words are shifted by the chunk start offset.
        self.assertEqual(
            merged["words"][2], {"text": "第二", "start": 242.0, "end": 242.6}
        )

    def test_skips_empty_chunks_and_missing_words(self):
        results = [
            {"text": "", "duration_seconds": 10.0, "words": None},
            {"text": "有声", "duration_seconds": 5.0, "words": []},
        ]
        merged = TranscriptionService._merge_chunk_results(results, [0.0, 10.0])
        self.assertEqual(merged["text"], "有声")
        self.assertEqual(merged["duration_seconds"], 15.0)
        self.assertIsNone(merged["words"])

    def test_duration_none_when_chunks_report_nothing(self):
        merged = TranscriptionService._merge_chunk_results(
            [{"text": "x", "duration_seconds": None, "words": None}], [0.0]
        )
        self.assertIsNone(merged["duration_seconds"])


class TranscribeMediaRoutingTests(unittest.IsolatedAsyncioTestCase):
    def _fake_file_patches(self):
        """The routing tests pass synthetic paths; skip on-disk validation."""
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(
            patch.object(TranscriptionService, "_validate_file", staticmethod(lambda path: None))
        )
        return stack

    async def test_short_small_audio_goes_direct(self):
        service = _make_service()
        service.transcribe_file = AsyncMock(
            return_value={"text": "ok", "duration_seconds": 30.0, "words": None}
        )
        probe = _probe(30.0, size=1024)
        with (
            self._fake_file_patches(),
            patch.object(audio_tools, "ffmpeg_available", return_value=True),
            patch.object(audio_tools, "probe_media", new=AsyncMock(return_value=probe)),
            patch.object(audio_tools, "transcode_for_asr", new=AsyncMock()) as transcode_mock,
        ):
            result = await service.transcribe_media(Path("clip.wav"))
        self.assertEqual(result["text"], "ok")
        service.transcribe_file.assert_awaited_once()
        # Direct path: original file is passed through untouched.
        called_path = service.transcribe_file.await_args.args[0]
        self.assertEqual(Path(called_path).name, "clip.wav")
        transcode_mock.assert_not_awaited()

    async def test_video_container_triggers_audio_extraction(self):
        service = _make_service()
        service.transcribe_file = AsyncMock(
            return_value={"text": "视频音轨", "duration_seconds": 60.0, "words": None}
        )
        original_probe = _probe(60.0, video=True, size=50 * 1024 * 1024)
        normalized_probe = _probe(60.0, size=500 * 1024)

        async def fake_probe(path: Path) -> MediaProbe:
            if path.name.startswith("normalized_"):
                return normalized_probe
            return original_probe

        async def fake_transcode(source: Path, output_path: Path) -> Path:
            output_path.write_bytes(b"fake-mp3")
            return output_path

        with (
            self._fake_file_patches(),
            patch.object(audio_tools, "ffmpeg_available", return_value=True),
            patch.object(audio_tools, "probe_media", new=AsyncMock(side_effect=fake_probe)),
            patch.object(audio_tools, "transcode_for_asr", new=AsyncMock(side_effect=fake_transcode)),
        ):
            result = await service.transcribe_media(Path("movie.mkv"))

        self.assertEqual(result["text"], "视频音轨")
        # The ASR call must receive the extracted/normalized audio, not the mkv.
        # Suffix is .mp3 when the local ffmpeg has an MP3 encoder, else .wav.
        called_path = service.transcribe_file.await_args.args[0]
        self.assertIn(Path(called_path).suffix, {".mp3", ".wav"})
        self.assertTrue(Path(called_path).name.startswith("normalized_"))

    async def test_long_audio_is_chunked_and_merged(self):
        service = _make_service()
        chunk_results = [
            {
                "text": "第一部分",
                "duration_seconds": float(CHUNK_TARGET_SECONDS),
                "words": [{"text": "开", "start": 1.0, "end": 1.5}],
                "provider": "dashscope",
            },
            {
                "text": "第二部分",
                "duration_seconds": 100.0,
                "words": [{"text": "结", "start": 2.0, "end": 2.5}],
                "provider": "dashscope",
            },
        ]
        service.transcribe_file = AsyncMock(side_effect=chunk_results)

        long_duration = float(SYNC_MAX_DURATION_SECONDS + 300)
        original_probe = _probe(long_duration, size=2 * 1024 * 1024)
        chunk_probe = _probe(float(CHUNK_TARGET_SECONDS), size=400 * 1024)

        async def fake_probe(path: Path) -> MediaProbe:
            if path.name.startswith("chunk_"):
                return chunk_probe
            return original_probe

        async def fake_transcode_split(source: Path, chunk_seconds: int, output_dir: Path) -> list[Path]:
            self.assertEqual(chunk_seconds, CHUNK_TARGET_SECONDS)
            return [output_dir / "chunk_0000.mp3", output_dir / "chunk_0001.mp3"]

        progress_messages: list[str] = []
        with (
            self._fake_file_patches(),
            patch.object(audio_tools, "ffmpeg_available", return_value=True),
            patch.object(audio_tools, "asr_limits", return_value=(SYNC_MAX_DURATION_SECONDS, CHUNK_TARGET_SECONDS)),
            patch.object(audio_tools, "probe_media", new=AsyncMock(side_effect=fake_probe)),
            patch.object(audio_tools, "transcode_and_split", new=AsyncMock(side_effect=fake_transcode_split)),
        ):
            result = await service.transcribe_media(
                Path("long.mp3"), on_progress=progress_messages.append
            )

        self.assertEqual(result["text"], "第一部分\n第二部分")
        self.assertEqual(service.transcribe_file.await_count, 2)
        # Words from chunk 2 are shifted by chunk 1's measured duration.
        words = result["words"]
        self.assertEqual(words[0], {"text": "开", "start": 1.0, "end": 1.5})
        self.assertEqual(
            words[1],
            {
                "text": "结",
                "start": 2.0 + CHUNK_TARGET_SECONDS,
                "end": 2.5 + CHUNK_TARGET_SECONDS,
            },
        )
        self.assertEqual(result["provider"], "dashscope")
        self.assertTrue(any("2/2" in message for message in progress_messages))

    async def test_provider_pinned_after_first_chunk(self):
        service = _make_service()
        service.transcribe_file = AsyncMock(
            side_effect=[
                {"text": "a", "duration_seconds": 1.0, "words": None, "provider": "deepgram"},
                {"text": "b", "duration_seconds": 1.0, "words": None, "provider": "deepgram"},
            ]
        )

        async def fake_probe(path: Path) -> MediaProbe:
            if path.name.startswith("chunk_"):
                return _probe(60.0)
            return _probe(float(SYNC_MAX_DURATION_SECONDS + 60), size=100)

        async def fake_transcode_split(source: Path, chunk_seconds: int, output_dir: Path) -> list[Path]:
            return [output_dir / "chunk_0000.mp3", output_dir / "chunk_0001.mp3"]

        with (
            self._fake_file_patches(),
            patch.object(audio_tools, "ffmpeg_available", return_value=True),
            patch.object(audio_tools, "asr_limits", return_value=(SYNC_MAX_DURATION_SECONDS, CHUNK_TARGET_SECONDS)),
            patch.object(audio_tools, "probe_media", new=AsyncMock(side_effect=fake_probe)),
            patch.object(audio_tools, "transcode_and_split", new=AsyncMock(side_effect=fake_transcode_split)),
        ):
            await service.transcribe_media(Path("long.wav"))

        first_call_kwargs = service.transcribe_file.await_args_list[0].kwargs
        second_call_kwargs = service.transcribe_file.await_args_list[1].kwargs
        self.assertIsNone(first_call_kwargs.get("provider"))
        self.assertEqual(second_call_kwargs.get("provider"), "deepgram")

    async def test_falls_back_without_ffmpeg(self):
        service = _make_service()
        service.transcribe_file = AsyncMock(
            return_value={"text": "legacy", "duration_seconds": None, "words": None}
        )
        with (
            self._fake_file_patches(),
            patch.object(audio_tools, "ffmpeg_available", return_value=False),
            patch.object(audio_tools, "probe_media", new=AsyncMock()) as probe_mock,
        ):
            result = await service.transcribe_media(Path("movie.mp4"))
        self.assertEqual(result["text"], "legacy")
        probe_mock.assert_not_awaited()
        called_path = service.transcribe_file.await_args.args[0]
        self.assertEqual(Path(called_path).name, "movie.mp4")

    async def test_media_without_audio_track_rejected(self):
        service = _make_service()
        service.transcribe_file = AsyncMock()
        silent_video_probe = _probe(120.0, video=True, audio=False)
        with (
            self._fake_file_patches(),
            patch.object(audio_tools, "ffmpeg_available", return_value=True),
            patch.object(audio_tools, "probe_media", new=AsyncMock(return_value=silent_video_probe)),
        ):
            with self.assertRaises(ValueError):
                await service.transcribe_media(Path("silent.mp4"))
        service.transcribe_file.assert_not_awaited()


class LocalChunkedJobLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def _make_job(self, service: TranscriptionService) -> str:
        from services.transcription_service import TranscriptionJob

        job = TranscriptionJob(
            job_id="tx_chunktest0001",
            file_path="upload_test.mp3",
            mode="async",
            status="queued",
        )
        service._write_job(job)
        return str(job.job_id)

    async def test_completes_and_persists_transcript_and_words(self):
        service = _make_service()
        job_id = await self._make_job(service)
        service.transcribe_media = AsyncMock(
            return_value={
                "text": "完整转写结果",
                "duration_seconds": 500.0,
                "words": [{"text": "完", "start": 0.0, "end": 0.4}],
                "provider": "dashscope",
            }
        )

        job = await service.process_local_chunked_job(job_id)
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.provider, "dashscope")
        self.assertIsNotNone(job.transcript_path)
        self.assertEqual(
            Path(str(job.transcript_path)).read_text(encoding="utf-8"),
            "完整转写结果",
        )
        words_path = service.jobs_dir / f"{job_id}_words.json"
        self.assertTrue(words_path.is_file())

    async def test_failure_recorded_on_job(self):
        service = _make_service()
        job_id = await self._make_job(service)
        service.transcribe_media = AsyncMock(side_effect=RuntimeError("ASR 密钥缺失"))

        job = await service.process_local_chunked_job(job_id)
        self.assertEqual(job.status, "failed")
        self.assertIn("ASR 密钥缺失", str(job.error))

    async def test_unknown_job_raises(self):
        service = _make_service()
        with self.assertRaises(FileNotFoundError):
            await service.process_local_chunked_job("tx_missing000000")


class ValidationTests(unittest.TestCase):
    def test_video_suffixes_accepted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            for suffix in (".mkv", ".mov", ".avi", ".mp4", ".webm"):
                media_path = Path(tmp_dir) / f"sample{suffix}"
                media_path.write_bytes(b"fake-media")
                # Must not raise.
                TranscriptionService._validate_file(media_path)

    def test_unsupported_suffix_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            text_path = Path(tmp_dir) / "notes.txt"
            text_path.write_text("hi", encoding="utf-8")
            with self.assertRaises(ValueError):
                TranscriptionService._validate_file(text_path)


class ListJobsFilterTests(unittest.TestCase):
    def test_running_filter_includes_transient_states(self):
        service = _make_service()
        from services.transcription_service import TranscriptionJob

        for index, status in enumerate(("queued", "running", "submitted", "completed")):
            service._write_job(
                TranscriptionJob(
                    job_id=f"tx_filter{index:08d}",
                    file_path="x.mp3",
                    mode="async",
                    status=status,
                )
            )
        jobs = service.list_jobs(statuses={"running"}, limit=50)
        statuses = {job.status for job in jobs}
        self.assertEqual(statuses, {"queued", "running", "submitted"})


class JobStoreEvictionTests(unittest.TestCase):
    def test_evicts_oldest_jobs_and_sidecars_beyond_cap(self):
        import json
        import os

        from services.transcription_service import (
            MAX_TRANSCRIPTION_JOBS,
            TranscriptionJob,
        )

        service = _make_service()
        for index in range(MAX_TRANSCRIPTION_JOBS + 5):
            job_id = f"tx_evict{index:08d}"
            path = service.jobs_dir / f"{job_id}.json"
            path.write_text(
                json.dumps({"job_id": job_id, "file_path": "x.mp3", "mode": "sync"}),
                encoding="utf-8",
            )
            # Ascending mtimes so eviction order is deterministic.
            os.utime(path, (1000 + index, 1000 + index))

        oldest_id = "tx_evict00000000"
        (service.jobs_dir / f"{oldest_id}.txt").write_text("transcript", encoding="utf-8")
        (service.jobs_dir / f"{oldest_id}_words.json").write_text("[]", encoding="utf-8")

        service._write_job(
            TranscriptionJob(job_id="tx_evict_trigger", file_path="x.mp3", mode="sync")
        )

        remaining = list(service.jobs_dir.glob("tx_*.json"))
        self.assertEqual(len(remaining), MAX_TRANSCRIPTION_JOBS)
        self.assertFalse((service.jobs_dir / f"{oldest_id}.json").exists())
        self.assertFalse((service.jobs_dir / f"{oldest_id}.txt").exists())
        self.assertFalse((service.jobs_dir / f"{oldest_id}_words.json").exists())
        # Newest jobs survive.
        self.assertTrue((service.jobs_dir / "tx_evict_trigger.json").exists())

    def test_no_eviction_under_cap(self):
        from services.transcription_service import TranscriptionJob

        service = _make_service()
        for index in range(3):
            service._write_job(
                TranscriptionJob(
                    job_id=f"tx_keep{index:08d}", file_path="x.mp3", mode="sync"
                )
            )
        self.assertEqual(len(list(service.jobs_dir.glob("tx_*.json"))), 3)

    def test_eviction_removes_uploaded_source_media(self):
        import json
        import os

        from services.transcription_service import (
            MAX_TRANSCRIPTION_JOBS,
            TranscriptionJob,
        )

        service = _make_service()
        uploads_dir = service.jobs_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        orphan_id = "tx_upload00000001"
        upload_file = uploads_dir / f"{orphan_id}.mp4"
        upload_file.write_bytes(b"fake media bytes")

        # A user original OUTSIDE jobs_dir must never be touched.
        external = service.jobs_dir.parent / "user_original.mp3"
        external.write_bytes(b"user data")

        for index in range(MAX_TRANSCRIPTION_JOBS + 5):
            job_id = f"tx_evict{index:08d}"
            path = service.jobs_dir / f"{job_id}.json"
            path.write_text(
                json.dumps({"job_id": job_id, "file_path": "x.mp3", "mode": "sync"}),
                encoding="utf-8",
            )
            os.utime(path, (1000 + index, 1000 + index))

        oldest_id = "tx_evict00000000"
        oldest_path = service.jobs_dir / f"{oldest_id}.json"
        payload = json.loads(oldest_path.read_text(encoding="utf-8"))
        payload["file_path"] = str(upload_file)
        oldest_path.write_text(json.dumps(payload), encoding="utf-8")
        os.utime(oldest_path, (999, 999))

        # Second-oldest points at the external file.
        second_id = "tx_evict00000001"
        second_path = service.jobs_dir / f"{second_id}.json"
        second_payload = json.loads(second_path.read_text(encoding="utf-8"))
        second_payload["file_path"] = str(external)
        second_path.write_text(json.dumps(second_payload), encoding="utf-8")
        os.utime(second_path, (1000, 1000))

        service._write_job(
            TranscriptionJob(job_id="tx_evict_trigger", file_path="x.mp3", mode="sync")
        )

        self.assertFalse((service.jobs_dir / f"{oldest_id}.json").exists())
        # The managed upload was removed with its job record...
        self.assertFalse(upload_file.exists())
        # ...but the user's own file outside jobs_dir survives.
        self.assertTrue(external.exists())

        external.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
