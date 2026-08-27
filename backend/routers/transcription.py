import asyncio
import json
import logging
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

# Ensure robust imports for both runtime and IDE
try:
    from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect # type: ignore
    from fastapi.responses import Response # type: ignore
    from pydantic import BaseModel, Field # type: ignore
except ImportError:
    # Rich mocks for IDE to silence "unexpected keyword" and "no attribute" errors
    class MockDecorator:
        def __call__(self, f: Any) -> Any: return f

    class APIRouter:
        def post(self, *args, **kwargs): return lambda f: f
        def get(self, *args, **kwargs): return lambda f: f
        def put(self, *args, **kwargs): return lambda f: f
        def delete(self, *args, **kwargs): return lambda f: f
        def websocket(self, *args, **kwargs): return lambda f: f
        def include_router(self, *args, **kwargs): pass

    class BaseModel:
        def __init__(self, **kwargs): pass
        @classmethod
        def model_validate(cls, obj: Any): return cls()

    def Field(*args, **kwargs) -> Any: return Any

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: Any = None, headers: dict | None = None):
            super().__init__(str(detail))
            self.status_code = status_code
            self.detail = detail
            self.headers = headers

    class Response:
        headers: dict[str, str] = {}
        def __init__(self, content: Any = None, status_code: int = 200, headers: dict | None = None, media_type: str | None = None):
            self.content = content
            self.status_code = status_code
            if headers: self.headers.update(headers)

    class Request:
        headers: dict[str, str] = {}
        state: Any = None

    class WebSocket:
        async def accept(self) -> None: pass
        async def receive(self) -> dict: return {}
        async def send_json(self, data: Any) -> None: pass
        async def close(self, code: int = 1000) -> None: pass

    class WebSocketDisconnect(Exception):
        pass

    class UploadFile:
        filename: str | None = None
        async def read(self) -> bytes: return b""

    def Query(*args, **kwargs) -> Any: return Any
    def File(*args, **kwargs) -> Any: return Any
    def Form(*args, **kwargs) -> Any: return Any

try:
    # Prefer relative import for runtime stability
    from .transcription_service import SUPPORTED_AUDIO_SUFFIXES, TranscriptionJob, TranscriptionService # type: ignore
except ImportError:
    try:
        from backend.services.transcription_service import SUPPORTED_AUDIO_SUFFIXES, TranscriptionJob, TranscriptionService # type: ignore
    except ImportError:
        # Last resort
        from services.transcription_service import SUPPORTED_AUDIO_SUFFIXES, TranscriptionJob, TranscriptionService # type: ignore

try:
    from services.realtime_asr_service import (
        RealtimeAsrError,
        STREAMING_MODEL_LANGUAGE_HINT_CAPS,
        build_streaming_asr_session,
    )
except ImportError:  # pragma: no cover - IDE fallback
    from backend.services.realtime_asr_service import (  # type: ignore
        RealtimeAsrError,
        build_streaming_asr_session,
    )

from services.api_auth_guard import validate_websocket_token

logger = logging.getLogger(__name__)
router = APIRouter()
transcription_service = TranscriptionService()

# Strong references for in-flight local chunked transcription tasks. asyncio
# only keeps weak references to tasks, so without this registry a background
# job could be garbage-collected mid-run. Keyed by job id so deleting a job
# cancels its pipeline instead of letting it keep spending ASR budget.
_BACKGROUND_TASKS: dict[str, asyncio.Task] = {}


def _spawn_background_task(coro, job_id: str = "") -> None:
    task = asyncio.create_task(coro)
    if job_id:
        _BACKGROUND_TASKS[job_id] = task

    def _on_done(done: asyncio.Task) -> None:
        if job_id and _BACKGROUND_TASKS.get(job_id) is done:
            del _BACKGROUND_TASKS[job_id]
        # Surface unexpected failures — a silently dead background task would
        # leave the job polling as "running" forever with no diagnostics.
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None:
            logger.error(
                "Background transcription task failed: [%s] %s",
                type(exc).__name__,
                exc,
            )

    task.add_done_callback(_on_done)


def _cancel_background_task(job_id: str) -> None:
    task = _BACKGROUND_TASKS.pop(str(job_id), None)
    if task is not None and not task.done():
        task.cancel()


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


class WordTimestamp(BaseModel):
    text: str
    start: float
    end: float


class TranscriptionSyncResponse(BaseModel):
    transcript: str
    job_id: str | None = None
    memory_saved: bool = False
    duration_seconds: float | None = None
    words: list[WordTimestamp] | None = None
    provider: str | None = None
    source_url: str | None = None


class TranscriptionJobResponse(BaseModel):
    job_id: str
    remote_job_id: str | None = None
    mode: str
    status: str
    file_name: str
    created_at: str | None = None
    updated_at: str | None = None
    transcript: str | None = None
    has_transcript: bool = False
    transcript_download_url: str | None = None
    source_url: str | None = None
    error: str | None = None
    memory_saved: bool = False
    provider: str | None = None
    progress: str | None = None
    duration_seconds: float | None = None
    # Where the recording came from: "upload" | "url" | "realtime".
    origin: str | None = None
    # Short head of the transcript so the library can preview content
    # without fetching the full text for every record.
    transcript_preview: str | None = None


class TranscriptionJobRenameRequest(BaseModel):
    file_name: str = Field(..., min_length=1, max_length=200)


class TranscriptionJobListResponse(BaseModel):
    count: int
    jobs: list[TranscriptionJobResponse]


class TranscriptionUrlJobRequest(BaseModel):
    file_url: str = Field(..., min_length=1, max_length=4000)
    provider: str | None = None


class TranscriptionBatchDeleteRequest(BaseModel):
    job_ids: list[str] = Field(default_factory=list)


class TranscriptionBatchDeleteResponse(BaseModel):
    deleted: list[str]
    failed: list[str]
    deleted_count: int
    failed_count: int


def _error(code: str, message: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "meta": meta or {}}


def _validate_upload(file: UploadFile) -> str:
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_FILE_MISSING", "No file uploaded."),
        )
    filename = str(file.filename)
    suffix = str(Path(filename).suffix).lower()
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=_error(
                "TRANSCRIPTION_UNSUPPORTED_FORMAT",
                "Unsupported audio format.",
                {"supported_suffixes": sorted(list(SUPPORTED_AUDIO_SUFFIXES))},
            ),
        )
    return suffix


def _extract_transcript_preview(path: Path, limit: int = 160) -> str | None:
    """Read just the head of a transcript file for list-view previews."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = handle.read(2048)
    except Exception:
        return None
    cleaned = " ".join(raw.split())
    return cleaned[:limit] or None


async def _job_to_response(
    job: TranscriptionJob, *, include_transcript: bool = True
) -> TranscriptionJobResponse:
    transcript = None
    has_transcript = False
    transcript_download_url = None
    transcript_preview = None
    if job.transcript_path:
        path = Path(str(job.transcript_path))
        if path.is_file():
            has_transcript = True
            transcript_download_url = f"/api/transcription/jobs/{job.job_id}/transcript.txt"
            if include_transcript:
                try:
                    # Transcript files can reach MBs for long recordings —
                    # read off the event loop. List responses pass
                    # include_transcript=False and skip this entirely.
                    transcript = await asyncio.to_thread(
                        lambda: path.read_text(encoding="utf-8")
                    )
                    transcript_preview = " ".join(transcript.split())[:160] or None
                except Exception:
                    transcript = None
            else:
                transcript_preview = await asyncio.to_thread(
                    _extract_transcript_preview, path
                )
    
    # Use dictionary unpacking to avoid "unexpected keyword" IDE errors if inheritance is broken
    # Always prefer the local proxy endpoint when the file exists locally,
    # so the browser doesn't try to fetch a remote/public URL directly.
    source_url: str | None = None
    if job.file_path:
        path = Path(str(job.file_path))
        if path.is_file():
            source_url = f"/api/transcription/jobs/{job.job_id}/audio"
    if not source_url:
        source_url = job.source_url

    data: dict[str, Any] = {
        "job_id": str(job.job_id or ""),
        "remote_job_id": job.remote_job_id,
        "mode": job.mode,
        "status": job.status,
        "file_name": job.original_filename or Path(str(job.file_path)).name,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "transcript": transcript,
        "has_transcript": has_transcript,
        "transcript_download_url": transcript_download_url,
        "source_url": source_url,
        "error": job.error,
        "memory_saved": bool(job.memory_saved),
        "provider": job.provider,
        "progress": job.progress,
        "duration_seconds": job.duration_seconds,
        "origin": job.origin,
        "transcript_preview": transcript_preview,
    }
    return TranscriptionJobResponse(**data)


# Upload size cap for transcription files. The local chunking pipeline
# handles arbitrarily long media, so this guards against pathological
# uploads (disk exhaustion) rather than acting as a functional limit.
MAX_TRANSCRIPTION_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB

_UPLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MiB


class _UploadTooLarge(Exception):
    """Raised inside the copy loop when the upload size cap is exceeded."""


def _upload_too_large_exception() -> HTTPException:
    max_bytes = MAX_TRANSCRIPTION_UPLOAD_BYTES
    if max_bytes >= 1024**3 and max_bytes % 1024**3 == 0:
        limit_desc = f"{max_bytes // 1024**3} GB"
    elif max_bytes >= 1024**2 and max_bytes % 1024**2 == 0:
        limit_desc = f"{max_bytes // 1024**2} MB"
    else:
        limit_desc = f"{max_bytes} bytes"
    return HTTPException(
        status_code=413,
        detail=_error(
            "TRANSCRIPTION_FILE_TOO_LARGE",
            f"Uploaded file exceeds the {limit_desc} limit.",
            {"max_bytes": max_bytes},
        ),
    )


async def _persist_upload(file: UploadFile, target_dir: Path, suffix: str) -> Path:
    """Persist an upload to disk.

    Streams through the spooled temp file when available so large uploads
    (video files can be gigabytes) never sit fully in process memory.
    Rejects uploads larger than MAX_TRANSCRIPTION_UPLOAD_BYTES with HTTP 413.
    """
    declared_size = getattr(file, "size", None)
    if isinstance(declared_size, int) and declared_size > MAX_TRANSCRIPTION_UPLOAD_BYTES:
        raise _upload_too_large_exception()

    target_dir.mkdir(parents=True, exist_ok=True)
    raw_uuid = str(uuid.uuid4().hex)
    uuid_part = "".join([raw_uuid[i] for i in range(12)])
    target_path = target_dir / f"upload_{uuid_part}{suffix}"
    spool = getattr(file, "file", None)
    if spool is not None and hasattr(spool, "read"):
        def _copy() -> None:
            written = 0
            with target_path.open("wb") as out:
                while True:
                    chunk = spool.read(_UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_TRANSCRIPTION_UPLOAD_BYTES:
                        raise _UploadTooLarge()
                    out.write(chunk)

        try:
            await asyncio.to_thread(_copy)
        except _UploadTooLarge:
            target_path.unlink(missing_ok=True)
            raise _upload_too_large_exception() from None
    else:
        # Fallback for file-likes without a spooled buffer: chunked async
        # reads with the same cap, then a single off-loop write.
        chunks: list[bytes] = []
        written = 0
        while True:
            chunk = await file.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_TRANSCRIPTION_UPLOAD_BYTES:
                raise _upload_too_large_exception()
            chunks.append(chunk)
        await asyncio.to_thread(target_path.write_bytes, b"".join(chunks))
    return target_path


@router.post( # type: ignore
    "/",
    response_model=TranscriptionSyncResponse,
    responses={
        400: {"description": "Invalid transcription upload.", "model": StructuredErrorResponse},
        413: {"description": "Upload exceeds the size limit.", "model": StructuredErrorResponse},
        500: {"description": "Transcription failed.", "model": StructuredErrorResponse},
    },
)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    provider: str | None = Query(
        default=None,
        description=(
            "ASR provider to use: deepgram, google/gemini (Gemini 3.5 Transcribe), openai/whisper, assemblyai, doubao, "
            "dashscope/qwen (Qwen-Audio-3.0-ASR-Flash), xiaomi/mimo, "
            "qwen-legacy (qwen3-asr-flash). Auto-selects if not specified."
        ),
    ),
    language_hints: str | None = Query(
        default=None,
        description="Comma-separated language codes (e.g. zh,en). Qwen-Audio ASR only, max 4.",
    ),
    vocabulary: str | None = Query(
        default=None,
        description='JSON object of instant hotwords with weights 1-5 or 50, e.g. {"通义千问": 5}. Qwen-Audio ASR only.',
    ),
) -> TranscriptionSyncResponse:
    suffix = _validate_upload(file)

    try:
        parsed_language_hints = [
            code.strip()
            for code in (language_hints or "").split(",")
            if code.strip()
        ] or None
        parsed_vocabulary = None
        if vocabulary and vocabulary.strip():
            try:
                raw_vocabulary = json.loads(vocabulary)
            except json.JSONDecodeError as exc:
                raise ValueError(f"vocabulary must be a JSON object of hotword weights: {exc}") from exc
            if not isinstance(raw_vocabulary, dict):
                raise ValueError("vocabulary must be a JSON object of hotword weights.")
            parsed_vocabulary = {
                str(word): int(weight) for word, weight in raw_vocabulary.items()
            }

        upload_path = await _persist_upload(file, transcription_service.jobs_dir / "uploads", suffix)
        # transcribe_media transparently extracts video audio tracks,
        # transcodes oversized files and chunks long recordings before
        # calling the sync ASR APIs.
        result = await transcription_service.transcribe_media(
            upload_path,
            provider=provider,
            language_hints=parsed_language_hints,
            vocabulary=parsed_vocabulary,
        )
        transcript = result["text"]
        duration_seconds = result.get("duration_seconds")
        words_raw = result.get("words")

        # Convert words to WordTimestamp objects
        words = None
        if words_raw:
            words = [WordTimestamp(**w) for w in words_raw if isinstance(w, dict)]

        job = await transcription_service.create_completed_sync_job(
            file_path=str(upload_path),
            original_filename=file.filename or "sync_upload",
            transcript=transcript,
            duration_seconds=duration_seconds,
            origin="upload",
        )
        if result.get("provider"):
            transcription_service.update_job(job.job_id or "", provider=result.get("provider"))

        # Save words to job if available (off the event loop — word lists
        # grow to MBs for long recordings).
        if words:
            await asyncio.to_thread(
                transcription_service._persist_words, job.job_id or "", words_raw
            )

        memory_saved = await transcription_service.maybe_save_memory(
            transcript_text=transcript,
            headers=dict(request.headers),
            source="transcription_sync",
        )

        if memory_saved:
            transcription_service.update_job(job.job_id or "", memory_saved=True)

        return TranscriptionSyncResponse(
            **{
                "transcript": transcript,
                "job_id": job.job_id,
                "memory_saved": memory_saved,
                "duration_seconds": duration_seconds,
                "words": words,
                "provider": result.get("provider"),
                "source_url": f"/api/transcription/jobs/{job.job_id}/audio" if job.job_id else None,
            }
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_VALIDATION_ERROR", str(exc)),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_ERROR", str(exc)),
        ) from exc


@router.post( # type: ignore
    "/jobs",
    response_model=TranscriptionJobResponse,
    responses={
        400: {"description": "Invalid transcription job upload.", "model": StructuredErrorResponse},
        413: {"description": "Upload exceeds the size limit.", "model": StructuredErrorResponse},
        500: {"description": "Failed to create transcription job.", "model": StructuredErrorResponse},
    },
)
async def create_transcription_job(
    file: UploadFile = File(...),
    provider: str | None = Form(default=None),
) -> TranscriptionJobResponse:
    suffix = _validate_upload(file)

    try:
        upload_path = await _persist_upload(file, transcription_service.jobs_dir / "uploads", suffix)
        job = await transcription_service.prepare_long_transcription_job(upload_path, file.filename)
        if provider:
            job = transcription_service.update_job(job.job_id or "", provider=provider.strip())
        # Publishing copies (or uploads, for S3) the entire file — potentially
        # gigabytes of video — so run it off the event loop.
        if await asyncio.to_thread(transcription_service.can_publish_local_async):
            job = await asyncio.to_thread(
                transcription_service.publish_local_job_for_async, job.job_id or ""
            )
            job = await transcription_service.submit_long_transcription_job(job.job_id or "")
        else:
            # No public publisher configured — instead of staging the file
            # forever, run the local chunked pipeline: ffmpeg preprocessing +
            # per-chunk sync ASR in the background. The client polls this job
            # exactly like a DashScope async job.
            job = transcription_service.update_job(
                job.job_id or "",
                status="running",
                progress="任务已创建，正在排队…",
                error="",
            )
            _spawn_background_task(
                transcription_service.process_local_chunked_job(
                    job.job_id or "", provider=(provider or None)
                ),
                job_id=job.job_id or "",
            )
        return await _job_to_response(job)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_JOB_BAD_REQUEST", str(exc)),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_CREATE_FAILED", str(exc)),
        ) from exc


@router.post( # type: ignore
    "/jobs/from-url",
    response_model=TranscriptionJobResponse,
    responses={
        400: {"description": "Invalid transcription job URL.", "model": StructuredErrorResponse},
        500: {"description": "Failed to create URL transcription job.", "model": StructuredErrorResponse},
    },
)
async def create_transcription_job_from_url(payload: TranscriptionUrlJobRequest) -> TranscriptionJobResponse:
    try:
        job = await transcription_service.prepare_long_transcription_url_job(
            payload.file_url, provider=payload.provider
        )
        job = await transcription_service.submit_long_transcription_job(job.job_id or "")
        return await _job_to_response(job)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_JOB_BAD_REQUEST", str(exc)),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_CREATE_FAILED", str(exc)),
        ) from exc


@router.get( # type: ignore
    "/jobs",
    response_model=TranscriptionJobListResponse,
    responses={
        400: {"description": "Invalid transcription job query.", "model": StructuredErrorResponse},
        500: {"description": "Failed to list transcription jobs.", "model": StructuredErrorResponse},
    },
)
async def list_transcription_jobs(
    status: str | None = Query(
        default=None,
        description="Comma-separated status filter, e.g. completed,running,failed",
    ),
    limit: int = Query(default=20, ge=1, le=200),
) -> TranscriptionJobListResponse:
    try:
        statuses = {
            item.strip().lower()
            for item in str(status or "").split(",")
            if item.strip()
        }
        # Job-store scan + per-job JSON parsing run in a worker thread.
        # List items omit the transcript text (the UI only renders metadata
        # plus the has_transcript flag), so no per-job transcript reads
        # happen here — previously this endpoint read every transcript file
        # synchronously on the event loop.
        jobs = await asyncio.to_thread(
            transcription_service.list_jobs, statuses=statuses, limit=limit
        )
        job_responses = [
            await _job_to_response(job, include_transcript=False) for job in jobs
        ]
        return TranscriptionJobListResponse(
            **{
                "count": len(jobs),
                "jobs": job_responses,
            }
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_JOB_BAD_REQUEST", str(exc)),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_LIST_FAILED", str(exc)),
        ) from exc


@router.get( # type: ignore
    "/jobs/{job_id}",
    response_model=TranscriptionJobResponse,
    responses={
        404: {"description": "Transcription job not found.", "model": StructuredErrorResponse},
        400: {"description": "Invalid job request.", "model": StructuredErrorResponse},
        500: {"description": "Failed to fetch transcription job.", "model": StructuredErrorResponse},
    },
)
async def get_transcription_job(
    request: Request,
    job_id: str,
    refresh: bool = Query(default=True, description="Refresh remote status before returning."),
) -> TranscriptionJobResponse:
    job = transcription_service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", f"Transcription job not found: {job_id}"),
        )
    # Self-heal records whose local pipeline died with a previous process so
    # the detail view reports an interrupt error instead of polling forever.
    job = transcription_service.reap_stale_active_job(job)

    try:
        if refresh and job.remote_job_id and job.status not in {"completed", "failed"}:
            job = await transcription_service.refresh_long_transcription_job(job_id)
        else:
            job = transcription_service.get_job(job_id) or job

        if (
            job.status == "completed"
            and not job.memory_saved
            and job.transcript_path
            and Path(job.transcript_path).is_file()
        ):
            transcript_path_obj = Path(job.transcript_path)
            transcript_text = await asyncio.to_thread(
                lambda: transcript_path_obj.read_text(encoding="utf-8")
            )
            memory_saved = await transcription_service.maybe_save_memory(
                transcript_text=transcript_text,
                headers=dict(request.headers),
                source="transcription_async",
            )
            if memory_saved:
                job = transcription_service.update_job(job_id, memory_saved=True)
        return await _job_to_response(job)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_JOB_BAD_REQUEST", str(exc)),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_GET_FAILED", str(exc)),
        ) from exc


@router.post( # type: ignore
    "/jobs/{job_id}/retry",
    response_model=TranscriptionJobResponse,
    responses={
        404: {"description": "Transcription job not found.", "model": StructuredErrorResponse},
        400: {"description": "Invalid retry request.", "model": StructuredErrorResponse},
        500: {"description": "Failed to retry transcription job.", "model": StructuredErrorResponse},
    },
)
async def retry_transcription_job(job_id: str) -> TranscriptionJobResponse:
    try:
        existing = transcription_service.get_job(job_id)
        if existing is None:
            raise FileNotFoundError(f"Transcription job not found: {job_id}")
        if existing.mode == "async" and not existing.source_url:
            # Local chunked job — re-run the local pipeline on the stored upload.
            if not existing.file_path or not Path(existing.file_path).is_file():
                raise FileNotFoundError(
                    f"Source file no longer exists for job: {job_id}"
                )
            job = transcription_service.update_job(
                job_id,
                status="running",
                transcript_path="",
                error="",
                progress="正在重新排队…",
            )
            _spawn_background_task(
                transcription_service.process_local_chunked_job(
                    job_id, provider=job.provider
                ),
                job_id=job_id,
            )
            return await _job_to_response(job)
        job = await transcription_service.retry_long_transcription_job(job_id)
        return await _job_to_response(job)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", str(exc)),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_JOB_BAD_REQUEST", str(exc)),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_RETRY_FAILED", str(exc)),
        ) from exc


@router.patch( # type: ignore
    "/jobs/{job_id}",
    response_model=TranscriptionJobResponse,
    responses={
        404: {"description": "Transcription job not found.", "model": StructuredErrorResponse},
        400: {"description": "Invalid rename request.", "model": StructuredErrorResponse},
        500: {"description": "Failed to rename transcription job.", "model": StructuredErrorResponse},
    },
)
async def rename_transcription_job(
    job_id: str, payload: TranscriptionJobRenameRequest
) -> TranscriptionJobResponse:
    """Rename a transcription record's display name."""
    try:
        job = transcription_service.rename_job(job_id, payload.file_name)
        return await _job_to_response(job, include_transcript=False)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", str(exc)),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_JOB_BAD_REQUEST", str(exc)),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_RENAME_FAILED", str(exc)),
        ) from exc


