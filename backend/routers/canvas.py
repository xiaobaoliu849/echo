from typing import Literal, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

try:
    from services.canvas_service import CanvasService
except ImportError:
    from backend.services.canvas_service import CanvasService

router = APIRouter()
canvas_service = CanvasService()

class CanvasGenerateRequest(BaseModel):
    prompt: str = Field(..., max_length=4000)
    images: list[str] = Field(default_factory=list)
    mode: Literal["react", "html"] = Field(default="react")
    existing_code: str | None = None
    provider: str | None = None
    model: str | None = None

class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)

class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail

@router.post(
    "/generate",
    responses={
        401: {"description": "Missing Bearer token", "model": StructuredErrorResponse},
        403: {"description": "Authentication invalid", "model": StructuredErrorResponse},
    },
)
async def generate_canvas(payload: CanvasGenerateRequest, request: Request) -> StreamingResponse:
    async def event_generator():
        try:
            async for event_str in canvas_service.generate_code_stream(
                prompt=payload.prompt,
                images=payload.images,
                mode=payload.mode,
                existing_code=payload.existing_code,
                provider=payload.provider,
                model=payload.model,
            ):
                yield event_str
        except Exception as exc:
            import json
            error_payload = {"type": "error", "detail": str(exc), "code": "internal_error"}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )
