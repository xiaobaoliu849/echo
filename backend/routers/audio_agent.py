from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

try:
    from services.audio_agent_service import AudioAgentService, AudioAgentServiceError
except ImportError:
    from backend.services.audio_agent_service import AudioAgentService, AudioAgentServiceError


router = APIRouter()
audio_agent_service = AudioAgentService()
_run_threads: dict[int, threading.Thread] = {}
_run_threads_lock = threading.Lock()


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


class AudioAgentStepResponse(BaseModel):
    id: int
    run_id: int
    step_name: str
    status: str
    attempt_index: int
    started_at: str = ""
    finished_at: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""


class AudioAgentSourceResponse(BaseModel):
    id: int
    run_id: int
    source_type: str
    title: str = ""
    uri: str = ""
    snippet: str = ""
    content: str = ""
    score: float = 0.0
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AudioAgentEventResponse(BaseModel):
    id: int
    run_id: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AudioAgentRunResponse(BaseModel):
    id: int
    podcast_id: int | None = None
    topic: str
    language: str
    status: str
    current_step: str
    provider: str
    model: str = ""
    use_memory: bool
    input_payload: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    created_at: str
    updated_at: str
    completed_at: str = ""


class AudioAgentRunDetailResponse(AudioAgentRunResponse):
    steps: list[AudioAgentStepResponse] = Field(default_factory=list)
    sources: list[AudioAgentSourceResponse] = Field(default_factory=list)


class AudioAgentRunListResponse(BaseModel):
    count: int
    runs: list[AudioAgentRunResponse] = Field(default_factory=list)


class AudioAgentEventListResponse(BaseModel):
    count: int
    events: list[AudioAgentEventResponse] = Field(default_factory=list)


class AudioAgentRunCreateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    language: str = Field(default="zh", min_length=1, max_length=20)
    provider: str = Field(default="DashScope", min_length=1, max_length=40)
    model: str | None = Field(default=None, max_length=200)
    use_memory: bool = True
    source_urls: list[str] = Field(default_factory=list, max_length=10)
    source_text: str | None = Field(default=None, max_length=8000)
    generation_constraints: str | None = Field(default=None, max_length=4000)
    turn_count: int = Field(default=8, ge=2, le=40)
    auto_execute: bool = False


class AudioAgentSynthesizeRequest(BaseModel):
    voice_a: str | None = Field(default=None, max_length=200)
    voice_b: str | None = Field(default=None, max_length=200)
    rate: str = Field(default="+0%", max_length=20)
    language: str | None = Field(default=None, max_length=20)
    gap_ms: int = Field(default=250, ge=0, le=3000)
    merge_strategy: str = Field(default="auto", min_length=1, max_length=20)
    intro_music: bool = Field(default=False)
    intro_music_style: str = Field(default="warm", min_length=1, max_length=20)
    intro_music_duration_ms: int = Field(default=2500, ge=800, le=8000)


def _raise_structured(
    status_code: int,
    *,
    code: str,
    message: str,
    meta: dict[str, Any] | None = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "meta": meta or {}},
    )


def _schedule_run_execution(run_id: int, request_headers: dict[str, Any]) -> None:
    with _run_threads_lock:
        existing = _run_threads.get(run_id)
        if existing is not None and existing.is_alive():
            return

        def worker() -> None:
            try:
                asyncio.run(
                    audio_agent_service.execute_until_draft(
                        run_id,
                        request_headers=request_headers,
                    )
                )
            except Exception:
                # Execution failures are persisted by the service.
                pass
            finally:
                with _run_threads_lock:
                    current = _run_threads.get(run_id)
                    if current is thread:
                        _run_threads.pop(run_id, None)

        thread = threading.Thread(
            target=worker,
            name=f"audio-agent-run-{run_id}",
            daemon=True,
        )
        _run_threads[run_id] = thread
        thread.start()


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


@router.post(
    "/runs",
    response_model=AudioAgentRunDetailResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        400: {"description": "Invalid audio agent run request.", "model": StructuredErrorResponse},
        500: {"description": "Failed to create audio agent run.", "model": StructuredErrorResponse},
    },
)
async def create_audio_agent_run(
    payload: AudioAgentRunCreateRequest,
    request: Request,
) -> AudioAgentRunDetailResponse:
    try:
        created = audio_agent_service.create_run(
            topic=payload.topic,
            language=payload.language,
            provider=payload.provider,
            model=payload.model,
            use_memory=payload.use_memory,
            source_urls=payload.source_urls,
            source_text=payload.source_text,
            generation_constraints=payload.generation_constraints,
            turn_count=payload.turn_count,
            auto_execute=payload.auto_execute,
            request_headers=dict(request.headers),
        )
        if payload.auto_execute:
            _schedule_run_execution(int(created["id"]), dict(request.headers))
            result = audio_agent_service.get_run(int(created["id"]))
        else:
            result = created
    except ValueError as exc:
        _raise_structured(400, code="AUDIO_AGENT_RUN_BAD_REQUEST", message=str(exc))
    except AudioAgentServiceError as exc:
        status_code = 404 if exc.code == "AUDIO_AGENT_RUN_NOT_FOUND" else 502
        raise HTTPException(status_code=status_code, detail=exc.to_dict()) from exc
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_AGENT_RUN_CREATE_FAILED",
            message=f"Create audio agent run failed: {exc}",
        )
    return AudioAgentRunDetailResponse(**result)