@router.delete( # type: ignore
    "/jobs/{job_id}",
    responses={
        404: {"description": "Transcription job not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to delete transcription job.", "model": StructuredErrorResponse},
    },
)
async def delete_transcription_job(job_id: str) -> dict[str, bool]:
    try:
        # Stop any in-flight chunked pipeline first: otherwise it keeps
        # running ffmpeg + paid ASR for a deleted job, and each progress
        # write resurrects the deleted record.
        _cancel_background_task(job_id)
        deleted = transcription_service.delete_job(job_id)
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", f"Transcription job not found: {job_id}"),
            )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_DELETE_FAILED", str(exc)),
        ) from exc


@router.post( # type: ignore
    "/jobs/batch-delete",
    response_model=TranscriptionBatchDeleteResponse,
    responses={
        400: {"description": "Invalid batch delete request.", "model": StructuredErrorResponse},
        500: {"description": "Failed to delete transcription jobs.", "model": StructuredErrorResponse},
    },
)
async def batch_delete_transcription_jobs(
    payload: TranscriptionBatchDeleteRequest,
) -> TranscriptionBatchDeleteResponse:
    job_ids = [str(job_id).strip() for job_id in (payload.job_ids or []) if str(job_id).strip()]
    if not job_ids:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_JOB_BAD_REQUEST", "job_ids must not be empty."),
        )
    try:
        for job_id in job_ids:
            _cancel_background_task(job_id)
        result = transcription_service.delete_jobs(job_ids)
        deleted = cast(list[str], result["deleted"])
        failed = cast(list[str], result["failed"])
        return TranscriptionBatchDeleteResponse(
            **{
                "deleted": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
            }
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_DELETE_FAILED", str(exc)),
        ) from exc


