import json
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, cast

# Ensure robust imports for both runtime and IDE
try:
    from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile # type: ignore
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

    class UploadFile:
        filename: str | None = None
        async def read(self) -> bytes: return b""
    
    def Query(*args, **kwargs) -> Any: return Any
    def File(*args, **kwargs) -> Any: return Any

try:
    # Prefer relative import for runtime stability
    from .transcription_service import SUPPORTED_AUDIO_SUFFIXES, TranscriptionJob, TranscriptionService # type: ignore
except ImportError:
    try:
        from backend.services.transcription_service import SUPPORTED_AUDIO_SUFFIXES, TranscriptionJob, TranscriptionService # type: ignore
    except ImportError:
        # Last resort
        from services.transcription_service import SUPPORTED_AUDIO_SUFFIXES, TranscriptionJob, TranscriptionService # type: ignore

logger = logging.getLogger(__name__)
router = APIRouter()
transcription_service = TranscriptionService()


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


class TranscriptionJobListResponse(BaseModel):
    count: int
    jobs: list[TranscriptionJobResponse]


class TranscriptionUrlJobRequest(BaseModel):
    file_url: str = Field(..., min_length=1, max_length=4000)


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
    }
    return TranscriptionJobResponse(**data)


async def _persist_upload(file: UploadFile, target_dir: Path, suffix: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_uuid = str(uuid.uuid4().hex)
    uuid_part = "".join([raw_uuid[i] for i in range(12)])
    target_path = target_dir / f"upload_{uuid_part}{suffix}"
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
            "ASR provider to use: deepgram, openai/whisper, assemblyai, "
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
        result = await transcription_service.transcribe_file(
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
async def create_transcription_job(file: UploadFile = File(...)) -> TranscriptionJobResponse:
    suffix = _validate_upload(file)

    try:
        upload_path = await _persist_upload(file, transcription_service.jobs_dir / "uploads", suffix)
        job = await transcription_service.prepare_long_transcription_job(upload_path, file.filename)
        if transcription_service.can_publish_local_async():
            job = transcription_service.publish_local_job_for_async(job.job_id or "")
            job = await transcription_service.submit_long_transcription_job(job.job_id or "")
        else:
            job = transcription_service.update_job(
                job.job_id or "",
                status="uploaded",
                error=(
                    "Local async uploads are staged only. "
                    "Configure transcription_settings.public_base_url or use "
                    "/api/transcription/jobs/from-url for true DashScope async transcription."
                ),
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
        job = await transcription_service.prepare_long_transcription_url_job(payload.file_url)
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
async def download_transcription_job_audio(job_id: str):
    from fastapi.responses import FileResponse # type: ignore
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
    return FileResponse(
        path=str(audio_path),
        filename=filename,
        media_type=TranscriptionService._guess_mime_type(audio_path),
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
