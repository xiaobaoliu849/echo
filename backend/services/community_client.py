"""Community client mode: a local backend that defers to a hosted Echo server.

Set ``ECHO_COMMUNITY_SERVER=https://host:port`` (and ``ECHO_COMMUNITY_CA`` to
the server's self-signed certificate) on a neighbour's machine. The local
backend then:

* forwards login and balance requests to the hosted server, which owns the
  accounts and minutes;
* for a call, asks the server for a short-lived provider client secret and
  connects to the provider *from this machine's own network* — the
  operator's key never leaves the server and the audio never crosses it;
* reports a heartbeat every few seconds; the server bills by its own clock
  and tells us when to hang up.
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import time
from typing import Any

import httpx
from fastapi import WebSocket

from .session_meter import install_activity_hook

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


def community_server_url() -> str:
    return os.getenv("ECHO_COMMUNITY_SERVER", "").strip().rstrip("/")


def is_community_client() -> bool:
    return bool(community_server_url())


def _verify() -> ssl.SSLContext | bool:
    ca_file = os.getenv("ECHO_COMMUNITY_CA", "").strip()
    if ca_file:
        # The server's own self-signed certificate is the only trust anchor.
        return ssl.create_default_context(cafile=ca_file)
    return True


class CommunityServerError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


async def forward(method: str, path: str, *, token: str = "", json: Any = None, client_id: str = "") -> Any:
    """Call the hosted server and return its JSON, raising on HTTP errors."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if client_id:
        headers["X-Client-ID"] = client_id
    async with httpx.AsyncClient(verify=_verify(), timeout=REQUEST_TIMEOUT) as client:
        try:
            response = await client.request(method, f"{community_server_url()}{path}", headers=headers, json=json)
        except httpx.HTTPError as exc:
            raise CommunityServerError(
                503, {"code": "COMMUNITY_SERVER_UNREACHABLE", "message": "连接服务器失败，请检查网络。", "meta": {}}
            ) from exc
    try:
        body = response.json()
    except ValueError:
        body = {"detail": {"code": "COMMUNITY_SERVER_ERROR", "message": response.text[:200], "meta": {}}}
    if response.status_code >= 400:
        raise CommunityServerError(response.status_code, body.get("detail", body) if isinstance(body, dict) else body)
    return body


class CommunityCallMeter:
    """Heartbeats one direct call to the hosted server and obeys its verdicts."""

    def __init__(self, websocket: WebSocket, *, token: str, call_id: str, heartbeat_seconds: float) -> None:
        self._ws = websocket
        self._token = token
        self._call_id = call_id
        self._interval = max(1.0, float(heartbeat_seconds))
        self._active = False
        self._failures = 0
        self.end_reason = ""
        install_activity_hook(websocket, self._touch)

    def _touch(self) -> None:
        self._active = True

    async def _beat(self, *, final: bool) -> dict[str, Any]:
        active, self._active = self._active, False
        return await forward(
            "POST",
            "/api/billing/direct/heartbeat",
            token=self._token,
            json={"call_id": self._call_id, "active": active, "final": final},
        )

    async def _notify(self, payload: dict[str, Any]) -> None:
        try:
            await self._ws.send_json(payload)
        except Exception:
            pass

    async def _hang_up(self, reason: str, message: str) -> None:
        self.end_reason = reason
        await self._notify({"type": "billing_end", "reason": reason, "message": message})
        await asyncio.sleep(0.2)
        try:
            await self._ws.close(code=4402 if reason == "balance_exhausted" else 4408)
        except Exception:
            pass

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                verdict = await self._beat(final=False)
                self._failures = 0
            except CommunityServerError as exc:
                self._failures += 1
                logger.warning("community heartbeat failed (%d): %s", self._failures, exc)
                # The server reaps calls it has not heard from for a minute;
                # stop before that rather than talk on unbilled.
                if self._failures * self._interval >= 45:
                    await self._hang_up("server_unreachable", "与服务器的连接中断，通话已结束。")
                    return
                continue
            await self._notify({"type": "billing", "remaining_seconds": int(verdict.get("remaining_seconds", 0))})
            if verdict.get("stop"):
                await self._hang_up(str(verdict.get("reason") or "stopped"), str(verdict.get("message") or "通话已结束。"))
                return

    async def finalize(self) -> None:
        try:
            await asyncio.wait_for(self._beat(final=True), timeout=10)
        except Exception as exc:
            # The server settles unreported calls itself when it reaps them.
            logger.warning("community final heartbeat failed: %s", exc)


async def start_direct_call(token: str, provider: str, model: str | None) -> dict[str, Any]:
    started = time.monotonic()
    result = await forward("POST", "/api/billing/direct/start", token=token, json={"provider": provider, "model": model or ""})
    logger.info("community direct call authorised in %.0f ms", (time.monotonic() - started) * 1000)
    return result