@router.post( # type: ignore
    "/jobs/{job_id}/save-memory",
    response_model=TranscriptionJobResponse,
    responses={
        404: {"description": "Transcription job not found.", "model": StructuredErrorResponse},
        400: {"description": "Job not ready or memory service unavailable.", "model": StructuredErrorResponse},
        500: {"description": "Failed to save transcription to memory.", "model": StructuredErrorResponse},
    },
)
async def save_transcription_job_memory(request: Request, job_id: str) -> TranscriptionJobResponse:
    """Explicitly persist a finished transcript to EverMem on user request.

    Unlike the automatic save on completion, this is a deliberate action, so the
    client sends EverMem headers that bypass the ``remember_recordings`` auto
    toggle. Idempotent: an already-saved job is returned unchanged.
    """
    job = transcription_service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", f"Transcription job not found: {job_id}"),
        )
    if job.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=_error(
                "TRANSCRIPTION_NOT_COMPLETED",
                "Only completed transcriptions can be saved to memory.",
            ),
        )
    if job.memory_saved:
        return await _job_to_response(job)

    transcript_path = Path(job.transcript_path or "")
    if not transcript_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=_error(
                "TRANSCRIPTION_TRANSCRIPT_NOT_FOUND",
                f"Transcript not found for job: {job_id}",
            ),
        )

    try:
        transcript_text = await asyncio.to_thread(
            lambda: transcript_path.read_text(encoding="utf-8")
        )
        memory_saved = await transcription_service.maybe_save_memory(
            transcript_text=transcript_text,
            headers=dict(request.headers),
            source="transcription_manual",
        )
        if not memory_saved:
            raise HTTPException(
                status_code=400,
                detail=_error(
                    "TRANSCRIPTION_MEMORY_UNAVAILABLE",
                    "Memory service is not configured or rejected the request.",
                ),
            )
        job = transcription_service.update_job(job_id, memory_saved=True)
        return await _job_to_response(job)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_JOB_BAD_REQUEST", str(exc)),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_MEMORY_SAVE_FAILED", str(exc)),
        ) from exc


