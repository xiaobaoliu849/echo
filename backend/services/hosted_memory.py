"""Per-account EverOS memory for hosted mode.

The operator's single EverOS key stays on the server. Each account gets its
own random EverOS ``user_id`` (never the account name), and every request
this server makes or relays is pinned to that id, so one neighbour's calls
can never read or write another's memories.

Memory is a membership feature: it is on while ``memory_until`` lies in the
future (a monthly card extends it) and the user has not switched it off.

Community clients whose Gemini calls run on the user's own machine reach
EverOS through :func:`rewrite_gateway_request` — an EverOS-shaped gateway on
this server that authenticates the user's token and rewrites every
user / session field to the caller's own scope before forwarding.
"""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

from .db_utils import get_db_connection

logger = logging.getLogger(__name__)

GATEWAY_OPERATIONS = frozenset({"add", "flush", "search", "get"})
MAX_SEARCH_TOP_K = 20
MAX_PAGE_SIZE = 50
REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class HostedMemoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or self._default_db_path()
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hosted_memory (
                    user_email TEXT PRIMARY KEY,
                    scope TEXT NOT NULL UNIQUE,
                    memory_until INTEGER NOT NULL DEFAULT 0,
                    opted_out INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _default_db_path() -> Path:
        from .config_loader import get_data_file_path

        return get_data_file_path("voice_spirit.db")

    @staticmethod
    def _normalize(email: str) -> str:
        return str(email or "").strip().lower()

    def _row(self, email: str) -> dict[str, Any]:
        user = self._normalize(email)
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM hosted_memory WHERE user_email = ?", (user,)).fetchone()
            if row is None:
                # A random id, not a hash of the account: nothing about the
                # neighbour (e.g. a door number) is sent to EverOS.
                scope = f"echo_{secrets.token_hex(12)}"
                conn.execute(
                    "INSERT INTO hosted_memory (user_email, scope, updated_at) VALUES (?, ?, ?)",
                    (user, scope, int(time.time())),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM hosted_memory WHERE user_email = ?", (user,)).fetchone()
        return dict(row)

    def scope(self, email: str) -> str:
        return str(self._row(email)["scope"])

    def status(self, email: str) -> dict[str, Any]:
        row = self._row(email)
        until = int(row["memory_until"] or 0)
        opted_out = bool(row["opted_out"])
        member = until > int(time.time())
        return {
            "configured": bool(server_settings()[1]),
            "member": member,
            "memory_until": until or None,
            "opted_out": opted_out,
            "active": member and not opted_out and bool(server_settings()[1]),
        }

    def extend(self, email: str, days: int) -> int:
        """Add ``days`` of membership (from now, or from a later expiry). 0 revokes."""
        row = self._row(email)
        now = int(time.time())
        until = 0 if days <= 0 else max(now, int(row["memory_until"] or 0)) + int(days) * 86400
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE hosted_memory SET memory_until = ?, updated_at = ? WHERE user_email = ?",
                (until, now, self._normalize(email)),
            )
            conn.commit()
        return until

    def set_opted_out(self, email: str, opted_out: bool) -> None:
        self._row(email)
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE hosted_memory SET opted_out = ?, updated_at = ? WHERE user_email = ?",
                (1 if opted_out else 0, int(time.time()), self._normalize(email)),
            )
            conn.commit()

    def memberships(self) -> dict[str, int]:
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT user_email, memory_until FROM hosted_memory").fetchall()
        return {str(r["user_email"]): int(r["memory_until"] or 0) for r in rows}


def server_settings() -> tuple[str, str]:
    """The operator's EverOS endpoint and key from the server's config.json."""
    from .evermem_config import DEFAULT_EVERMEM_URL, _load_server_evermem_settings

    url, key = _load_server_evermem_settings()
    return (url or DEFAULT_EVERMEM_URL).rstrip("/"), key


def session_payload(store: HostedMemoryStore, email: str) -> dict[str, Any] | None:
    """Memory config for a call run on this server, or None when memory is off."""
    if not store.status(email)["active"]:
        return None
    url, key = server_settings()
    return {"enabled": True, "api_url": url, "api_key": key, "scope_id": store.scope(email)}


# ── gateway for calls that run on a community client ────────────────────


def _session_for(scope: str, value: Any) -> str:
    raw = str(value or "").strip()[-80:] or "default"
    return raw if raw.startswith(f"{scope}_") else f"{scope}_{raw}"


