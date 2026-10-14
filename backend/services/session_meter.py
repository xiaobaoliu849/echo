"""Wall-clock metering for one hosted realtime call.

The meter runs beside the provider session. Every tick it charges the time
elapsed since the previous tick (times the model's multiplier), tells the
client the remaining balance, and closes the socket when the balance is
exhausted, the line has been idle too long, or the call hit its length cap.

Idle detection is provider-agnostic: it watches what the backend *sends* to
the client. Any transcript, assistant text or binary audio counts as
conversation; heartbeats and status frames do not. Providers stop sending
those as soon as nobody is talking, which is exactly when the upstream meter
keeps running for nothing.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from typing import Any

from fastapi import WebSocket

from .billing_service import BillingService

logger = logging.getLogger(__name__)

ACTIVITY_EVENT_TYPES = frozenset(
    {
        "assistant_text",
        "assistant_audio",
        "user_transcript",
        "user_transcript_preview",
        "speech_started",
        "turn_complete",
    }
)
_TYPE_RE = re.compile(r'"type"\s*:\s*"([A-Za-z0-9_.]+)"')


class SessionMeter:
    def __init__(
        self,
        websocket: WebSocket,
        *,
        billing: BillingService,
        user_email: str,
        provider: str,
        model: str,
        multiplier: float,
        idle_timeout: int,
        warning_threshold: int,
        max_session: int,
        tick_seconds: float = 5.0,
    ) -> None:
        self._ws = websocket
        self._billing = billing
        self._user = user_email
        self._provider = provider
        self._model = model
        self._multiplier = multiplier
        self._idle_timeout = idle_timeout
        self._warning_threshold = warning_threshold
        self._max_session = max_session
        self._tick = tick_seconds
        self._started = time.monotonic()
        self._last_charged = self._started
        self._last_activity = self._started
        self._carry = 0.0  # sub-second remainder, so short ticks are not lost
        self._billed_total = 0
        self._warned = False
        self.end_reason = ""
        self._install_send_hook()

    # ── activity tracking ────────────────────────────────────────────────

    def _install_send_hook(self) -> None:
        original_send = self._ws.send

        async def metered_send(message: Any) -> None:
            self._observe(message)
            await original_send(message)

        # Every send_json/send_text/send_bytes funnels through ``send``.
        self._ws.send = metered_send  # type: ignore[method-assign]

    def _observe(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        if message.get("bytes") is not None:
            self._last_activity = time.monotonic()
            return
        text = message.get("text")
        if not isinstance(text, str):
            return
        match = _TYPE_RE.search(text[:200])
        if match and match.group(1) in ACTIVITY_EVENT_TYPES:
            self._last_activity = time.monotonic()

    # ── charging ─────────────────────────────────────────────────────────

    def _charge_elapsed(self, *, final: bool = False) -> int:
        now = time.monotonic()
        wall = now - self._last_charged
        self._last_charged = now
        billed_exact = wall * self._multiplier + self._carry
        # Ticks bill whole seconds and carry the fraction forward; the final
        # charge rounds the leftover up so every call costs at least 1s.
        billed = math.ceil(billed_exact) if final else int(billed_exact)
        if final and self._billed_total == 0:
            billed = max(1, billed)  # a connected call opened an upstream session
        self._carry = 0.0 if final else billed_exact - billed
        self._billed_total += billed
        return self._billing.charge(
            self._user,
            billed,
            wall_seconds=int(round(wall)),
            provider=self._provider,
            model=self._model,
        )

    async def _notify(self, payload: dict[str, Any]) -> None:
        try:
            await self._ws.send_json(payload)
        except Exception:
            pass

    async def _hang_up(self, reason: str, message: str) -> None:
        self.end_reason = reason
        logger.info("hosted_session_end user=%s reason=%s", self._user, reason)
        await self._notify({"type": "billing_end", "reason": reason, "message": message})
        await asyncio.sleep(0.2)
        try:
            await self._ws.close(code=4402 if reason == "balance_exhausted" else 4408)
        except Exception:
            pass

    async def run(self) -> None:
        balance = self._billing.get_balance(self._user)
        await self._notify({"type": "billing", "remaining_seconds": balance})
        while True:
            await asyncio.sleep(self._tick)
            # SQLite writes are short but can wait on busy_timeout; keep them
            # off the event loop that is relaying live audio.
            balance = await asyncio.to_thread(self._charge_elapsed)
            await self._notify({"type": "billing", "remaining_seconds": balance})
            if balance <= 0:
                await self._hang_up("balance_exhausted", "时长已用完，请联系管理员充值。")
                return
            if not self._warned and balance <= self._warning_threshold:
                self._warned = True
                await self._notify(
                    {
                        "type": "billing_warning",
                        "remaining_seconds": balance,
                        "message": f"剩余时长不足 {math.ceil(balance / 60)} 分钟。",
                    }
                )
            now = time.monotonic()
            if now - self._last_activity >= self._idle_timeout:
                await self._hang_up("idle", "长时间没有说话，已自动挂断以节省时长。")
                return
            if now - self._started >= self._max_session:
                await self._hang_up(
                    "max_session",
                    f"单次通话已达 {self._max_session // 60} 分钟上限，请重新开始通话。",
                )
                return

    def finalize(self) -> int:
        """Charge the tail since the last tick. Call once after the session ends."""
        try:
            return self._charge_elapsed(final=True)
        except Exception:
            logger.exception("hosted_session_final_charge_failed user=%s", self._user)
            return -1
