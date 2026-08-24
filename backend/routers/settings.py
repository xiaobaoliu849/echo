from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.desktop_diagnostics_service import DesktopDiagnosticsService
from services.config_loader import GOOGLE_INTERACTIONS_BASE_URL
from services.settings_service import MASKED_SECRET, SettingsService

router = APIRouter()
settings_service = SettingsService()
desktop_diagnostics_service = DesktopDiagnosticsService()


class SettingsResponse(BaseModel):
    config_path: str
    providers: list[str]
    settings: dict[str, Any]


class SettingsUpdateRequest(BaseModel):
    merge: bool = Field(default=True, description="Merge into existing config when true; replace when false.")
    settings: dict[str, Any] = Field(default_factory=dict, description="Partial settings object to update.")


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


class DesktopStatusResponse(BaseModel):
    runtime_dir: str
    diagnostics_dir: str
    preflight: dict[str, Any]
    latest_error: dict[str, Any]


@router.get(
    "/",
    response_model=SettingsResponse,
    responses={
        500: {"description": "Failed to load settings.", "model": StructuredErrorResponse},
    },
)
async def get_settings() -> SettingsResponse:
    try:
        result = settings_service.get_settings()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SETTINGS_LOAD_FAILED",
                "message": f"Load settings failed: {exc}",
                "meta": {},
            },
        ) from exc

    # On every load, re-filter the DashScope available_models list that is persisted in
    # config.json.  Old fetches may have stored hundreds of raw checkpoint IDs; the filter
    # keeps only the production-grade models that VoiceSpirit actually needs.
    # This prevents the jarring "221 models" → "45 models after Fetch" UX mismatch.
    try:
        settings_blob = result.get("settings", {})
        dm = settings_blob.get("default_models", {})
        if isinstance(dm, dict) and "DashScope" in dm:
            ds_entry = dm["DashScope"]
            if isinstance(ds_entry, dict):
                raw_avail = ds_entry.get("available", [])
                if isinstance(raw_avail, list) and len(raw_avail) > 30:
                    ds_entry["available"] = _filter_dashscope_models(raw_avail)
                # Drop retired legacy realtime models (qwen3-omni-*, qwen3-livetranslate-*)
                # from BOTH the available and enabled lists so superseded checkpoints such as
                # qwen3-omni-flash-2025-12-01 no longer surface in the model picker. This runs
                # on every load (not only when the list is bloated) and mutates only the API
                # response, never the persisted config.json.
                for list_key in ("available", "enabled"):
                    existing = ds_entry.get(list_key)
                    if isinstance(existing, list):
                        ds_entry[list_key] = [
                            item for item in existing
                            if not _is_retired_dashscope_model(str(item))
                        ]
                # Merge the curated supplements regardless of whether the filter ran, so
                # versioned voice models (qwen3.5-livetranslate-flash-realtime, omni/tts
                # checkpoints) are always present — consistent with the fetch-models
                # endpoint, which filters then appends DASHSCOPE_MODEL_LIST_SUPPLEMENTS.
                # TTS supplements land in tts_available; chat/realtime ones in available.
                _merge_dashscope_supplements(ds_entry)
    except Exception:
        pass  # never let filter errors break settings load

    return SettingsResponse(**result)



@router.get(
    "/desktop-status",
    response_model=DesktopStatusResponse,
    responses={
        500: {"description": "Failed to load desktop status.", "model": StructuredErrorResponse},
    },
)
async def get_desktop_status() -> DesktopStatusResponse:
    try:
        result = desktop_diagnostics_service.get_status()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "DESKTOP_STATUS_LOAD_FAILED",
                "message": f"Load desktop status failed: {exc}",
                "meta": {},
            },
        ) from exc
    return DesktopStatusResponse(**result)


@router.put(
    "/",
    response_model=SettingsResponse,
    responses={
        401: {"description": "Missing admin Bearer token when admin token is enabled.", "model": StructuredErrorResponse},
        400: {"description": "Settings patch validation failed.", "model": StructuredErrorResponse},
        403: {"description": "Authentication token invalid or non-admin token used.", "model": StructuredErrorResponse},
        500: {"description": "Settings update failed.", "model": StructuredErrorResponse},
    },
)
async def update_settings(payload: SettingsUpdateRequest) -> SettingsResponse:
    try:
        result = settings_service.update_settings(payload.settings, merge=payload.merge)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "SETTINGS_BAD_REQUEST", "message": str(exc), "meta": {}},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SETTINGS_UPDATE_FAILED",
                "message": f"Update settings failed: {exc}",
                "meta": {},
            },
        ) from exc
    return SettingsResponse(**result)


class FetchModelsRequest(BaseModel):
    api_key: str | None = Field(default=None, description="Optional API key override")
    base_url: str | None = Field(default=None, description="Optional API base URL override")


class FetchModelsResponse(BaseModel):
    provider: str
    models: list[str]
    tts_models: list[str] = Field(default_factory=list)


GOOGLE_MODEL_LIST_SUPPLEMENTS = [
    # Mainline and frontier text/multimodal models
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    # Realtime voice and live translation models
    "gemini-3.1-flash-live-preview",
    "gemini-3.5-live-translate-preview",
]
DASHSCOPE_MODEL_LIST_SUPPLEMENTS = [
    # TTS synthesis models (current generation only)
    "qwen-audio-3.0-tts-plus",
    "qwen-audio-3.0-tts-flash",
    "qwen-audio-3.0-realtime-plus",
    "qwen-audio-3.0-realtime-flash",
    "qwen3-tts-flash-2025-11-27",
    # Realtime omni models
    "qwen3.5-omni-plus-realtime-2026-03-15",
    # Live translation (DashScope Realtime WebSocket — integrated)
    "qwen3.5-livetranslate-flash-realtime",
]
DOUBAO_MODEL_LIST_SUPPLEMENTS = [
    "doubao-realtime",
    "doubao-1.5-pro-32k",
    "doubao-1.5-lite-32k",
    "doubao-pro-32k",
    "doubao-lite-32k",
]
CARTESIA_MODEL_LIST_SUPPLEMENTS = [
    "cartesia-realtime",
    "sonic-preview",
    "sonic-3.5",
    "sonic-3",
]
GOOGLE_MODELS_BASE_URL = GOOGLE_INTERACTIONS_BASE_URL


# Legacy DashScope realtime families retired in favour of the qwen3.5 series:
#   qwen3-omni-*          -> superseded by qwen3.5-omni-*
#   qwen3-livetranslate-* -> superseded by qwen3.5-livetranslate-*
# The pattern requires a hyphen immediately after "qwen3", so the current qwen3.5-*
# models (which carry a minor version: "qwen3.5-...") never match.
_RETIRED_DASHSCOPE_REALTIME_RE = re.compile(r"^qwen3-(?:omni|livetranslate)-", re.IGNORECASE)


def _is_retired_dashscope_model(model_id: str) -> bool:
    return bool(_RETIRED_DASHSCOPE_REALTIME_RE.match(str(model_id).strip().lower()))


def _filter_dashscope_models(model_ids: list[str]) -> list[str]:
    """
    Filter DashScope model list down to production-grade API alias models only.

    Strategy: blocklist noise rather than whitelist specific model names.
    DashScope exposes two distinct categories:
      - Product API aliases  (e.g. qwen-max, qwen-plus, deepseek-r1, qwq-32b)
        -> no or symbolic parameter-count suffix; these track "latest" automatically.
      - Raw academic checkpoints  (e.g. qwen2.5-72b-instruct, deepseek-r1-distill-llama-8b)
        -> carry explicit size suffixes like -7b / -72b; NOT meant for product API use.

    Noise patterns we strip:
      1. Explicit parameter-size suffixes  (-7b, -14b, -32b, -72b, -0.5b, -1.5b, -3b, etc.)
      2. Distillation checkpoints          (-distill-)
      3. Quantization variants             (-int4, -int8, -fp16)
      4. Date-stamped snapshots            (-20xxxxxx or -2025xxxx style 6-8 digit suffix)
         EXCEPTION: keep qwen3-tts-flash-2025-11-27 which is a production TTS model
      5. Non-DashScope models that leaked in from gateway responses
    """
    import re

    # VoiceSpirit uses DashScope for:
    #   - Qwen/QwQ chat models   (qwen-max, qwen-plus, qwen-turbo, qwen-long, qwen-omni-*)
    #   - Machine translation    (qwen-mt-*)
    #   - Voice synthesis        (qwen-audio-*, cosyvoice-*, sambert-*)  → TTS
    #   - ASR / transcription    (paraformer-*, sensevoice-*)             → speech recognition
    # Excluded intentionally:
    #   - deepseek-* : pure text/coding LLMs, no voice relevance
    #   - farui-*    : enterprise compliance tool, out of scope
    _DASHSCOPE_PREFIXES = (
        "qwen", "qwq", "cosyvoice", "sambert",
        "paraformer", "sensevoice",
    )

    # Qwen sub-families that are completely off-topic for VoiceSpirit.
    # Using keyword fragments that are unambiguous within the qwen namespace.
    _OFF_TOPIC_KEYWORDS = (
        "-image-",       # qwen-image-*, qwen-image-edit-*  → image generation
        "-vl-",          # qwen-vl-*, qwen-vl-ocr-*         → vision-language
        "-ocr",          # qwen*-ocr, qwen3.5-ocr            → OCR, not voice-relevant
        "-coder-",       # qwen-coder-*                     → code generation
        "-math-",        # qwen-math-*                      → mathematics
        "-deep-research",# qwen-deep-research-*             → agentic research tool
        "-deep-search",  # qwen-deep-search-*               → web search tool
        "-flash-",       # qwen-flash-* (legacy tiny model series, NOT qwen3-tts-flash-*)
    )

    # Parameter-size-like suffixes that indicate raw academic checkpoints, NOT product APIs.
    # We match things like -7b, -14b, -72b, -0.5b, -1.5b, -3b at a word boundary.
    # NOTE: MoE models use -235b-a22b pattern; the -a22b part is the active-param suffix
    # which we do NOT want to block — only block the raw dense parameter suffixes.
    _SIZE_SUFFIX_RE = re.compile(r"(?<!-a)-\d*\.?\d+b\b", re.IGNORECASE)

    # Date-snapshot suffixes to DROP — ALL date formats:
    #   Compressed 8-digit:  -20241018, -20250601  (DashScope alias snapshots)
    #   Compressed 4-digit:  -0107, -1201, -0919   (month-day pinned aliases)
    #   Hyphenated YYYY-MM-DD: -2025-11-05, -2024-11-01  (also alias snapshots)
    #
    # Note: production versioned models we specifically want (e.g. qwen3-tts-flash-2025-11-27)
    # are guaranteed via DASHSCOPE_MODEL_LIST_SUPPLEMENTS which
    # is applied AFTER this filter, so we can safely drop all date-suffixed names here.
    _DATE_SUFFIX_RE = re.compile(
        r"(-\d{4}-\d{2}-\d{2}|-\d{6,8}|-(?!\d{4}-\d{2}-\d{2})\d{4})$", re.IGNORECASE
    )

    filtered: list[str] = []
    for m in model_ids:
        raw = m.strip()
        if not raw:
            continue
        low = raw.lower()

        # 1. Must belong to a DashScope official model family
        if not any(low.startswith(p) for p in _DASHSCOPE_PREFIXES):
            continue

        # 1b. Drop retired legacy realtime families (superseded by the qwen3.5
        #     series): qwen3-omni-* and qwen3-livetranslate-*. The qwen3.5-* models
        #     are unaffected (their names carry a minor version, e.g. qwen3.5-omni-*).
        if _is_retired_dashscope_model(low):
            continue

        # 2. Strip off-topic Qwen sub-families (image, coder, math, search, research)
        if any(kw in low for kw in _OFF_TOPIC_KEYWORDS):
            # Special-case: voice/realtime models that incidentally contain "-flash-":
            #   qwen3-tts-flash-*, qwen3-omni-flash-*, qwen-audio-*-realtime-flash
            is_voice_flash = low.startswith("qwen") and any(
                kw in low for kw in ("tts", "omni", "realtime", "audio")
            )
            if not is_voice_flash:
                continue

        # 3. Strip legacy tiny parameter models (e.g. qwen-1.8b-longcontext-chat)
        if re.search(r"qwen-\d+\.?\d*b-", low):
            continue

        # 4. Strip distillation checkpoints (e.g. deepseek-r1-distill-qwen-7b)
        if "-distill-" in low:
            continue

        # 5. Strip quantization variants
        if any(q in low for q in ("-int4", "-int8", "-fp16")):
            continue

        # 6. Strip models with an explicit dense-parameter-size suffix (raw checkpoints).
        #    MoE heuristic: a product MoE (e.g. qwen3-235b-a22b) ends with -Xb-aYb$ and
        #    has NO minor version in its name (qwen3-, not qwen3.5-).
        #    qwen3.5-122b-a10b / qwen3.5-35b-a3b: intermediate research checkpoints → DROP.
        #    qwen2-57b-a14b-instruct: has -instruct after MoE suffix → old checkpoint → DROP.
        if _SIZE_SUFFIX_RE.search(low):
            # True product MoE: ends with -Xb-aYb$ AND comes from a major-only family
            is_flagship_moe = (
                bool(re.search(r"-\d+b-a\d+b$", low))
                and not re.search(r"qwen\d+\.\d+", low)  # no minor version (qwen3.5 etc.)
            )
            if not is_flagship_moe:
                if re.match(r"(qwen\d|deepseek-v\d)", low):
                    continue
                if re.search(r"-\d*\.?\d+b-(instruct|chat|base|preview)", low):
                    continue

        # 6b. Block standalone versioned flash models (e.g. qwen3.5-flash).
        #     These are tiny capability-specific models, not product-grade chat APIs.
        if re.match(r"qwen\d+\.\d+-flash$", low):
            continue

        # 7. Strip ALL date-suffixed names (both compressed and YYYY-MM-DD).
        #    Curated versioned models we want are guaranteed via DASHSCOPE_MODEL_LIST_SUPPLEMENTS
        #    which is merged AFTER this filter runs (see fetch_models endpoint).
        if _DATE_SUFFIX_RE.search(low):
            continue

        filtered.append(raw)

    return filtered


# Keyword fragments that mark a model id as a TTS/voice-synthesis model rather than a
# chat/realtime model.  Shared by the fetch-models endpoint and the GET /settings
# supplement-merge path so both classify curated models identically.
TTS_MODEL_KEYWORDS = ("tts", "speech", "cosyvoice", "sambert", "voice", "eleven", "qwen-audio", "sonic")


def _is_tts_model_id(model_id: str) -> bool:
    low = model_id.lower()
    return any(kw in low for kw in TTS_MODEL_KEYWORDS)


def _append_unique(target: list[str], seen: set[str], model_id: str) -> None:
    if model_id not in seen:
        target.append(model_id)
        seen.add(model_id)


def _merge_dashscope_supplements(ds_entry: dict[str, Any]) -> None:
    """
    Merge the curated DASHSCOPE_MODEL_LIST_SUPPLEMENTS into a DashScope models entry,
    routing each supplement to the correct sub-list:
      - TTS/voice-synthesis models  -> ``tts_available``
      - chat / realtime / livetranslate models -> ``available``

    This mirrors the fetch-models endpoint (filter first, then append supplements) so that
    versioned production voice models — e.g. ``qwen3.5-livetranslate-flash-realtime`` and the
    omni/tts checkpoints whose date suffixes the filter strips — are guaranteed present on
    every settings load, even when the persisted list in config.json predates them.  Dedupes
    against whatever is already in each list; order of existing entries is preserved.
    """
    chat_avail = ds_entry.get("available")
    if not isinstance(chat_avail, list):
        chat_avail = []
    tts_avail = ds_entry.get("tts_available")
    if not isinstance(tts_avail, list):
        tts_avail = []

    chat_seen = {str(m).strip() for m in chat_avail}
    tts_seen = {str(m).strip() for m in tts_avail}

    for supplement in DASHSCOPE_MODEL_LIST_SUPPLEMENTS:
        if _is_tts_model_id(supplement):
            _append_unique(tts_avail, tts_seen, supplement)
        else:
            _append_unique(chat_avail, chat_seen, supplement)

    ds_entry["available"] = chat_avail
    ds_entry["tts_available"] = tts_avail