def rewrite_gateway_request(operation: str, payload: dict[str, Any], scope: str) -> dict[str, Any]:
    """Pin an EverOS v2 request to ``scope``; only known fields survive."""
    if operation not in GATEWAY_OPERATIONS:
        raise ValueError("unsupported operation")
    body = payload if isinstance(payload, dict) else {}
    if operation == "add":
        messages = []
        for message in body.get("messages") or []:
            if not isinstance(message, dict):
                continue
            messages.append(
                {
                    "sender_id": scope,
                    "role": "assistant" if message.get("role") == "assistant" else "user",
                    "timestamp": int(message.get("timestamp") or time.time() * 1000),
                    "content": str(message.get("content") or "")[:8000],
                    **({"sender_name": str(message["sender_name"])[:60]} if message.get("sender_name") else {}),
                }
            )
        if not messages:
            raise ValueError("no messages")
        return {
            "session_id": _session_for(scope, body.get("session_id")),
            "async_mode": bool(body.get("async_mode", True)),
            "messages": messages[:20],
        }
    if operation == "flush":
        return {"session_id": _session_for(scope, body.get("session_id"))}
    if operation == "search":
        out: dict[str, Any] = {
            "query": str(body.get("query") or "")[:2000],
            "user_id": scope,
            "method": "hybrid",
            "top_k": max(1, min(int(body.get("top_k") or 5), MAX_SEARCH_TOP_K)),
        }
        if body.get("include_profile"):
            out["include_profile"] = True
        filters = body.get("filters")
        if isinstance(filters, dict) and filters.get("session_id"):
            out["filters"] = {"session_id": _session_for(scope, filters["session_id"])}
        return out
    memory_type = str(body.get("memory_type") or "episode")
    return {
        "memory_type": memory_type if memory_type in {"episode", "profile"} else "episode",
        "user_id": scope,
        "page": max(1, int(body.get("page") or 1)),
        "page_size": max(1, min(int(body.get("page_size") or 20), MAX_PAGE_SIZE)),
    }


async def call_everos(operation: str, body: dict[str, Any]) -> httpx.Response:
    url, key = server_settings()
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        return await client.post(
            f"{url}/api/v2/memory/{operation}",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )


async def overview(store: HostedMemoryStore, email: str) -> dict[str, Any]:
    """What the AI remembers about this user: profile plus recent episodes."""
    scope = store.scope(email)
    result: dict[str, Any] = {"profile": [], "episodes": []}
    if not server_settings()[1]:
        return result
    try:
        profile = await call_everos("get", rewrite_gateway_request("get", {"memory_type": "profile"}, scope))
        episodes = await call_everos(
            "get", rewrite_gateway_request("get", {"memory_type": "episode", "page_size": 20}, scope)
        )
    except httpx.HTTPError as exc:
        logger.warning("hosted memory overview failed: %s", exc)
        result["error"] = "暂时读取不到记忆，请稍后再试。"
        return result
    result["profile"] = _profile_lines(profile)
    result["episodes"] = _episode_items(episodes)
    return result


def _data(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        return {}
    try:
        body = response.json()
    except ValueError:
        return {}
    data = body.get("data") or body.get("result") or {}
    return data if isinstance(data, dict) else {}


def _profile_lines(response: httpx.Response) -> list[str]:
    data = _data(response)
    lines: list[str] = []
    for profile in data.get("profiles") or ([data["profile_data"]] if data.get("profile_data") else []):
        if isinstance(profile, dict):
            source = profile.get("profile_data") if isinstance(profile.get("profile_data"), dict) else profile
            for key, value in source.items():
                if key in {"user_id", "id", "created_at", "updated_at"} or value in (None, "", [], {}):
                    continue
                text = "、".join(str(v) for v in value) if isinstance(value, list) else str(value)
                lines.append(f"{key}: {text}"[:300])
        elif profile:
            lines.append(str(profile)[:300])
    return lines[:30]


def _episode_items(response: httpx.Response) -> list[dict[str, Any]]:
    data = _data(response)
    items = []
    for episode in data.get("episodes") or data.get("memories") or []:
        if not isinstance(episode, dict):
            continue
        text = episode.get("summary") or episode.get("episode") or episode.get("content") or episode.get("title")
        if not text:
            continue
        stamp = episode.get("timestamp") or episode.get("created_at") or episode.get("updated_at")
        items.append({"id": str(episode.get("id") or episode.get("episode_id") or ""), "text": str(text)[:500], "at": stamp})
    return items


async def clear(store: HostedMemoryStore, email: str) -> int:
    """Delete everything EverOS holds for this user. Raises on failure."""
    response = await call_everos("delete", {"user_id": store.scope(email)})
    if response.status_code != 200:
        raise RuntimeError(f"EverOS delete failed ({response.status_code})")
    data = _data(response)
    return int(data.get("count") or data.get("deleted") or 0)


hosted_memory_store = HostedMemoryStore()
