from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.tavus_config import TavusConfig
from services.tavus_service import TavusError

router = APIRouter()


class TavusCreateConversationRequest(BaseModel):
    pal_id: str | None = Field(default=None, min_length=1, max_length=256)
    conversation_name: str | None = Field(default=None, min_length=1, max_length=256)
    face_id: str | None = Field(default=None, min_length=1, max_length=256)


class TavusConversationResponse(BaseModel):
    conversation_id: str
    conversation_url: str
    status: str | None = None
    # Only present upstream when the conversation was created with
    # require_auth; the browser must pass it as the Daily join token.
    meeting_token: str | None = None


class TavusPalSummary(BaseModel):
    pal_id: str
    pal_name: str


class TavusPalListResponse(BaseModel):
    pals: list[TavusPalSummary]


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "meta": {}},
    )


def _map_tavus_error(exc: TavusError) -> HTTPException:
    if exc.upstream_status in (401, 403):
        return _http_error(
            502,
            "TAVUS_AUTH_REJECTED",
            "Tavus rejected the API key. Check the key in the PAL page or server config.",
        )
    return _http_error(
        502,
        exc.code if exc.code.startswith("TAVUS_") else "TAVUS_UPSTREAM_ERROR",
        exc.message,
    )


def _load_config(request: Request) -> TavusConfig:
    config = TavusConfig()
    config.update_from_headers(dict(request.headers))
    return config


@router.get(
    "/pals",
    response_model=TavusPalListResponse,
    responses={
        400: {"description": "Tavus API key is not configured.", "model": StructuredErrorResponse},
        502: {"description": "Tavus upstream request failed.", "model": StructuredErrorResponse},
    },
)
async def list_tavus_pals(request: Request) -> TavusPalListResponse:
    config = _load_config(request)
    service = config.get_service()
    if not service:
        raise _http_error(
            400,
            "TAVUS_NOT_CONFIGURED",
            "A Tavus API key is required. Set it in the PAL page or via TAVUS_API_KEY.",
        )

    try:
        pals = await service.list_pals()
    except TavusError as exc:
        raise _map_tavus_error(exc)

    summaries: list[TavusPalSummary] = []
    for item in pals:
        pal_id = str(item.get("pal_id", "")).strip()
        if not pal_id:
            continue
        summaries.append(
            TavusPalSummary(
                pal_id=pal_id,
                pal_name=str(item.get("pal_name", "")).strip() or pal_id,
            )
        )
    return TavusPalListResponse(pals=summaries)


@router.post(
    "/conversations",
    response_model=TavusConversationResponse,
    responses={
        400: {"description": "Tavus credentials or PAL id are missing.", "model": StructuredErrorResponse},
        502: {"description": "Tavus upstream request failed.", "model": StructuredErrorResponse},
    },
)
async def create_tavus_conversation(
    payload: TavusCreateConversationRequest,
    request: Request,
) -> TavusConversationResponse:
    config = _load_config(request)
    service = config.get_service()
    if not service:
        raise _http_error(
            400,
            "TAVUS_NOT_CONFIGURED",
            "A Tavus API key is required. Set it in the PAL page or via TAVUS_API_KEY.",
        )

    pal_id = (payload.pal_id or "").strip() or (config.pal_id or "")
    if not pal_id:
        raise _http_error(
            400,
            "TAVUS_PAL_ID_MISSING",
            "Choose a PAL (or set TAVUS_PAL_ID) before starting a video conversation.",
        )

    try:
        result = await service.create_conversation(
            pal_id=pal_id,
            conversation_name=(payload.conversation_name or "").strip() or None,
            face_id=(payload.face_id or "").strip() or None,
        )
    except TavusError as exc:
        raise _map_tavus_error(exc)

    return TavusConversationResponse(
        conversation_id=str(result.get("conversation_id", "")).strip(),
        conversation_url=str(result.get("conversation_url", "")).strip(),
        status=str(result.get("status", "")).strip() or None,
        meeting_token=str(result.get("meeting_token", "")).strip() or None,
    )


@router.delete(
    "/conversations/{conversation_id}",
    responses={
        400: {"description": "Tavus API key is not configured.", "model": StructuredErrorResponse},
        502: {"description": "Tavus upstream request failed.", "model": StructuredErrorResponse},
    },
)
async def end_tavus_conversation(conversation_id: str, request: Request) -> dict[str, bool]:
    config = _load_config(request)
    service = config.get_service()
    if not service:
        raise _http_error(
            400,
            "TAVUS_NOT_CONFIGURED",
            "A Tavus API key is required. Set it in the PAL page or via TAVUS_API_KEY.",
        )

    try:
        await service.end_conversation(conversation_id.strip())
    except TavusError as exc:
        raise _map_tavus_error(exc)
    return {"ended": True}
