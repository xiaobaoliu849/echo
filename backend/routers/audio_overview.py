from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from services.audio_overview_service import AudioOverviewService, AudioOverviewServiceError

router = APIRouter()
audio_overview_service = AudioOverviewService()


class ScriptLine(BaseModel):
    role: str = Field(default="A", min_length=1, max_length=8)
    text: str = Field(..., min_length=1, max_length=4000)


class PodcastCreateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    language: str = Field(default="zh", min_length=1, max_length=20)
    audio_path: str | None = None
    script_lines: list[ScriptLine] = Field(default_factory=list)


class PodcastUpdateRequest(BaseModel):
    topic: str | None = Field(default=None, min_length=1, max_length=500)
    language: str | None = Field(default=None, min_length=1, max_length=20)
    audio_path: str | None = None
    script_lines: list[ScriptLine] | None = None


class ScriptUpdateRequest(BaseModel):
    script_lines: list[ScriptLine] = Field(default_factory=list)


class ScriptGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=2000)
    language: str = Field(default="zh", min_length=1, max_length=20)
    turn_count: int = Field(default=10, ge=2, le=40)
    provider: str = Field(default="DashScope", min_length=1, max_length=40)
    model: str | None = Field(default=None, max_length=200)


class ScriptGenerateResponse(BaseModel):
    topic: str
    language: str
    turn_count: int
    provider: str
    model: str
    script_lines: list[dict[str, str]] = Field(default_factory=list)
    memories_retrieved: int = 0
    memory_saved: bool = False


class PodcastResponse(BaseModel):
    id: int
    topic: str
    language: str
    audio_path: str | None = None
    created_at: str
    updated_at: str
    script_lines: list[dict[str, str]] = Field(default_factory=list)


class PodcastListResponse(BaseModel):
    count: int
    podcasts: list[PodcastResponse]


class PodcastDeleteResponse(BaseModel):
    id: int
    deleted: bool


class PodcastSynthesizeRequest(BaseModel):
    voice_a: str | None = Field(default=None, max_length=200, description="Voice name for role A.")
    voice_b: str | None = Field(default=None, max_length=200, description="Voice name for role B.")
    rate: str = Field(default="+0%", max_length=20, description="Speech rate, e.g. +0%, +10%, -10%.")
    language: str | None = Field(default=None, max_length=20, description="Language hint. Supported values: zh, en.")
    gap_ms: int = Field(default=250, ge=0, le=3000, description="Silence gap between lines in milliseconds.")
    merge_strategy: str = Field(
        default="auto",
        min_length=1,
        max_length=20,
        description="Audio merge strategy: auto|pydub|ffmpeg|concat.",
    )
    intro_music: bool = Field(default=False, description="Prepend a generated intro music bed.")
    intro_music_style: str = Field(default="warm", min_length=1, max_length=20)
    intro_music_duration_ms: int = Field(default=2500, ge=800, le=8000)


class PodcastSynthesizeResponse(BaseModel):
    podcast_id: int
    audio_path: str
    audio_download_url: str
    line_count: int
    voice_a: str
    voice_b: str
    rate: str
    cache_hits: int
    gap_ms: int
    gap_ms_applied: int
    merge_strategy: str
    intro_music: bool = False
    intro_music_style: str = "off"
    intro_music_duration_ms: int = 0


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


def _error_detail(code: str, message: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "meta": meta or {}}


def _raise_structured(
    status_code: int,
    *,
    code: str,
    message: str,
    meta: dict[str, Any] | None = None,
) -> None:
    raise HTTPException(status_code=status_code, detail=_error_detail(code, message, meta))


AUTH_WRITE_RESPONSES = {
    401: {
        "description": "Missing Bearer token when write auth is enabled.",
        "model": StructuredErrorResponse,
    },
    403: {
        "description": "Authentication token invalid.",
        "model": StructuredErrorResponse,
    },
}


@router.get(
    "/podcasts",
    response_model=PodcastListResponse,
    responses={
        500: {"description": "Failed to list podcasts.", "model": StructuredErrorResponse},
    },
)
async def list_podcasts(
    limit: int = Query(default=20, ge=1, le=200, description="Maximum number of podcasts to return."),
) -> PodcastListResponse:
    try:
        podcasts = audio_overview_service.list_podcasts(limit=limit)
        details = [
            audio_overview_service.get_podcast(item["id"], include_script=True)
            for item in podcasts
        ]
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_OVERVIEW_LIST_FAILED",
            message=f"List podcasts failed: {exc}",
        )

    result = [item for item in details if item is not None]
    return PodcastListResponse(count=len(result), podcasts=[PodcastResponse(**item) for item in result])


