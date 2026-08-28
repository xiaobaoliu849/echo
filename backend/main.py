import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from routers import agent_runs, audio_agent, audio_overview, auth, chat, documents, evermem, settings, tavus, transcription, translate, tts, voice_chat, voices
from services.api_auth_guard import (
    is_auth_enabled,
    should_enforce_auth,
    should_require_admin_auth,
    validate_auth_header,
)
from services.config_loader import get_data_dir

request_logger = logging.getLogger("voicespirit.request")
error_logger = logging.getLogger("voicespirit.error")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Echo API",
        description="Echo — local-first realtime voice AI assistant backend",
        version="0.1.0",
    )

    # NOTE: no "null" origin here — sandboxed iframes send Origin: null, and
    # allowing it with credentials would let any web page drive this API.
    # Desktop mode loads http://127.0.0.1:8000/app same-origin, dev uses
    # localhost:5173; neither needs "null".

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    def _resolve_request_id(request: Request) -> str:
        incoming = str(request.headers.get("X-Request-ID", "")).strip()
        if incoming and len(incoming) <= 128:
            return incoming
        return uuid.uuid4().hex

    def _ensure_request_id(request: Request) -> str:
        existing = getattr(request.state, "request_id", "")
        if isinstance(existing, str) and existing.strip():
            return existing.strip()
        resolved = _resolve_request_id(request)
        request.state.request_id = resolved
        return resolved

    def _log_request(
        *,
        request_id: str,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        auth_result: str,
    ) -> None:
        payload = {
            "event": "http_request",
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "auth_result": auth_result,
        }
        request_logger.info(json.dumps(payload, ensure_ascii=False))

    def _log_error(
        *,
        request_id: str,
        method: str,
        path: str,
        status: int,
        code: str = "",
        message: str = "",
    ) -> None:
        payload = {
            "event": "http_error",
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": status,
            "code": code,
            "message": message,
        }
        error_logger.error(json.dumps(payload, ensure_ascii=False))

    def _extract_error_detail(response: Any) -> tuple[str, str]:
        try:
            body = getattr(response, "body", b"")
            if not body:
                return "", ""
            payload = json.loads(body.decode("utf-8"))
            detail = payload.get("detail")
            if isinstance(detail, dict):
                code = str(detail.get("code", "")).strip()
                message = str(detail.get("message", "")).strip()
                return code, message
            if isinstance(detail, str):
                return "", detail.strip()
            return "", ""
        except Exception:
            return "", ""

    def _normalize_http_exception_detail(exc: HTTPException) -> dict[str, Any]:
        raw = exc.detail
        if isinstance(raw, dict):
            code = str(raw.get("code", "")).strip() or f"HTTP_{exc.status_code}_ERROR"
            message = str(raw.get("message", "")).strip() or str(raw)
            meta_raw = raw.get("meta")
            meta = dict(meta_raw) if isinstance(meta_raw, dict) else {}
            return {"code": code, "message": message, "meta": meta}
        if isinstance(raw, str):
            return {"code": f"HTTP_{exc.status_code}_ERROR", "message": raw, "meta": {}}
        return {
            "code": f"HTTP_{exc.status_code}_ERROR",
            "message": str(raw),
            "meta": {},
        }

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = _ensure_request_id(request)
        detail = _normalize_http_exception_detail(exc)
        meta = detail.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        meta["request_id"] = request_id
        detail["meta"] = meta
        _log_error(
            request_id=request_id,
            method=request.method.upper(),
            path=request.url.path,
            status=exc.status_code,
            code=str(detail.get("code", "")),
            message=str(detail.get("message", "")),
        )
        request.state.error_logged = True
        response = JSONResponse(status_code=exc.status_code, content={"detail": detail})
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = _ensure_request_id(request)
        detail = {
            "code": "REQUEST_VALIDATION_ERROR",
            "message": "Request validation failed.",
            "meta": {
                "errors": exc.errors(),
                "request_id": request_id,
            },
        }
        _log_error(
            request_id=request_id,
            method=request.method.upper(),
            path=request.url.path,
            status=422,
            code="REQUEST_VALIDATION_ERROR",
            message="Request validation failed.",
        )
        request.state.error_logged = True
        response = JSONResponse(status_code=422, content={"detail": detail})
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        start = time.perf_counter()
        request_id = _resolve_request_id(request)
        request.state.request_id = request_id
        method = request.method.upper()
        path = request.url.path
        if should_enforce_auth(request.method, request.url.path):
            try:
                auth_header = request.headers.get("Authorization")
                if not auth_header and request.query_params.get("token"):
                    auth_header = f"Bearer {request.query_params.get('token')}"
                validate_auth_header(
                    auth_header,
                    require_admin=should_require_admin_auth(request.method, request.url.path),
                )
            except HTTPException as exc:
                detail_raw = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                detail: dict[str, Any] = dict(detail_raw)
                meta_raw = detail.get("meta")
                meta: dict[str, Any]
                if isinstance(meta_raw, dict):
                    meta = dict(meta_raw)
                else:
                    meta = {}
                meta["request_id"] = request_id
                detail["meta"] = meta
                response = JSONResponse(status_code=exc.status_code, content={"detail": detail})
                response.headers["X-Request-ID"] = request_id
                code, message = _extract_error_detail(response)
                _log_error(
                    request_id=request_id,
                    method=method,
                    path=path,
                    status=exc.status_code,
                    code=code,
                    message=message,
                )
                request.state.error_logged = True
                _log_request(
                    request_id=request_id,
                    method=method,
                    path=path,
                    status=exc.status_code,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    auth_result="denied",
                )
                return response

        try:
            response = await call_next(request)
        except Exception:
            _log_error(
                request_id=request_id,
                method=method,
                path=path,
                status=500,
                code="UNHANDLED_EXCEPTION",
                message="Unhandled server exception.",
            )
            _log_request(
                request_id=request_id,
                method=method,
                path=path,
                status=500,
                duration_ms=(time.perf_counter() - start) * 1000,
                auth_result="passed" if should_enforce_auth(method, path) else "not_required",
            )
            raise
        response.headers["X-Request-ID"] = request_id
        if response.status_code >= 400 and not bool(getattr(request.state, "error_logged", False)):
            code, message = _extract_error_detail(response)
            _log_error(
                request_id=request_id,
                method=method,
                path=path,
                status=response.status_code,
                code=code,
                message=message,
            )
        _log_request(
            request_id=request_id,
            method=method,
            path=path,
            status=response.status_code,
            duration_ms=(time.perf_counter() - start) * 1000,
            auth_result="passed" if should_enforce_auth(method, path) else "not_required",
        )
        return response

    # Registered LAST on purpose: Starlette's add_middleware inserts at the
    # front, so the last-registered middleware ends up OUTERMOST. CORSMiddleware
    # must wrap the auth middleware so that 401/403 responses still carry
    # Access-Control-Allow-* headers (otherwise dev-origin clients only see
    # opaque network errors instead of the structured error body).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tts.router, prefix="/api/tts", tags=["tts"])
    app.include_router(documents.router, prefix="/api/tts", tags=["documents"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(evermem.router, prefix="/api/evermem", tags=["evermem"])
    app.include_router(tavus.router, prefix="/api/tavus", tags=["tavus"])
    app.include_router(translate.router, prefix="/api/translate", tags=["translate"])
    app.include_router(voices.router, prefix="/api/voices", tags=["voices"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    app.include_router(agent_runs.router, prefix="/api/agent-runs", tags=["agent-runs"])
    app.include_router(audio_agent.router, prefix="/api/audio-agent", tags=["audio-agent"])
    app.include_router(audio_overview.router, prefix="/api/audio-overview", tags=["audio-overview"])
    app.include_router(transcription.router, prefix="/api/transcription", tags=["transcription"])
    app.include_router(voice_chat.router, prefix="/api/voice-chat", tags=["voice-chat"])

    frontend_dist_env = os.environ.get("VOICESPIRIT_FRONTEND_DIST", "").strip()
    frontend_dist = (
        Path(frontend_dist_env)
        if frontend_dist_env
        else Path(__file__).resolve().parents[1] / "frontend" / "dist"
    )
    frontend_dist_resolved = frontend_dist.resolve()
    frontend_assets = frontend_dist / "assets"
    transcription_public_dir = get_data_dir() / "temp_audio" / "transcription_jobs" / "published"
    transcription_public_dir.mkdir(parents=True, exist_ok=True)
    # Capability URL, deliberately unauthenticated: the consumer is the cloud
    # ASR provider fetching source_url (it cannot send Bearer headers). Files
    # are named "{job_id}{ext}" with a 64-bit random job_id, so URLs are
    # unguessable; the mount only matters when the user explicitly configures
    # transcription_settings.public_base_url.
    app.mount(
        "/public/transcription",
        StaticFiles(directory=str(transcription_public_dir)),
        name="transcription-public",
    )
    if frontend_dist.is_dir() and (frontend_dist / "index.html").is_file():
        if frontend_assets.is_dir():
            app.mount(
                "/app/assets",
                StaticFiles(directory=str(frontend_assets)),
                name="frontend-assets",
            )
            # Vite build uses absolute "/assets/*" by default.
            # Mount a root alias so desktop "/app/" entry can load bundles correctly.
            app.mount(
                "/assets",
                StaticFiles(directory=str(frontend_assets)),
                name="frontend-assets-root",
            )

        INDEX_HEADERS = {
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }

        @app.get("/app")
        @app.get("/app/")
        async def web_app_index() -> FileResponse:
            return FileResponse(frontend_dist / "index.html", headers=INDEX_HEADERS)

        @app.get("/app/{full_path:path}")
        async def web_app_spa(full_path: str) -> FileResponse:
            safe_target = (frontend_dist / full_path).resolve()
            # is_relative_to (not a string-prefix check) so sibling directories
            # like frontend/dist.bak cannot be read via /app/../dist-old/...
            if (
                safe_target.is_relative_to(frontend_dist_resolved)
                and safe_target.is_file()
            ):
                return FileResponse(safe_target)
            if (
                full_path.startswith("assets/")
                or full_path.endswith((".js", ".css", ".map", ".wasm", ".ico", ".png", ".jpg", ".svg", ".json"))
            ):
                raise HTTPException(status_code=404, detail=f"Asset not found: {full_path}")
            return FileResponse(frontend_dist / "index.html", headers=INDEX_HEADERS)

    @app.get("/")
    async def root() -> dict:
        return {
            "name": "Echo API",
            "version": "0.1.0",
            "status": "running",
            "auth_enabled": is_auth_enabled(),
            "auth_mode": "user-or-token-write-auth",
        }

    @app.get("/health")
    async def health() -> dict:
        return {"status": "healthy"}

    return app


app = create_app()


if __name__ == "__main__":
    import sys

    import uvicorn

    if getattr(sys, "frozen", False):
        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
