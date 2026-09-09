from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from services.elevenlabs_voice_service import ElevenLabsVoiceService
from services.qwen_voice_service import QwenVoiceService
from services.xiaomi_voice_service import XiaomiVoiceService
from services.tts_service import TTSService

VoiceType = Literal["voice_design", "voice_clone"]
MAX_LOCAL_CLONE_FILE_BYTES = 20 * 1024 * 1024

router = APIRouter()
qwen_voice_service = QwenVoiceService()
xiaomi_voice_service = XiaomiVoiceService()
elevenlabs_voice_service = ElevenLabsVoiceService()
tts_service = TTSService()
_whisper_model = None
_whisper_model_lock = threading.Lock()


def _transcribe_local_clone_sync(audio_path: str) -> str:
    global _whisper_model
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is required to create GPT-SoVITS local clones.") from exc

    with _whisper_model_lock:
        if _whisper_model is None:
            _whisper_model = WhisperModel("tiny", device="cpu")
        segments, _info = _whisper_model.transcribe(audio_path)
        return "".join(segment.text for segment in segments).strip()


async def _transcribe_local_clone(audio_path: str) -> str:
    return await asyncio.to_thread(_transcribe_local_clone_sync, audio_path)


class VoiceDesignRequest(BaseModel):
    voice_prompt: str = Field(..., min_length=1, max_length=4000)
    preview_text: str = Field(..., min_length=1, max_length=1200)
    preferred_name: str = Field(..., min_length=1, max_length=80)
    language: str = Field(default="zh", min_length=1, max_length=20)
    provider: str = Field(default="qwen", min_length=1, max_length=20)


class VoiceCreateResponse(BaseModel):
    voice: str | None = None
    type: VoiceType
    target_model: str | None = None
    preferred_name: str | None = None
    language: str | None = None
    preview_audio_data: str | None = None
    provider: str | None = None


class VoiceListResponse(BaseModel):
    voice_type: VoiceType
    voice_provider: str | None = None
    count: int
    voices: list[dict[str, Any]]


class VoiceDeleteResponse(BaseModel):
    voice: str
    type: VoiceType
    deleted: bool


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


@router.post(
    "/design",
    response_model=VoiceCreateResponse,
    responses={
        401: {"description": "Missing Bearer token when write auth is enabled.", "model": StructuredErrorResponse},
        403: {"description": "Authentication token invalid.", "model": StructuredErrorResponse},
        400: {"description": "Invalid voice design request.", "model": StructuredErrorResponse},
        502: {"description": "Provider upstream request failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected server error.", "model": StructuredErrorResponse},
    },
)
async def create_voice_design(payload: VoiceDesignRequest) -> VoiceCreateResponse:
    provider = (payload.provider or "qwen").strip().lower()
    try:
        if provider == "xiaomi" or provider == "mimo":
            result = await xiaomi_voice_service.create_voice_design(
                voice_prompt=payload.voice_prompt,
                preview_text=payload.preview_text,
                language=payload.language,
            )
            result["provider"] = "xiaomi"
        elif provider == "gpt_sovits":
            raise ValueError("GPT-SoVITS local API does not support voice design. Use voice clone instead.")
        elif provider == "elevenlabs":
            raise ValueError("ElevenLabs does not support voice design. Use voice clone instead.")
        else:
            result = await qwen_voice_service.create_voice_design(
                voice_prompt=payload.voice_prompt,
                preview_text=payload.preview_text,
                preferred_name=payload.preferred_name,
                language=payload.language,
            )
            result["provider"] = "qwen"
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "VOICE_DESIGN_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "VOICE_DESIGN_PROVIDER_ERROR", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "VOICE_DESIGN_INTERNAL_ERROR",
                "message": f"Create voice design failed: {exc}",
                "meta": {},
            },
        ) from exc
    return VoiceCreateResponse(**result)