@router.get( # type: ignore
    "/jobs/{job_id}/transcript.txt",
    responses={
        404: {"description": "Transcript file not found.", "model": StructuredErrorResponse},
    },
)
async def download_transcription_job_transcript(job_id: str) -> Response:
    job = transcription_service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", f"Transcription job not found: {job_id}"),
        )

    transcript_path = Path(job.transcript_path or "")
    if not transcript_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_TRANSCRIPT_NOT_FOUND", f"Transcript not found for job: {job_id}"),
        )

    # FileResponse streams from the threadpool instead of buffering the whole
    # (potentially MB-scale) transcript into memory on the event loop.
    from fastapi.responses import FileResponse  # type: ignore

    return FileResponse(
        path=str(transcript_path),
        media_type="text/plain; charset=utf-8",
        filename=f"{job_id}.txt",
    )


@router.get( # type: ignore
    "/jobs/{job_id}/audio",
    responses={
        404: {"description": "Audio file not found.", "model": StructuredErrorResponse},
    },
)
async def download_transcription_job_audio(request: Request, job_id: str, download: bool = False):
    import anyio # type: ignore
    from fastapi.responses import FileResponse, StreamingResponse # type: ignore
    job = transcription_service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", f"Transcription job not found: {job_id}"),
        )

    if not job.file_path:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_AUDIO_NOT_FOUND", f"Audio path not set for job: {job_id}"),
        )
        
    audio_path = Path(str(job.file_path))
    if not audio_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_AUDIO_NOT_FOUND", f"Audio file not found on disk for job: {job_id}"),
        )

    filename = job.original_filename or audio_path.name
    media_type = TranscriptionService._guess_mime_type(audio_path)
    file_size = audio_path.stat().st_size
    range_header = request.headers.get("range")

    # HTTP headers are latin-1; a non-ASCII (e.g. Chinese) filename interpolated
    # raw would raise on encode and kill the response. Fall back to an ASCII
    # name and carry the real one via RFC 5987 filename*.
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.replace('"', "").replace("\\", "").strip()
    # An all-CJK name strips down to just the extension (".m4a"), which reads as a
    # dotfile to clients that ignore filename*. Note pathlib is no help here:
    # Path(".m4a").stem is ".m4a", not "" — so test the leading dot directly.
    if not ascii_name or ascii_name.startswith("."):
        ascii_name = f"audio{audio_path.suffix}"
    # Default is inline so <audio>/<video> can stream it; ?download=1 flips it to
    # attachment for the transport bar's download button.
    disposition_type = "attachment" if download else "inline"
    disposition = (
        f'{disposition_type}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'
    )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": media_type,
        "Content-Disposition": disposition,
    }

    if range_header and range_header.startswith("bytes="):
        try:
            range_val = range_header.replace("bytes=", "").strip()
            parts = range_val.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
            end = min(end, file_size - 1)

            if start > end or start >= file_size:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}"},
                )

            content_length = end - start + 1
            range_headers = dict(headers)
            range_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            range_headers["Content-Length"] = str(content_length)

            # Async generator: streams off the event loop without occupying an
            # anyio worker thread.  A synchronous generator here is run via
            # iterate_in_threadpool, so a handful of concurrent media range
            # requests (browsers open several per play/seek) can exhaust the
            # default 40-thread pool and stall every other endpoint.
            async def iter_file():
                chunk_size = 256 * 1024
                async with await anyio.open_file(audio_path, "rb") as f:
                    await f.seek(start)
                    remaining = content_length
                    while remaining > 0:
                        data = await f.read(min(chunk_size, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            return StreamingResponse(
                iter_file(),
                status_code=206,
                headers=range_headers,
                media_type=media_type,
            )
        except Exception:
            pass

    headers["Content-Length"] = str(file_size)
    # No filename= here: FileResponse would append a second, conflicting
    # Content-Disposition (attachment) on top of the inline one above.
    return FileResponse(
        path=str(audio_path),
        media_type=media_type,
        headers=headers,
    )


@router.get( # type: ignore
    "/jobs/{job_id}/words",
    response_model=list[WordTimestamp],
    responses={
        404: {"description": "Words data not found.", "model": StructuredErrorResponse},
    },
)
async def get_transcription_job_words(job_id: str) -> list[WordTimestamp]:
    """Get word-level timestamps for a transcription job."""
    job = transcription_service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", f"Transcription job not found: {job_id}"),
        )

    words_path = transcription_service.jobs_dir / f"{job_id}_words.json"
    if not words_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_WORDS_NOT_FOUND", f"Words data not found for job: {job_id}"),
        )

    try:
        # Words JSON grows linearly with audio length — read + parse off the
        # event loop.
        words_data = await asyncio.to_thread(
            lambda: json.loads(words_path.read_text(encoding="utf-8"))
        )
        if not isinstance(words_data, list):
            raise ValueError("Invalid words data format")
        return [WordTimestamp(**w) for w in words_data if isinstance(w, dict)]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_WORDS_READ_FAILED", f"Failed to read words data: {str(exc)}"),
        ) from exc


