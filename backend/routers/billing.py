"""Minutes balance (end users) and account administration (operator).

Only meaningful in hosted mode; outside it every route except
``/hosted-info`` answers 404 so the desktop app exposes nothing new.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services import hosted_mode
from services.billing_service import billing_service
from services.user_auth_service import user_auth_service

router = APIRouter()

MAX_GRANT_MINUTES = 100_000


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


@router.get("/hosted-info")
async def hosted_info() -> dict[str, Any]:
    if not hosted_mode.is_hosted_mode():
        return {"hosted": False, "providers": []}
    return {
        "hosted": True,
        "providers": [
            {"provider": name, "models": list(entry.get("models") or [])}
            for name, entry in hosted_mode.hosted_providers().items()
        ],
    }


@router.get("/me")
async def my_balance(request: Request) -> dict[str, Any]:
    _require_hosted()
    email = _current_email(request)
    return {
        "account": hosted_mode.display_account_id(email),
        "remaining_seconds": billing_service.get_balance(email),
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