@router.post(
    "/providers/{provider}/fetch-models",
    response_model=FetchModelsResponse,
    responses={
        400: {"description": "Validation error or invalid provider.", "model": StructuredErrorResponse},
        500: {"description": "Failed to fetch models.", "model": StructuredErrorResponse},
    },
)
async def fetch_models(provider: str, payload: FetchModelsRequest) -> FetchModelsResponse:
    cfg_settings = {}
    try:
        cfg_settings = settings_service.config.get_provider_settings(provider)
    except Exception:
        pass

    api_key = (payload.api_key or "").strip()
    if api_key == MASKED_SECRET and cfg_settings:
        # The settings UI sends back the masked placeholder when the user did
        # not retype the stored key — resolve it to the real configured key.
        api_key = str(cfg_settings.get("api_key", "")).strip()
    if not api_key and cfg_settings:
        api_key = cfg_settings.get("api_key", "").strip()

    if provider == "Ollama" and not api_key:
        api_key = "ollama"

    base_url = (payload.base_url or "").strip()
    if not base_url and cfg_settings:
        base_url = cfg_settings.get("base_url", "").strip()

    if not base_url:
        from services.config_loader import DEFAULT_BASE_URLS
        if provider == "Google":
            base_url = GOOGLE_MODELS_BASE_URL
        else:
            base_url = DEFAULT_BASE_URLS.get(provider, "").strip()

    base_url = base_url.rstrip("/")

    if not api_key:
        if provider == "Doubao":
            return FetchModelsResponse(
                provider=provider,
                models=[m for m in DOUBAO_MODEL_LIST_SUPPLEMENTS if _is_tts_model_id(m) is False],
                tts_models=[m for m in DOUBAO_MODEL_LIST_SUPPLEMENTS if _is_tts_model_id(m) is True],
            )
        if provider == "Cartesia":
            return FetchModelsResponse(
                provider=provider,
                models=[m for m in CARTESIA_MODEL_LIST_SUPPLEMENTS if _is_tts_model_id(m) is False],
                tts_models=[m for m in CARTESIA_MODEL_LIST_SUPPLEMENTS if _is_tts_model_id(m) is True],
            )
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_API_KEY",
                "message": f"API key is required to fetch models for {provider}.",
                "meta": {},
            },
        )
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_BASE_URL",
                "message": f"Base URL is required to fetch models for {provider}.",
                "meta": {},
            },
        )

    if api_key and not api_key.isascii():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_API_KEY_ENCODING",
                "message": f"API Key for provider '{provider}' contains non-ASCII characters (e.g., Chinese text or full-width symbols). Please enter a valid ASCII API Key.",
                "meta": {},
            },
        )

    if base_url and not base_url.isascii():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_BASE_URL_ENCODING",
                "message": f"Base URL for provider '{provider}' contains non-ASCII characters. Please enter a valid URL.",
                "meta": {},
            },
        )

    if provider == "Ollama":
        base = base_url
        if base.endswith("/v1"):
            base = base[:-3]
        url = f"{base}/api/tags"
        headers = {
            "Accept": "application/json",
        }
        if api_key and api_key != "ollama":
            headers["Authorization"] = f"Bearer {api_key}"
    else:
        url = f"{base_url}/models"
        headers = {"Accept": "application/json"}
        if provider == "Google":
            headers["x-goog-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
        if provider == "OpenRouter":
            headers["HTTP-Referer"] = "https://voicespirit.local"
            headers["X-Title"] = "VoiceSpirit"

    import httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if provider == "Doubao":
            # Doubao Ark may not expose a standard /models endpoint for all API keys.
            # Fall back gracefully to curated DOUBAO_MODEL_LIST_SUPPLEMENTS.
            return FetchModelsResponse(
                provider=provider,
                models=[m for m in DOUBAO_MODEL_LIST_SUPPLEMENTS if _is_tts_model_id(m) is False],
                tts_models=[m for m in DOUBAO_MODEL_LIST_SUPPLEMENTS if _is_tts_model_id(m) is True],
            )
        if provider == "Cartesia":
            # Cartesia has no /models endpoint — return curated model list.
            return FetchModelsResponse(
                provider=provider,
                models=[m for m in CARTESIA_MODEL_LIST_SUPPLEMENTS if _is_tts_model_id(m) is False],
                tts_models=[m for m in CARTESIA_MODEL_LIST_SUPPLEMENTS if _is_tts_model_id(m) is True],
            )
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "FETCH_MODELS_HTTP_ERROR",
                "message": f"Provider returned status {exc.response.status_code}: {detail}",
                "meta": {},
            },
        ) from exc
    except UnicodeEncodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_HEADER_ENCODING",
                "message": f"Failed to connect to provider '{provider}': input contains non-ASCII characters. Please check your API Key and Base URL.",
                "meta": {},
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "FETCH_MODELS_FAILED",
                "message": f"Failed to connect to provider: {exc}",
                "meta": {},
            },
        ) from exc

    try:
        data = response.json()
        model_ids = []
        if provider == "Ollama":
            raw_models = data.get("models", [])
            for m in raw_models:
                if isinstance(m, dict) and "name" in m:
                    model_ids.append(str(m["name"]))
        else:
            if provider == "Google":
                raw_models = data.get("models", [])
            else:
                raw_models = data.get("data", [])
            if not isinstance(raw_models, list):
                if isinstance(data, list):
                    raw_models = data
                else:
                    raw_models = []

            for m in raw_models:
                if isinstance(m, dict) and provider == "Google":
                    model_id = str(m.get("name") or m.get("baseModelId") or "").strip()
                    if model_id.startswith("models/"):
                        model_id = model_id.removeprefix("models/")
                    if model_id:
                        model_ids.append(model_id)
                elif isinstance(m, dict) and "id" in m:
                    model_ids.append(str(m["id"]))
                elif isinstance(m, str):
                    model_ids.append(m)

        if provider == "Google":
            model_ids.extend(GOOGLE_MODEL_LIST_SUPPLEMENTS)
        elif provider == "DashScope":
            # Filter API response first, then append curated supplements.
            # This ensures versioned production models in DASHSCOPE_MODEL_LIST_SUPPLEMENTS
            # survive even though the filter drops all date-suffixed names.
            model_ids = _filter_dashscope_models(model_ids)
            model_ids.extend(DASHSCOPE_MODEL_LIST_SUPPLEMENTS)
        elif provider == "Doubao":
            model_ids.extend(DOUBAO_MODEL_LIST_SUPPLEMENTS)

        model_ids = sorted(list(set(model_ids)))
        tts_ids = [m for m in model_ids if _is_tts_model_id(m)]
        tts_set = set(tts_ids)
        chat_ids = [m for m in model_ids if m not in tts_set]

        return FetchModelsResponse(provider=provider, models=chat_ids, tts_models=tts_ids)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "FETCH_MODELS_PARSE_FAILED",
                "message": f"Failed to parse models list from provider response: {exc}",
                "meta": {},
            },
        ) from exc