class TranscriptionTextSaveRequest(BaseModel):
    transcript: str
    file_name: str | None = None
    words: list[WordTimestamp] = Field(default_factory=list)


class CueItem(BaseModel):
    start: float
    end: float
    text: str
    translation: str | None = None
    speaker: str | None = None


class TranslateJobRequest(BaseModel):
    target_language: str = Field(default="zh-CN")
    provider: str | None = None
    model: str | None = None
    cues: list[CueItem] = Field(default_factory=list)


class TranslateJobResponse(BaseModel):
    job_id: str
    target_language: str
    cues: list[CueItem]


class BurnVideoRequest(BaseModel):
    srt_content: str = Field(..., min_length=1)
    target_language: str | None = None
    bilingual: bool = True


class BurnVideoResponse(BaseModel):
    job_id: str
    download_url: str
    message: str


@router.post( # type: ignore
    "/jobs/{job_id}/translate",
    response_model=TranslateJobResponse,
    responses={
        404: {"description": "Transcription job not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to translate cues.", "model": StructuredErrorResponse},
    },
)
async def translate_transcription_job(job_id: str, payload: TranslateJobRequest) -> TranslateJobResponse:
    job = transcription_service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", f"Transcription job not found: {job_id}"),
        )
    try:
        cues_to_translate = [c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in payload.cues]
        if not cues_to_translate:
            transcript_path = Path(job.transcript_path or "")
            if transcript_path.is_file():
                text = transcript_path.read_text(encoding="utf-8")
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                cues_to_translate = [{"start": float(i * 4), "end": float((i + 1) * 4), "text": line} for i, line in enumerate(lines)]

        translated_cues = await transcription_service.translate_cues(
            cues_to_translate,
            target_language=payload.target_language,
            provider=payload.provider,
            model=payload.model,
        )

        trans_data = {
            "job_id": job_id,
            "target_language": payload.target_language,
            "cues": translated_cues,
        }
        await asyncio.to_thread(transcription_service._persist_translation, job_id, trans_data)

        return TranslateJobResponse(
            job_id=job_id,
            target_language=payload.target_language,
            cues=[CueItem(**c) for c in translated_cues],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_TRANSLATE_FAILED", str(exc)),
        ) from exc


