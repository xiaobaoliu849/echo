from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from services.llm_service import LLMService

router = APIRouter()
llm_service = LLMService()


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=12000)
    target_language: str = Field(..., min_length=1, max_length=40)
    source_language: str | None = Field(default="auto", max_length=40)
    provider: str = Field(default="DashScope")
    model: str | None = None


class TranslateResponse(BaseModel):
    provider: str
    model: str
    translated_text: str


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, str] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


@router.post(
    "/",
    response_model=TranslateResponse,
    responses={
        401: {"description": "Missing Bearer token when write auth is enabled.", "model": StructuredErrorResponse},
        400: {"description": "Invalid translation request payload.", "model": StructuredErrorResponse},
        403: {"description": "Authentication token invalid.", "model": StructuredErrorResponse},
        502: {"description": "Provider upstream request failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected server error.", "model": StructuredErrorResponse},
    },
)
async def translate(payload: TranslateRequest) -> TranslateResponse:
    try:
        result = await llm_service.translate_text(
            text=payload.text,
            target_language=payload.target_language,
            source_language=payload.source_language,
            provider=payload.provider,
            model=payload.model,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "TRANSLATE_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "TRANSLATE_PROVIDER_ERROR", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "TRANSLATE_INTERNAL_ERROR",
                "message": f"Translation failed: {exc}",
                "meta": {},
            },
        ) from exc
    return TranslateResponse(**result)


@router.post(
    "/image",
    response_model=TranslateResponse,
    responses={
        401: {"description": "Missing Bearer token when write auth is enabled.", "model": StructuredErrorResponse},
        400: {"description": "Invalid image translation request payload.", "model": StructuredErrorResponse},
        403: {"description": "Authentication token invalid.", "model": StructuredErrorResponse},
        502: {"description": "Provider upstream request failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected server error.", "model": StructuredErrorResponse},
    },
)
async def translate_image(
    image_file: UploadFile = File(...),
    target_language: str = Form(..., min_length=1, max_length=40),
    source_language: str = Form(default="auto", max_length=40),
    provider: str = Form(default="DashScope"),
    model: str | None = Form(default=None),
) -> TranslateResponse:
    if not image_file.filename:
        raise HTTPException(
            status_code=400,
            detail={"code": "TRANSLATE_IMAGE_BAD_REQUEST", "message": "image_file is required.", "meta": {}},
        )

    if image_file.content_type and not image_file.content_type.lower().startswith("image/"):
        # Cheap check before reading anything into memory.
        raise HTTPException(
            status_code=400,
            detail={"code": "TRANSLATE_IMAGE_BAD_REQUEST", "message": "Only image files are supported.", "meta": {}},
        )

    # Stream-read with a hard cap: slurping first and validating later let a
    # huge upload spike RSS by several times its size (raw + base64 + JSON)
    # in this single-process server.
    max_image_bytes = 20 * 1024 * 1024
    buffer = bytearray()
    while True:
        chunk = await image_file.read(1024 * 1024)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_image_bytes:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "TRANSLATE_IMAGE_TOO_LARGE",
                    "message": f"Image files larger than {max_image_bytes // (1024 * 1024)} MB are not supported.",
                    "meta": {},
                },
            )
    data = bytes(buffer)
    if not data:
        raise HTTPException(
            status_code=400,
            detail={"code": "TRANSLATE_IMAGE_BAD_REQUEST", "message": "image_file is empty.", "meta": {}},
        )

    try:
        result = await llm_service.translate_image(
            image_bytes=data,
            image_mime_type=image_file.content_type or "",
            target_language=target_language,
            source_language=source_language,
            provider=provider,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "TRANSLATE_IMAGE_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "TRANSLATE_IMAGE_PROVIDER_ERROR", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "TRANSLATE_IMAGE_INTERNAL_ERROR",
                "message": f"Image translation failed: {exc}",
                "meta": {},
            },
        ) from exc
    return TranslateResponse(**result)
