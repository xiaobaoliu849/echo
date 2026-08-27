from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx  # type: ignore
import logging

try:
    from google import genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)

from .config_loader import BackendConfig
from .evermem_config import EverMemConfig
from .transcription_publish_adapter import build_transcription_publisher
from .llm_service import LLMService
from . import audio_tools
from .audio_tools import AudioToolsError, MediaProbe
from .doubao_asr_provider import doubao_asr_transcribe_file, DOUBAO_ASR_2_RESOURCE

QWEN_ASR_SYNC_MODEL = "qwen3-asr-flash-2026-02-10"
# DashScope async (file-transcription) ASR. "链式" URL jobs are DashScope-only;
# the selectable engine is which DashScope ASR model the async task runs.
QWEN_ASR_ASYNC_MODEL = "qwen3-asr-flash-filetrans"
QWEN_AUDIO_ASR_ASYNC_MODEL = "qwen-audio-3.0-asr-flash-filetrans"
ASYNC_MODEL_BY_PROVIDER = {
    "qwen-filetrans": QWEN_ASR_ASYNC_MODEL,
    "qwen-audio-filetrans": QWEN_AUDIO_ASR_ASYNC_MODEL,
}
QWEN_COMPATIBLE_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
# Alternate specialized endpoint for direct ASR tasks
QWEN_ASR_DIRECT_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"

# Qwen-Audio-3.0-ASR-Flash (Fun-ASR Flash) — multimodal-generation API.
# Supports word-level timestamps, instant hotwords (vocabulary) and language hints.
# https://help.aliyun.com/zh/model-studio/non-real-time-speech-recognition-for-fun-asr-flash
QWEN_AUDIO_ASR_MODEL = "qwen-audio-3.0-asr-flash"
QWEN_AUDIO_ASR_PATH = "/services/aigc/multimodal-generation/generation"
# Base64 data-URI uploads are limited to 10MB by the API.
QWEN_AUDIO_ASR_MAX_BASE64_BYTES = 10 * 1024 * 1024
# language_hints accepts at most 4 codes for this model family.
QWEN_AUDIO_ASR_MAX_LANGUAGE_HINTS = 4

# Xiaomi MiMo ASR (OpenAI-compatible)
MIMO_ASR_MODEL = "mimo-v2.5-asr"
MIMO_DEFAULT_CHAT_URL = "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"

# Google Gemini 3.5 Transcribe ASR
GEMINI_TRANSCRIBE_MODEL = "gemini-3.5-transcribe"

# Deepgram ASR
DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_DEFAULT_MODEL = "nova-3"

# OpenAI Whisper ASR
OPENAI_WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_WHISPER_MODEL = "whisper-1"

# AssemblyAI ASR
ASSEMBLYAI_BASE_URL = "https://api.assemblyai.com"
SUPPORTED_AUDIO_SUFFIXES = {
    ".wav",
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".mp4",
    ".ogg",
    ".opus",
    ".webm",
    # Video containers — the audio track is extracted locally via ffmpeg
    # before transcription (see transcribe_media).
    ".mkv",
    ".mov",
    ".avi",
    ".flv",
    ".wmv",
    ".m4v",
    ".ts",
    ".3gp",
    ".mpg",
    ".mpeg",
}

# --- Long-audio / video preprocessing limits --------------------------------
# Qwen-Audio-3.0-ASR-Flash (and most sync engines) cap a single request at
# ~5 minutes. Keep chunks comfortably below that; after transcoding to 16kHz
# mono MP3 each chunk is also well under every provider's size cap.
CHUNK_TARGET_SECONDS = 240
# Files at or below this duration skip chunking entirely.
SYNC_MAX_DURATION_SECONDS = 270
# Above this raw size we always transcode first, even for short files
# (10MB is the Qwen base64 limit; OpenAI Whisper caps at 25MB).
PREPROCESS_SIZE_THRESHOLD_BYTES = 8 * 1024 * 1024


def _read_file_base64(path: Path) -> str:
    """Read a file and return its base64-encoded contents.

    Runs via ``asyncio.to_thread`` at the call sites so multi-MB audio
    reads + encoding never block the event loop.
    """
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _read_qwen_audio_base64(path: Path) -> str:
    """Read audio for Qwen-Audio ASR, enforcing the 10MB base64 cap.

    Runs via ``asyncio.to_thread``; raises ValueError when the audio is
    too large for the base64 data-URI upload path. A stat-based pre-check
    rejects oversized files without reading them into memory first (the
    whole-file read is kept as the authoritative check).
    """
    try:
        file_size: int | None = path.stat().st_size
    except OSError:
        file_size = None
    if file_size is not None and file_size > QWEN_AUDIO_ASR_MAX_BASE64_BYTES:
        raise ValueError(
            "Qwen-Audio ASR accepts base64 audio up to 10MB. "
            "Use the async from-url pipeline for larger files."
        )
    audio_bytes = path.read_bytes()
    if len(audio_bytes) > QWEN_AUDIO_ASR_MAX_BASE64_BYTES:
        raise ValueError(
            "Qwen-Audio ASR accepts base64 audio up to 10MB. "
            "Use the async from-url pipeline for larger files."
        )
    return base64.b64encode(audio_bytes).decode("utf-8")


# Bound the tx_*.json job store: without eviction every transcription job
# (plus its .txt/_words.json sidecars) accumulates forever, and list_jobs
# re-reads the whole directory each call.
MAX_TRANSCRIPTION_JOBS = 500

# A local chunked job (no remote_job_id) is only "queued"/"running" while its
# in-process asyncio task is alive. When the process dies, nothing resumes it,
# so a record left in a transient state for this long is treated as
# interrupted instead of polling forever as "排队中". Remote DashScope jobs are
# exempt: their status stays resolvable via refresh_long_transcription_job.
INTERRUPTED_JOB_STALE_SECONDS = 300
TRANSIENT_JOB_STATUSES = {"queued", "running", "submitted", "uploaded"}
JOB_INTERRUPTED_MESSAGE = (
    "转写任务因应用退出或重启而中断，请重试。 "
    "(The transcription task was interrupted because the app exited or restarted. Retry to run it again.)"
)


@dataclass(slots=True)
class TranscriptionJob:
    file_path: str
    mode: str
    status: str = "queued"
    job_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    transcript_path: str | None = None
    error: str | None = None
    remote_job_id: str | None = None
    source_url: str | None = None
    memory_saved: bool = False
    original_filename: str | None = None
    provider: str | None = None
    # Human-readable progress line for local chunked jobs (e.g. "第 3/12 段转写中").
    progress: str | None = None
    # Audio duration in seconds, persisted when a job completes so the library
    # can show it without re-probing the media file.
    duration_seconds: float | None = None
    # Where the recording came from: "upload" | "url" | "realtime".
    origin: str | None = None