@router.get(
    "/podcasts/latest",
    response_model=PodcastResponse,
    responses={
        404: {"description": "No podcast found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to load latest podcast.", "model": StructuredErrorResponse},
    },
)
async def get_latest_podcast() -> PodcastResponse:
    try:
        podcast = audio_overview_service.get_latest_podcast(include_script=True)
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_OVERVIEW_GET_LATEST_FAILED",
            message=f"Get latest podcast failed: {exc}",
        )
    if podcast is None:
        _raise_structured(404, code="AUDIO_OVERVIEW_NOT_FOUND", message="No podcast found.")
    return PodcastResponse(**podcast)


@router.get(
    "/podcasts/{podcast_id}",
    response_model=PodcastResponse,
    responses={
        404: {"description": "Podcast not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to load podcast.", "model": StructuredErrorResponse},
    },
)
async def get_podcast(podcast_id: int) -> PodcastResponse:
    try:
        podcast = audio_overview_service.get_podcast(podcast_id, include_script=True)
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_OVERVIEW_GET_FAILED",
            message=f"Get podcast failed: {exc}",
            meta={"podcast_id": podcast_id},
        )
    if podcast is None:
        _raise_structured(
            404,
            code="AUDIO_OVERVIEW_NOT_FOUND",
            message=f"Podcast not found: {podcast_id}",
            meta={"podcast_id": podcast_id},
        )
    return PodcastResponse(**podcast)


@router.get(
    "/podcasts/{podcast_id}/audio",
    responses={
        404: {"description": "Podcast/audio file not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to load podcast audio.", "model": StructuredErrorResponse},
    },
)
async def get_podcast_audio(podcast_id: int) -> Response:
    try:
        podcast = audio_overview_service.get_podcast(podcast_id, include_script=False)
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_OVERVIEW_AUDIO_GET_FAILED",
            message=f"Get podcast audio failed: {exc}",
            meta={"podcast_id": podcast_id},
        )

    if podcast is None:
        _raise_structured(
            404,
            code="AUDIO_OVERVIEW_NOT_FOUND",
            message=f"Podcast not found: {podcast_id}",
            meta={"podcast_id": podcast_id},
        )

    raw_audio_path = podcast.get("audio_path")
    audio_path = str(raw_audio_path or "").strip()
    if not audio_path or audio_path.lower() == "none":
        _raise_structured(
            404,
            code="AUDIO_OVERVIEW_AUDIO_MISSING",
            message=f"Podcast has no synthesized audio: {podcast_id}",
            meta={"podcast_id": podcast_id},
        )

    file_path = Path(audio_path)
    
    if not file_path.exists():
        # Fallback 1: Attempt WSL to Windows path translation
        path_str = str(file_path).replace("\\", "/")
        if path_str.startswith("/mnt/"):
            drive = path_str[5:6].upper()
            rest = path_str[6:]
            fallback_path = Path(f"{drive}:{rest}")
            if fallback_path.exists():
                file_path = fallback_path
                
    if not file_path.exists():
        # Fallback 2: Check standard backend output directory
        base_dir = Path(__file__).resolve().parents[1] / "temp_audio" / "audio_overview"
        fallback_path = base_dir / file_path.name
        if fallback_path.exists():
            file_path = fallback_path

    if not file_path.exists() or not file_path.is_file():
        _raise_structured(
            404,
            code="AUDIO_OVERVIEW_AUDIO_FILE_NOT_FOUND",
            message=f"Audio file not found: {audio_path}",
            meta={"podcast_id": podcast_id, "audio_path": audio_path},
        )

    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        headers={"Accept-Ranges": "bytes"},
    )


