import asyncio
import json
import logging
import shutil
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

logger = logging.getLogger(__name__)
router = APIRouter()
transcription_service = TranscriptionService()

# Strong references for in-flight local chunked transcription tasks. asyncio
# only keeps weak references to tasks, so without this set a background job
# could be garbage-collected mid-run.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn_background_task(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


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


def _job_to_response(job: TranscriptionJob) -> TranscriptionJobResponse:
    transcript = None
    has_transcript = False
    transcript_download_url = None
    if job.transcript_path:
        path = Path(str(job.transcript_path))
        if path.is_file():
            try:
                transcript = path.read_text(encoding="utf-8")
                has_transcript = True
                transcript_download_url = f"/api/transcription/jobs/{job.job_id}/transcript.txt"
            except Exception:
                pass
    
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
    }
    return TranscriptionJobResponse(**data)


async def _persist_upload(file: UploadFile, target_dir: Path, suffix: str) -> Path:
    """Persist an upload to disk.

    Streams through the spooled temp file when available so large uploads
    (video files can be gigabytes) never sit fully in process memory.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_uuid = str(uuid.uuid4().hex)
    uuid_part = "".join([raw_uuid[i] for i in range(12)])
    target_path = target_dir / f"upload_{uuid_part}{suffix}"
    spool = getattr(file, "file", None)
    if spool is not None and hasattr(spool, "read"):
        def _copy() -> None:
            with target_path.open("wb") as out:
                shutil.copyfileobj(spool, out)

        await asyncio.to_thread(_copy)
    else:
        content = await file.read()
        target_path.write_bytes(content)
    return target_path


@router.post( # type: ignore
    "/",
    response_model=TranscriptionSyncResponse,
    responses={
        400: {"description": "Invalid transcription upload.", "model": StructuredErrorResponse},
        500: {"description": "Transcription failed.", "model": StructuredErrorResponse},
    },
)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    provider: str | None = Query(
        default=None,
        description=(
            "ASR provider to use: deepgram, openai/whisper, assemblyai, doubao, "
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
            transcript=transcript
        )
        if result.get("provider"):
            transcription_service.update_job(job.job_id or "", provider=result.get("provider"))

        # Save words to job if available
        if words:
            transcription_service._persist_words(job.job_id or "", words_raw)

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
            }
        )
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
        if transcription_service.can_publish_local_async():
            job = transcription_service.publish_local_job_for_async(job.job_id or "")
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
                )
            )
        return _job_to_response(job)
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
        return _job_to_response(job)
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
        jobs = transcription_service.list_jobs(statuses=statuses, limit=limit)
        return TranscriptionJobListResponse(
            **{
                "count": len(jobs),
                "jobs": [_job_to_response(job) for job in jobs],
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
            transcript_text = Path(job.transcript_path).read_text(encoding="utf-8")
            memory_saved = await transcription_service.maybe_save_memory(
                transcript_text=transcript_text,
                headers=dict(request.headers),
                source="transcription_async",
            )
            if memory_saved:
                job = transcription_service.update_job(job_id, memory_saved=True)
        return _job_to_response(job)
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
                )
            )
            return _job_to_response(job)
        job = await transcription_service.retry_long_transcription_job(job_id)
        return _job_to_response(job)
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


@router.delete( # type: ignore
    "/jobs/{job_id}",
    responses={
        404: {"description": "Transcription job not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to delete transcription job.", "model": StructuredErrorResponse},
    },
)
async def delete_transcription_job(job_id: str) -> dict[str, bool]:
    try:
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
        return _job_to_response(job)

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
        transcript_text = transcript_path.read_text(encoding="utf-8")
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
        return _job_to_response(job)
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

    response = Response(
        content=transcript_path.read_bytes(),
        media_type="text/plain; charset=utf-8",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{job_id}.txt"'
    return response


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
        words_data = json.loads(words_path.read_text(encoding="utf-8"))
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
        )
        if payload.words:
            transcription_service._persist_words(
                job.job_id or "",
                [w.model_dump() for w in payload.words],
            )
        return _job_to_response(job)
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