class TranscriptionService:
    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig()
        self.llm_service = LLMService(self.config)
        from .config_loader import get_data_dir

        self.jobs_dir = get_data_dir() / "temp_audio" / "transcription_jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def published_dir(self) -> Path:
        path = self.jobs_dir / "published"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _dashscope_key(self) -> str:
        self.config.reload()
        return str(self.config.peek_setting("dashscope_api_key", "")).strip()

    def _xiaomi_key(self) -> str:
        self.config.reload()
        return str(self.config.peek_setting("xiaomi_api_key", "")).strip()

    def _deepgram_key(self) -> str:
        self.config.reload()
        return str(self.config.peek_setting("deepgram_api_key", "")).strip()

    def _google_key(self) -> str:
        if hasattr(self, "config") and self.config is not None:
            self.config.reload()
            key = str(self.config.peek_setting("google_api_key", "")).strip()
            if key:
                return key
        import os
        return (os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")).strip()

    def _google_interactions_base_url(self) -> str:
        if hasattr(self, "config") and self.config is not None:
            base_url = self.config.get_provider_settings("Google").get("base_url", "").strip()
            if base_url:
                return base_url.rstrip("/")
        return "https://generativelanguage.googleapis.com/v1beta"

    def _openai_key(self) -> str:
        self.config.reload()
        return str(self.config.peek_setting("openai_api_key", "")).strip()

    def _assemblyai_key(self) -> str:
        self.config.reload()
        return str(self.config.peek_setting("assemblyai_api_key", "")).strip()

    def _doubao_key(self) -> str:
        self.config.reload()
        # Only the dedicated doubao_access_token field (voice-console API Key);
        # doubao_api_key is the Ark text-chat key, a different credential system.
        return str(self.config.peek_setting("doubao_access_token", "")).strip()

    def _doubao_app_id(self) -> str:
        self.config.reload()
        return str(self.config.peek_setting("doubao_app_id", "")).strip()

    def _doubao_resource_id(self) -> str:
        self.config.reload()
        res_id = str(self.config.peek_setting("doubao_asr_resource_id", "")).strip()
        if not res_id:
            res_id = str(self.config.peek_setting("doubao_resource_id", "")).strip()
        return res_id if res_id else DOUBAO_ASR_2_RESOURCE

    def _mimo_chat_url(self) -> str:
        base_url = self.config.get_provider_settings("Xiaomi").get("base_url", "").strip()
        if not base_url:
            return MIMO_DEFAULT_CHAT_URL
        return base_url.rstrip("/") + "/chat/completions"

    def _dashscope_async_base_url(self) -> str:
        base_url = self.config.get_provider_settings("DashScope").get("base_url", "").strip()
        if not base_url:
            return "https://dashscope.aliyuncs.com/api/v1"
        if base_url.endswith("/compatible-mode/v1"):
            return base_url[: -len("/compatible-mode/v1")] + "/api/v1"
        return base_url.rstrip("/")

    @staticmethod
    def _guess_mime_type(file_path: Path) -> str:
        guessed, _ = mimetypes.guess_type(str(file_path))
        return guessed or "audio/wav"

    @staticmethod
    def _validate_file(path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {path}")
        if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
            raise ValueError(
                "Unsupported audio format. Supported formats: "
                + ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES))
            )
        if path.stat().st_size <= 0:
            raise ValueError("Audio file is empty.")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _write_job(self, job: TranscriptionJob) -> TranscriptionJob:
        if not job.job_id:
            raise ValueError("job_id is required to persist transcription job.")
        
        # Explicitly cast or handle types to satisfy linting
        job_id_str = str(job.job_id)
        
        payload = {
            "job_id": job_id_str,
            "file_path": job.file_path,
            "mode": job.mode,
            "status": job.status,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "transcript_path": job.transcript_path,
            "error": job.error,
            "remote_job_id": job.remote_job_id,
            "source_url": job.source_url,
            "memory_saved": bool(job.memory_saved),
            "original_filename": job.original_filename,
            "provider": job.provider,
            "progress": job.progress,
            "duration_seconds": job.duration_seconds,
            "origin": job.origin,
        }
        self._job_path(job_id_str).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._evict_old_jobs()
        return job

    def _evict_old_jobs(self, max_jobs: int = MAX_TRANSCRIPTION_JOBS) -> None:
        """Remove oldest job records (and sidecar files) beyond the cap.

        Oldest-first by mtime; in-flight jobs are always the newest so they
        are never evicted here. Word-timestamp and translation sidecars are
        not job records — counting them would evict real jobs early, so they
        are skipped (they die with their owning job instead). Files under
        published/ are untouched.
        """
        try:
            paths = sorted(
                (
                    p
                    for p in self.jobs_dir.glob("tx_*.json")
                    if not (
                        p.stem.endswith("_words")  # word-timestamp sidecar, not a job
                        or p.stem.endswith("_translation")  # cue-translation sidecar
                    )
                ),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError:
            return
        excess = len(paths) - max_jobs
        if excess <= 0:
            return
        uploads_root = (self.jobs_dir / "uploads").resolve()
        for path in paths[:excess]:
            job_id = path.stem
            artifacts = [
                path,
                self.jobs_dir / f"{job_id}.txt",
                self.jobs_dir / f"{job_id}_words.json",
            ]
            # Also drop the uploaded source media, otherwise multi-GB files
            # accumulate in uploads/ forever after eviction. Only files this
            # service manages (inside jobs_dir/uploads) are eligible — never
            # user originals elsewhere on disk.
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = None
            if isinstance(payload, dict):
                try:
                    source = Path(str(payload.get("file_path", "") or "")).expanduser().resolve()
                    if uploads_root in source.parents:
                        artifacts.append(source)
                except OSError:
                    pass
            for artifact in artifacts:
                try:
                    artifact.unlink(missing_ok=True)
                except OSError:
                    continue

    def reap_stale_active_job(self, job: TranscriptionJob) -> TranscriptionJob:
        """Fail one locally-interrupted transient job record; pass others through.

        A record stuck in queued/running/submitted without a remote_job_id has no
        owning pipeline task anymore (its process died). After
        INTERRUPTED_JOB_STALE_SECONDS without an update it is flipped to failed,
        so the UI surfaces a retryable error instead of polling "排队中" forever.
        Fresh records are untouched: an in-flight chunked pipeline keeps writing
        progress (and thus updated_at) while it runs.
        """
        if job.remote_job_id or job.mode == "sync":
            return job
        if str(job.status).lower() not in TRANSIENT_JOB_STATUSES:
            return job
        try:
            updated_ts = datetime.fromisoformat(str(job.updated_at)).timestamp()
        except ValueError:
            return job
        stale_seconds = datetime.now(timezone.utc).timestamp() - updated_ts
        if stale_seconds < INTERRUPTED_JOB_STALE_SECONDS:
            return job
        job.status = "failed"
        job.error = job.error or JOB_INTERRUPTED_MESSAGE
        job.progress = ""
        job.updated_at = self._now_iso()
        return self._write_job(job)

    def get_job(self, job_id: str) -> TranscriptionJob | None:
        path = self._job_path(job_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return TranscriptionJob(
                file_path=str(payload.get("file_path", "")),
                mode=str(payload.get("mode", "sync")),
                status=str(payload.get("status", "queued")),
                job_id=payload.get("job_id"),
                created_at=payload.get("created_at"),
                updated_at=payload.get("updated_at"),
                transcript_path=payload.get("transcript_path"),
                error=payload.get("error"),
                remote_job_id=payload.get("remote_job_id"),
                source_url=payload.get("source_url"),
                memory_saved=bool(payload.get("memory_saved", False)),
                original_filename=payload.get("original_filename"),
                provider=payload.get("provider"),
                progress=payload.get("progress"),
                duration_seconds=payload.get("duration_seconds"),
                origin=payload.get("origin"),
            )
        except Exception:
            return None

    def list_jobs(
        self,
        *,
        statuses: set[str] | None = None,
        limit: int = 50,
    ) -> list[TranscriptionJob]:
        normalized_statuses = {status.strip().lower() for status in (statuses or set()) if status.strip()}
        # The UI's "running" filter means "in progress" — expand it to every
        # transient state a job can be in while work is pending.
        if "running" in normalized_statuses:
            normalized_statuses.update({"submitted", "queued", "uploaded"})
        jobs: list[TranscriptionJob] = []
        for path in self.jobs_dir.glob("tx_*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                # Explicitly convert and validate types for dataclass unpacking
                job = TranscriptionJob(
                    file_path=str(payload.get("file_path", "")),
                    mode=str(payload.get("mode", "sync")),
                    status=str(payload.get("status", "queued")),
                    job_id=payload.get("job_id"),
                    created_at=payload.get("created_at"),
                    updated_at=payload.get("updated_at"),
                    transcript_path=payload.get("transcript_path"),
                    error=payload.get("error"),
                    remote_job_id=payload.get("remote_job_id"),
                    source_url=payload.get("source_url"),
                    memory_saved=bool(payload.get("memory_saved", False)),
                    original_filename=payload.get("original_filename"),
                    provider=payload.get("provider"),
                    progress=payload.get("progress"),
                    duration_seconds=payload.get("duration_seconds"),
                    origin=payload.get("origin"),
                )
            except Exception:
                continue
            # Self-heal records whose pipeline died with a previous process
            # before they enter the listing, so stale rows don't sit in the
            # library as eternal "排队中" entries.
            job = self.reap_stale_active_job(job)
            if normalized_statuses and job.status.lower() not in normalized_statuses:
                continue
            jobs.append(job)

        jobs.sort(
            key=lambda item: (
                str(item.updated_at or ""),
                str(item.created_at or ""),
                str(item.job_id or ""),
            ),
            reverse=True,
        )
        # Avoid direct list slicing if it causes lint issues, use helper
        result_jobs: list[TranscriptionJob] = []
        for i, item in enumerate(jobs):
            if i >= limit:
                break
            result_jobs.append(item)
        return result_jobs

    def can_publish_local_async(self) -> bool:
        return build_transcription_publisher(
            self.config,
            published_dir=self.published_dir,
        ).is_enabled()

    def delete_job(self, job_id: str) -> bool:
        """Delete a transcription job and its associated files. Returns True if deleted."""
        job = self.get_job(job_id)
        if job is None:
            return False

        # Remove associated files
        for path in [
            self._job_path(job_id),
            self.jobs_dir / f"{job_id}_words.json",
            self.jobs_dir / f"{job_id}_translation.json",
            self.jobs_dir / f"{job_id}_burn.srt",
            self.jobs_dir / f"{job_id}_subtitled.mp4",
        ]:
            try:
                if path.is_file():
                    path.unlink()
            except Exception:
                pass

        # Remove uploaded audio if it lives in our jobs dir
        if job.file_path:
            audio_path = Path(job.file_path)
            try:
                if audio_path.is_file() and self.jobs_dir in audio_path.parents:
                    audio_path.unlink()
            except Exception:
                pass

        # Remove transcript file if it lives in our jobs dir
        if job.transcript_path:
            transcript_path = Path(job.transcript_path)
            try:
                if transcript_path.is_file() and self.jobs_dir in transcript_path.parents:
                    transcript_path.unlink()
            except Exception:
                pass

        return True

    def delete_jobs(self, job_ids: list[str]) -> dict[str, Any]:
        """Bulk-delete transcription jobs. Returns counts + per-id failures.

        Missing/invalid ids are reported in ``failed`` rather than aborting the
        whole batch, so one stale client entry can't block a bulk cleanup.
        """
        seen: set[str] = set()
        deleted: list[str] = []
        failed: list[str] = []
        for raw_id in job_ids:
            job_id = str(raw_id or "").strip()
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            try:
                if self.delete_job(job_id):
                    deleted.append(job_id)
                else:
                    failed.append(job_id)
            except Exception:
                logger.exception("Failed to delete transcription job %s", job_id)
                failed.append(job_id)
        return {"deleted": deleted, "failed": failed}

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        transcript_path: str | None = None,
        error: str | None = None,
        remote_job_id: str | None = None,
        source_url: str | None = None,
        memory_saved: bool | None = None,
        provider: str | None = None,
        progress: str | None = None,
        duration_seconds: float | None = None,
        original_filename: str | None = None,
    ) -> TranscriptionJob:
        job = self.get_job(job_id)
        if job is None:
            raise FileNotFoundError(f"Transcription job not found: {job_id}")
        if status is not None:
            job.status = status
        if transcript_path is not None:
            job.transcript_path = transcript_path
        if error is not None:
            job.error = error
        if remote_job_id is not None:
            job.remote_job_id = remote_job_id
        if source_url is not None:
            job.source_url = source_url
        if memory_saved is not None:
            job.memory_saved = memory_saved
        if provider is not None:
            job.provider = provider
        if progress is not None:
            job.progress = progress
        if duration_seconds is not None:
            job.duration_seconds = duration_seconds
        if original_filename is not None:
            job.original_filename = original_filename
        job.updated_at = self._now_iso()
        return self._write_job(job)

    def rename_job(self, job_id: str, file_name: str) -> TranscriptionJob:
        """Set a user-facing display name; falls back are untouched elsewhere."""
        cleaned = str(file_name or "").strip()
        if not cleaned:
            raise ValueError("file_name must not be empty.")
        if len(cleaned) > 200:
            raise ValueError("file_name is too long (max 200 characters).")
        return self.update_job(job_id, original_filename=cleaned)

    async def transcribe_media(
        self,
        file_path: str | Path,
        provider: str | None = None,
        *,
        language_hints: list[str] | None = None,
        vocabulary: dict[str, int] | None = None,
        on_progress: Any = None,
    ) -> dict:
        """Smart transcription pipeline that lifts the sync API limits.

        Compared to :meth:`transcribe_file` (one API call on the raw upload),
        this adds a local ffmpeg preprocessing stage when needed:

        - video containers (mp4/mkv/mov/...) have their audio track extracted;
        - oversized files are transcoded to 16kHz mono MP3 (~10-50x smaller);
        - audio longer than the per-request cap is split into chunks, each
          chunk is transcribed separately and the results are merged back
          with correct global word timestamps.

        Falls back to the plain single-call path when ffmpeg is unavailable,
        preserving the legacy behavior. Returns the same shape as
        :meth:`transcribe_file`.
        """
        path = Path(file_path).expanduser().resolve()
        self._validate_file(path)
        suffix = path.suffix.lower()

        probe: MediaProbe | None = None
        if audio_tools.ffmpeg_available():
            # Resolve the MP3-encoder cache off the event loop before the
            # sync helpers below (first call shells out to ffmpeg -encoders).
            await audio_tools.warmup_mp3_encoder()
            try:
                probe = await audio_tools.probe_media(path)
            except AudioToolsError as exc:
                logger.warning("ffprobe failed for %s (%s); using direct path", path.name, exc)

        # Codec-dependent limits: WAV fallback chunks are larger per second,
        # so their thresholds are tighter (see audio_tools.asr_limits).
        sync_max_seconds, chunk_seconds = audio_tools.asr_limits(
            SYNC_MAX_DURATION_SECONDS, CHUNK_TARGET_SECONDS
        )

        needs_preprocess = suffix in audio_tools.VIDEO_CONTAINER_SUFFIXES
        if probe is not None:
            if not probe.has_audio_stream:
                raise ValueError("This file has no audio track and cannot be transcribed.")
            if probe.duration_seconds > sync_max_seconds:
                needs_preprocess = True
            if probe.size_bytes > PREPROCESS_SIZE_THRESHOLD_BYTES:
                needs_preprocess = True

        if not needs_preprocess or not audio_tools.ffmpeg_available():
            return await self.transcribe_file(
                path,
                provider=provider,
                language_hints=language_hints,
                vocabulary=vocabulary,
            )

        if callable(on_progress):
            try:
                on_progress("正在预处理媒体文件（提取音轨/压缩）…")
            except Exception:
                logger.exception("on_progress callback failed")

        import tempfile

        work_dir = Path(tempfile.mkdtemp(prefix="voicespirit_asr_"))
        temp_artifacts: list[Path] = [work_dir]
        try:
            # The chunking decision must come from the ORIGINAL probe, not a
            # probe of the transcoded intermediate — some encoders write
            # unreliable duration metadata (e.g. Windows MediaFoundation MP3),
            # which once caused a 300s file to be misread as 112s and sent
            # whole, getting rejected by the API.
            should_chunk = (
                probe is None
                or probe.duration_seconds <= 0.0
                or probe.duration_seconds > sync_max_seconds
            )

            if should_chunk:
                # Long or unknown-length media: transcode + split in a single
                # ffmpeg pass (re-encode, exact boundaries, no intermediate).
                chunk_paths = await audio_tools.transcode_and_split(
                    path, chunk_seconds, work_dir / "chunks"
                )
            else:
                # Short media that only needed audio extraction / shrink:
                # a single normalized file is enough for one API call.
                normalized_path = (
                    work_dir
                    / f"normalized_{path.stem or 'audio'}{audio_tools.normalized_suffix()}"
                )
                await audio_tools.transcode_for_asr(path, normalized_path)
                chunk_paths = [normalized_path]

            temp_artifacts.extend(chunk_paths)
            chunk_count = len(chunk_paths)

            # Measure each chunk's real duration so merged word timestamps land
            # at their true global positions even if segment boundaries drift.
            chunk_offsets: list[float] = []
            cursor = 0.0
            for chunk in chunk_paths:
                chunk_offsets.append(cursor)
                try:
                    chunk_probe = await audio_tools.probe_media(chunk)
                    cursor += chunk_probe.duration_seconds
                except AudioToolsError:
                    cursor += float(chunk_seconds)

            chunk_results: list[dict] = []
            resolved_provider = provider
            for index, chunk in enumerate(chunk_paths, start=1):
                if chunk_count > 1 and callable(on_progress):
                    try:
                        on_progress(f"正在转写第 {index}/{chunk_count} 段…")
                    except Exception:
                        logger.exception("on_progress callback failed")
                result = await self.transcribe_file(
                    chunk,
                    provider=resolved_provider,
                    language_hints=language_hints,
                    vocabulary=vocabulary,
                )
                # Pin the auto-selected provider after the first chunk so all
                # chunks run on the same engine (consistent accuracy/latency).
                if resolved_provider is None and result.get("provider"):
                    resolved_provider = str(result.get("provider"))
                chunk_results.append(result)

            if chunk_count == 1:
                # Single-chunk path: return the result as-is (no offsetting).
                return chunk_results[0]

            merged = self._merge_chunk_results(chunk_results, chunk_offsets)
            if resolved_provider:
                merged["provider"] = resolved_provider
            return merged
        finally:
            # Deleting the ffmpeg work dir can remove hundreds of MB of
            # chunks — keep it off the event loop.
            await asyncio.to_thread(self._cleanup_artifacts, temp_artifacts)

    @staticmethod
    def _cleanup_artifacts(artifacts: list[Path]) -> None:
        """Remove preprocessing artifacts (blocking; run via to_thread)."""
        for artifact in artifacts:
            if artifact.is_dir():
                try:
                    shutil.rmtree(artifact, ignore_errors=True)
                except Exception:
                    logger.debug("Could not remove work dir: %s", artifact)
            else:
                audio_tools.cleanup_paths([artifact])

    @staticmethod
    def _merge_chunk_results(
        chunk_results: list[dict], chunk_offsets: list[float]
    ) -> dict:
        """Merge per-chunk ASR results into one transcript.

        Word timestamps are shifted by each chunk's start offset so subtitles
        stay aligned with the original (pre-split) media timeline.
        """
        texts: list[str] = []
        words: list[dict[str, Any]] = []
        total_duration = 0.0
        any_words = False
        for result, offset in zip(chunk_results, chunk_offsets):
            text = str(result.get("text", "") or "").strip()
            if text:
                texts.append(text)
            chunk_words = result.get("words")
            if chunk_words:
                any_words = True
                for w in chunk_words:
                    if not isinstance(w, dict):
                        continue
                    word_text = str(w.get("text", "")).strip()
                    start = w.get("start")
                    end = w.get("end")
                    if not word_text or start is None or end is None:
                        continue
                    words.append(
                        {
                            "text": word_text,
                            "start": float(start) + offset,
                            "end": float(end) + offset,
                        }
                    )
            duration = result.get("duration_seconds")
            if isinstance(duration, (int, float)) and duration > 0:
                total_duration += float(duration)
        return {
            "text": "\n".join(texts),
            "duration_seconds": total_duration if total_duration > 0 else None,
            "words": words if any_words else None,
        }

    async def process_local_chunked_job(
        self, job_id: str, provider: str | None = None
    ) -> TranscriptionJob:
        """Run the smart pipeline in the background for a locally uploaded job.

        This is the fallback for async jobs when no public publisher is
        configured: instead of staging the file forever, the upload is
        preprocessed and chunked locally, then fed through the sync ASR APIs.
        """
        job = self.get_job(job_id)
        if job is None:
            raise FileNotFoundError(f"Transcription job not found: {job_id}")

        def _progress(message: str) -> None:
            try:
                self.update_job(job_id, progress=message)
            except Exception:
                logger.exception("Failed to persist progress for job %s", job_id)

        try:
            self.update_job(
                job_id, status="running", progress="正在预处理媒体文件…", error=""
            )
            result = await self.transcribe_media(
                job.file_path,
                provider=provider,
                on_progress=_progress,
            )
            transcript = str(result.get("text", "") or "").strip()
            if not transcript:
                raise ValueError("Transcription finished but no speech was recognized.")
            # Persist off the event loop — transcripts/word lists grow to MBs
            # for multi-hour audio.
            transcript_path = await asyncio.to_thread(
                self._persist_transcript, job_id, transcript
            )
            words = result.get("words")
            if words:
                await asyncio.to_thread(self._persist_words, job_id, words)
            update_fields: dict[str, Any] = {
                "status": "completed",
                "transcript_path": transcript_path,
                "error": "",
                "progress": "转写完成",
            }
            result_duration = result.get("duration_seconds")
            if isinstance(result_duration, (int, float)) and result_duration > 0:
                update_fields["duration_seconds"] = float(result_duration)
            final_provider = str(result.get("provider") or provider or "").strip()
            if final_provider:
                update_fields["provider"] = final_provider
            return self.update_job(job_id, **update_fields)
        except Exception as exc:
            logger.exception("Local chunked transcription job %s failed", job_id)
            message = str(exc)[:1000]
            return self.update_job(
                job_id, status="failed", error=message, progress=""
            )

    async def transcribe_file(
        self,
        file_path: str | Path,
        provider: str | None = None,
        *,
        language_hints: list[str] | None = None,
        vocabulary: dict[str, int] | None = None,
    ) -> dict:
        """Returns {"text": str, "duration_seconds": float | None, "words": list[dict] | None}."""
        path = Path(file_path).expanduser().resolve()
        self._validate_file(path)

        # If provider is specified, use it directly
        if provider:
            provider = provider.lower().strip()
            if provider == "deepgram":
                api_key = self._deepgram_key()
                if not api_key:
                    raise ValueError("Deepgram API key not configured.")
                result = await self._transcribe_with_deepgram(path, api_key)
            elif provider == "openai" or provider == "whisper":
                api_key = self._openai_key()
                if not api_key:
                    raise ValueError("OpenAI API key not configured.")
                result = await self._transcribe_with_openai_whisper(path, api_key)
                provider = "openai"
            elif provider in {"dashscope", "qwen", "qwen-audio", "qwen-audio-asr", "funasr", "fun-asr"}:
                api_key = self._dashscope_key()
                if not api_key:
                    raise ValueError("DashScope API key not configured.")
                result = await self._transcribe_with_qwen_audio_asr(
                    path,
                    api_key,
                    language_hints=language_hints,
                    vocabulary=vocabulary,
                )
                provider = "dashscope"
            elif provider in {"qwen-legacy", "qwen3-asr"}:
                api_key = self._dashscope_key()
                if not api_key:
                    raise ValueError("DashScope API key not configured.")
                result = await self._transcribe_with_openai_asr(
                    path, api_key, QWEN_COMPATIBLE_CHAT_URL, QWEN_ASR_SYNC_MODEL, "Qwen"
                )
                provider = "qwen-legacy"
            elif provider == "xiaomi" or provider == "mimo":
                api_key = self._xiaomi_key()
                if not api_key:
                    raise ValueError("Xiaomi API key not configured.")
                result = await self._transcribe_with_openai_asr(
                    path, api_key, self._mimo_chat_url(), MIMO_ASR_MODEL, "MiMo"
                )
                provider = "xiaomi"
            elif provider in {"google", "gemini", "gemini-3.5-transcribe", "google-transcribe"}:
                api_key = self._google_key()
                if not api_key:
                    raise ValueError("Google API key not configured. Set google_api_key in Settings.")
                result = await self._transcribe_with_google_gemini(
                    path,
                    api_key,
                    language_hints=language_hints,
                    vocabulary=vocabulary,
                )
                provider = "google"
            elif provider == "assemblyai":
                api_key = self._assemblyai_key()
                if not api_key:
                    raise ValueError("AssemblyAI API key not configured.")
                result = await self._transcribe_with_assemblyai(path, api_key)
            elif provider == "doubao":
                api_key = self._doubao_key()
                if not api_key:
                    raise ValueError("Doubao Access Token not configured. Set the Doubao Voice API Key (Access Token field) in Settings.")
                app_id = self._doubao_app_id()
                result = await self._transcribe_with_doubao(path, api_key, app_id=app_id)
            else:
                raise ValueError(f"Unsupported ASR provider: {provider}")
            # Echo the actual engine so the UI can show which model was used.
            result["provider"] = provider
            return result

        # Auto-select: try providers in priority order
        # Deepgram, Google Gemini, OpenAI Whisper, and AssemblyAI support word-level timestamps
        deepgram_key = self._deepgram_key()
        if deepgram_key:
            result = await self._transcribe_with_deepgram(path, deepgram_key)
            result["provider"] = "deepgram"
            return result

        google_key = self._google_key()
        if google_key:
            result = await self._transcribe_with_google_gemini(
                path,
                google_key,
                language_hints=language_hints,
                vocabulary=vocabulary,
            )
            result["provider"] = "google"
            return result

        openai_key = self._openai_key()
        if openai_key:
            result = await self._transcribe_with_openai_whisper(path, openai_key)
            result["provider"] = "openai"
            return result

        assemblyai_key = self._assemblyai_key()
        if assemblyai_key:
            result = await self._transcribe_with_assemblyai(path, assemblyai_key)
            result["provider"] = "assemblyai"
            return result

        doubao_key = self._doubao_key()
        if doubao_key:
            app_id = self._doubao_app_id()
            result = await self._transcribe_with_doubao(path, doubao_key, app_id=app_id)
            result["provider"] = "doubao"
            return result

        # Qwen-Audio-3.0-ASR-Flash also returns word-level timestamps
        dashscope_key = self._dashscope_key()
        if dashscope_key:
            result = await self._transcribe_with_qwen_audio_asr(
                path,
                dashscope_key,
                language_hints=language_hints,
                vocabulary=vocabulary,
            )
            result["provider"] = "dashscope"
            return result

        # MiMo doesn't support word-level timestamps
        xiaomi_key = self._xiaomi_key()
        if xiaomi_key:
            result = await self._transcribe_with_openai_asr(
                path, xiaomi_key, self._mimo_chat_url(), MIMO_ASR_MODEL, "MiMo"
            )
            result["provider"] = "xiaomi"
            return result

        raise ValueError("No ASR API key configured. Set deepgram_api_key, google_api_key, openai_api_key, assemblyai_api_key, doubao_access_token, dashscope_api_key, or xiaomi_api_key.")

    async def _transcribe_with_openai_asr(
        self, path: Path, api_key: str, url: str, model: str, provider_name: str
    ) -> dict:
        """Returns {"text": str, "duration_seconds": float | None}."""
        # Read + base64-encode off the event loop (files up to ~25MB).
        audio_b64 = await asyncio.to_thread(_read_file_base64, path)
        extension = path.suffix.lower().lstrip(".")
        if extension == "mp3":
            mime_type = "audio/mpeg"
        else:
            mime_type = f"audio/{extension}"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:{mime_type};base64,{audio_b64}"
                            },
                        }
                    ],
                }
            ],
            "modalities": ["text"],
            "stream": False,
            "asr_options": {"language": "auto"},
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(url, headers=headers, json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise RuntimeError(f"{provider_name} ASR request failed: {detail}") from exc

        response_json = response.json()

        choices = response_json.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and "text" in item
                ]
                text = "".join(text_parts).strip()
            else:
                text = str(content).strip()
        else:
            text = ""

        if not text:
            raise RuntimeError(f"{provider_name} ASR returned empty transcript: {response_json}")

        # Extract audio duration from usage.seconds (MiMo API returns this)
        duration_seconds = None
        usage = response_json.get("usage", {})
        if isinstance(usage, dict):
            secs = usage.get("seconds")
            if isinstance(secs, (int, float)) and secs > 0:
                duration_seconds = float(secs)

        return {"text": text, "duration_seconds": duration_seconds, "words": None}

    async def _transcribe_with_qwen_audio_asr(
        self,
        path: Path,
        api_key: str,
        *,
        language_hints: list[str] | None = None,
        vocabulary: dict[str, int] | None = None,
    ) -> dict:
        """Transcribe with Qwen-Audio-3.0-ASR-Flash via the multimodal-generation API.

        Returns {"text": str, "duration_seconds": float | None, "words": list[dict] | None}.
        Supports instant hotwords (vocabulary, weight 1-5 or 50) and up to 4 language hints.
        """
        # Read + size-check + base64-encode off the event loop (≤10MB).
        audio_b64 = await asyncio.to_thread(_read_qwen_audio_base64, path)
        extension = path.suffix.lower().lstrip(".") or "wav"
        if extension in {"mp3", "mpga"}:
            mime_type = "audio/mpeg"
        else:
            mime_type = f"audio/{extension}"

        parameters: dict[str, Any] = {"format": extension}
        if language_hints:
            parameters["language_hints"] = language_hints[:QWEN_AUDIO_ASR_MAX_LANGUAGE_HINTS]
        if vocabulary:
            parameters["vocabulary"] = vocabulary

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "disable",
        }
        payload = {
            "model": QWEN_AUDIO_ASR_MODEL,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": f"data:{mime_type};base64,{audio_b64}"
                                },
                            }
                        ],
                    }
                ]
            },
            "parameters": parameters,
        }

        url = f"{self._dashscope_async_base_url()}{QWEN_AUDIO_ASR_PATH}"
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(url, headers=headers, json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise RuntimeError(f"Qwen-Audio ASR request failed: {detail}") from exc

        response_json = response.json()
        output = response_json.get("output", {})
        if not isinstance(output, dict):
            output = {}
        text = str(output.get("text", "")).strip()
        if not text:
            raise RuntimeError(f"Qwen-Audio ASR returned empty transcript: {response_json}")

        words = self._extract_qwen_audio_words(output)

        duration_seconds = None
        usage = response_json.get("usage", {})
        if isinstance(usage, dict):
            duration = usage.get("duration")
            if isinstance(duration, (int, float)) and duration > 0:
                duration_seconds = float(duration)

        return {"text": text, "duration_seconds": duration_seconds, "words": words}

    @staticmethod
    def _extract_qwen_audio_words(output: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Extract word-level timestamps (ms -> s) from a Qwen-Audio ASR output object."""
        sentences: list[Any] = []
        sentence = output.get("sentence")
        if isinstance(sentence, dict):
            sentences.append(sentence)
        extra = output.get("sentences")
        if isinstance(extra, list):
            sentences.extend(extra)

        words: list[dict[str, Any]] = []
        for item in sentences:
            if not isinstance(item, dict):
                continue
            words_raw = item.get("words")
            if not isinstance(words_raw, list):
                continue
            for w in words_raw:
                if not isinstance(w, dict):
                    continue
                word_text = str(w.get("text", "") or w.get("word", "")).strip()
                begin_time = w.get("begin_time")
                end_time = w.get("end_time")
                if word_text and begin_time is not None and end_time is not None:
                    words.append({
                        "text": word_text,
                        "start": float(begin_time) / 1000.0,
                        "end": float(end_time) / 1000.0,
                    })
        return words if words else None

    async def _transcribe_with_deepgram(self, path: Path, api_key: str) -> dict:
        """Transcribe with Deepgram API. Returns {"text": str, "duration_seconds": float | None, "words": list[dict] | None}."""
        # Read off the event loop (files up to ~25MB).
        audio_bytes = await asyncio.to_thread(path.read_bytes)
        extension = path.suffix.lower().lstrip(".")
        if extension == "mp3":
            content_type = "audio/mpeg"
        else:
            content_type = f"audio/{extension}"

        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": content_type,
        }
        params = {
            "model": DEEPGRAM_DEFAULT_MODEL,
            "smart_format": "true",
            "punctuate": "true",
            "language": "auto",
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                DEEPGRAM_API_URL,
                headers=headers,
                content=audio_bytes,
                params=params,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise RuntimeError(f"Deepgram ASR request failed: {detail}") from exc

        response_json = response.json()

        # Extract transcript text
        results = response_json.get("results", {})
        channels = results.get("channels", [])
        if not channels:
            raise RuntimeError(f"Deepgram ASR returned no channels: {response_json}")

        alternatives = channels[0].get("alternatives", [])
        if not alternatives:
            raise RuntimeError(f"Deepgram ASR returned no alternatives: {response_json}")

        transcript = alternatives[0].get("transcript", "")
        if not transcript:
            raise RuntimeError(f"Deepgram ASR returned empty transcript: {response_json}")

        # Extract word-level timestamps
        words_raw = alternatives[0].get("words", [])
        words = []
        for w in words_raw:
            word_text = w.get("word", "")
            start = w.get("start")
            end = w.get("end")
            if word_text and start is not None and end is not None:
                words.append({
                    "text": word_text,
                    "start": float(start),
                    "end": float(end),
                })

        # Extract duration from metadata
        duration_seconds = None
        metadata = response_json.get("metadata", {})
        if isinstance(metadata, dict):
            duration = metadata.get("duration")
            if isinstance(duration, (int, float)) and duration > 0:
                duration_seconds = float(duration)

        return {
            "text": transcript,
            "duration_seconds": duration_seconds,
            "words": words if words else None,
        }

    async def _transcribe_with_openai_whisper(self, path: Path, api_key: str) -> dict:
        """Transcribe with OpenAI Whisper API. Returns {"text": str, "duration_seconds": float | None, "words": list[dict] | None}."""
        # Read off the event loop (files up to 25MB).
        audio_bytes = await asyncio.to_thread(path.read_bytes)
        filename = path.name

        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        # Determine MIME type for the file upload
        extension = path.suffix.lower().lstrip(".")
        if extension == "mp3":
            mime_type = "audio/mpeg"
        elif extension == "m4a":
            mime_type = "audio/mp4"
        else:
            mime_type = f"audio/{extension}"

        # Use multipart form upload
        files = {
            "file": (filename, audio_bytes, mime_type),
        }
        data = {
            "model": OPENAI_WHISPER_MODEL,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
            "language": "auto",
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                OPENAI_WHISPER_URL,
                headers=headers,
                files=files,
                data=data,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise RuntimeError(f"OpenAI Whisper ASR request failed: {detail}") from exc

        response_json = response.json()

        # Extract transcript text
        transcript = response_json.get("text", "")
        if not transcript:
            raise RuntimeError(f"OpenAI Whisper ASR returned empty transcript: {response_json}")

        # Extract word-level timestamps
        words_raw = response_json.get("words", [])
        words = []
        for w in words_raw:
            word_text = w.get("word", "")
            start = w.get("start")
            end = w.get("end")
            if word_text and start is not None and end is not None:
                words.append({
                    "text": word_text,
                    "start": float(start),
                    "end": float(end),
                })

        # Extract duration
        duration_seconds = None
        duration = response_json.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            duration_seconds = float(duration)

        return {
            "text": transcript,
            "duration_seconds": duration_seconds,
            "words": words if words else None,
        }

    async def _transcribe_with_assemblyai(self, path: Path, api_key: str) -> dict:
        """Transcribe with AssemblyAI API. Supports word-level timestamps, speaker diarization, and auto-highlights."""
        # Read off the event loop (files up to ~25MB).
        audio_bytes = await asyncio.to_thread(path.read_bytes)
        extension = path.suffix.lower().lstrip(".")
        if extension == "mp3":
            content_type = "audio/mpeg"
        elif extension == "m4a":
            content_type = "audio/mp4"
        else:
            content_type = f"audio/{extension}"

        headers = {
            "Authorization": api_key,
        }

        # Step 1: Upload audio file
        async with httpx.AsyncClient(timeout=180.0) as client:
            upload_response = await client.post(
                f"{ASSEMBLYAI_BASE_URL}/v2/upload",
                headers={
                    "Authorization": api_key,
                    "Content-Type": content_type,
                },
                content=audio_bytes,
            )
            upload_response.raise_for_status()
            upload_url = upload_response.json().get("upload_url")
            if not upload_url:
                raise RuntimeError(f"AssemblyAI upload failed: no upload_url returned")

            # Step 2: Submit transcription request
            transcript_payload = {
                "audio_url": upload_url,
                "punctuate": True,
                "format_text": True,
                "language_detection": True,
                "word_boost": [],
                "boost_param": "default",
            }
            submit_response = await client.post(
                f"{ASSEMBLYAI_BASE_URL}/v2/transcript",
                headers={**headers, "Content-Type": "application/json"},
                json=transcript_payload,
            )
            submit_response.raise_for_status()
            transcript_id = submit_response.json().get("id")
            if not transcript_id:
                raise RuntimeError(f"AssemblyAI submission failed: no transcript ID returned")

            # Step 3: Poll until completed
            max_polls = 120  # 120 * 3s = 6 min max
            for _ in range(max_polls):
                await asyncio.sleep(3)
                poll_response = await client.get(
                    f"{ASSEMBLYAI_BASE_URL}/v2/transcript/{transcript_id}",
                    headers=headers,
                )
                poll_response.raise_for_status()
                result = poll_response.json()
                status = result.get("status", "")
                if status == "completed":
                    break
                if status == "error":
                    error_msg = result.get("error", "Unknown error")
                    raise RuntimeError(f"AssemblyAI transcription failed: {error_msg}")
            else:
                raise RuntimeError("AssemblyAI transcription timed out after 6 minutes")

        # Step 4: Extract results
        transcript = result.get("text", "")
        if not transcript:
            raise RuntimeError(f"AssemblyAI returned empty transcript")

        # Extract word-level timestamps
        words_raw = result.get("words", [])
        words = []
        for w in words_raw:
            word_text = w.get("text", "")
            start = w.get("start")
            end = w.get("end")
            if word_text and start is not None and end is not None:
                words.append({
                    "text": word_text,
                    "start": float(start) / 1000.0,  # AssemblyAI returns ms
                    "end": float(end) / 1000.0,
                })

        # Extract duration
        duration_seconds = None
        audio_duration = result.get("audio_duration")
        if isinstance(audio_duration, (int, float)) and audio_duration > 0:
            duration_seconds = float(audio_duration)

        return {
            "text": transcript,
            "duration_seconds": duration_seconds,
            "words": words if words else None,
        }

    async def _transcribe_with_doubao(
        self,
        path: Path,
        api_key: str,
        app_id: str | None = None,
        resource_id: str | None = None,
    ) -> dict:
        """Transcribe using Doubao (ByteDance Volcengine) ASR.

        Returns {"text": str, "duration_seconds": float | None, "words": list[dict] | None}.
        """
        res_id = resource_id or self._doubao_resource_id()
        app_id_val = app_id or self._doubao_app_id()
        result = await doubao_asr_transcribe_file(
            file_path=path,
            api_key=api_key,
            resource_id=res_id,
            app_id=app_id_val,
        )
        return result

    @staticmethod
    def _parse_time_offset(val: Any) -> float | None:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            val_clean = val.strip().rstrip("sS")
            try:
                return float(val_clean)
            except ValueError:
                return None
        return None

    @staticmethod
    def _get_first_present_field(d: dict[str, Any], *keys: str) -> Any:
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return None

    @classmethod
    def _extract_google_words(cls, data: dict[str, Any] | list[Any]) -> list[dict[str, Any]] | None:
        """Extract word-level timestamps from Gemini 3.5 Transcribe response payload."""
        words: list[dict[str, Any]] = []

        def _traverse(node: Any) -> None:
            if isinstance(node, dict):
                # Check if this dict itself is a word entry
                text = str(node.get("text") or node.get("word") or "").strip()
                start_val = cls._get_first_present_field(node, "start_time", "start", "begin_time", "start_offset")
                end_val = cls._get_first_present_field(node, "end_time", "end", "end_offset")
                start = cls._parse_time_offset(start_val)
                end = cls._parse_time_offset(end_val)
                if text and start is not None and end is not None and "words" not in node:
                    words.append({"text": text, "start": start, "end": end})
                    return

                # Otherwise inspect nested structures
                for key, val in node.items():
                    if key in {"words", "tokens", "segments", "chunks", "sentences", "items"} or isinstance(val, (dict, list)):
                        _traverse(val)
            elif isinstance(node, list):
                for item in node:
                    _traverse(item)

        _traverse(data)
        return words if words else None

    async def _transcribe_with_google_gemini(
        self,
        path: Path,
        api_key: str,
        *,
        language_hints: list[str] | None = None,
        vocabulary: dict[str, int] | None = None,
    ) -> dict:
        """Transcribe audio using Google Gemini 3.5 Transcribe (Files API + Interactions API).

        Returns {"text": str, "duration_seconds": float | None, "words": list[dict] | None}.
        """
        extension = path.suffix.lower().lstrip(".") or "wav"
        if extension in {"mp3", "mpga"}:
            mime_type = "audio/mpeg"
        elif extension == "wav":
            mime_type = "audio/wav"
        elif extension == "m4a":
            mime_type = "audio/mp4"
        elif extension == "ogg":
            mime_type = "audio/ogg"
        elif extension == "flac":
            mime_type = "audio/flac"
        elif extension == "aac":
            mime_type = "audio/aac"
        else:
            mime_type = f"audio/{extension}"

        base_url = self._google_interactions_base_url()

        # 1. Primary path: Use official google.genai SDK
        if genai is not None:
            http_options: dict[str, Any] = {"api_version": "v1beta"}
            if base_url and base_url != "https://generativelanguage.googleapis.com/v1beta":
                http_options["base_url"] = base_url

            client = genai.Client(api_key=api_key, http_options=http_options)
            audio_file = await asyncio.to_thread(client.files.upload, file=str(path))
            try:
                interaction_input = [
                    {
                        "type": "audio",
                        "uri": audio_file.uri,
                        "mime_type": audio_file.mime_type or mime_type,
                    }
                ]
                kwargs: dict[str, Any] = {
                    "model": GEMINI_TRANSCRIBE_MODEL,
                    "input": interaction_input,
                }
                gen_config: dict[str, Any] = {}
                if vocabulary:
                    gen_config["custom_vocabulary"] = list(vocabulary.keys())
                if language_hints:
                    gen_config["language_hints"] = language_hints
                if gen_config:
                    kwargs["generation_config"] = {"transcription_config": gen_config}

                interaction = await asyncio.to_thread(
                    lambda: client.interactions.create(**kwargs)
                )

                # Extract text
                transcript = ""
                if hasattr(interaction, "output_text") and interaction.output_text:
                    transcript = str(interaction.output_text).strip()
                elif hasattr(interaction, "steps") and interaction.steps:
                    texts: list[str] = []
                    for step in interaction.steps:
                        content = getattr(step, "content", None)
                        if isinstance(content, str) and content.strip():
                            texts.append(content.strip())
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, str) and part.strip():
                                    texts.append(part.strip())
                                elif hasattr(part, "text") and part.text:
                                    texts.append(str(part.text).strip())
                                elif isinstance(part, dict) and part.get("text"):
                                    texts.append(str(part["text"]).strip())
                        elif isinstance(content, dict) and content.get("text"):
                            texts.append(str(content["text"]).strip())
                    transcript = "".join(texts).strip()

                interaction_dict: dict[str, Any] = {}
                if hasattr(interaction, "to_dict"):
                    try:
                        interaction_dict = interaction.to_dict()
                    except Exception:
                        interaction_dict = {}

                if not transcript and isinstance(interaction_dict, dict):
                    transcript = str(
                        interaction_dict.get("output_text")
                        or interaction_dict.get("text")
                        or interaction_dict.get("output", {}).get("text")
                        or ""
                    ).strip()

                if not transcript:
                    raise RuntimeError(f"Google Gemini Transcribe returned empty transcript: {interaction_dict or interaction}")

                words = self._extract_google_words(interaction_dict) if interaction_dict else None

                duration_seconds = None
                usage = getattr(interaction, "usage", None) or interaction_dict.get("usage")
                if usage is not None:
                    if hasattr(usage, "duration_seconds"):
                        duration_seconds = self._parse_time_offset(usage.duration_seconds)
                    elif isinstance(usage, dict):
                        duration_seconds = self._parse_time_offset(usage.get("duration_seconds") or usage.get("duration"))

                return {
                    "text": transcript,
                    "duration_seconds": duration_seconds,
                    "words": words,
                }
            finally:
                try:
                    if hasattr(client.files, "delete") and hasattr(audio_file, "name"):
                        await asyncio.to_thread(client.files.delete, name=audio_file.name)
                except Exception:
                    pass

        # 2. REST HTTP fallback
        headers = {
            "x-goog-api-key": api_key,
        }
        audio_bytes = await asyncio.to_thread(path.read_bytes)
        upload_base = base_url.replace("/v1beta", "")
        upload_url = f"{upload_base}/upload/v1beta/files"
        file_name = ""
        file_uri = ""

        async with httpx.AsyncClient(timeout=180.0) as http_client:
            upload_files = {
                "metadata": (None, json.dumps({"file": {"display_name": path.name}}), "application/json; charset=UTF-8"),
                "file": (path.name, audio_bytes, mime_type),
            }
            upload_resp = await http_client.post(
                upload_url,
                headers={"x-goog-api-key": api_key, "X-Goog-Upload-Protocol": "multipart"},
                files=upload_files,
            )
            upload_resp.raise_for_status()
            file_data = upload_resp.json().get("file", {})
            file_name = file_data.get("name", "")
            file_uri = file_data.get("uri", "")

            try:
                interactions_url = f"{base_url}/interactions"
                interaction_input = [
                    {
                        "type": "audio",
                        "uri": file_uri,
                        "mime_type": mime_type,
                    }
                ]
                interaction_config: dict[str, Any] = {
                    "type": "verbatim",
                    "timestamp_granularities": ["word"],
                }
                if language_hints:
                    interaction_config["language_hints"] = language_hints
                if vocabulary:
                    interaction_config["vocabulary"] = list(vocabulary.keys())

                payload = {
                    "model": GEMINI_TRANSCRIBE_MODEL,
                    "input": interaction_input,
                    "config": interaction_config,
                }
                resp = await http_client.post(
                    interactions_url,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                resp.raise_for_status()
                response_json = resp.json()

                transcript = ""
                if isinstance(response_json.get("output_text"), str):
                    transcript = str(response_json.get("output_text", "")).strip()
                elif isinstance(response_json.get("text"), str):
                    transcript = str(response_json.get("text", "")).strip()
                elif isinstance(response_json.get("output"), dict):
                    out = response_json["output"]
                    transcript = str(out.get("text") or out.get("transcript") or out.get("output_text") or "").strip()
                elif isinstance(response_json.get("steps"), list):
                    texts = []
                    for step in response_json["steps"]:
                        if isinstance(step, dict):
                            content = step.get("content")
                            if isinstance(content, str):
                                texts.append(content)
                            elif isinstance(content, list):
                                for p in content:
                                    if isinstance(p, dict) and p.get("text"):
                                        texts.append(p["text"])
                                    elif isinstance(p, str):
                                        texts.append(p)
                    transcript = "".join(texts).strip()

                if not transcript:
                    raise RuntimeError(f"Google Gemini Transcribe returned empty transcript: {response_json}")

                words = self._extract_google_words(response_json)
                duration_seconds = self._parse_time_offset(
                    response_json.get("duration")
                    or response_json.get("duration_seconds")
                    or response_json.get("usage", {}).get("duration_seconds")
                )

                return {
                    "text": transcript,
                    "duration_seconds": duration_seconds,
                    "words": words,
                }
            finally:
                if file_name:
                    try:
                        delete_url = f"{base_url}/{file_name}"
                        await http_client.delete(delete_url, headers={"x-goog-api-key": api_key})
                    except Exception:
                        pass

    async def create_completed_sync_job(
        self,
        file_path: str,
        original_filename: str,
        transcript: str,
        duration_seconds: float | None = None,
        origin: str | None = "upload",
    ) -> TranscriptionJob:
        """
        Creates a completed job record for a synchronous transcription result.
        This allows sync jobs to appear in the recent records list and be reloadable.
        """
        timestamp = self._now_iso()
        # Primitive extraction with type ignore to silence pedantic linters
        raw_uuid = str(uuid.uuid4().hex)
        job_id_part = str(raw_uuid[:16]) # type: ignore
        job_id = f"tx_sync_{job_id_part}"

        # Save transcript to file (off the event loop)
        transcript_path = await asyncio.to_thread(
            self._persist_transcript, job_id, transcript
        )

        # Explicit initialization with type ignores
        job = TranscriptionJob(
            job_id=str(job_id), # type: ignore
            file_path=str(file_path), # type: ignore
            mode="sync", # type: ignore
            status="completed", # type: ignore
            created_at=str(timestamp), # type: ignore
            updated_at=str(timestamp), # type: ignore
            transcript_path=str(transcript_path), # type: ignore
            error=None, # type: ignore
            remote_job_id=None, # type: ignore
            source_url=None, # type: ignore
            memory_saved=False, # type: ignore
            original_filename=original_filename, # type: ignore
            duration_seconds=duration_seconds, # type: ignore
            origin=origin, # type: ignore
        )
        return self._write_job(job)

    async def prepare_long_transcription_job(self, file_path: str | Path, original_filename: str | None = None) -> TranscriptionJob:
        path = Path(file_path).expanduser().resolve()
        self._validate_file(path)
        timestamp = self._now_iso()
        full_hex = str(uuid.uuid4().hex)
        job_id_part = ""
        for i in range(16):
            job_id_part += full_hex[i]
            
        job = TranscriptionJob(
            job_id=f"tx_{job_id_part}",
            file_path=str(path),
            mode="async",
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
            original_filename=original_filename,
            origin="upload",
        )
        return self._write_job(job)

    async def prepare_long_transcription_url_job(
        self, file_url: str, provider: str | None = None
    ) -> TranscriptionJob:
        normalized_url = self._validate_remote_file_url(file_url)
        timestamp = self._now_iso()
        full_hex = str(uuid.uuid4().hex)
        job_id_part = ""
        for i in range(16):
            job_id_part += full_hex[i]
            
        original_filename = normalized_url.split("/")[-1] if "/" in normalized_url else normalized_url
        job = TranscriptionJob(
            job_id=f"tx_{job_id_part}",
            file_path=normalized_url,
            mode="async",
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
            source_url=normalized_url,
            original_filename=original_filename,
            origin="url",
        )
        job.provider = provider or "qwen-filetrans"
        return self._write_job(job)

    async def submit_long_transcription_job(self, job_id: str) -> TranscriptionJob:
        job = self.get_job(job_id)
        if job is None:
            raise FileNotFoundError(f"Transcription job not found: {job_id}")
        if job.mode != "async":
            raise ValueError("Only async transcription jobs can be submitted.")

        if job.source_url:
            remote_job_id = await self._submit_remote_job_from_url(
                str(job.source_url), provider=job.provider
            )
        else:
            raise ValueError(
                "DashScope async transcription requires a public file_url. "
                "Use the from-url endpoint or sync transcription for local uploads."
            )
        return self.update_job(
            job_id,
            status="submitted",
            remote_job_id=remote_job_id,
            error="",
        )

    def publish_local_job_for_async(self, job_id: str) -> TranscriptionJob:
        job = self.get_job(job_id)
        if job is None:
            raise FileNotFoundError(f"Transcription job not found: {job_id}")

        source_path = Path(job.file_path).expanduser().resolve()
        self._validate_file(source_path)
        publisher = build_transcription_publisher(
            self.config,
            published_dir=self.published_dir,
        )
        published_asset = publisher.publish(
            job_id=job.job_id or uuid.uuid4().hex,
            source_path=source_path,
        )
        return self.update_job(
            job_id,
            source_url=published_asset.source_url,
            error="",
        )

    async def retry_long_transcription_job(self, job_id: str) -> TranscriptionJob:
        job = self.get_job(job_id)
        if job is None:
            raise FileNotFoundError(f"Transcription job not found: {job_id}")
        if job.mode != "async":
            raise ValueError("Only async transcription jobs can be retried.")
        if not job.source_url:
            raise ValueError(
                "Only URL-based async transcription jobs can be retried. "
                "Local uploads still require a public file_url."
            )

        if job.transcript_path:
            transcript_path_val = str(job.transcript_path)
            transcript_path = Path(transcript_path_val)
            try:
                transcript_path.unlink(missing_ok=True)
            except Exception:
                pass

        self.update_job(
            job_id,
            status="queued",
            transcript_path="",
            error="",
            remote_job_id="",
            memory_saved=False,
        )
        return await self.submit_long_transcription_job(job_id)

    async def refresh_long_transcription_job(self, job_id: str) -> TranscriptionJob:
        job = self.get_job(job_id)
        if job is None:
            raise FileNotFoundError(f"Transcription job not found: {job_id}")
        if not job.remote_job_id:
            raise ValueError("Transcription job has not been submitted yet.")

        remote_job_id_str = str(job.remote_job_id)
        remote_status = await self._fetch_remote_job_status(remote_job_id_str)
        mapped_status = self._map_remote_status(remote_status)
        transcript_path = job.transcript_path
        error = job.error or ""

        if mapped_status == "completed":
            # Try to extract with words first
            try:
                result = await self._resolve_remote_transcript_with_words(remote_status)
                transcript_text = result["text"]
                words = result.get("words")
                transcript_path = await asyncio.to_thread(
                    self._persist_transcript, job.job_id or "", transcript_text
                )
                # Save words separately if available
                if words:
                    await asyncio.to_thread(
                        self._persist_words, job.job_id or "", words
                    )
            except Exception:
                # Fallback to text-only extraction
                transcript_text = await self._resolve_remote_transcript(remote_status)
                transcript_path = await asyncio.to_thread(
                    self._persist_transcript, job.job_id or "", transcript_text
                )
            error = ""
        elif mapped_status == "failed":
            error = self._extract_remote_error(remote_status) or "Remote transcription failed."

        return self.update_job(
            job_id,
            status=mapped_status,
            transcript_path=transcript_path,
            error=error,
        )

    async def maybe_save_memory(
        self,
        *,
        transcript_text: str,
        headers: dict[str, Any],
        source: str,
    ) -> bool:
        evermem_config = EverMemConfig()
        evermem_config.update_from_headers(headers)
        evermem_service = evermem_config.get_service()
        if not evermem_service:
            return False

        # Apply Deep Thinking/Reasoning to the transcript before saving
        logger.info("Applying Deep Thinking reasoning to transcript content...")
        reasoned_text = await self.llm_service.reason_about_text(transcript_text, mode="memory")
        if reasoned_text:
            logger.info("Deep Thinking reasoning successful.")
            memory_text = reasoned_text
        else:
            logger.warning("Deep Thinking reasoning returned None, falling back to basic summary.")
            # Fallback to basic summary if reasoning fails or is empty
            memory_text = self._build_transcript_memory_entry(transcript_text)
            
        if not memory_text:
            logger.warning("No memory text generated (summary failed).")
            return False

        logger.info("Saving reasoning results to EverMind memory...")
        saved = await evermem_service.add_memory(
            content=memory_text,
            user_id=evermem_config.memory_scope,
            sender=f"{evermem_config.memory_scope}_{source}",
            sender_name="Echo Transcription",
        )
        if saved is None:
            logger.error("EverMind add_memory returned None.")
        return saved is not None



    async def _submit_remote_job_from_url(
        self, file_url: str, provider: str | None = None
    ) -> str:
        normalized_url = self._validate_remote_file_url(file_url)
        api_key = self._dashscope_key()
        if not api_key:
            raise ValueError("DashScope API Key missing.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": ASYNC_MODEL_BY_PROVIDER.get(provider or "", QWEN_ASR_ASYNC_MODEL),
            "input": {"file_url": normalized_url},
            "parameters": {
                "channel_id": [0],
                "enable_itn": False,
                "enable_words": True,
            },
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{self._dashscope_async_base_url()}/services/audio/asr/transcription",
                headers=headers,
                json=payload,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise RuntimeError(f"Qwen async ASR submission failed: {detail}") from exc

        output = response.json().get("output", {})
        task_id = output.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise RuntimeError("Qwen async ASR submission returned no task_id.")
        return task_id.strip()

    async def _fetch_remote_job_status(self, remote_job_id: str) -> dict[str, Any]:
        api_key = self._dashscope_key()
        if not api_key:
            raise ValueError("DashScope API Key missing.")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.get(
                f"{self._dashscope_async_base_url()}/tasks/{remote_job_id}",
                headers=headers,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise RuntimeError(f"Qwen async ASR status query failed: {detail}") from exc
        return response.json()

    async def _resolve_remote_transcript(self, payload: dict[str, Any]) -> str:
        direct_text = self._extract_remote_transcript(payload)
        if direct_text:
            return direct_text

        result = payload.get("result")
        if isinstance(result, dict):
            transcription_url = result.get("transcription_url")
            if isinstance(transcription_url, str) and transcription_url.strip():
                return await self._download_remote_transcript(transcription_url.strip())

        raise RuntimeError("Remote transcription completed without transcript text.")

    async def _resolve_remote_transcript_with_words(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Resolve remote transcript and extract word-level timestamps.
        Returns {"text": str, "words": list[dict] | None}."""
        # Try to extract from direct payload
        extracted = self._extract_remote_transcript_with_words(payload)
        if extracted.get("text"):
            return extracted

        # Try to download from transcription_url
        result = payload.get("result")
        if isinstance(result, dict):
            transcription_url = result.get("transcription_url")
            if isinstance(transcription_url, str) and transcription_url.strip():
                downloaded = await self._download_remote_transcript_with_words(transcription_url.strip())
                if downloaded.get("text"):
                    return downloaded

        raise RuntimeError("Remote transcription completed without transcript text.")

    async def _download_remote_transcript(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise RuntimeError(f"Failed to download transcription result: {detail}") from exc

        data = response.json()
        if isinstance(data, dict):
            text = self._extract_remote_transcript(data)
            if text:
                return text
            results = data.get("results")
            if isinstance(results, list):
                pieces: list[str] = []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    sentence = item.get("text")
                    if isinstance(sentence, str) and sentence.strip():
                        pieces.append(sentence.strip())
                if pieces:
                    return "\n".join(pieces)
        raise RuntimeError("Downloaded transcription result did not contain transcript text.")

    async def _download_remote_transcript_with_words(self, url: str) -> dict[str, Any]:
        """Download transcription result and extract word-level timestamps.
        Returns {"text": str, "words": list[dict] | None}."""
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise RuntimeError(f"Failed to download transcription result: {detail}") from exc

        data = response.json()
        if isinstance(data, dict):
            extracted = self._extract_remote_transcript_with_words(data)
            if extracted.get("text"):
                return extracted
            # Try results array
            results = data.get("results")
            if isinstance(results, list):
                pieces: list[str] = []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    sentence = item.get("text")
                    if isinstance(sentence, str) and sentence.strip():
                        pieces.append(sentence.strip())
                if pieces:
                    return {"text": "\n".join(pieces), "words": None}
        raise RuntimeError("Downloaded transcription result did not contain transcript text.")

    def _persist_transcript(self, job_id: str, transcript_text: str) -> str:
        transcript_path = self.jobs_dir / f"{job_id}.txt"
        transcript_path.write_text(transcript_text.strip(), encoding="utf-8")
        return str(transcript_path)

    def _persist_words(self, job_id: str, words: list[dict[str, Any]] | None) -> str | None:
        """Save word-level timestamps to JSON file. Returns path or None."""
        if not words:
            return None
        words_path = self.jobs_dir / f"{job_id}_words.json"
        words_path.write_text(
            json.dumps(words, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(words_path)

    def _persist_translation(
        self, job_id: str, translation_data: dict[str, Any]
    ) -> str:
        path = self.jobs_dir / f"{job_id}_translation.json"
        path.write_text(
            json.dumps(translation_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)

    def get_job_translation(self, job_id: str) -> dict[str, Any] | None:
        path = self.jobs_dir / f"{job_id}_translation.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    DEFAULT_TRANSLATION_MODELS = {
        "DashScope": "qwen-plus",
        "Google": "gemini-2.5-flash",
        "DeepSeek": "deepseek-chat",
        "OpenRouter": "deepseek/deepseek-chat",
        "SiliconFlow": "deepseek-ai/DeepSeek-V3",
        "Xiaomi": "mimo-v2.5-pro",
    }

    async def translate_cues(
        self,
        cues: list[dict[str, Any]],
        target_language: str = "zh-CN",
        provider: str | None = None,
        model: str | None = None,
    ) -> list[dict[str, Any]]:
        """Translate a list of subtitle cues preserving timing."""
        if not cues:
            return []

        texts = [str(c.get("text", "")).strip() for c in cues]
        chunk_size = 30
        translated_all: list[str] = []

        lang_names = {
            "zh": "简体中文 (Simplified Chinese)",
            "zh-CN": "简体中文 (Simplified Chinese)",
            "zh-TW": "繁体中文 (Traditional Chinese)",
            "en": "English",
            "ja": "日本語 (Japanese)",
            "ko": "한국어 (Korean)",
            "fr": "Français (French)",
            "de": "Deutsch (German)",
            "es": "Español (Spanish)",
            "ru": "Русский (Russian)",
        }
        target_name = lang_names.get(target_language, target_language)

        # 1. Resolve provider with configured API key
        resolved_provider = provider or "DashScope"
        p_settings = self.config.get_provider_settings(resolved_provider)
        if not p_settings.get("api_key"):
            found = False
            for fallback_p in ["DashScope", "Google", "DeepSeek", "Xiaomi", "OpenRouter", "SiliconFlow"]:
                candidate = self.config.get_provider_settings(fallback_p)
                if candidate.get("api_key"):
                    resolved_provider = fallback_p
                    p_settings = candidate
                    found = True
                    break
            if not found:
                raise ValueError("未检测到任何可用的大模型 API Key。请在“设置 -> API 设置”中配置 DashScope、Google、DeepSeek 或 Xiaomi 的 API Key。")

        # 2. Resolve model name for the provider
        resolved_model = (model or "").strip()
        if not resolved_model:
            configured_model = (p_settings.get("model") or "").strip()
            resolved_model = configured_model or self.DEFAULT_TRANSLATION_MODELS.get(resolved_provider, "qwen-plus")

        def _extract_translated_lines(reply_text: str, expected_len: int) -> list[str]:
            reply_text = reply_text.strip()
            # Try JSON parsing
            clean_json = reply_text
            if "```json" in clean_json:
                clean_json = clean_json.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in clean_json:
                clean_json = clean_json.split("```", 1)[1].split("```", 1)[0].strip()
            try:
                parsed = json.loads(clean_json)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed][:expected_len]
                if isinstance(parsed, dict):
                    for k in ["translations", "subtitles", "results", "cues", "data"]:
                        if isinstance(parsed.get(k), list):
                            return [str(item).strip() for item in parsed[k]][:expected_len]
            except Exception:
                pass

            # Fallback line-by-line parsing
            lines = [l.strip() for l in reply_text.split("\n") if l.strip()]
            parsed_lines = []
            for l in lines:
                if l in ("[", "]", "{", "}"):
                    continue
                cleaned_line = re.sub(r'^(?:\[\d+\]|\d+[\.\:\、\s\-\)]+|\"\d+\"\:)\s*', '', l).strip()
                if (cleaned_line.startswith('"') and cleaned_line.endswith('"')) or (cleaned_line.startswith("'") and cleaned_line.endswith("'")):
                    cleaned_line = cleaned_line[1:-1].strip()
                if cleaned_line:
                    parsed_lines.append(cleaned_line)
            if parsed_lines:
                return parsed_lines[:expected_len]
            raise ValueError(f"无法解析大模型翻译结果: {reply_text[:120]}")

        for i in range(0, len(texts), chunk_size):
            chunk = texts[i : i + chunk_size]
            prompt = (
                f"You are an expert video subtitle translator.\n"
                f"Translate each of the following subtitle lines into {target_name}.\n"
                f"Requirements:\n"
                f"1. Accurately translate each line into natural, fluent {target_name}.\n"
                f"2. Return ONLY a JSON array of strings with EXACTLY {len(chunk)} elements matching the input index order.\n"
                f"3. Do not include any explanations, markdown code fences, or additional text.\n\n"
                f"Input Subtitles:\n{json.dumps(chunk, ensure_ascii=False)}"
            )

            try:
                result = await self.llm_service.chat_completion(
                    provider=resolved_provider,
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": f"You are a specialized video subtitle translation engine. Always translate input text into {target_name}. Output a valid JSON array of strings only."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=3000,
                    use_memory=False,
                )
                reply = result.get("reply", "").strip()
                extracted = _extract_translated_lines(reply, len(chunk))
                for trans_text in extracted:
                    translated_all.append(str(trans_text))
                while len(translated_all) < i + len(chunk):
                    idx_missing = len(translated_all) - i
                    translated_all.append(chunk[idx_missing] if idx_missing < len(chunk) else "")
            except Exception as exc:
                logger.error("Subtitle chunk translation failed with provider %s (%s)", resolved_provider, exc)
                raise RuntimeError(f"使用 {resolved_provider} 模型翻译字幕失败: {exc}") from exc

        result_cues: list[dict[str, Any]] = []
        for idx, cue in enumerate(cues):
            trans = translated_all[idx] if idx < len(translated_all) else ""
            result_cues.append({
                **cue,
                "translation": trans,
            })
        return result_cues

    async def burn_subtitles_to_video(
        self,
        job_id: str,
        srt_content: str,
    ) -> Path:
        job = self.get_job(job_id)
        if not job or not job.file_path:
            raise FileNotFoundError(f"Job or video file not found: {job_id}")
        video_path = Path(str(job.file_path))
        if not video_path.is_file():
            raise FileNotFoundError(f"Video file does not exist: {video_path}")

        srt_path = self.jobs_dir / f"{job_id}_burn.srt"
        srt_path.write_text(srt_content.strip(), encoding="utf-8")

        output_path = self.jobs_dir / f"{job_id}_subtitled.mp4"
        escaped_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
        vf_filter = f"subtitles='{escaped_srt}':force_style='FontSize=19,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=1.2,Shadow=0,MarginV=26,Alignment=2'"

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path.resolve()),
            "-vf",
            vf_filter,
            "-c:a",
            "copy",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "22",
            str(output_path.resolve()),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"Video subtitle burn failed: {err_msg[-400:]}")

        return output_path

    @staticmethod
    def _build_transcript_memory_entry(transcript_text: str) -> str:
        compact = " ".join(str(transcript_text or "").split()).strip()
        if len(compact) < 12:
            return ""
        limit = 320
        if len(compact) > limit:
            snippet = ""
            for i in range(limit):
                snippet += compact[i]
        else:
            snippet = compact
        return f"Echo 转写完成。关键信息摘要：{snippet}"

    @staticmethod
    def _map_remote_status(payload: dict[str, Any]) -> str:
        raw = str(
            payload.get("task_status")
            or payload.get("status")
            or payload.get("state")
            or ""
        ).strip().upper()
        if raw in {"RUNNING", "PENDING", "QUEUED", "SUBMITTED"}:
            return "running"
        if raw in {"SUCCEEDED", "SUCCESS", "COMPLETED", "FINISHED"}:
            return "completed"
        if raw in {"FAILED", "ERROR", "CANCELLED"}:
            return "failed"
        return "running"

    @staticmethod
    def _extract_remote_transcript(payload: dict[str, Any]) -> str:
        transcript = payload.get("transcript")
        if isinstance(transcript, str) and transcript.strip():
            return transcript.strip()

        output = payload.get("output")
        if isinstance(output, dict):
            text = output.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()

        result = payload.get("result")
        if isinstance(result, dict):
            text = result.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            sentences = result.get("sentences")
            if isinstance(sentences, list):
                pieces = [
                    str(item.get("text", "")).strip()
                    for item in sentences
                    if isinstance(item, dict) and str(item.get("text", "")).strip()
                ]
                if pieces:
                    return "\n".join(pieces)

        return ""

    @staticmethod
    def _extract_remote_transcript_with_words(payload: dict[str, Any]) -> dict[str, Any]:
        """Extract transcript text and word-level timestamps from DashScope async response.
        Returns {"text": str, "words": list[dict] | None}."""
        # First extract text using existing method
        text = TranscriptionService._extract_remote_transcript(payload)
        if not text:
            return {"text": "", "words": None}

        # Try to extract word-level timestamps
        words: list[dict[str, Any]] = []

        # Check result.words (top-level words array)
        result = payload.get("result")
        if isinstance(result, dict):
            # Direct words array
            words_raw = result.get("words")
            if isinstance(words_raw, list):
                for w in words_raw:
                    if not isinstance(w, dict):
                        continue
                    word_text = str(w.get("word", "") or w.get("text", "")).strip()
                    begin_time = w.get("begin_time") or w.get("start")
                    end_time = w.get("end_time") or w.get("end")
                    if word_text and begin_time is not None and end_time is not None:
                        # DashScope uses milliseconds, convert to seconds
                        words.append({
                            "text": word_text,
                            "start": float(begin_time) / 1000.0,
                            "end": float(end_time) / 1000.0,
                        })

            # Also check sentences[].words[]
            sentences = result.get("sentences")
            if isinstance(sentences, list) and not words:
                for sentence in sentences:
                    if not isinstance(sentence, dict):
                        continue
                    sentence_words = sentence.get("words")
                    if not isinstance(sentence_words, list):
                        continue
                    for w in sentence_words:
                        if not isinstance(w, dict):
                            continue
                        word_text = str(w.get("word", "") or w.get("text", "")).strip()
                        begin_time = w.get("begin_time") or w.get("start")
                        end_time = w.get("end_time") or w.get("end")
                        if word_text and begin_time is not None and end_time is not None:
                            words.append({
                                "text": word_text,
                                "start": float(begin_time) / 1000.0,
                                "end": float(end_time) / 1000.0,
                            })

        return {
            "text": text,
            "words": words if words else None,
        }

    @staticmethod
    def _extract_remote_error(payload: dict[str, Any]) -> str:
        for key in ("message", "error", "error_message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        output = payload.get("output")
        if isinstance(output, dict):
            message = output.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return ""

    @staticmethod
    def _validate_remote_file_url(file_url: str) -> str:
        normalized = str(file_url or "").strip()
        if not normalized:
            raise ValueError("file_url is required.")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https", "oss"}:
            raise ValueError("file_url must use http, https, or oss scheme.")
        return normalized

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        output = data.get("output")
        if not isinstance(output, dict):
            return ""

        direct_text = output.get("text")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()

        choices = output.get("choices")
        if not isinstance(choices, list):
            return ""

        texts: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                texts.append(content.strip())
                continue
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())

        return "\n".join(part for part in texts if part).strip()
