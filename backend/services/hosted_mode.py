"""Hosted (paid, multi-user) deployment mode.

When ``ECHO_HOSTED_MODE=1`` the backend runs on a shared server holding the
operator's provider keys. End users only get the realtime voice coach:

* every ``/api/*`` route outside ``HOSTED_ALLOWED_PREFIXES`` is refused, so
  nobody can read keys, change settings or spend credits on TTS/chat/etc.;
* public registration is closed — the operator creates accounts;
* realtime calls require a user token (no loopback exemption, since nginx
  makes every client look like 127.0.0.1), are limited to the providers in
  ``hosted_settings.providers`` and are metered against a minutes balance.

Shared memory/learning stores are not per-user yet, so they stay disabled.
"""

from __future__ import annotations

import os
from typing import Any

from .config_loader import BackendConfig

# Routes an authenticated end user may call in hosted mode. Everything else
# under /api/ is refused before it reaches a router.
HOSTED_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/api/billing/",
    "/api/voice-chat/ws",
)
# Routes that work before login (the login form itself).
HOSTED_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/auth/login",
        "/api/billing/hosted-info",
    }
)
HOSTED_ADMIN_PREFIXES: tuple[str, ...] = ("/api/billing/admin/",)

# Default paid offering. ``models`` empty = any model of that provider;
# ``multiplier`` scales billed seconds (e.g. 2.0 for a pricier model).
DEFAULT_HOSTED_PROVIDERS: dict[str, dict[str, Any]] = {
    "Vercel": {
        "multiplier": 1.0,
        "models": ["google/gemini-3.8-live", "google/gemini-3.8-live-extended-thinking"],
    },
    "DashScope": {"multiplier": 1.0, "models": ["qwen3.8-omni-flash-realtime"]},
    "Doubao": {"multiplier": 1.0, "models": ["doubao-realtime"]},
}
DEFAULT_IDLE_TIMEOUT_SECONDS = 60
DEFAULT_LOW_BALANCE_WARNING_SECONDS = 300
DEFAULT_MAX_SESSION_SECONDS = 30 * 60

_config = BackendConfig()


def is_hosted_mode() -> bool:
    return os.getenv("ECHO_HOSTED_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _hosted_settings() -> dict[str, Any]:
    try:
        _config.reload()
        section = _config.get_all().get("hosted_settings", {})
    except Exception:
        return {}
    return section if isinstance(section, dict) else {}


def _int_setting(name: str, default: int) -> int:
    try:
        value = int(_hosted_settings().get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def idle_timeout_seconds() -> int:
    return _int_setting("idle_timeout_seconds", DEFAULT_IDLE_TIMEOUT_SECONDS)


def low_balance_warning_seconds() -> int:
    return _int_setting("low_balance_warning_seconds", DEFAULT_LOW_BALANCE_WARNING_SECONDS)


def max_session_seconds() -> int:
    return _int_setting("max_session_seconds", DEFAULT_MAX_SESSION_SECONDS)


def hosted_providers() -> dict[str, dict[str, Any]]:
    configured = _hosted_settings().get("providers")
    if isinstance(configured, dict) and configured:
        return {str(k): v for k, v in configured.items() if isinstance(v, dict)}
    return DEFAULT_HOSTED_PROVIDERS


def _allowed_models(entry: dict[str, Any]) -> list[str]:
    return [str(m).strip() for m in entry.get("models") or [] if str(m).strip()]


def resolve_hosted_model(provider: str, model: str | None) -> str | None:
    """Fill an omitted model with the provider's first sold model.

    Without this a client that leaves ``model`` blank would fall through to
    the provider's built-in default, which may be a model nobody priced.
    """
    cleaned = str(model or "").strip()
    if cleaned:
        return cleaned
    entry = hosted_providers().get(provider)
    models = _allowed_models(entry) if entry else []
    return models[0] if models else None


def resolve_billing_multiplier(provider: str, model: str | None) -> float | None:
    """Return the billing multiplier, or ``None`` when the pair is not sold."""
    entry = hosted_providers().get(provider)
    if entry is None:
        return None
    models = _allowed_models(entry)
    if models and str(model or "").strip() not in models:
        return None
    try:
        multiplier = float(entry.get("multiplier", 1.0))
    except (TypeError, ValueError):
        multiplier = 1.0
    return multiplier if multiplier > 0 else 1.0


def is_path_allowed(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in HOSTED_ALLOWED_PREFIXES)


def is_blocked_path(path: str) -> bool:
    """HTTP paths refused outright in hosted mode (WebSockets bypass HTTP middleware)."""
    if path.startswith("/api/"):
        return not is_path_allowed(path)
    # Published transcription audio is a desktop-only feature.
    return path.startswith("/public/")


def is_public_path(path: str) -> bool:
    return path in HOSTED_PUBLIC_PATHS


def is_admin_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in HOSTED_ADMIN_PREFIXES)


class HostedWebSocketGuard:
    """ASGI middleware refusing WebSocket routes not sold in hosted mode.

    FastAPI's HTTP middleware never sees WebSocket scopes, and other realtime
    endpoints (e.g. live transcription) treat 127.0.0.1 as trusted — which is
    every client once nginx proxies them. Refuse those handshakes outright.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            scope.get("type") == "websocket"
            and is_hosted_mode()
            and not is_path_allowed(str(scope.get("path", "")))
        ):
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


HOSTED_ACCOUNT_DOMAIN = "echo.local"


def normalize_account_id(value: str) -> str:
    """Let neighbours log in with a short name like ``1203`` instead of an email.

    Accounts are stored as emails; a bare name maps to ``name@echo.local``.
    """
    cleaned = str(value or "").strip().lower()
    if cleaned and "@" not in cleaned:
        return f"{cleaned}@{HOSTED_ACCOUNT_DOMAIN}"
    return cleaned


def display_account_id(email: str) -> str:
    suffix = f"@{HOSTED_ACCOUNT_DOMAIN}"
    return email[: -len(suffix)] if email.endswith(suffix) else email