@router.post(
    "/clone",
    response_model=VoiceCreateResponse,
    responses={
        401: {"description": "Missing Bearer token when write auth is enabled.", "model": StructuredErrorResponse},
        403: {"description": "Authentication token invalid.", "model": StructuredErrorResponse},
        400: {"description": "Invalid voice clone request.", "model": StructuredErrorResponse},
        502: {"description": "Provider upstream request failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected server error.", "model": StructuredErrorResponse},
    },
)
async def create_voice_clone(
    preferred_name: str = Form(..., min_length=1, max_length=80),
    audio_file: UploadFile = File(...),
    provider: str = Form(default="qwen"),
) -> VoiceCreateResponse:
    if not audio_file.filename:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VOICE_CLONE_BAD_REQUEST",
                "message": "audio_file is required.",
                "meta": {},
            },
        )

    data = await audio_file.read()
    if not data:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VOICE_CLONE_BAD_REQUEST",
                "message": "audio_file is empty.",
                "meta": {},
            },
        )
    if len(data) > MAX_LOCAL_CLONE_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VOICE_CLONE_BAD_REQUEST",
                "message": "audio_file is too large. Keep it within 20MB.",
                "meta": {"max_bytes": MAX_LOCAL_CLONE_FILE_BYTES},
            },
        )

    provider = (provider or "qwen").strip().lower()
    try:
        if provider == "xiaomi" or provider == "mimo":
            result = await xiaomi_voice_service.create_voice_clone(
                audio_bytes=data,
                mime_type=audio_file.content_type or "",
            )
            result["provider"] = "xiaomi"
            result["preferred_name"] = preferred_name
        elif provider == "elevenlabs":
            result = await elevenlabs_voice_service.create_voice_clone(
                audio_bytes=data,
                mime_type=audio_file.content_type or "",
                preferred_name=preferred_name,
            )
            result["provider"] = "elevenlabs"
        elif provider == "gpt_sovits":
            prompt_text = ""
            saved = tts_service.save_local_gpt_sovits_voice(
                preferred_name=preferred_name,
                audio_bytes=data,
                filename=audio_file.filename,
                content_type=audio_file.content_type or "",
                prompt_text="",
            )

            try:
                local_voice = tts_service._find_local_gpt_sovits_voice(saved["voice"])
                if local_voice:
                    audio_path, text_path = local_voice
                    prompt_text = await _transcribe_local_clone(str(audio_path))
                    if text_path:
                        text_path.write_text(prompt_text, encoding="utf-8")
            except Exception as e:
                print(f"Local Whisper transcription failed: {e}")
                prompt_text = ""

            result = saved
        else:
            result = await qwen_voice_service.create_voice_clone(
                audio_bytes=data,
                mime_type=audio_file.content_type or "",
                preferred_name=preferred_name,
            )
            result["provider"] = "qwen"
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "VOICE_CLONE_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "VOICE_CLONE_PROVIDER_ERROR", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "VOICE_CLONE_INTERNAL_ERROR",
                "message": f"Create voice clone failed: {exc}",
                "meta": {},
            },
        ) from exc
    return VoiceCreateResponse(**result)


@router.get(
    "/",
    response_model=VoiceListResponse,
    responses={
        400: {"description": "Invalid voice list query.", "model": StructuredErrorResponse},
        502: {"description": "Provider upstream request failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected server error.", "model": StructuredErrorResponse},
    },
)
async def list_voices(
    voice_type: VoiceType = Query(default="voice_design"),
    page_index: int = Query(default=0, ge=0),
    page_size: int = Query(default=100, ge=1, le=200),
    provider: str = Query(default="qwen"),
) -> VoiceListResponse:
    provider = (provider or "qwen").strip().lower()
    try:
        if provider == "xiaomi" or provider == "mimo":
            # Xiaomi doesn't have persistent voice management
            result = {"voice_type": voice_type, "count": 0, "voices": []}
            result["voice_provider"] = "xiaomi"
        elif provider == "gpt_sovits":
            local_voices = tts_service._get_local_gpt_sovits_voices()
            result = {
                "voice_type": voice_type,
                "count": len(local_voices),
                "voices": local_voices,
            }
            result["voice_provider"] = "gpt_sovits"
        elif provider == "elevenlabs":
            result = await elevenlabs_voice_service.list_voices()
            result["voice_provider"] = "elevenlabs"
        else:
            result = await qwen_voice_service.list_voices(
                voice_type=voice_type,
                page_index=page_index,
                page_size=page_size,
            )
            result["voice_provider"] = "qwen"
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "VOICE_LIST_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "VOICE_LIST_PROVIDER_ERROR", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "VOICE_LIST_INTERNAL_ERROR",
                "message": f"List voices failed: {exc}",
                "meta": {},
            },
        ) from exc
    return VoiceListResponse(**result)


@router.delete(
    "/{voice_name}",
    response_model=VoiceDeleteResponse,
    responses={
        401: {"description": "Missing Bearer token when write auth is enabled.", "model": StructuredErrorResponse},
        403: {"description": "Authentication token invalid.", "model": StructuredErrorResponse},
        400: {"description": "Invalid delete request.", "model": StructuredErrorResponse},
        502: {"description": "Provider upstream request failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected server error.", "model": StructuredErrorResponse},
    },
)
async def delete_voice(
    voice_name: str,
    voice_type: VoiceType = Query(default="voice_design"),
    provider: str = Query(default="qwen"),
) -> VoiceDeleteResponse:
    provider = (provider or "qwen").strip().lower()
    try:
        if provider == "xiaomi" or provider == "mimo":
            raise ValueError("Xiaomi does not support persistent voice deletion. Voices are generated on-the-fly.")
        elif provider == "gpt_sovits":
            deleted = tts_service.delete_local_gpt_sovits_voice(voice_name)
            result = {
                "voice": voice_name,
                "type": voice_type,
                "deleted": deleted
            }
        elif provider == "elevenlabs":
            result = await elevenlabs_voice_service.delete_voice(voice_name=voice_name)
            result["type"] = voice_type
        else:
            result = await qwen_voice_service.delete_voice(voice_name=voice_name, voice_type=voice_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "VOICE_DELETE_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "VOICE_DELETE_PROVIDER_ERROR", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "VOICE_DELETE_INTERNAL_ERROR",
                "message": f"Delete voice failed: {exc}",
                "meta": {},
            },
        ) from exc
    return VoiceDeleteResponse(**result)