@router.get( # type: ignore
    "/jobs/{job_id}/translation",
)
async def get_transcription_job_translation(job_id: str) -> Any:
    data = transcription_service.get_job_translation(job_id)
    if not data:
        return {"job_id": job_id, "target_language": "", "cues": []}
    return data


@router.post( # type: ignore
    "/jobs/{job_id}/burn-video",
    response_model=BurnVideoResponse,
    responses={
        404: {"description": "Job or video file not found.", "model": StructuredErrorResponse},
        500: {"description": "Video burn failed.", "model": StructuredErrorResponse},
    },
)
async def burn_transcription_video(job_id: str, payload: BurnVideoRequest) -> BurnVideoResponse:
    job = transcription_service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_JOB_NOT_FOUND", f"Transcription job not found: {job_id}"),
        )
    try:
        await transcription_service.burn_subtitles_to_video(
            job_id,
            payload.srt_content,
        )
        return BurnVideoResponse(
            job_id=job_id,
            download_url=f"/api/transcription/jobs/{job_id}/burned-video",
            message="Subtitles successfully burned into video.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_BURN_FAILED", str(exc)),
        ) from exc


@router.get( # type: ignore
    "/jobs/{job_id}/burned-video",
    responses={
        404: {"description": "Burned video not found.", "model": StructuredErrorResponse},
    },
)
async def download_burned_video(request: Request, job_id: str, download: bool = False):
    import anyio
    from fastapi.responses import FileResponse, StreamingResponse
    video_path = transcription_service.jobs_dir / f"{job_id}_subtitled.mp4"
    if not video_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=_error("TRANSCRIPTION_VIDEO_NOT_FOUND", f"Subtitled video not found for job: {job_id}"),
        )

    filename = f"{job_id}_subtitled.mp4"
    job = transcription_service.get_job(job_id)
    if job and job.original_filename:
        stem = Path(job.original_filename).stem
        filename = f"{stem}_双语字幕.mp4"

    media_type = "video/mp4"
    file_size = video_path.stat().st_size
    range_header = request.headers.get("range")

    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.replace('"', "").replace("\\", "").strip()
    if not ascii_name or ascii_name.startswith("."):
        ascii_name = "subtitled.mp4"
    disposition_type = "attachment" if download else "inline"
    disposition = f'{disposition_type}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": media_type,
        "Content-Disposition": disposition,
    }

    if range_header and range_header.startswith("bytes="):
        try:
            range_val = range_header.replace("bytes=", "").strip()
            parts = range_val.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
            end = min(end, file_size - 1)

            if start > end or start >= file_size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

            content_length = end - start + 1
            range_headers = dict(headers)
            range_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            range_headers["Content-Length"] = str(content_length)

            async def iter_file():
                chunk_size = 256 * 1024
                async with await anyio.open_file(video_path, "rb") as f:
                    await f.seek(start)
                    remaining = content_length
                    while remaining > 0:
                        data = await f.read(min(chunk_size, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            return StreamingResponse(
                iter_file(),
                status_code=206,
                headers=range_headers,
                media_type=media_type,
            )
        except Exception:
            pass

    headers["Content-Length"] = str(file_size)
    return FileResponse(path=str(video_path), media_type=media_type, headers=headers)



@router.post( # type: ignore
    "/jobs/save-text",
    response_model=TranscriptionJobResponse,
    responses={
        400: {"description": "Invalid transcript text.", "model": StructuredErrorResponse},
        500: {"description": "Failed to save transcript.", "model": StructuredErrorResponse},
    },
)
async def save_transcription_text(payload: TranscriptionTextSaveRequest) -> TranscriptionJobResponse:
    """Persist a finished realtime transcription as a completed job record."""
    transcript = (payload.transcript or "").strip()
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail=_error("TRANSCRIPTION_VALIDATION_ERROR", "transcript must not be empty."),
        )
    try:
        job = await transcription_service.create_completed_sync_job(
            file_path="realtime_mic",
            original_filename=(payload.file_name or "").strip() or "实时转写",
            transcript=transcript,
            origin="realtime",
        )
        if payload.words:
            await asyncio.to_thread(
                transcription_service._persist_words,
                job.job_id or "",
                [w.model_dump() for w in payload.words],
            )
        return await _job_to_response(job)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error("TRANSCRIPTION_JOB_CREATE_FAILED", str(exc)),
        ) from exc


