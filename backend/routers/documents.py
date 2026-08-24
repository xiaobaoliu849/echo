import asyncio
import io
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

try:
    import pypdf
except ImportError:
    pypdf = None  # type: ignore[assignment]

from services.evermem_config import EverMemConfig
from services.llm_service import LLMService

router = APIRouter()
llm_service = LLMService()

# Generous ceiling for read-aloud documents; anything bigger is almost
# certainly a mis-selected file and would balloon memory during parsing.
MAX_PDF_UPLOAD_BYTES = 50 * 1024 * 1024


class _PdfEncryptedError(Exception):
    pass


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)

class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


def _extract_pdf_sync(content: bytes) -> tuple[int, str]:
    """CPU-bound pypdf work, run off the event loop by the caller."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            try:
                # Many "encrypted" PDFs ship with an owner password only and
                # open fine with an empty user password.
                reader.decrypt("")
            except Exception:
                pass
            if reader.is_encrypted:
                raise _PdfEncryptedError(
                    "This PDF is password-protected. Remove the password and try again."
                )
        pages = list(reader.pages)
    except _PdfEncryptedError:
        raise
    except Exception as exc:
        raise ValueError(f"Unable to read PDF file: {exc}") from exc

    extracted_text = []
    for page in pages:
        try:
            text = page.extract_text()
        except Exception:
            text = ""  # one malformed page must not sink the whole document
        if text:
            extracted_text.append(text)

    return len(pages), "\n\n".join(extracted_text)


@router.post(
    "/extract-pdf",
    responses={
        400: {"description": "Invalid PDF file or extraction failed.", "model": StructuredErrorResponse},
        500: {"description": "Unexpected error during extraction.", "model": StructuredErrorResponse},
    },
)
async def extract_pdf(
    file: UploadFile = File(..., description="The PDF file to extract text from")
) -> dict[str, Any]:
    if pypdf is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "PDF_EXTRACT_MISSING_DEP", "message": "pypdf is not installed. Run: pip install pypdf", "meta": {}},
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "PDF_EXTRACT_BAD_REQUEST",
                "message": "Only PDF files are supported.",
                "meta": {},
            },
        )

    # Stream-read with a running size cap instead of slurping the whole
    # upload into memory up front.
    buffer = io.BytesIO()
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_PDF_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "PDF_EXTRACT_TOO_LARGE",
                    "message": f"PDF files larger than {MAX_PDF_UPLOAD_BYTES // (1024 * 1024)} MB are not supported.",
                    "meta": {},
                },
            )
        buffer.write(chunk)
    content = buffer.getvalue()

    try:
        # pypdf parsing is CPU-bound; keep it off the event loop so a big
        # document cannot freeze realtime voice and every other request.
        page_count, full_text = await asyncio.to_thread(_extract_pdf_sync, content)
    except _PdfEncryptedError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "PDF_EXTRACT_ENCRYPTED", "message": str(exc), "meta": {}},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "PDF_EXTRACT_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PDF_EXTRACT_INTERNAL_ERROR",
                "message": f"Failed to extract text from PDF: {exc}",
                "meta": {},
            },
        ) from exc

    return {
        "filename": file.filename,
        "page_count": page_count,
        "text": full_text,
        # Lets the UI distinguish "empty document" from "scanned/no-text PDF".
        "has_text": bool(full_text.strip()),
    }


class PolishTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=30000)
    provider: str | None = Field(default=None)
    model: str | None = Field(default=None)

class PolishTextResponse(BaseModel):
    provider: str
    model: str | None
    polished_text: str

@router.post(
    "/polish-pdf-text",
    response_model=PolishTextResponse,
    responses={
        400: {"description": "Invalid request.", "model": StructuredErrorResponse},
        500: {"description": "Failed to polish text.", "model": StructuredErrorResponse},
    },
)
async def polish_pdf_text(payload: PolishTextRequest) -> PolishTextResponse:
    cleaned = payload.text.strip()
    if not cleaned:
        raise HTTPException(
            status_code=400,
            detail={"code": "TTS_POLISH_BAD_REQUEST", "message": "Text is empty.", "meta": {}},
        )

    # Resolve provider and model if not provided
    provider = payload.provider
    model = payload.model
    if not provider:
        # Check active API keys in configuration
        config_data = llm_service.config.get_all()
        api_keys = config_data.get("api_keys", {})
        from services.config_loader import PROVIDER_KEY_MAP
        for p in ["DashScope", "DeepSeek", "SiliconFlow", "Google", "Groq", "OpenRouter", "Ollama"]:
            key_name = PROVIDER_KEY_MAP.get(p)
            if key_name and (api_keys.get(key_name) or p == "Ollama"):
                provider = p
                break
        if not provider:
            provider = "DashScope"  # fallback default

    system_prompt = (
        "You are an expert assistant designed to optimize text for Text-to-Speech (TTS) synthesis.\n"
        "Your task is to take raw extracted PDF text (which contains LaTeX, math formulas, headers, footers, page numbers, citation brackets) and rewrite/polish it so it reads smoothly as natural spoken language.\n"
        "Follow these rules strictly:\n"
        "1. Remove reading noise: page numbers, running headers/footers, citation brackets (e.g. [1], Ref [2]), URLs, and bibliography references.\n"
        "2. Convert math equations and formulas: Translate mathematical symbols and LaTeX expressions into their spoken language equivalents (e.g., '$n \\ge 3$' to 'n大于等于3' or 'n is greater than or equal to 3').\n"
        "3. Resolve word breaks: Connect hyphenated words split across line breaks (e.g., 'sub- stantial' to 'substantial').\n"
        "4. Preserve core meaning: Do not summarize or omit sentences. Just clean up noise and expand notations.\n"
        "5. Output format: Return ONLY the polished text. Do not output any markdown blocks, introductions, notes, or explanations."
    )

    try:
        result = await llm_service.chat_completion(
            provider=provider,
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": cleaned},
            ],
            temperature=0.2,
            max_tokens=4096,
        )
        return PolishTextResponse(
            provider=result["provider"],
            model=result["model"],
            polished_text=result["reply"],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "TTS_POLISH_INTERNAL_ERROR",
                "message": f"Failed to polish text: {exc}",
                "meta": {},
            },
        ) from exc