@router.get(
    "/runs",
    response_model=AudioAgentRunListResponse,
    responses={
        500: {"description": "Failed to list audio agent runs.", "model": StructuredErrorResponse},
    },
)
async def list_audio_agent_runs(
    limit: int = Query(default=20, ge=1, le=200, description="Maximum number of runs to return."),
) -> AudioAgentRunListResponse:
    try:
        runs = audio_agent_service.list_runs(limit=limit)
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_AGENT_RUN_LIST_FAILED",
            message=f"List audio agent runs failed: {exc}",
        )
    return AudioAgentRunListResponse(
        count=len(runs),
        runs=[AudioAgentRunResponse(**item) for item in runs],
    )


@router.get(
    "/runs/{run_id}",
    response_model=AudioAgentRunDetailResponse,
    responses={
        404: {"description": "Audio agent run not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to load audio agent run.", "model": StructuredErrorResponse},
    },
)
async def get_audio_agent_run(run_id: int) -> AudioAgentRunDetailResponse:
    try:
        run = audio_agent_service.get_run(run_id)
    except AudioAgentServiceError as exc:
        raise HTTPException(status_code=404, detail=exc.to_dict()) from exc
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_AGENT_RUN_GET_FAILED",
            message=f"Get audio agent run failed: {exc}",
            meta={"run_id": run_id},
        )
    return AudioAgentRunDetailResponse(**run)


@router.get(
    "/runs/{run_id}/events",
    response_model=AudioAgentEventListResponse,
    responses={
        404: {"description": "Audio agent run not found.", "model": StructuredErrorResponse},
        500: {"description": "Failed to load audio agent run events.", "model": StructuredErrorResponse},
    },
)
async def list_audio_agent_run_events(
    run_id: int,
    limit: int = Query(default=200, ge=1, le=1000, description="Maximum number of events to return."),
) -> AudioAgentEventListResponse:
    try:
        events = audio_agent_service.list_events(run_id, limit=limit)
    except AudioAgentServiceError as exc:
        raise HTTPException(status_code=404, detail=exc.to_dict()) from exc
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_AGENT_EVENT_LIST_FAILED",
            message=f"List audio agent run events failed: {exc}",
            meta={"run_id": run_id},
        )
    return AudioAgentEventListResponse(
        count=len(events),
        events=[AudioAgentEventResponse(**item) for item in events],
    )


@router.post(
    "/runs/{run_id}/execute",
    response_model=AudioAgentRunDetailResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        404: {"description": "Audio agent run not found.", "model": StructuredErrorResponse},
        502: {"description": "Audio agent execution failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected audio agent execution error.", "model": StructuredErrorResponse},
    },
)
async def execute_audio_agent_run(run_id: int, request: Request) -> AudioAgentRunDetailResponse:
    try:
        _schedule_run_execution(run_id, dict(request.headers))
        run = audio_agent_service.get_run(run_id)
    except AudioAgentServiceError as exc:
        status_code = 404 if exc.code == "AUDIO_AGENT_RUN_NOT_FOUND" else 502
        raise HTTPException(status_code=status_code, detail=exc.to_dict()) from exc
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_AGENT_RUN_EXECUTE_FAILED",
            message=f"Execute audio agent run failed: {exc}",
            meta={"run_id": run_id},
        )
    return AudioAgentRunDetailResponse(**run)


@router.post(
    "/runs/{run_id}/synthesize",
    response_model=AudioAgentRunDetailResponse,
    responses={
        **AUTH_WRITE_RESPONSES,
        404: {"description": "Audio agent run not found.", "model": StructuredErrorResponse},
        502: {"description": "Audio agent synthesis failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected audio agent synthesis error.", "model": StructuredErrorResponse},
    },
)
async def synthesize_audio_agent_run(
    run_id: int,
    payload: AudioAgentSynthesizeRequest,
) -> AudioAgentRunDetailResponse:
    try:
        run = await audio_agent_service.synthesize_run(
            run_id,
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
    except AudioAgentServiceError as exc:
        status_code = 404 if exc.code == "AUDIO_AGENT_RUN_NOT_FOUND" else 502
        raise HTTPException(status_code=status_code, detail=exc.to_dict()) from exc
    except Exception as exc:
        _raise_structured(
            500,
            code="AUDIO_AGENT_RUN_SYNTHESIZE_FAILED",
            message=f"Synthesize audio agent run failed: {exc}",
            meta={"run_id": run_id},
        )
    return AudioAgentRunDetailResponse(**run)
