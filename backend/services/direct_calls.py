"""Server side of *direct* hosted calls.

In a direct call the user's own machine talks to the realtime provider over
its own network; this server only authorises the call (a short-lived
provider client secret, minted with the operator's key) and bills it.

Billing uses this server's clock, never the client's: each heartbeat charges
the time since the previous charge. A client that stops heartbeating is
reaped after ``STALE_AFTER_SECONDS`` and billed up to its last sign of life
plus one heartbeat interval. The provider session itself runs outside our
reach, so a modified client could keep talking after it stops heartbeating —
that is the accepted trade-off of direct calls (reconcile against the
provider dashboard).
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from dataclasses import dataclass, field

from .billing_service import BillingService

HEARTBEAT_SECONDS = 15
STALE_AFTER_SECONDS = 60
MAX_STARTS_PER_HOUR = 40


@dataclass
class DirectCall:
    call_id: str
    user_email: str
    provider: str
    model: str
    multiplier: float
    started: float
    last_charged: float
    last_seen: float
    last_activity: float
    carry: float = 0.0
    billed_total: int = 0


@dataclass
class HeartbeatResult:
    remaining_seconds: int
    stop: bool = False
    reason: str = ""
    message: str = ""


@dataclass
class DirectCallRegistry:
    billing: BillingService
    idle_timeout: int
    max_session: int
    clock: object = time.monotonic
    _calls: dict[str, DirectCall] = field(default_factory=dict)
    _starts: dict[str, list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _now(self) -> float:
        return self.clock()  # type: ignore[operator]

    def _charge(self, call: DirectCall, until: float, *, final: bool) -> int:
        wall = max(0.0, until - call.last_charged)
        call.last_charged = max(call.last_charged, until)
        exact = wall * call.multiplier + call.carry
        billed = math.ceil(exact) if final else int(exact)
        if final and call.billed_total == 0:
            billed = max(1, billed)  # an authorised call opened a provider session
        call.carry = 0.0 if final else exact - billed
        call.billed_total += billed
        return self.billing.charge(
            call.user_email, billed, wall_seconds=int(round(wall)), provider=call.provider, model=call.model
        )

    def reap_stale(self) -> None:
        now = self._now()
        with self._lock:
            stale = [c for c in self._calls.values() if now - c.last_seen > STALE_AFTER_SECONDS]
            for call in stale:
                self._calls.pop(call.call_id, None)
                self._charge(call, call.last_seen + HEARTBEAT_SECONDS, final=True)

    def start(self, user_email: str, *, provider: str, model: str, multiplier: float) -> DirectCall:
        """Register a call. Raises ValueError when the user may not start one."""
        self.reap_stale()
        now = self._now()
        with self._lock:
            recent = [t for t in self._starts.get(user_email, []) if now - t < 3600]
            if len(recent) >= MAX_STARTS_PER_HOUR:
                raise ValueError("通话次数过于频繁，请稍后再试。")
            if self.billing.get_balance(user_email) <= 0:
                raise ValueError("时长已用完，请联系管理员充值。")
            # One live call per account: a new call settles the previous one.
            for old in [c for c in self._calls.values() if c.user_email == user_email]:
                self._calls.pop(old.call_id, None)
                self._charge(old, now, final=True)
            recent.append(now)
            self._starts[user_email] = recent
            call = DirectCall(
                call_id=secrets.token_urlsafe(16),
                user_email=user_email,
                provider=provider,
                model=model,
                multiplier=multiplier,
                started=now,
                last_charged=now,
                last_seen=now,
                last_activity=now,
            )
            self._calls[call.call_id] = call
            return call

    def heartbeat(self, user_email: str, call_id: str, *, active: bool, final: bool) -> HeartbeatResult:
        self.reap_stale()
        now = self._now()
        with self._lock:
            call = self._calls.get(call_id)
            if call is None or call.user_email != user_email:
                return HeartbeatResult(
                    remaining_seconds=self.billing.get_balance(user_email),
                    stop=True,
                    reason="unknown_call",
                    message="通话已结束，请重新开始。",
                )
            call.last_seen = now
            if active:
                call.last_activity = now
            remaining = self._charge(call, now, final=final)
            if final:
                self._calls.pop(call_id, None)
                return HeartbeatResult(remaining_seconds=remaining, stop=True, reason="ended")
            stop = HeartbeatResult(remaining_seconds=remaining, stop=True)
            if remaining <= 0:
                stop.reason, stop.message = "balance_exhausted", "时长已用完，请联系管理员充值。"
            elif now - call.last_activity >= self.idle_timeout:
                stop.reason, stop.message = "idle", "长时间没有说话，已自动挂断以节省时长。"
            elif now - call.started >= self.max_session:
                stop.reason = "max_session"
                stop.message = f"单次通话已达 {self.max_session // 60} 分钟上限，请重新开始通话。"
            else:
                return HeartbeatResult(remaining_seconds=remaining)
            self._calls.pop(call_id, None)
            self._charge(call, now, final=True)
            stop.remaining_seconds = self.billing.get_balance(user_email)
            return stop

    def open_calls(self) -> int:
        with self._lock:
            return len(self._calls)