def _parse_realtime_config(raw: Any) -> dict[str, Any]:
    """Validate the realtime WS config message. Returns kwargs for the session factory."""
    if not isinstance(raw, dict):
        return {}
    config: dict[str, Any] = {}

    hints = raw.get("language_hints")
    if isinstance(hints, list):
        cleaned = [str(code).strip() for code in hints if str(code).strip()]
        if cleaned:
            config["language_hints"] = cleaned[:4]

    vocabulary = raw.get("vocabulary")
    if isinstance(vocabulary, dict):
        parsed: dict[str, int] = {}
        for word, weight in vocabulary.items():
            try:
                parsed[str(word)] = int(weight)
            except (TypeError, ValueError):
                continue
        if parsed:
            config["vocabulary"] = parsed

    semantic = raw.get("semantic_punctuation")
    if isinstance(semantic, bool):
        config["semantic_punctuation"] = semantic

    silence = raw.get("max_sentence_silence")
    if isinstance(silence, (int, float)) and 200 <= int(silence) <= 6000:
        config["max_sentence_silence"] = int(silence)

    model = raw.get("model")
    if isinstance(model, str) and model.strip() in STREAMING_MODEL_LANGUAGE_HINT_CAPS:
        config["model"] = model.strip()

    return config


# If the browser stops sending frames and the upstream stays quiet for this long,
# assume the client vanished (tab killed / network drop without a TCP close) and
# tear the session down rather than holding a live paid upstream socket forever.
REALTIME_IDLE_TIMEOUT = 120.0


@router.websocket("/realtime") # type: ignore
async def transcription_realtime_ws(websocket: WebSocket) -> None:
    """Proxy browser mic PCM (16kHz mono) to Qwen-Audio-3.0-ASR-Flash-Streaming.

    Client protocol:
      1. (optional) text JSON {"type": "config", "language_hints": [...], "vocabulary": {...}}
      2. binary PCM16 frames
      3. text JSON {"type": "finish"} to flush and end
    Server sends: started / sentence / finished / error.
    """
    # The HTTP auth middleware does not cover WebSocket scopes; enforce auth
    # during the handshake itself (browser passes the bearer token as the
    # ``token`` query parameter).
    try:
        validate_websocket_token(websocket.query_params.get("token"))
    except HTTPException:
        # Closing before accept() rejects the handshake (HTTP 403 upstream).
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session = None
    upstream_task: asyncio.Task | None = None
    receive_task: asyncio.Task | None = None
    try:
        # First message may be a JSON config; audio frames follow.
        try:
            first = await asyncio.wait_for(websocket.receive(), timeout=10.0)
        except asyncio.TimeoutError as exc:
            raise ValueError("Realtime transcription config message timed out.") from exc
        if first.get("type") == "websocket.disconnect":
            return
        config_kwargs: dict[str, Any] = {}
        pending_audio: bytes | None = None
        if first.get("text"):
            try:
                config_kwargs = _parse_realtime_config(json.loads(first["text"]))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid realtime config JSON: {exc}") from exc
        elif first.get("bytes"):
            pending_audio = bytes(first["bytes"])

        session = build_streaming_asr_session(
            transcription_service.config,
            **config_kwargs,
        )
        await session.start()
        await websocket.send_json({"type": "started"})
        if pending_audio:
            await session.send_audio(pending_audio)

        async def _forward_upstream() -> None:
            assert session is not None
            async for sentence in session.events():
                await websocket.send_json(sentence.to_client_dict())

        upstream_task = asyncio.create_task(_forward_upstream())
        client_finished = False
        disconnected = False

        while not disconnected and not (client_finished and upstream_task.done()):
            receive_task = asyncio.create_task(websocket.receive())
            done, _pending = await asyncio.wait(
                {receive_task, upstream_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=REALTIME_IDLE_TIMEOUT,
            )
            if not done:
                # Idle timeout: no client frames and no upstream results. The
                # client almost certainly went away without a clean close; drop
                # the session instead of blocking (and billing) forever.
                receive_task.cancel()
                logger.info("Realtime ASR session closed after idle timeout.")
                break
            if upstream_task in done:
                exc = upstream_task.exception()
                if exc is not None:
                    receive_task.cancel()
                    raise exc
                # Upstream finished cleanly (task-finished).
                if not receive_task.done():
                    receive_task.cancel()
                break
            message = receive_task.result()
            if message.get("type") == "websocket.disconnect":
                disconnected = True
                break
            if message.get("bytes") is not None:
                await session.send_audio(bytes(message["bytes"]))
            elif message.get("text"):
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("type") == "finish":
                    await session.finish()
                    client_finished = True

        if client_finished and not disconnected:
            try:
                await asyncio.wait_for(asyncio.shield(upstream_task), timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Realtime ASR upstream drain timed out after finish-task")
            await websocket.send_json({"type": "finished"})
            await websocket.close(code=1000)
        elif not disconnected:
            # Upstream ended on its own (or the session idled out). Tell the
            # client the session is finished so it can surface whatever was
            # transcribed, then close cleanly instead of leaving it hanging.
            try:
                await websocket.send_json({"type": "finished"})
            except Exception:
                pass
            try:
                await websocket.close(code=1000)
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    except (ValueError, RealtimeAsrError) as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=1003)
        except Exception:
            pass
    except Exception as exc:
        logger.exception("Realtime transcription session failed")
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        pending_tasks = [
            task for task in (receive_task, upstream_task)
            if task is not None and not task.done()
        ]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        if session is not None:
            await session.close()
