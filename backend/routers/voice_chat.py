from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket
from pydantic import BaseModel, Field

from services.realtime_voice_service import (
    DEFAULT_DASHSCOPE_REALTIME_VOICE,
    DEFAULT_GOOGLE_REALTIME_VOICE,
    DEFAULT_OPENAI_REALTIME_VOICE,
    RealtimeVoiceService,
)
from services.voice_agent_session_repository import VoiceAgentSessionRepository

router = APIRouter()
voice_chat_service = RealtimeVoiceService()
voice_agent_session_repository = VoiceAgentSessionRepository()


class VoiceAgentSessionResponse(BaseModel):
    id: str
    provider: str
    model: str = ""
    voice: str = ""
    status: str
    started_at: str
    ended_at: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class VoiceAgentTurnResponse(BaseModel):
    id: int
    session_id: str
    turn_id: str
    user_text: str = ""
    assistant_text: str = ""
    memory_payload: dict[str, Any] = Field(default_factory=dict)
    completed: bool
    interrupted: bool = False
    completion_status: str = "pending"
    started_at: str
    completed_at: str = ""


class VoiceAgentToolEventResponse(BaseModel):
    id: int
    session_id: str
    turn_id: str = ""
    event_type: str
    tool_name: str = ""
    query: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class VoiceAgentTimelineEventResponse(BaseModel):
    id: str
    event_type: str
    source: str
    turn_id: str = ""
    tool_name: str = ""
    query: str = ""
    text: str = ""
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int | None = None
    provider: str = ""
    transport: str = ""
    stage: str = ""


class VoiceAgentSessionListResponse(BaseModel):
    count: int
    sessions: list[VoiceAgentSessionResponse] = Field(default_factory=list)


class VoiceAgentRunLinkResponse(BaseModel):
    id: int
    agent_run_id: str
    voice_session_id: str
    voice_turn_id: str
    relation_type: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    run: dict[str, Any] = Field(default_factory=dict)


class MetricDistributionResponse(BaseModel):
    count: int = 0
    avg: int | None = None
    p50: int | None = None
    p95: int | None = None
    min: int | None = None
    max: int | None = None


class VoiceAgentMetricProviderResponse(BaseModel):
    provider: str
    session_count: int
    turn_count: int
    completed_turn_count: int
    interrupted_turn_count: int
    decision_count: int
    classifications: dict[str, int] = Field(default_factory=dict)
    false_interruption_rate: float | None = None
    first_audio_ms: MetricDistributionResponse
    interruption_decision_ms: MetricDistributionResponse
    interruption_stop_ms: MetricDistributionResponse
    turn_completion_ms: MetricDistributionResponse


class VoiceAgentMetricsSummaryResponse(VoiceAgentMetricProviderResponse):
    provider: str = "all"
    providers: list[VoiceAgentMetricProviderResponse] = Field(default_factory=list)


class VoiceAgentSessionDetailResponse(VoiceAgentSessionResponse):
    turns: list[VoiceAgentTurnResponse] = Field(default_factory=list)
    tool_events: list[VoiceAgentToolEventResponse] = Field(default_factory=list)
    timeline: list[VoiceAgentTimelineEventResponse] = Field(default_factory=list)
    agent_run_links: list[VoiceAgentRunLinkResponse] = Field(default_factory=list)


def _raise_not_found(session_id: str) -> None:
    raise HTTPException(
        status_code=404,
        detail={
            "code": "VOICE_AGENT_SESSION_NOT_FOUND",
            "message": f"Voice agent session not found: {session_id}",
            "meta": {"session_id": session_id},
        },
    )


@router.get("/sessions", response_model=VoiceAgentSessionListResponse)
async def list_voice_agent_sessions(
    limit: int = Query(default=20, ge=1, le=200),
) -> VoiceAgentSessionListResponse:
    sessions = voice_agent_session_repository.list_sessions(limit=limit)
    return VoiceAgentSessionListResponse(count=len(sessions), sessions=sessions)


@router.get("/sessions/metrics/summary", response_model=VoiceAgentMetricsSummaryResponse)
async def get_voice_agent_metrics_summary(
    limit: int = Query(default=200, ge=1, le=200),
    provider: str = Query(default="", max_length=80),
) -> VoiceAgentMetricsSummaryResponse:
    summary = voice_agent_session_repository.summarize_metrics(limit=limit, provider=provider)
    return VoiceAgentMetricsSummaryResponse(provider=(provider or "all"), **summary)


@router.get("/sessions/{session_id}", response_model=VoiceAgentSessionDetailResponse)
async def get_voice_agent_session(session_id: str) -> VoiceAgentSessionDetailResponse:
    session = voice_agent_session_repository.get_session(session_id)
    if session is None:
        _raise_not_found(session_id)
    assert session is not None
    return VoiceAgentSessionDetailResponse(
        **session,
        turns=voice_agent_session_repository.list_turns(session_id),
        tool_events=voice_agent_session_repository.list_tool_events(session_id),
        timeline=voice_agent_session_repository.build_timeline(session_id),
        agent_run_links=voice_agent_session_repository.list_agent_run_links(session_id),
    )


@router.websocket("/ws")
async def voice_chat_ws(
    websocket: WebSocket,
    provider: str = "Google",
    model: str | None = None,
    voice: str | None = None,
    target_language_code: str = "en",
    echo_target_language: bool = True,
) -> None:
    await websocket.accept()

    selected_provider = (provider or "Google").strip()
    if selected_provider not in {"Google", "DashScope", "OpenAI"}:
        await websocket.send_json(
            {
                "type": "error",
                "message": f"当前 Web 实时语音暂不支持 {selected_provider} 供应商。",
                "provider": selected_provider,
            }
        )
        await websocket.close(code=1003)
        return

    try:
        if selected_provider == "DashScope":
            if voice_chat_service._is_qwen_audio_model(model):
                await voice_chat_service.stream_dashscope_audio_session(
                    websocket,
                    model=model,
                    voice=(voice or DEFAULT_DASHSCOPE_REALTIME_VOICE).strip(),
                )
            else:
                await voice_chat_service.stream_dashscope_session(
                    websocket,
                    model=model,
                    voice=(voice or DEFAULT_DASHSCOPE_REALTIME_VOICE).strip(),
                )
        elif selected_provider == "OpenAI":
            await voice_chat_service.stream_openai_session(
                websocket,
                model=model,
                voice=(voice or DEFAULT_OPENAI_REALTIME_VOICE).strip(),
            )
        else:
            await voice_chat_service.stream_google_session(
                websocket,
                model=model,
                voice=(voice or DEFAULT_GOOGLE_REALTIME_VOICE).strip(),
                target_language_code=(target_language_code or "en").strip(),
                echo_target_language=bool(echo_target_language),
            )
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
