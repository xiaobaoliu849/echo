"""Transparent Gemini Live reconnection across server GoAway / lifetime limits.

A Gemini Live WebSocket has a fixed lifetime. Shortly before it ends the
server sends ``go_away`` (with ``time_left``) and then closes with
``1000 GoAway deadline exceeded``. When session resumption is enabled the
server also streams ``session_resumption_update`` messages carrying a handle
that a new connection can pass to continue the same conversation.

``ResumableGoogleLiveSession`` wraps the SDK session behind the same duck-typed
surface the provider loops already use (``receive`` / ``send_*`` / ``close``)
and swaps the underlying connection when the old one is about to expire or has
just been closed by the server, so the browser socket stays open.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import Any, AsyncIterator, Callable

logger = logging.getLogger(__name__)

try:
    from websockets import ConnectionClosed as _WsConnectionClosed
except ImportError:  # pragma: no cover
    _WsConnectionClosed = None

try:
    from google.genai import errors as _genai_errors
except ImportError:  # pragma: no cover
    _genai_errors = None

# Normal / going-away closes are what the server uses at the end of a
# connection's lifetime; 1006 is a dropped connection with no close frame.
# Policy errors (1008) or bad requests must surface.
_RESUMABLE_CLOSE_CODES = {1000, 1001, 1006}
_MAX_RECONNECTS_PER_WINDOW = 3
_RECONNECT_WINDOW_SECONDS = 60.0


def is_google_live_connection_end(exc: BaseException) -> bool:
    """True when ``exc`` is the server ending the connection (not an error)."""
    if "goaway" in str(exc).replace(" ", "").lower():
        return True
    if _WsConnectionClosed is not None and isinstance(exc, _WsConnectionClosed):
        rcvd = getattr(exc, "rcvd", None)
        return rcvd is None or rcvd.code in _RESUMABLE_CLOSE_CODES
    if _genai_errors is not None and isinstance(exc, _genai_errors.APIError):
        return getattr(exc, "code", None) in _RESUMABLE_CLOSE_CODES
    return False


def _rejects_resumption_config(exc: BaseException) -> bool:
    text = str(exc).lower().replace("_", "").replace(" ", "")
    return any(key in text for key in ("sessionresumption", "contextwindowcompression", "slidingwindow"))


class ResumableGoogleLiveSession:
    """Async context manager yielding a session that survives GoAway closes.

    ``connect(handle)`` must return an async context manager for a new SDK
    live session, configured with ``SessionResumptionConfig(handle=handle)``
    (``handle`` is ``None`` for the first connection). If the endpoint rejects
    the resumption settings at setup, ``fallback_connect()`` opens a plain
    session instead so chat still works (just without auto-resume).
    """

    def __init__(
        self,
        connect: Callable[[str | None], Any],
        fallback_connect: Callable[[], Any] | None = None,
    ) -> None:
        self._connect = connect
        self._fallback_connect = fallback_connect
        self._cm: Any = None
        self._session: Any = None
        self._generation = 0
        self._handle: str | None = None
        self._resumable = False
        self._go_away = False
        self._closed = False
        self._lock = asyncio.Lock()
        self._reconnect_times: list[float] = []

    @property
    def resumption_handle(self) -> str | None:
        return self._handle

    async def __aenter__(self) -> "ResumableGoogleLiveSession":
        try:
            self._cm, self._session = await self._enter(self._connect(None))
        except Exception as exc:
            if self._fallback_connect is None or not _rejects_resumption_config(exc):
                raise
            logger.warning("google_live_resumption_unsupported, connecting without it: %s", exc)
            self._cm, self._session = await self._enter(self._fallback_connect())
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self._closed = True
        cm, self._cm, self._session = self._cm, None, None
        await self._exit(cm)

    @staticmethod
    async def _enter(cm: Any) -> tuple[Any, Any]:
        return cm, await cm.__aenter__()

    @staticmethod
    async def _exit(cm: Any) -> None:
        if cm is not None:
            with suppress(Exception):
                await cm.__aexit__(None, None, None)

    async def _reconnect(self, generation: int, reason: str) -> bool:
        """Replace the connection seen as ``generation``; True if one is live."""
        async with self._lock:
            if self._generation != generation:
                return self._session is not None
            if self._closed or not self._handle:
                return False
            now = time.monotonic()
            self._reconnect_times = [t for t in self._reconnect_times if now - t < _RECONNECT_WINDOW_SECONDS]
            if len(self._reconnect_times) >= _MAX_RECONNECTS_PER_WINDOW:
                logger.warning("google_live_resume_gave_up: too many reconnects reason=%s", reason)
                return False
            self._reconnect_times.append(now)
            # Make before break: the old connection may still be serving the
            # tail of its lifetime, and keeps working if the new one fails.
            try:
                new_cm, new_session = await self._enter(self._connect(self._handle))
            except Exception:
                logger.exception("google_live_resume_failed reason=%s", reason)
                return False
            old_cm = self._cm
            self._cm, self._session = new_cm, new_session
            self._resumable = False
            self._go_away = False
            self._generation += 1
            logger.info("google_live_resumed reason=%s generation=%s", reason, self._generation)
        # Closing waits for the close handshake; don't block other callers.
        await self._exit(old_cm)
        return True

    def _note_server_message(self, message: Any) -> None:
        update = getattr(message, "session_resumption_update", None)
        if update is not None:
            new_handle = getattr(update, "new_handle", None)
            # Only a fresh handle marks *now* as a safe point; an older handle
            # would resume from an earlier checkpoint and drop recent context.
            self._resumable = bool(getattr(update, "resumable", False) and new_handle)
            if self._resumable:
                self._handle = new_handle
        go_away = getattr(message, "go_away", None)
        if go_away is not None and not self._go_away:
            self._go_away = True
            logger.info(
                "google_live_go_away time_left=%s has_handle=%s",
                getattr(go_away, "time_left", None),
                bool(self._handle),
            )

    async def receive(self) -> AsyncIterator[Any]:
        """One model turn, like the SDK; ends early when the connection is swapped."""
        generation, session = self._generation, self._session
        if session is None:
            return
        stream = session.receive()
        try:
            async for message in stream:
                self._note_server_message(message)
                yield message
                # Resume at a point the server marked resumable rather than
                # waiting for the hard close, which would cut off a reply.
                if self._go_away and self._resumable and self._handle:
                    if await self._reconnect(generation, "go_away"):
                        return
        except Exception as exc:
            if not is_google_live_connection_end(exc):
                raise
            if not await self._reconnect(generation, f"closed: {exc}"):
                raise
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                with suppress(Exception):
                    await aclose()

    async def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        generation, session = self._generation, self._session
        if session is None:
            raise RuntimeError("Google Live session is closed.")
        try:
            return await getattr(session, name)(*args, **kwargs)
        except Exception as exc:
            if not is_google_live_connection_end(exc):
                raise
            if not await self._reconnect(generation, f"send failed: {exc}"):
                raise
        return await getattr(self._session, name)(*args, **kwargs)

    async def send_realtime_input(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call("send_realtime_input", *args, **kwargs)

    async def send_client_content(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call("send_client_content", *args, **kwargs)

    async def send_tool_response(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call("send_tool_response", *args, **kwargs)

    async def send(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call("send", *args, **kwargs)

    async def close(self) -> None:
        self._closed = True
        session = self._session
        if session is not None:
            await session.close()
