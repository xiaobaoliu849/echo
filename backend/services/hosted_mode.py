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
        "/api/billing/register",
    }
)
HOSTED_ADMIN_PREFIXES: tuple[str, ...] = ("/api/billing/admin/",)

# Default paid offering. ``models`` empty = any model of that provider;
# ``multiplier`` scales billed seconds (e.g. 2.0 for a pricier model) and
# ``model_multipliers`` overrides it per model. A minute is priced for the
# Gemini Live default; thinking tokens make extended thinking pricier and
# Qwen Omni is several times cheaper, sold as the economy option.
DEFAULT_HOSTED_PROVIDERS: dict[str, dict[str, Any]] = {
    "Vercel": {
        "multiplier": 1.0,
        "models": ["google/gemini-3.8-live", "google/gemini-3.8-live-extended-thinking"],
        "model_multipliers": {"google/gemini-3.8-live-extended-thinking": 1.5},
    },
    "DashScope": {"multiplier": 0.5, "models": ["qwen3.8-omni-flash-realtime"]},
    "Doubao": {"multiplier": 1.0, "models": ["doubao-realtime"]},
}
DEFAULT_IDLE_TIMEOUT_SECONDS = 60
DEFAULT_LOW_BALANCE_WARNING_SECONDS = 300
# Live models re-bill the whole context every turn, so per-minute cost grows
# with call length; a 15 min cap keeps the worst case bounded.
DEFAULT_MAX_SESSION_SECONDS = 15 * 60
# Minutes from each top-up expire this many days later (0 = never), which
# caps how long sold-but-unused minutes stay a liability.
DEFAULT_MINUTES_VALID_DAYS = 90
# Relayed calls stream audio through this server; a 3 Mbps uplink carries
# about five without stuttering.
DEFAULT_MAX_RELAY_SESSIONS = 5
EXPIRY_WARNING_DAYS = 7

_config = BackendConfig()


def is_hosted_mode() -> bool:
    return os.getenv("ECHO_HOSTED_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def is_locked_down() -> bool:
    """Hosted server, or a community client deferring to one: coach only."""
    from .community_client import is_community_client

    return is_hosted_mode() or is_community_client()


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


def max_relay_sessions() -> int:
    return _int_setting("max_relay_sessions", DEFAULT_MAX_RELAY_SESSIONS)


def minutes_valid_days() -> int:
    try:
        value = int(_hosted_settings().get("minutes_valid_days", DEFAULT_MINUTES_VALID_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_MINUTES_VALID_DAYS
    return max(0, value)


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
    per_model = entry.get("model_multipliers")
    raw = entry.get("multiplier", 1.0)
    if isinstance(per_model, dict) and str(model or "").strip() in per_model:
        raw = per_model[str(model or "").strip()]
    try:
        multiplier = float(raw)
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
            and is_locked_down()
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
