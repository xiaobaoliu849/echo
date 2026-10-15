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

    def test_ticks_are_grouped_into_calls(self) -> None:
        self.billing.grant("a@x", 6000)
        clock = iter([1000, 1005, 1010, 1300, 1305, 1310])
        models = ["m", "m", "m", "m", "m", "other"]
        with patch("services.billing_service.time.time", side_effect=lambda: next(clock)):
            for model in models:
                self.billing.charge("a@x", 10, wall_seconds=5, provider="p", model=model)
        calls = self.billing.recent_calls("a@x")
        self.assertEqual([c["model"] for c in calls], ["other", "m", "m"])
        oldest = calls[-1]
        self.assertEqual((oldest["started_at"], oldest["ended_at"]), (995, 1010))
        self.assertEqual((oldest["wall_seconds"], oldest["billed_seconds"]), (15, 30))
        self.assertEqual(len(self.billing.recent_calls("a@x", limit=1)), 1)

    def test_daily_usage_uses_viewer_timezone(self) -> None:
        self.billing.grant("a@x", 6000, note="WeChat 49")
        # 2026-10-14 20:00 UTC is already 10-15 in UTC+8.
        with patch("services.billing_service.time.time", return_value=1792008000):
            self.billing.charge("a@x", 120, wall_seconds=60, provider="p", model="m")
            self.billing.charge("b@x", 0, wall_seconds=0, provider="p", model="m")
        self.assertEqual(self.billing.usage_by_day()[0]["day"], "2026-10-14")
        [day] = self.billing.usage_by_day(utc_offset_minutes=480)
        self.assertEqual(day, {"day": "2026-10-15", "wall_seconds": 60, "billed_seconds": 120, "users": 1})
        self.assertEqual(self.billing.usage_by_day(email="b@x"), [])
        [grant] = self.billing.grants("A@x")
        self.assertEqual((grant["delta_seconds"], grant["note"]), (6000, "WeChat 49"))


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

    def test_per_model_multipliers(self) -> None:
        from services import hosted_mode

        self.assertEqual(hosted_mode.resolve_billing_multiplier("Vercel", "google/gemini-3.8-live"), 1.0)
        self.assertEqual(
            hosted_mode.resolve_billing_multiplier("Vercel", "google/gemini-3.8-live-extended-thinking"), 1.5
        )
        self.assertEqual(hosted_mode.resolve_billing_multiplier("DashScope", "qwen3.8-omni-flash-realtime"), 0.5)
        self.assertIsNone(hosted_mode.resolve_billing_multiplier("Vercel", "unsold-model"))
        vercel = next(
            p for p in self._request("GET", "/api/billing/hosted-info").json()["providers"] if p["provider"] == "Vercel"
        )
        self.assertEqual(vercel["multipliers"]["google/gemini-3.8-live-extended-thinking"], 1.5)

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

    def test_admin_dashboard_and_user_detail(self) -> None:
        self.billing.grant(USER[0], 600, note="first top-up")
        self.billing.charge(USER[0], 90, wall_seconds=90, provider="Vercel", model="m")
        body = self._request("GET", "/api/billing/admin/users?days=7&tz=480", self.admin_token).json()
        self.assertEqual(body["daily"][0]["wall_seconds"], 90)
        self.assertEqual(body["live"], [])
        user = next(u for u in body["users"] if u["account"] == "1203")
        self.assertEqual((user["remaining_seconds"], user["used_seconds"]), (510, 90))
        self.assertTrue(user["created_at"])
        detail = self._request("GET", "/api/billing/admin/user-detail?account=1203", self.admin_token).json()
        self.assertEqual(detail["remaining_seconds"], 510)
        self.assertEqual(detail["grants"][0]["note"], "first top-up")
        self.assertEqual(detail["daily"][0]["billed_seconds"], 90)
        missing = self._request("GET", "/api/billing/admin/user-detail?account=nobody", self.admin_token)
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(
            self._request("GET", "/api/billing/admin/user-detail?account=1203", self.user_token).status_code, 403
        )

    def test_my_history(self) -> None:
        self.billing.grant(USER[0], 600, note="WeChat 49")
        self.billing.charge(USER[0], 60, wall_seconds=60, provider="Vercel", model="m")
        self.assertEqual(self._request("GET", "/api/billing/me/history").status_code, 401)
        body = self._request("GET", "/api/billing/me/history?days=7&tz=480", self.user_token).json()
        self.assertEqual(body["remaining_seconds"], 540)
        self.assertEqual(body["calls"][0]["wall_seconds"], 60)
        self.assertEqual(body["grants"][0]["note"], "WeChat 49")
        self.assertEqual(body["daily"][0]["billed_seconds"], 60)

    def test_renewal_info_is_set_by_admin(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir, patch.dict(os.environ, {"ECHO_DATA_DIR": data_dir}):
            self.assertEqual(self._request("GET", "/api/billing/renewal").status_code, 401)
            self.assertEqual(self._request("GET", "/api/billing/renewal", self.user_token).json(), {"text": "", "qr": ""})
            qr = "data:image/png;base64,iVBORw0KGgo="
            payload = {"text": "300 分钟 ¥49", "qr": qr}
            self.assertEqual(
                self._request("POST", "/api/billing/admin/renewal", self.user_token, json=payload).status_code, 403
            )
            saved = self._request("POST", "/api/billing/admin/renewal", self.admin_token, json=payload)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(self._request("GET", "/api/billing/renewal", self.user_token).json(), payload)
            bad = self._request(
                "POST", "/api/billing/admin/renewal", self.admin_token, json={"text": "", "qr": "javascript:alert(1)"}
            )
            self.assertEqual(bad.status_code, 400)

    def test_user_can_change_own_password(self) -> None:
        wrong = self._request(
            "POST", "/api/auth/change-password", self.user_token,
            json={"current_password": "nope", "new_password": "newpass1"},
        )
        self.assertEqual(wrong.status_code, 400)
        ok = self._request(
            "POST", "/api/auth/change-password", self.user_token,
            json={"current_password": USER[1], "new_password": "newpass1"},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(self._request("GET", "/api/billing/me", self.user_token).status_code, 200)
        login = self._request("POST", "/api/auth/login", json={"email": "1203", "password": "newpass1"})
        self.assertEqual(login.status_code, 200)

    def test_admin_cannot_be_disabled(self) -> None:
        response = self._request(
            "POST", "/api/billing/admin/active", self.admin_token, json={"account": "boss", "active": False}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._request("GET", "/api/billing/admin/users", self.admin_token).status_code, 200)

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

        async def fake_session(websocket: Any, model: str | None = None, voice: str | None = None, **_: Any) -> None:
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


class DirectCallRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        from services.direct_calls import DirectCallRegistry

        self._tmp = tempfile.TemporaryDirectory()
        self.billing = BillingService(db_path=Path(self._tmp.name) / "b.db")
        self.now = 1000.0
        self.reg = DirectCallRegistry(
            billing=self.billing, idle_timeout=60, max_session=1800, clock=lambda: self.now
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _start(self, multiplier: float = 1.0):
        return self.reg.start("u@x", provider="Vercel", model="m", multiplier=multiplier)

    def test_heartbeats_bill_server_time(self) -> None:
        self.billing.grant("u@x", 600)
        call = self._start()
        self.now += 15
        self.assertEqual(self.reg.heartbeat("u@x", call.call_id, active=True, final=False).remaining_seconds, 585)
        self.now += 15
        result = self.reg.heartbeat("u@x", call.call_id, active=True, final=True)
        self.assertTrue(result.stop)
        self.assertEqual(result.remaining_seconds, 570)
        self.assertEqual(self.reg.open_calls(), 0)

    def test_no_balance_no_call(self) -> None:
        with self.assertRaises(ValueError):
            self._start()

    def test_balance_runs_out_mid_call(self) -> None:
        self.billing.grant("u@x", 20)
        call = self._start(multiplier=2.0)
        self.now += 15
        result = self.reg.heartbeat("u@x", call.call_id, active=True, final=False)
        self.assertEqual((result.stop, result.reason, result.remaining_seconds), (True, "balance_exhausted", 0))

    def test_idle_call_is_stopped(self) -> None:
        self.billing.grant("u@x", 600)
        call = self._start()
        for _ in range(4):
            self.now += 15
            result = self.reg.heartbeat("u@x", call.call_id, active=False, final=False)
        self.assertEqual((result.stop, result.reason), (True, "idle"))

    def test_silent_client_is_reaped_and_billed(self) -> None:
        self.billing.grant("u@x", 600)
        self._start()
        self.now += 10  # last sign of life is the start itself
        self.now += 120  # then nothing: reaped on the next registry call
        self.reg.reap_stale()
        self.assertEqual(self.reg.open_calls(), 0)
        # Billed up to last_seen + one heartbeat interval, not the whole silence.
        self.assertEqual(self.billing.get_balance("u@x"), 600 - 15)

    def test_heartbeat_for_someone_elses_call_is_refused(self) -> None:
        self.billing.grant("u@x", 600)
        call = self._start()
        result = self.reg.heartbeat("other@x", call.call_id, active=True, final=False)
        self.assertEqual((result.stop, result.reason), (True, "unknown_call"))
        self.assertEqual(self.reg.open_calls(), 1)

    def test_new_call_settles_the_previous_one(self) -> None:
        self.billing.grant("u@x", 600)
        first = self._start()
        self.now += 30
        self._start()
        self.assertEqual(self.reg.open_calls(), 1)
        self.assertEqual(self.billing.get_balance("u@x"), 570)
        self.assertTrue(self.reg.heartbeat("u@x", first.call_id, active=True, final=False).stop)


class CommunityClientTests(unittest.TestCase):
    """Local backend deferring to a hosted server (ECHO_COMMUNITY_SERVER)."""

    def setUp(self) -> None:
        from services import community_client

        self.cc = community_client
        self.calls: list[tuple[str, str, Any]] = []
        self.heartbeat_verdicts: list[dict[str, Any]] = []

        async def fake_forward(method: str, path: str, *, token: str = "", json: Any = None, client_id: str = ""):
            self.calls.append((method, path, json))
            if path == "/api/auth/login":
                if json["password"] != "pw":
                    raise community_client.CommunityServerError(401, {"code": "AUTH_LOGIN_FAILED", "message": "bad"})
                return {"access_token": "remote-token", "token_type": "bearer", "user": {"email": "1203@echo.local"}}
            if path == "/api/billing/hosted-info":
                return {"hosted": True, "providers": [{"provider": "Vercel", "models": ["google/gemini-3.8-live"]},
                                                      {"provider": "DashScope", "models": ["q"]}]}
            if path == "/api/billing/me":
                return {"account": "1203", "remaining_seconds": 300}
            if path.startswith("/api/billing/me/history"):
                return {"account": "1203", "remaining_seconds": 300, "calls": [], "daily": [], "grants": [], "token": token}
            if path == "/api/billing/renewal":
                return {"text": "¥49", "qr": ""}
            if path == "/api/auth/change-password":
                if json["current_password"] != "pw":
                    raise community_client.CommunityServerError(400, {"code": "AUTH_CHANGE_PASSWORD_FAILED", "message": "bad"})
                return {"id": "1", "email": "1203@echo.local", "is_admin": False, "is_active": True, "created_at": "x"}
            if path == "/api/billing/direct/start":
                if token != "remote-token":
                    raise community_client.CommunityServerError(401, {"message": "login"})
                return {"call_id": "c1", "client_secret": "vcst_x", "model": "google/gemini-3.8-live",
                        "ws_url": "wss://gw/realtime", "heartbeat_seconds": 0.05, "remaining_seconds": 300}
            if path == "/api/billing/direct/heartbeat":
                return self.heartbeat_verdicts.pop(0) if self.heartbeat_verdicts else {"remaining_seconds": 290, "stop": False}
            raise AssertionError(path)

        self._patches = [
            patch.dict(os.environ, {"ECHO_COMMUNITY_SERVER": "https://hosted.test:8443", "ECHO_HOSTED_MODE": ""}),
            patch.object(community_client, "forward", side_effect=fake_forward),
        ]
        for p in self._patches:
            p.start()
        self.app = create_app()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async def run() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run())

    def test_local_features_stay_blocked(self) -> None:
        self.assertEqual(self._request("GET", "/api/settings/").status_code, 404)
        self.assertEqual(self._request("GET", "/docs").status_code, 404)

    def test_login_is_answered_by_the_hosted_server(self) -> None:
        ok = self._request("POST", "/api/auth/login", json={"email": "1203", "password": "pw"})
        self.assertEqual(ok.json()["access_token"], "remote-token")
        bad = self._request("POST", "/api/auth/login", json={"email": "1203", "password": "nope"})
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(bad.json()["detail"]["code"], "AUTH_LOGIN_FAILED")

    def test_account_page_requests_go_to_the_server(self) -> None:
        auth = {"Authorization": "Bearer remote-token"}
        history = self._request("GET", "/api/billing/me/history?days=7&tz=480", headers=auth).json()
        self.assertEqual(history["token"], "remote-token")
        self.assertIn(("GET", "/api/billing/me/history?days=7&tz=480", None), self.calls)
        self.assertEqual(self._request("GET", "/api/billing/renewal", headers=auth).json()["text"], "¥49")
        bad = self._request(
            "POST", "/api/auth/change-password", headers=auth,
            json={"current_password": "x", "new_password": "newpass1"},
        )
        self.assertEqual(bad.status_code, 400)
        ok = self._request(
            "POST", "/api/auth/change-password", headers=auth,
            json={"current_password": "pw", "new_password": "newpass1"},
        )
        self.assertEqual(ok.json()["email"], "1203@echo.local")

    def test_only_direct_capable_models_are_offered(self) -> None:
        body = self._request("GET", "/api/billing/hosted-info").json()
        self.assertEqual([p["provider"] for p in body["providers"]], ["Vercel"])

    def test_balance_is_forwarded_with_the_token(self) -> None:
        body = self._request("GET", "/api/billing/me", headers={"Authorization": "Bearer remote-token"}).json()
        self.assertEqual(body["remaining_seconds"], 300)

    def test_call_uses_the_server_grant_and_heartbeats(self) -> None:
        captured: dict[str, Any] = {}
        self.heartbeat_verdicts = [
            {"remaining_seconds": 290, "stop": False},
            {"remaining_seconds": 0, "stop": True, "reason": "balance_exhausted", "message": "时长已用完"},
        ]

        async def fake_session(websocket: Any, **kwargs: Any) -> None:
            from starlette.websockets import WebSocketState

            captured.update(kwargs)
            await websocket.send_json({"type": "assistant_text", "text": "hi"})
            # Talk until the meter hangs up (heartbeats are >= 1 s apart).
            for _ in range(200):
                if websocket.application_state != WebSocketState.CONNECTED:
                    return
                await asyncio.sleep(0.05)

        with patch.object(
            voice_chat_router.voice_chat_service, "stream_vercel_session", AsyncMock(side_effect=fake_session)
        ):
            client = TestClient(self.app)
            events = []
            with client.websocket_connect("/api/voice-chat/ws?provider=Vercel&token=remote-token") as ws:
                try:
                    while True:
                        events.append(ws.receive_json())
                except WebSocketDisconnect:
                    pass
        # No local Gateway key was needed: the grant came from the server.
        self.assertEqual(captured["direct_grant"]["client_secret"], "vcst_x")
        self.assertEqual(captured["model"], "google/gemini-3.8-live")
        self.assertEqual(events[0], {"type": "billing", "remaining_seconds": 300})
        self.assertEqual(events[-1]["type"], "billing_end")
        self.assertEqual(events[-1]["reason"], "balance_exhausted")
        beats = [c for c in self.calls if c[1] == "/api/billing/direct/heartbeat"]
        self.assertTrue(beats[0][2]["active"])  # the assistant spoke before the first beat
        self.assertTrue(any(b[2]["final"] for b in beats))

    def test_call_refused_by_server_shows_its_reason(self) -> None:
        client = TestClient(self.app)
        with client.websocket_connect("/api/voice-chat/ws?provider=Vercel&token=wrong") as ws:
            self.assertEqual(ws.receive_json()["type"], "error")

    def test_qwen_is_not_offered_directly(self) -> None:
        client = TestClient(self.app)
        with client.websocket_connect("/api/voice-chat/ws?provider=DashScope&token=remote-token") as ws:
            self.assertIn("Gemini", ws.receive_json()["message"])
