"""Minutes balance (end users) and account administration (operator).

Only meaningful in hosted mode; outside it every route except
``/hosted-info`` answers 404 so the desktop app exposes nothing new.
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services import community_client, hosted_mode, hosted_renewal
from services.billing_service import billing_service
from services.direct_calls import HEARTBEAT_SECONDS, DirectCallRegistry
from services.user_auth_service import user_auth_service

router = APIRouter()
# Mounted ahead of ``router`` only on a community client (see main.py).
community_admin_router = APIRouter()

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
    # Per-package validity (e.g. a 30-day monthly card); None = server default.
    valid_days: int | None = Field(default=None, ge=1, le=366)


class GrantRequest(BaseModel):
    account: str = Field(min_length=1, max_length=120)
    minutes: int = Field(ge=-MAX_GRANT_MINUTES, le=MAX_GRANT_MINUTES)
    note: str = Field(default="", max_length=200)
    valid_days: int | None = Field(default=None, ge=1, le=366)


class RenewalRequest(BaseModel):
    text: str = Field(default="", max_length=hosted_renewal.MAX_TEXT_LENGTH)
    qr: str = Field(default="", max_length=hosted_renewal.MAX_QR_BYTES)


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
        # Gemini goes direct; Qwen Omni and Doubao are relayed through the server.
        try:
            info = await community_client.forward("GET", "/api/billing/hosted-info")
        except community_client.CommunityServerError as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        supported = community_client.DIRECT_PROVIDERS | community_client.RELAY_PROVIDERS
        info["providers"] = [p for p in info.get("providers", []) if p.get("provider") in supported]
        return info
    if not hosted_mode.is_hosted_mode():
        return {"hosted": False, "providers": []}
    return {
        "hosted": True,
        "providers": [
            {
                "provider": name,
                "models": list(entry.get("models") or []),
                # Minutes deducted per minute of talk, shown next to each model.
                "multipliers": {
                    model: hosted_mode.resolve_billing_multiplier(name, model)
                    for model in entry.get("models") or []
                },
            }
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
        "expiring_soon": _expiring_soon(billing_service.active_lots(email)),
    }


def _expiring_soon(lots: list[dict[str, Any]]) -> dict[str, int] | None:
    """Minutes that lapse within the warning window, for a reminder."""
    horizon = int(time.time()) + hosted_mode.EXPIRY_WARNING_DAYS * 86400
    due = [lot for lot in lots if lot["expires_at"] is not None and lot["expires_at"] <= horizon]
    if not due:
        return None
    return {"seconds": sum(lot["remaining_seconds"] for lot in due), "expires_at": min(lot["expires_at"] for lot in due)}


async def _forward_to_server(method: str, path: str, authorization: str | None) -> Any:
    try:
        return await community_client.forward(method, path, token=_bearer(authorization))
    except community_client.CommunityServerError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@router.get("/me/history", response_model=None)
async def my_history(
    request: Request,
    days: int = Query(default=30, ge=1, le=366),
    tz: int = Query(default=0, ge=-840, le=840),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any] | JSONResponse:
    if community_client.is_community_client():
        return await _forward_to_server("GET", f"/api/billing/me/history?days={days}&tz={tz}", authorization)
    _require_hosted()
    email = _current_email(request)
    since = int(time.time()) - days * 86400
    return {
        "account": hosted_mode.display_account_id(email),
        "remaining_seconds": billing_service.get_balance(email),
        "daily": billing_service.usage_by_day(since=since, utc_offset_minutes=tz, email=email),
        "calls": billing_service.recent_calls(email, since=since),
        "grants": billing_service.grants(email, limit=20),
        "lots": billing_service.active_lots(email),
    }


@router.get("/renewal", response_model=None)
async def renewal_info(
    request: Request, authorization: str | None = Header(default=None, alias="Authorization")
) -> dict[str, Any] | JSONResponse:
    if community_client.is_community_client():
        return await _forward_to_server("GET", "/api/billing/renewal", authorization)
    _require_hosted()
    _current_email(request)
    return hosted_renewal.load()


# ── direct calls: the user's machine talks to the provider itself ────────

# Only providers that can mint short-lived client secrets can go direct; the
# operator's real key must never leave this server.
DIRECT_PROVIDERS = community_client.DIRECT_PROVIDERS
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


def _live_calls() -> list[dict[str, Any]]:
    from services.session_meter import live_sessions

    calls = live_sessions() + _registry().live_calls()
    return [
        {
            "account": hosted_mode.display_account_id(str(call["user_email"])),
            "provider": call["provider"],
            "model": call["model"],
            "mode": call["mode"],
            "elapsed_seconds": call["elapsed_seconds"],
        }
        for call in sorted(calls, key=lambda c: -int(c["elapsed_seconds"]))
    ]


def _known_email(account: str) -> str:
    email = hosted_mode.normalize_account_id(account)
    if email not in {str(u["email"]) for u in user_auth_service.list_users()}:
        raise _bad_request(ValueError("User not found."))
    return email


@router.get("/admin/users")
async def admin_list_users(
    days: int = Query(default=30, ge=1, le=366),
    tz: int = Query(default=0, ge=-840, le=840, description="Viewer's UTC offset in minutes, for daily buckets."),
) -> dict[str, Any]:
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
                "created_at": user.get("created_at"),
                "remaining_seconds": int(row.get("balance_seconds", 0)),
                "used_seconds": int(row.get("used_seconds", 0)),
                "last_used_at": row.get("last_used_at"),
            }
        )
    return {
        "days": days,
        "minutes_valid_days": hosted_mode.minutes_valid_days(),
        "users": users,
        "by_model": billing_service.usage_by_model(since=since),
        "daily": billing_service.usage_by_day(since=since, utc_offset_minutes=tz),
        "live": _live_calls(),
    }


@router.get("/admin/user-detail")
async def admin_user_detail(
    account: str = Query(min_length=1, max_length=120),
    days: int = Query(default=30, ge=1, le=366),
    tz: int = Query(default=0, ge=-840, le=840),
) -> dict[str, Any]:
    _require_hosted()
    email = _known_email(account)
    since = int(time.time()) - days * 86400
    return {
        "account": hosted_mode.display_account_id(email),
        "remaining_seconds": billing_service.get_balance(email),
        "grants": billing_service.grants(email),
        "lots": billing_service.active_lots(email),
        "daily": billing_service.usage_by_day(since=since, utc_offset_minutes=tz, email=email),
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
        balance = billing_service.grant(
            email,
            payload.minutes * 60,
            note=payload.note or "initial",
            valid_days=payload.valid_days or hosted_mode.minutes_valid_days(),
        )
    return {"account": hosted_mode.display_account_id(email), "remaining_seconds": balance}


@router.post("/admin/grant")
async def admin_grant(payload: GrantRequest) -> dict[str, Any]:
    _require_hosted()
    email = _known_email(payload.account)
    try:
        balance = billing_service.grant(
            email,
            payload.minutes * 60,
            note=payload.note,
            valid_days=payload.valid_days or hosted_mode.minutes_valid_days(),
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"account": hosted_mode.display_account_id(email), "remaining_seconds": balance}


@router.post("/admin/active")
async def admin_set_active(payload: SetActiveRequest) -> dict[str, Any]:
    _require_hosted()
    email = hosted_mode.normalize_account_id(payload.account)
    if not payload.active and any(u["email"] == email and u.get("is_admin") for u in user_auth_service.list_users()):
        # Disabling the operator would lock everyone out of this page.
        raise _bad_request(ValueError("不能停用管理员账号。"))
    try:
        user_auth_service.set_active(email, payload.active)
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


@router.post("/admin/renewal")
async def admin_set_renewal(payload: RenewalRequest) -> dict[str, Any]:
    _require_hosted()
    try:
        return hosted_renewal.save(text=payload.text, qr=payload.qr)
    except ValueError as exc:
        raise _bad_request(exc) from exc


_ADMIN_PATH_RE = re.compile(r"^[a-z-]{1,40}$")


@community_admin_router.api_route("/admin/{path}", methods=["GET", "POST"], include_in_schema=False)
async def community_admin_proxy(
    path: str, request: Request, authorization: str | None = Header(default=None, alias="Authorization")
) -> Any:
    """On a community client the operator console talks to the hosted server."""
    if not _ADMIN_PATH_RE.match(path):
        raise HTTPException(status_code=404, detail={"code": "NOT_AVAILABLE", "message": "Not available.", "meta": {}})
    body = await request.json() if request.method == "POST" else None
    query = f"?{request.url.query}" if request.url.query else ""
    try:
        return await community_client.forward(
            request.method, f"/api/billing/admin/{path}{query}", token=_bearer(authorization), json=body
        )
    except community_client.CommunityServerError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
