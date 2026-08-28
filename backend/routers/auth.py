from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from services.user_auth_service import (
    AuthRateLimitError,
    auth_rate_limiter,
    user_auth_service,
)

router = APIRouter()


class AuthUserResponse(BaseModel):
    id: str
    email: str
    is_admin: bool
    is_active: bool
    created_at: str


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse


class AuthSessionInfo(BaseModel):
    client_id: str
    created_at: str
    expires_at: str
    is_current: bool


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class StructuredErrorDetail(BaseModel):
    code: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredErrorResponse(BaseModel):
    detail: StructuredErrorDetail


def _extract_bearer_token(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if not value.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_TOKEN_MISSING",
                "message": "Missing Bearer token.",
                "meta": {},
            },
        )
    token = value[7:].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_TOKEN_MISSING",
                "message": "Missing Bearer token.",
                "meta": {},
            },
        )
    return token


def _extract_client_id(client_id: str | None) -> str:
    return str(client_id or "").strip()[:128]


def _request_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited_exception(exc: AuthRateLimitError) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": "AUTH_RATE_LIMITED",
            "message": str(exc),
            "meta": {"retry_after": exc.retry_after},
        },
        headers={"Retry-After": str(exc.retry_after)},
    )


def _build_session(user: dict[str, Any], client_id: str = "") -> AuthSessionResponse:
    return AuthSessionResponse(
        access_token=user_auth_service.create_access_token(user, client_id=client_id),
        user=AuthUserResponse(**user),
    )


def _require_user(authorization: str | None) -> dict[str, Any]:
    token = _extract_bearer_token(authorization)
    user = user_auth_service.verify_access_token(token)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_TOKEN_INVALID",
                "message": "Invalid Bearer token.",
                "meta": {},
            },
        )
    return user


@router.post(
    "/register",
    response_model=AuthSessionResponse,
    responses={
        400: {"description": "Registration failed.", "model": StructuredErrorResponse},
        429: {"description": "Rate limited.", "model": StructuredErrorResponse},
    },
)
async def register(
    payload: RegisterRequest,
    request: Request,
    x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
) -> AuthSessionResponse:
    try:
        auth_rate_limiter.hit_ip(_request_ip(request))
        user = user_auth_service.register_user(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "AUTH_REGISTER_FAILED",
                "message": str(exc),
                "meta": {},
            },
        ) from exc
    except AuthRateLimitError as exc:
        raise _rate_limited_exception(exc) from exc
    return _build_session(user, _extract_client_id(x_client_id))


@router.post(
    "/login",
    response_model=AuthSessionResponse,
    responses={
        401: {"description": "Invalid credentials.", "model": StructuredErrorResponse},
        429: {"description": "Rate limited or locked out.", "model": StructuredErrorResponse},
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
) -> AuthSessionResponse:
    try:
        auth_rate_limiter.hit_ip(_request_ip(request))
        retry_after = auth_rate_limiter.lockout_remaining(payload.email)
        if retry_after > 0:
            raise AuthRateLimitError(
                retry_after,
                "Account temporarily locked after repeated failed logins.",
            )
        user = user_auth_service.authenticate_user(payload.email, payload.password)
        if user is None:
            auth_rate_limiter.record_login_failure(payload.email)
    except AuthRateLimitError as exc:
        raise _rate_limited_exception(exc) from exc
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_LOGIN_FAILED",
                "message": "Incorrect email or password.",
                "meta": {},
            },
        )
    auth_rate_limiter.clear_login_failures(payload.email)
    return _build_session(user, _extract_client_id(x_client_id))


@router.post(
    "/change-password",
    response_model=AuthUserResponse,
    responses={
        400: {"description": "Password change failed.", "model": StructuredErrorResponse},
        401: {"description": "Invalid credentials.", "model": StructuredErrorResponse},
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AuthUserResponse:
    user = _require_user(authorization)
    try:
        updated = user_auth_service.change_password(
            str(user.get("email", "")),
            payload.current_password,
            payload.new_password,
            current_jti=str(user.get("jti", "")),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "AUTH_CHANGE_PASSWORD_FAILED",
                "message": str(exc),
                "meta": {},
            },
        ) from exc
    return AuthUserResponse(**updated)


@router.post("/logout")
async def logout(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    token = _extract_bearer_token(authorization)
    user = user_auth_service.verify_access_token(token)
    revoked = False
    if user is not None and user.get("jti"):
        revoked = user_auth_service.revoke_session(str(user["jti"]))
    # Idempotent by design: an unusable token is already "logged out".
    return {"ok": True, "revoked": revoked}


@router.get(
    "/sessions",
    response_model=list[AuthSessionInfo],
    responses={
        401: {"description": "Invalid credentials.", "model": StructuredErrorResponse},
    },
)
async def sessions(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> list[AuthSessionInfo]:
    user = _require_user(authorization)
    active = user_auth_service.list_active_sessions(
        str(user.get("email", "")),
        current_jti=str(user.get("jti", "")),
    )
    return [AuthSessionInfo(**session) for session in active]


@router.post(
    "/sessions/revoke-others",
    responses={
        401: {"description": "Invalid credentials.", "model": StructuredErrorResponse},
    },
)
async def revoke_other_sessions(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    user = _require_user(authorization)
    revoked = user_auth_service.revoke_other_sessions(
        str(user.get("email", "")),
        current_jti=str(user.get("jti", "")),
    )
    return {"ok": True, "revoked": revoked}


@router.get(
    "/me",
    response_model=AuthUserResponse,
    responses={
        401: {"description": "Invalid credentials.", "model": StructuredErrorResponse},
    },
)
async def me(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AuthUserResponse:
    token = _extract_bearer_token(authorization)
    user = user_auth_service.verify_access_token(token)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_TOKEN_INVALID",
                "message": "Invalid Bearer token.",
                "meta": {},
            },
        )
    return AuthUserResponse(**user)
