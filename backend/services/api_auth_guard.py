from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import Header, HTTPException, status

from .config_loader import BackendConfig
from .user_auth_service import user_auth_service

_config = BackendConfig()
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SENSITIVE_READ_PATH_PREFIXES = (
    "/api/agent-runs",
    "/api/voice-chat/sessions",
    # GET /api/settings returns configuration incl. MASKED_SECRET credential
    # placeholders; POST reveal-secret returns real values. Reads must be
    # authenticated (admin-level when admin auth is configured, mirroring
    # the PUT guard).
    "/api/settings",
    # Transcription jobs expose full transcript text and job metadata.
    "/api/transcription",
)


def _read_token_from_config() -> str:
    try:
        _config.reload()
        data: dict[str, Any] = _config.get_all()
    except Exception:
        return ""

    auth_settings = data.get("auth_settings", {})
    if not isinstance(auth_settings, dict):
        return ""
    return str(auth_settings.get("api_token", "")).strip()


def resolve_api_token() -> str:
    env_token = os.getenv("VOICESPIRIT_API_TOKEN", "").strip()
    if env_token:
        return env_token
    return _read_token_from_config()


def resolve_admin_token() -> str:
    env_token = os.getenv("VOICESPIRIT_ADMIN_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        _config.reload()
        data: dict[str, Any] = _config.get_all()
    except Exception:
        return ""
    auth_settings = data.get("auth_settings", {})
    if not isinstance(auth_settings, dict):
        return ""
    return str(auth_settings.get("admin_token", "")).strip()


def is_auth_enabled() -> bool:
    return bool(resolve_api_token() or resolve_admin_token() or user_auth_service.has_users())


def should_enforce_auth(method: str, path: str) -> bool:
    if not is_auth_enabled():
        return False
    if path.startswith("/api/auth/"):
        return False
    if (
        method.upper() == "GET"
        and path.startswith("/api/")
        and any(path.startswith(prefix) for prefix in SENSITIVE_READ_PATH_PREFIXES)
    ):
        return True
    return path.startswith("/api/") and method.upper() in WRITE_METHODS


def should_require_admin_auth(method: str, path: str) -> bool:
    if not should_enforce_auth(method, path):
        return False
    if not resolve_admin_token() and not user_auth_service.has_users():
        return False
    return path.startswith("/api/settings")


def _missing_token_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "AUTH_TOKEN_MISSING",
            "message": "Missing Bearer token.",
            "meta": {"hint": "Use Authorization: Bearer <token>."},
        },
    )


def _invalid_token_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "AUTH_TOKEN_INVALID",
            "message": "Invalid Bearer token.",
            "meta": {},
        },
    )


def _missing_admin_token_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "AUTH_ADMIN_TOKEN_MISSING",
            "message": "Missing admin Bearer token.",
            "meta": {"hint": "Use Authorization: Bearer <admin-token>."},
        },
    )


def _invalid_admin_token_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "AUTH_ADMIN_TOKEN_INVALID",
            "message": "Invalid admin Bearer token.",
            "meta": {},
        },
    )


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise _missing_token_exception()
    value = authorization.strip()
    if not value.lower().startswith("bearer "):
        raise _missing_token_exception()
    token = value[7:].strip()
    if not token:
        raise _missing_token_exception()
    return token


def validate_auth_header(authorization: str | None, *, require_admin: bool = False) -> dict[str, Any] | None:
    expected_api = resolve_api_token()
    expected_admin = resolve_admin_token()
    has_user_auth = user_auth_service.has_users()
    if not expected_api and not expected_admin and not has_user_auth:
        return

    if require_admin:
        if not authorization:
            raise _missing_admin_token_exception()
        value = authorization.strip()
        if not value.lower().startswith("bearer "):
            raise _missing_admin_token_exception()
        provided = value[7:].strip()
        if not provided:
            raise _missing_admin_token_exception()
        if expected_admin and secrets.compare_digest(provided, expected_admin):
            return {"auth_type": "static_admin"}
        user = user_auth_service.verify_access_token(provided)
        if user and bool(user.get("is_admin")):
            return user
        raise _invalid_admin_token_exception()

    provided_token = _extract_bearer_token(authorization)
    allowed = [token for token in (expected_api, expected_admin) if token]
    if any(secrets.compare_digest(provided_token, token) for token in allowed):
        return {"auth_type": "static"}
    user = user_auth_service.verify_access_token(provided_token)
    if user is not None:
        return user
    raise _invalid_token_exception()


async def require_api_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    validate_auth_header(authorization)


def validate_websocket_token(token: str | None) -> None:
    """Validate a WebSocket handshake token before ``accept()``.

    The HTTP auth middleware never sees WebSocket scopes, so realtime
    endpoints must enforce auth themselves during the handshake.  Browsers
    cannot set custom headers on ``new WebSocket(url)``, so the client passes
    its bearer token as the ``token`` query parameter instead.

    No-op when auth is disabled (localhost single-user mode).  Otherwise
    raises the same 401/403 ``HTTPException``s as ``validate_auth_header``;
    callers should close the socket (without accepting) and return.
    """
    if not is_auth_enabled():
        return
    cleaned = str(token or "").strip()
    authorization = f"Bearer {cleaned}" if cleaned else None
    validate_auth_header(authorization)