@router.post(
    "/podcasts",
    response_model=PodcastResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        400: {"description": "Invalid podcast create request.", "model": StructuredErrorResponse},
        500: {"description": "Failed to create podcast.", "model": StructuredErrorResponse},
    },
)
async def create_podcast(payload: PodcastCreateRequest) -> PodcastResponse:
    try:
        podcast = audio_overview_service.create_podcast(
            topic=payload.topic,
            language=payload.language,
            audio_path=payload.audio_path,
            script_lines=[item.model_dump() for item in payload.script_lines],
        )
    except ValueError as exc:
        _raise_structured(400, code="AUDIO_OVERVIEW_CREATE_BAD_REQUEST", message=str(exc))
    except Exception as exc:
        _raise_structured(500, code="AUDIO_OVERVIEW_CREATE_FAILED", message=f"Create podcast failed: {exc}")
    return PodcastResponse(**podcast)


@router.put(
    "/podcasts/{podcast_id}",
    response_model=PodcastResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        400: {"description": "Invalid podcast update request.", "model": StructuredErrorResponse},
        404: {"description": "Podcast not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to update podcast.", "model": StructuredErrorResponse},
    },
)
async def update_podcast(podcast_id: int, payload: PodcastUpdateRequest) -> PodcastResponse:
    script_lines: list[dict[str, Any]] | None = None
    if payload.script_lines is not None:
        script_lines = [item.model_dump() for item in payload.script_lines]
    try:
        podcast = audio_overview_service.update_podcast(
            podcast_id,
            topic=payload.topic,
            language=payload.language,
            audio_path=payload.audio_path,
            script_lines=script_lines,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("podcast not found"):
            _raise_structured(
                404,
                code="AUDIO_OVERVIEW_NOT_FOUND",
                message=message,
                meta={"podcast_id": podcast_id},
            )
        _raise_structured(400, code="AUDIO_OVERVIEW_UPDATE_BAD_REQUEST", message=message)
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_OVERVIEW_UPDATE_FAILED",
            message=f"Update podcast failed: {exc}",
            meta={"podcast_id": podcast_id},
        )
    return PodcastResponse(**podcast)


@router.put(
    "/podcasts/{podcast_id}/script",
    response_model=PodcastResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        400: {"description": "Invalid script update request.", "model": StructuredErrorResponse},
        404: {"description": "Podcast not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to save podcast script.", "model": StructuredErrorResponse},
    },
)
async def save_podcast_script(podcast_id: int, payload: ScriptUpdateRequest) -> PodcastResponse:
    try:
        audio_overview_service.save_script(
            podcast_id,
            [item.model_dump() for item in payload.script_lines],
        )
        podcast = audio_overview_service.get_podcast(podcast_id, include_script=True)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("podcast not found"):
            _raise_structured(
                404,
                code="AUDIO_OVERVIEW_NOT_FOUND",
                message=message,
                meta={"podcast_id": podcast_id},
            )
        _raise_structured(400, code="AUDIO_OVERVIEW_SCRIPT_BAD_REQUEST", message=message)
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_OVERVIEW_SCRIPT_SAVE_FAILED",
            message=f"Save podcast script failed: {exc}",
            meta={"podcast_id": podcast_id},
        )

    if podcast is None:
        _raise_structured(
            404,
            code="AUDIO_OVERVIEW_NOT_FOUND",
            message=f"Podcast not found: {podcast_id}",
            meta={"podcast_id": podcast_id},
        )
    return PodcastResponse(**podcast)


@router.post(
    "/scripts/generate",
    response_model=ScriptGenerateResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        400: {"description": "Invalid script generation request.", "model": StructuredErrorResponse},
        502: {"description": "LLM provider request failed.", "model": StructuredErrorResponse},
        500: {"description": "Failed to generate script.", "model": StructuredErrorResponse},
    },
)
async def generate_script(payload: ScriptGenerateRequest, request: Request) -> ScriptGenerateResponse:
    try:
        result = await audio_overview_service.generate_script(
            topic=payload.topic,
            language=payload.language,
            turn_count=payload.turn_count,
            provider=payload.provider,
            model=payload.model,
            request_headers=dict(request.headers),
        )
    except ValueError as exc:
        _raise_structured(400, code="AUDIO_SCRIPT_GENERATE_BAD_REQUEST", message=str(exc))
    except RuntimeError as exc:
        _raise_structured(502, code="AUDIO_SCRIPT_GENERATE_PROVIDER_ERROR", message=str(exc))
    except Exception as exc:
        _raise_structured(500, code="AUDIO_SCRIPT_GENERATE_FAILED", message=f"Generate script failed: {exc}")

    return ScriptGenerateResponse(
        topic=result["topic"],
        language=result["language"],
        turn_count=result["turn_count"],
        provider=result["provider"],
        model=result["model"],
        script_lines=result["script_lines"],
        memories_retrieved=int(result.get("memories_retrieved", 0)),
        memory_saved=bool(result.get("memory_saved", False)),
    )


