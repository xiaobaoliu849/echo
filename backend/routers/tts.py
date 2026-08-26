from typing import Any
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from services import TTSService
from services.evermem_config import EverMemConfig

router = APIRouter()
tts_service = TTSService()


def _normalize_query_optional(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_query_string(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    normalized = value.strip()
    return normalized or default


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


@router.get(
    "/voices",
    responses={
        400: {"description": "Invalid voices query.", "model": StructuredErrorResponse},
        500: {"description": "Failed to list voices.", "model": StructuredErrorResponse},
    },
)
async def list_voices(
    locale: str | None = Query(default=None, description="Locale prefix, e.g. zh-CN"),
    engine: str = Query(
        default="edge",
        description="TTS engine: edge, qwen_flash, minimax, xiaomi, openai, elevenlabs, chattts, gpt_sovits, doubao, cartesia",
    ),
    model: str | None = Query(
        default=None,
        description="Optional TTS model; qwen_flash voices are filtered to the model's voice family.",
    ),
) -> dict:
    try:
        voices = await tts_service.list_voices(locale=locale, engine=engine, model=model)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "TTS_VOICES_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "TTS_VOICES_INTERNAL_ERROR", "message": f"List voices failed: {exc}", "meta": {}},
        ) from exc
    return {"count": len(voices), "voices": voices}


@router.get(
    "/speak",
    responses={
        400: {"description": "Invalid TTS request.", "model": StructuredErrorResponse},
        503: {"description": "TTS dependency unavailable.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected server error.", "model": StructuredErrorResponse},
    },
)
async def speak(
    request: Request,
    text: str = Query(..., min_length=1, max_length=3000),
    voice: str | None = Query(default=None),
    voice_b: str | None = Query(default=None),
    rate: str = Query(default="+0%"),
    engine: str = Query(
        default="edge",
        description="TTS engine: edge, qwen_flash, minimax, xiaomi, openai, elevenlabs, chattts, gpt_sovits, doubao, cartesia",
    ),
    engine_b: str | None = Query(
        default=None,
        description="Optional speaker B engine for dialogue synthesis.",
    ),
    model: str | None = Query(
        default=None,
        description="Optional TTS model identifier.",
    ),
    model_b: str | None = Query(
        default=None,
        description="Optional speaker B TTS model identifier for dialogue synthesis.",
    ),
) -> FileResponse:
    # FastAPI injects concrete values for HTTP requests. Direct route tests pass
    # Query objects for omitted defaults, so normalize all optional inputs here.
    voice = _normalize_query_optional(voice)
    voice_b = _normalize_query_optional(voice_b)
    rate = _normalize_query_string(rate, "+0%")
    engine = _normalize_query_string(engine, "edge")
    engine_b = _normalize_query_optional(engine_b)
    model = _normalize_query_optional(model)
    model_b = _normalize_query_optional(model_b)

    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model

    try:
        if voice_b:
            if model_b:
                kwargs["model_b"] = model_b
            result = await tts_service.generate_dialogue_audio(
                text=text,
                voice_a=voice,
                voice_b=voice_b,
                rate=rate,
                engine=engine,
                engine_b=engine_b,
                **kwargs,
            )
        else:
            result = await tts_service.generate_audio(
                text=text,
                voice=voice,
                rate=rate,
                engine=engine,
                **kwargs,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "TTS_SPEAK_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "TTS_SPEAK_DEPENDENCY_ERROR", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "TTS_SPEAK_INTERNAL_ERROR",
                "message": f"TTS generation failed: {exc}",
                "meta": {},
            },
        ) from exc

    memory_saved = False
    evermem_config = EverMemConfig()
    evermem_config.update_from_headers(dict(request.headers))
    evermem_service = evermem_config.get_service()
    if evermem_service:
        snippet = text.strip().replace("\n", " ")[:180]
        memory_text = (
            f"Echo 语音合成已生成。音色：{result.voice}。语速：{rate}。"
            f"文本摘要：{snippet}"
        )
        try:
            saved = await evermem_service.add_memory(
                content=memory_text,
                user_id=evermem_config.memory_scope,
                sender=f"{evermem_config.memory_scope}_tts",
                sender_name="Echo TTS",
            )
            memory_saved = saved is not None
        except Exception:
            memory_saved = False

    return FileResponse(
        result.file_path,
        media_type=result.media_type,
        filename=result.filename,
        headers={
            "X-TTS-Voice": result.voice,
            "X-TTS-Engine": result.engine,
            "X-Cache": "HIT" if result.cache_hit else "MISS",
            "X-EverMem-Saved": "true" if memory_saved else "false",
        },
    )






class StreamTtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=3000)
    voice: str = Field(default="zh-CN-YunxiNeural")

@router.post("/stream-with-timestamps")
async def stream_with_timestamps(req: StreamTtsRequest):
    return StreamingResponse(
        tts_service.stream_azure_tts_with_timestamps(req.text, req.voice),
        media_type="text/event-stream"
    )
