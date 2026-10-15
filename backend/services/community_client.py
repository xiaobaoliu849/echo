"""Community client mode: a local backend that defers to a hosted Echo server.

Set ``ECHO_COMMUNITY_SERVER=https://host:port`` (and ``ECHO_COMMUNITY_CA`` to
the server's self-signed certificate) on a neighbour's machine. The local
backend then:

* forwards login and balance requests to the hosted server, which owns the
  accounts and minutes;
* for a Gemini (Vercel) call, asks the server for a short-lived provider
  client secret and connects to the provider *from this machine's own
  network* — the operator's key never leaves the server and the audio never
  crosses it; a heartbeat every few seconds lets the server bill by its own
  clock and tell us when to hang up;
* providers that cannot mint client secrets (Qwen Omni, Doubao) are
  *relayed*: the call is piped to the hosted server's own voice socket,
  which talks to the provider and meters the call. Both are mainland
  services, so the extra hop through the (mainland) server costs little.
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

# Calls that go direct from this machine (the server mints a client secret)
# and calls piped through the hosted server.
DIRECT_PROVIDERS = frozenset({"Vercel"})
RELAY_PROVIDERS = frozenset({"DashScope", "Doubao"})


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


def _relay_url(query: str) -> str:
    base = community_server_url()
    base = "wss://" + base[len("https://"):] if base.startswith("https://") else base.replace("http://", "ws://", 1)
    return f"{base}/api/voice-chat/ws?{query}"


async def relay_call(websocket: WebSocket, query: str) -> None:
    """Pipe an accepted client socket to the hosted server's voice socket.

    ``query`` is the client's own query string (provider, model, voice and
    the user's server token); the server authenticates, meters and hangs up
    exactly as for a browser on the hosted site. Its close code (e.g. 4402
    for an empty balance) is passed back so the app shows the same reasons.
    """
    import websockets

    url = _relay_url(query)
    tls: dict[str, Any] = {}
    if url.startswith("wss://"):
        # ssl= is refused for a plain ws:// URL, so only pass it for TLS.
        verify = _verify()
        tls["ssl"] = verify if isinstance(verify, ssl.SSLContext) else ssl.create_default_context()
    try:
        upstream = await websockets.connect(
            url,
            **tls,
            proxy=None,  # the server is in the mainland; never route it via a local proxy
            max_size=2**24,
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
        )
    except Exception as exc:
        logger.warning("community relay connect failed: %s", exc)
        # The server refuses the handshake (403) for a stale or revoked token.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        message = "登录已失效，请退出后重新登录。" if status in (401, 403) else "连接服务器失败，请检查网络后重试。"
        try:
            await websocket.send_json({"type": "error", "message": message})
            await websocket.close(code=1011)
        except Exception:
            pass
        return

    client_gone = False

    async def client_to_server() -> None:
        nonlocal client_gone
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                client_gone = True
                return
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])

    async def server_to_client() -> None:
        async for data in upstream:
            if isinstance(data, str):
                await websocket.send_text(data)
            else:
                await websocket.send_bytes(data)

    tasks = [asyncio.create_task(client_to_server()), asyncio.create_task(server_to_client())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            # Hanging up here ends the server-side call, which settles billing.
            await upstream.close()
        except Exception:
            pass
    if not client_gone:
        code = getattr(upstream, "close_code", None) or 1000
        if code in (1005, 1006) or not 1000 <= code < 5000:
            code = 1011
        try:
            await websocket.close(code=code)
        except Exception:
            pass