@router.post(
    "/podcasts/{podcast_id}/synthesize",
    response_model=PodcastSynthesizeResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        400: {
            "description": "Invalid request payload or unsupported merge strategy.",
            "model": StructuredErrorResponse,
        },
        404: {"description": "Podcast not found.", "model": StructuredErrorResponse},
        503: {
            "description": "Synthesis or merge dependency is temporarily unavailable.",
            "model": StructuredErrorResponse,
        },
        500: {"description": "Unexpected synthesis server error.", "model": StructuredErrorResponse},
    },
)
async def synthesize_podcast_audio(
    podcast_id: int,
    payload: PodcastSynthesizeRequest,
) -> PodcastSynthesizeResponse:
    try:
        result = await audio_overview_service.synthesize_podcast_audio(
            podcast_id,
            voice_a=payload.voice_a,
            voice_b=payload.voice_b,
            rate=payload.rate,
            language=payload.language,
            gap_ms=payload.gap_ms,
            merge_strategy=payload.merge_strategy,
            intro_music=payload.intro_music,
            intro_music_style=payload.intro_music_style,
            intro_music_duration_ms=payload.intro_music_duration_ms,
        )
    except AudioOverviewServiceError as exc:
        if exc.code == "AUDIO_MERGE_STRATEGY_INVALID":
            status_code = 400
        elif (
            exc.code.startswith("AUDIO_MERGE_")
            or exc.code.startswith("AUDIO_INTRO_MUSIC_")
            or exc.code == "AUDIO_SEGMENT_SYNTHESIS_FAILED"
        ):
            status_code = 503
        else:
            status_code = 500
        raise HTTPException(status_code=status_code, detail=exc.to_dict()) from exc
    except ValueError as exc:
        message = str(exc)
        if message.startswith("podcast not found"):
            _raise_structured(
                404,
                code="AUDIO_OVERVIEW_NOT_FOUND",
                message=message,
                meta={"podcast_id": podcast_id},
            )
        _raise_structured(400, code="AUDIO_SYNTHESIZE_BAD_REQUEST", message=message)
    except RuntimeError as exc:
        _raise_structured(503, code="AUDIO_SYNTHESIZE_RUNTIME_ERROR", message=str(exc))
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_SYNTHESIZE_FAILED",
            message=f"Synthesize podcast failed: {exc}",
            meta={"podcast_id": podcast_id},
        )

    return PodcastSynthesizeResponse(
        podcast_id=result["podcast_id"],
        audio_path=result["audio_path"],
        audio_download_url=f"/api/audio-overview/podcasts/{podcast_id}/audio",
        line_count=result["line_count"],
        voice_a=result["voice_a"],
        voice_b=result["voice_b"],
        rate=result["rate"],
        cache_hits=result["cache_hits"],
        gap_ms=result["gap_ms"],
        gap_ms_applied=result["gap_ms_applied"],
        merge_strategy=result["merge_strategy"],
        intro_music=bool(result.get("intro_music", False)),
        intro_music_style=str(result.get("intro_music_style", "off")),
        intro_music_duration_ms=int(result.get("intro_music_duration_ms", 0)),
    )


@router.delete(
    "/podcasts/{podcast_id}",
    response_model=PodcastDeleteResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        404: {"description": "Podcast not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to delete podcast.", "model": StructuredErrorResponse},
    },
)
async def delete_podcast(podcast_id: int) -> PodcastDeleteResponse:
    try:
        deleted = audio_overview_service.delete_podcast(podcast_id)
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_OVERVIEW_DELETE_FAILED",
            message=f"Delete podcast failed: {exc}",
            meta={"podcast_id": podcast_id},
        )
    if not deleted:
        _raise_structured(
            404,
            code="AUDIO_OVERVIEW_NOT_FOUND",
            message=f"Podcast not found: {podcast_id}",
            meta={"podcast_id": podcast_id},
        )
    return PodcastDeleteResponse(id=podcast_id, deleted=True)
