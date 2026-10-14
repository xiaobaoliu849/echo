from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from main import create_app
from routers import auth as auth_router
from routers import billing as billing_router
from routers import voice_chat as voice_chat_router
from services import api_auth_guard
from services.billing_service import BillingService
from services.config_loader import BackendConfig
from services.session_meter import SessionMeter
from services.user_auth_service import AuthRateLimiter, UserAuthService

ADMIN = ("boss@echo.local", "admin-pass")
USER = ("1203@echo.local", "user-pass")


class BillingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.billing = BillingService(db_path=Path(self._tmp.name) / "b.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_grant_charge_and_ledger(self) -> None:
        self.assertEqual(self.billing.grant("A@x", 600), 600)
        self.assertEqual(
            self.billing.charge("a@x", 90, wall_seconds=45, provider="Vercel", model="m"), 510
        )
        [row] = self.billing.usage_summary()
        self.assertEqual(row["balance_seconds"], 510)
        self.assertEqual(row["used_seconds"], 45)
        self.assertEqual(self.billing.usage_by_model()[0]["wall_seconds"], 45)

    def test_usage_never_goes_negative(self) -> None:
        self.billing.grant("a@x", 10)
        self.assertEqual(self.billing.charge("a@x", 50, wall_seconds=50, provider="p", model="m"), 0)

    def test_zero_grant_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.billing.grant("a@x", 0)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed_code: int | None = None

    async def send(self, message: Any) -> None:
        pass

    async def send_json(self, data: dict[str, Any]) -> None:
        import json

        await self.send({"type": "websocket.send", "text": json.dumps(data)})
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


class SessionMeterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.billing = BillingService(db_path=Path(self._tmp.name) / "b.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _meter(self, ws: _FakeWebSocket, **overrides: Any) -> SessionMeter:
        options: dict[str, Any] = dict(
            billing=self.billing,
            user_email="u@x",
            provider="Vercel",
            model="m",
            multiplier=1.0,
            idle_timeout=60,
            warning_threshold=0,
            max_session=3600,
            tick_seconds=0.05,
        )
        options.update(overrides)
        return SessionMeter(ws, **options)  # type: ignore[arg-type]

    def test_hangs_up_when_balance_runs_out(self) -> None:
        self.billing.grant("u@x", 1)
        ws = _FakeWebSocket()
        meter = self._meter(ws, multiplier=100.0)
        asyncio.run(asyncio.wait_for(meter.run(), 2))
        self.assertEqual(meter.end_reason, "balance_exhausted")
        self.assertEqual(ws.closed_code, 4402)
        self.assertEqual(self.billing.get_balance("u@x"), 0)
        self.assertEqual(ws.sent[-1]["type"], "billing_end")

    def test_idle_line_is_hung_up(self) -> None:
        self.billing.grant("u@x", 600)
        ws = _FakeWebSocket()
        meter = self._meter(ws, idle_timeout=0)
        asyncio.run(asyncio.wait_for(meter.run(), 2))
        self.assertEqual(meter.end_reason, "idle")
        self.assertEqual(ws.closed_code, 4408)

    def test_conversation_events_keep_the_line_open(self) -> None:
        self.billing.grant("u@x", 600)
        ws = _FakeWebSocket()
        meter = self._meter(ws, idle_timeout=1)

        async def scenario() -> None:
            task = asyncio.create_task(meter.run())
            for _ in range(8):
                await asyncio.sleep(0.2)
                # Starlette's send_json uses compact separators.
                await ws.send({"type": "websocket.send", "text": '{"type":"assistant_text","text":"hi"}'})
            self.assertFalse(task.done())
            task.cancel()

        asyncio.run(scenario())
        self.assertEqual(meter.end_reason, "")

    def test_status_frames_do_not_count_as_activity(self) -> None:
        ws = _FakeWebSocket()
        meter = self._meter(ws)
        meter._last_activity = before = 0.0
        meter._observe({"type": "websocket.send", "text": '{"type":"billing","remaining_seconds":5}'})
        self.assertEqual(meter._last_activity, before)
        meter._observe({"type": "websocket.send", "bytes": b"\x00\x01"})
        self.assertGreater(meter._last_activity, before)

    def test_max_session_cap(self) -> None:
        self.billing.grant("u@x", 600)
        ws = _FakeWebSocket()
        meter = self._meter(ws, max_session=0)
        meter._last_activity = float("inf")  # never idle
        asyncio.run(asyncio.wait_for(meter.run(), 2))
        self.assertEqual(meter.end_reason, "max_session")


class HostedApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.users = UserAuthService(db_path=tmp / "auth.db")
        self.billing = BillingService(db_path=tmp / "billing.db")
        self.users.register_user(*ADMIN)  # first account = admin
        self.users.register_user(*USER)
        self._patches = [
            patch.dict(
                os.environ,
                {
                    "ECHO_HOSTED_MODE": "1",
                    "ECHO_API_TOKEN": "",
                    "ECHO_ADMIN_TOKEN": "",
                    "VOICESPIRIT_API_TOKEN": "",
                    "VOICESPIRIT_ADMIN_TOKEN": "",
                },
            ),
            patch.object(api_auth_guard, "user_auth_service", self.users),
            patch.object(api_auth_guard, "_read_token_from_config", return_value=""),
            patch.object(api_auth_guard, "resolve_admin_token", return_value=""),
            patch.object(auth_router, "user_auth_service", self.users),
            patch.object(auth_router, "auth_rate_limiter", AuthRateLimiter()),
            patch.object(billing_router, "user_auth_service", self.users),
            patch.object(billing_router, "billing_service", self.billing),
            patch.object(voice_chat_router, "billing_service", self.billing),
        ]
        for p in self._patches:
            p.start()
        self.app = create_app()
        self.admin_token = self.users.create_access_token(self.users.authenticate_user(*ADMIN))
        self.user_token = self.users.create_access_token(self.users.authenticate_user(*USER))

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _request(self, method: str, path: str, token: str | None = None, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async def run() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, headers=headers, **kwargs)

        return asyncio.run(run())

    # ── HTTP gate ────────────────────────────────────────────────────────

    def test_non_coach_routes_are_blocked_even_for_admin(self) -> None:
        for path in ("/api/settings/", "/api/tts/voices", "/api/learning/phrases", "/api/evermem/memories"):
            self.assertEqual(self._request("GET", path, self.admin_token).status_code, 404, path)
        self.assertEqual(self._request("POST", "/api/chat/completions", self.user_token, json={}).status_code, 404)

    def test_api_docs_are_hidden(self) -> None:
        self.assertEqual(self._request("GET", "/docs").status_code, 404)
        self.assertEqual(self._request("GET", "/openapi.json").status_code, 404)

    def test_login_with_short_account_name(self) -> None:
        response = self._request("POST", "/api/auth/login", json={"email": "1203", "password": USER[1]})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["access_token"])

    def test_public_registration_is_closed(self) -> None:
        response = self._request(
            "POST", "/api/auth/register", self.user_token, json={"email": "x@y.z", "password": "123456"}
        )
        self.assertEqual(response.status_code, 403)

    def test_balance_requires_login(self) -> None:
        self.assertEqual(self._request("GET", "/api/billing/me").status_code, 401)
        self.billing.grant(USER[0], 300)
        response = self._request("GET", "/api/billing/me", self.user_token)
        self.assertEqual(response.json(), {"account": "1203", "remaining_seconds": 300})

    def test_hosted_info_is_public(self) -> None:
        body = self._request("GET", "/api/billing/hosted-info").json()
        self.assertTrue(body["hosted"])
        self.assertIn("Vercel", [p["provider"] for p in body["providers"]])

    def test_admin_routes_need_admin(self) -> None:
        self.assertEqual(self._request("GET", "/api/billing/admin/users", self.user_token).status_code, 403)
        response = self._request(
            "POST",
            "/api/billing/admin/users",
            self.admin_token,
            json={"account": "1501", "password": "secret1", "minutes": 300},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["remaining_seconds"], 18000)
        response = self._request(
            "POST", "/api/billing/admin/grant", self.admin_token, json={"account": "1501", "minutes": 60}
        )
        self.assertEqual(response.json()["remaining_seconds"], 21600)
        listing = self._request("GET", "/api/billing/admin/users", self.admin_token).json()
        self.assertIn("1501", [u["account"] for u in listing["users"]])

    def test_disabled_account_loses_access(self) -> None:
        self._request("POST", "/api/billing/admin/active", self.admin_token, json={"account": "1203", "active": False})
        self.assertEqual(self._request("GET", "/api/billing/me", self.user_token).status_code, 403)

    # ── WebSocket gate ───────────────────────────────────────────────────

    def test_other_websockets_are_refused(self) -> None:
        client = TestClient(self.app)
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/transcription/realtime?token={self.user_token}") as ws:
                ws.receive_json()

    def test_voice_ws_requires_token_even_from_loopback(self) -> None:
        client = TestClient(self.app)
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect("/api/voice-chat/ws?provider=Vercel") as ws:
                ws.receive_json()

    def test_voice_ws_rejects_unsold_model(self) -> None:
        self.billing.grant(USER[0], 600)
        client = TestClient(self.app)
        with client.websocket_connect(
            f"/api/voice-chat/ws?provider=Vercel&model=openai/gpt-realtime-2&token={self.user_token}"
        ) as ws:
            self.assertIn("不支持", ws.receive_json()["message"])

    def test_voice_ws_rejects_empty_balance(self) -> None:
        client = TestClient(self.app)
        with client.websocket_connect(f"/api/voice-chat/ws?provider=Vercel&token={self.user_token}") as ws:
            self.assertIn("时长已用完", ws.receive_json()["message"])

    def test_voice_ws_meters_a_call(self) -> None:
        self.billing.grant(USER[0], 600)
        captured: dict[str, Any] = {}

        async def fake_session(websocket: Any, model: str | None = None, voice: str | None = None) -> None:
            captured["model"] = model
            await websocket.send_json({"type": "assistant_text", "text": "Hello!"})
            await asyncio.sleep(0.1)

        original_get_setting = BackendConfig.get_setting
        with patch.object(
            voice_chat_router.voice_chat_service, "stream_vercel_session", AsyncMock(side_effect=fake_session)
        ), patch.object(
            BackendConfig,
            "get_setting",
            lambda self, key, default="": "key" if key == "vercel_api_key" else original_get_setting(self, key, default),
        ):
            client = TestClient(self.app)
            with client.websocket_connect(f"/api/voice-chat/ws?provider=Vercel&token={self.user_token}") as ws:
                first = ws.receive_json()
                second = ws.receive_json()
        # A blank model is pinned to the first sold Gemini model, never the
        # provider's own default.
        self.assertEqual(captured["model"], "google/gemini-3.8-live")
        types = {first["type"], second["type"]}
        self.assertEqual(types, {"billing", "assistant_text"})
        # The handler bills the tail after the socket closes; give it a moment.
        import time

        deadline = time.monotonic() + 3
        ledger = self.billing.usage_by_model()
        while not ledger and time.monotonic() < deadline:
            time.sleep(0.05)
            ledger = self.billing.usage_by_model()
        self.assertEqual(ledger[0]["model"], "google/gemini-3.8-live")
        self.assertLess(self.billing.get_balance(USER[0]), 600)


if __name__ == "__main__":
    unittest.main()
