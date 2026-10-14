"""Minutes balance (end users) and account administration (operator).

Only meaningful in hosted mode; outside it every route except
``/hosted-info`` answers 404 so the desktop app exposes nothing new.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services import community_client, hosted_mode
from services.billing_service import billing_service
from services.direct_calls import HEARTBEAT_SECONDS, DirectCallRegistry
from services.user_auth_service import user_auth_service

router = APIRouter()

MAX_GRANT_MINUTES = 100_000


class DirectStartRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(default="", max_length=120)


class DirectHeartbeatRequest(BaseModel):
    call_id: str = Field(min_length=1, max_length=64)
    active: bool = False
    final: bool = False


class CreateAccountRequest(BaseModel):
    account: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=128)
    minutes: int = Field(default=0, ge=0, le=MAX_GRANT_MINUTES)
    note: str = Field(default="", max_length=200)


class GrantRequest(BaseModel):
    account: str = Field(min_length=1, max_length=120)
    minutes: int = Field(ge=-MAX_GRANT_MINUTES, le=MAX_GRANT_MINUTES)
    note: str = Field(default="", max_length=200)


class SetActiveRequest(BaseModel):
    account: str = Field(min_length=1, max_length=120)
    active: bool


class ResetPasswordRequest(BaseModel):
    account: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=128)


def _require_hosted() -> None:
    if not hosted_mode.is_hosted_mode():
        raise HTTPException(status_code=404, detail={"code": "NOT_AVAILABLE", "message": "Not available.", "meta": {}})


def _current_email(request: Request) -> str:
    user = getattr(request.state, "auth_user", None)
    email = str((user or {}).get("email", "")).strip().lower() if isinstance(user, dict) else ""
    if not email:
        raise HTTPException(status_code=401, detail={"code": "AUTH_TOKEN_MISSING", "message": "Login required.", "meta": {}})
    return email


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "BILLING_REQUEST_FAILED", "message": str(exc), "meta": {}})


def _bearer(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else ""


@router.get("/hosted-info", response_model=None)
async def hosted_info() -> dict[str, Any] | JSONResponse:
    if community_client.is_community_client():
        # Only providers that can go direct are offered on a community client.
        try:
            info = await community_client.forward("GET", "/api/billing/hosted-info")
        except community_client.CommunityServerError as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        info["providers"] = [p for p in info.get("providers", []) if p.get("provider") in DIRECT_PROVIDERS]
        return info
    if not hosted_mode.is_hosted_mode():
        return {"hosted": False, "providers": []}
    return {
        "hosted": True,
        "providers": [
            {"provider": name, "models": list(entry.get("models") or [])}
            for name, entry in hosted_mode.hosted_providers().items()
        ],
    }


@router.get("/me", response_model=None)
async def my_balance(
    request: Request, authorization: str | None = Header(default=None, alias="Authorization")
) -> dict[str, Any] | JSONResponse:
    if community_client.is_community_client():
        try:
            return await community_client.forward("GET", "/api/billing/me", token=_bearer(authorization))
        except community_client.CommunityServerError as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    _require_hosted()
    email = _current_email(request)
    return {
        "account": hosted_mode.display_account_id(email),
        "remaining_seconds": billing_service.get_balance(email),
    }


# ── direct calls: the user's machine talks to the provider itself ────────

# Only providers that can mint short-lived client secrets can go direct; the
# operator's real key must never leave this server.
DIRECT_PROVIDERS = frozenset({"Vercel"})
_direct_registry: DirectCallRegistry | None = None


def _registry() -> DirectCallRegistry:
    global _direct_registry
    if _direct_registry is None:
        _direct_registry = DirectCallRegistry(
            billing=billing_service,
            idle_timeout=hosted_mode.idle_timeout_seconds(),
            max_session=hosted_mode.max_session_seconds(),
        )
    return _direct_registry


async def _mint_direct_secret(model: str) -> dict[str, str]:
    # Imported lazily: the realtime service pulls in every provider SDK.
    from routers.voice_chat import voice_chat_service

    settings = voice_chat_service._resolve_vercel_settings(model)
    # The secret only has to outlive the client's connect handshake; an
    # established provider session is not cut off when it expires.
    secret = await voice_chat_service._mint_vercel_client_secret(settings, expires_after_seconds=60)
    return {
        "client_secret": secret,
        "model": settings["model"],
        "ws_url": voice_chat_service._vercel_ws_url(settings),
    }


@router.post("/direct/start")
async def direct_start(payload: DirectStartRequest, request: Request) -> dict[str, Any]:
    _require_hosted()
    email = _current_email(request)
    provider = payload.provider.strip()
    model = hosted_mode.resolve_hosted_model(provider, payload.model)
    multiplier = hosted_mode.resolve_billing_multiplier(provider, model)
    if provider not in DIRECT_PROVIDERS or multiplier is None or not model:
        raise _bad_request(ValueError("该模型不支持直连。"))
    try:
        call = _registry().start(email, provider=provider, model=model, multiplier=multiplier)
    except ValueError as exc:
        raise HTTPException(status_code=402, detail={"code": "BILLING_DENIED", "message": str(exc), "meta": {}}) from exc
    try:
        minted = await _mint_direct_secret(model)
    except Exception as exc:
        # Never bill a call the provider refused to authorise.
        _registry().heartbeat(email, call.call_id, active=False, final=True)
        raise HTTPException(
            status_code=502, detail={"code": "PROVIDER_AUTH_FAILED", "message": str(exc)[:200], "meta": {}}
        ) from exc
    return {
        "call_id": call.call_id,
        "provider": provider,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "remaining_seconds": billing_service.get_balance(email),
        **minted,
    }


@router.post("/direct/heartbeat")
async def direct_heartbeat(payload: DirectHeartbeatRequest, request: Request) -> dict[str, Any]:
    _require_hosted()
    email = _current_email(request)
    result = _registry().heartbeat(email, payload.call_id, active=payload.active, final=payload.final)
    return {
        "remaining_seconds": result.remaining_seconds,
        "stop": result.stop,
        "reason": result.reason,
        "message": result.message,
    }


# ── operator endpoints (admin token enforced by the auth middleware) ─────


@router.get("/admin/users")
async def admin_list_users(days: int = Query(default=30, ge=1, le=366)) -> dict[str, Any]:
    _require_hosted()
    since = int(time.time()) - days * 86400
    usage = {row["user_email"]: row for row in billing_service.usage_summary(since=since)}
    users = []
    for user in user_auth_service.list_users():
        email = str(user["email"])
        row = usage.get(email, {})
        users.append(
            {
                "account": hosted_mode.display_account_id(email),
                "is_admin": bool(user.get("is_admin")),
                "is_active": bool(user.get("is_active")),
                "remaining_seconds": int(row.get("balance_seconds", 0)),
                "used_seconds": int(row.get("used_seconds", 0)),
                "last_used_at": row.get("last_used_at"),
            }
        )
    return {
        "days": days,
        "users": users,
        "by_model": billing_service.usage_by_model(since=since),
    }


@router.post("/admin/users")
async def admin_create_user(payload: CreateAccountRequest) -> dict[str, Any]:
    _require_hosted()
    email = hosted_mode.normalize_account_id(payload.account)
    try:
        user_auth_service.register_user(email, payload.password)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    balance = billing_service.get_balance(email)
    if payload.minutes:
        balance = billing_service.grant(email, payload.minutes * 60, note=payload.note or "initial")
    return {"account": hosted_mode.display_account_id(email), "remaining_seconds": balance}


@router.post("/admin/grant")
async def admin_grant(payload: GrantRequest) -> dict[str, Any]:
    _require_hosted()
    email = hosted_mode.normalize_account_id(payload.account)
    if email not in {str(u["email"]) for u in user_auth_service.list_users()}:
        raise _bad_request(ValueError("User not found."))
    try:
        balance = billing_service.grant(email, payload.minutes * 60, note=payload.note)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"account": hosted_mode.display_account_id(email), "remaining_seconds": balance}


@router.post("/admin/active")
async def admin_set_active(payload: SetActiveRequest) -> dict[str, Any]:
    _require_hosted()
    try:
        user_auth_service.set_active(hosted_mode.normalize_account_id(payload.account), payload.active)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"ok": True}


@router.post("/admin/password")
async def admin_reset_password(payload: ResetPasswordRequest) -> dict[str, Any]:
    _require_hosted()
    try:
        user_auth_service.set_password(hosted_mode.normalize_account_id(payload.account), payload.password)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"ok": True}
