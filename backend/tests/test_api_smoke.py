from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import quote, urlparse

import httpx
from starlette.requests import Request
from starlette.routing import Mount, Route, WebSocketRoute

from main import create_app
from routers import agent_runs as agent_runs_router
from routers import audio_agent as audio_agent_router
from routers import audio_overview as audio_overview_router
from routers import chat as chat_router
from routers import evermem as evermem_router
from routers import settings as settings_router
from routers import transcription as transcription_router
from routers import translate as translate_router
from routers import tts as tts_router
from routers import voice_chat as voice_chat_router
from routers import voices as voices_router
from services.audio_overview_service import AudioOverviewService, AudioOverviewServiceError
from services.audio_agent_service import AudioAgentService
from services.agent_run_service import AgentRunService
from services.config_loader import BackendConfig, GOOGLE_INTERACTIONS_BASE_URL
from services.settings_service import MASKED_SECRET
from services.evermem_config import EverMemConfig
from services import realtime_voice_service as realtime_voice_module
from services import tts_service as tts_service_module
from services.llm_service import LLMService
from services.realtime_voice_service import RealtimeVoiceService
from services.settings_service import SettingsService
from services.tts_service import TTSAudioResult
from services.transcription_publish_adapter import build_transcription_publisher
from services.transcription_service import TranscriptionService
from services.user_auth_service import user_auth_service
from services.voice_agent_session_repository import VoiceAgentSessionRepository


class ApiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_env_patcher = patch.dict(
            os.environ,
            {
                "VOICESPIRIT_API_TOKEN": "test-api-token",
                "VOICESPIRIT_ADMIN_TOKEN": "test-admin-token",
            },
            clear=False,
        )
        self._auth_env_patcher.start()
        self.app = create_app()
        self._smoke_jobs_tmp = tempfile.TemporaryDirectory()
        self._smoke_original_jobs_dir = transcription_router.transcription_service.jobs_dir
        transcription_router.transcription_service.jobs_dir = Path(self._smoke_jobs_tmp.name)
        transcription_router.transcription_service.jobs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        transcription_router.transcription_service.jobs_dir = self._smoke_original_jobs_dir
        self._smoke_jobs_tmp.cleanup()
        self._auth_env_patcher.stop()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        default_auth = bool(kwargs.pop("default_auth", True))
        sensitive_read = method.upper() == "GET" and (
            path.startswith("/api/agent-runs")
            or path.startswith("/api/voice-chat/sessions")
            or path.startswith("/api/settings")
            or path.startswith("/api/transcription")
        )
        if (
            default_auth
            and path.startswith("/api/")
            and (method.upper() in {"POST", "PUT", "PATCH", "DELETE"} or sensitive_read)
        ):
            headers = dict(kwargs.get("headers") or {})
            if "Authorization" not in headers and not path.startswith("/api/auth/"):
                token_key = "VOICESPIRIT_ADMIN_TOKEN" if path.startswith("/api/settings") else "VOICESPIRIT_API_TOKEN"
                token = os.getenv(token_key, "").strip()
                if not token and token_key == "VOICESPIRIT_API_TOKEN":
                    token = os.getenv("VOICESPIRIT_ADMIN_TOKEN", "").strip()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    kwargs["headers"] = headers

        async def runner() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(runner())

    def test_health_endpoint(self) -> None:
        response = self._request("GET", "/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy"})
        self.assertTrue(bool(response.headers.get("x-request-id")))

    def test_voice_chat_websocket_route_registered(self) -> None:
        websocket_paths = {
            route.path
            for route in self.app.routes
            if isinstance(route, WebSocketRoute)
        }
        self.assertIn("/api/voice-chat/ws", websocket_paths)

    def test_voice_chat_session_history_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            original_repository = voice_chat_router.voice_agent_session_repository
            repository = VoiceAgentSessionRepository(Path(tmp_dir) / "voice_agent.db")
            voice_chat_router.voice_agent_session_repository = repository
            try:
                session = repository.create_session(
                    provider="DashScope",
                    model="qwen-realtime",
                    voice="Cherry",
                )
                repository.upsert_turn(
                    session["id"],
                    "voice-tool-1",
                    user_text="帮我搜索语音 Agent",
                    assistant_text="我查到这些信息。",
                    completed=True,
                )
                repository.add_tool_event(
                    session["id"],
                    "agent_result",
                    {
                        "tool_name": "search_web",
                        "turn_id": "voice-tool-1",
                        "query": "语音 Agent",
                        "answer": "我查到这些信息。",
                    },
                )
                repository.link_agent_run_artifact(
                    session["id"],
                    "voice-tool-1",
                    {
                        "type": "audio_agent_run",
                        "run_id": 77,
                        "status": "queued",
                        "topic": "语音 Agent 播客",
                        "current_step": "retrieve",
                    },
                )

                missing_auth_response = self._request(
                    "GET",
                    "/api/voice-chat/sessions?limit=5",
                    default_auth=False,
                )
                self.assertEqual(missing_auth_response.status_code, 401)
                self.assertEqual(
                    missing_auth_response.json()["detail"]["code"],
                    "AUTH_TOKEN_MISSING",
                )

                invalid_auth_response = self._request(
                    "GET",
                    "/api/voice-chat/sessions?limit=5",
                    headers={"Authorization": "Bearer wrong-token"},
                )
                self.assertEqual(invalid_auth_response.status_code, 403)
                self.assertEqual(
                    invalid_auth_response.json()["detail"]["code"],
                    "AUTH_TOKEN_INVALID",
                )

                list_response = self._request("GET", "/api/voice-chat/sessions?limit=5")
                self.assertEqual(list_response.status_code, 200)
                list_payload = list_response.json()
                self.assertEqual(list_payload["count"], 1)
                self.assertEqual(list_payload["sessions"][0]["id"], session["id"])

                detail_response = self._request("GET", f"/api/voice-chat/sessions/{session['id']}")
                self.assertEqual(detail_response.status_code, 200)
                detail_payload = detail_response.json()
                self.assertEqual(detail_payload["turns"][0]["user_text"], "帮我搜索语音 Agent")
                self.assertEqual(detail_payload["tool_events"][0]["event_type"], "agent_result")
                self.assertEqual(
                    [event["event_type"] for event in detail_payload["timeline"]],
                    [
                        "session_open",
                        "user_transcript",
                        "agent_result",
                        "assistant_response",
                        "turn_completed",
                    ],
                )
                self.assertEqual(detail_payload["timeline"][2]["source"], "tool_event")
                self.assertEqual(detail_payload["agent_run_links"][0]["agent_run_id"], "audio_agent:77")

                metrics_response = self._request(
                    "GET",
                    "/api/voice-chat/sessions/metrics/summary?limit=20",
                )
                self.assertEqual(metrics_response.status_code, 200)
                self.assertEqual(metrics_response.json()["session_count"], 1)
                self.assertEqual(metrics_response.json()["turn_count"], 1)

                missing_response = self._request("GET", "/api/voice-chat/sessions/missing")
                self.assertEqual(missing_response.status_code, 404)
                self.assertEqual(
                    missing_response.json()["detail"]["code"],
                    "VOICE_AGENT_SESSION_NOT_FOUND",
                )
            finally:
                voice_chat_router.voice_agent_session_repository = original_repository

    def test_unified_agent_run_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "unified_agent_runs.db"
            audio_service = AudioAgentService(db_path=db_path)
            source = audio_service.create_run(topic="统一任务 API", auto_execute=False)
            service = AgentRunService(db_path=db_path, audio_agent_service=audio_service)
            original_service = agent_runs_router.agent_run_service
            agent_runs_router.agent_run_service = service
            try:
                missing_auth = self._request(
                    "GET",
                    "/api/agent-runs/?limit=10",
                    default_auth=False,
                )
                self.assertEqual(missing_auth.status_code, 401)

                listed = self._request("GET", "/api/agent-runs/?limit=10")
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()["count"], 1)
                canonical_id = listed.json()["runs"][0]["id"]
                self.assertEqual(canonical_id, f"audio_agent:{source['id']}")

                detail = self._request("GET", f"/api/agent-runs/{canonical_id}")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["title"], "统一任务 API")

                events = self._request("GET", f"/api/agent-runs/{canonical_id}/events")
                self.assertEqual(events.status_code, 200)
                self.assertGreaterEqual(events.json()["count"], 1)
                self.assertEqual(events.json()["events"][0]["agent_run_id"], canonical_id)

                missing = self._request("GET", "/api/agent-runs/audio_agent:999999")
                self.assertEqual(missing.status_code, 404)
            finally:
                agent_runs_router.agent_run_service = original_service

    def test_realtime_voice_service_requires_google_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "api_keys": {"google_api_key": ""},
                        "api_urls": {"Google": ""},
                        "default_models": {"Google": {"default": "", "available": []}},
                    }
                ),
                encoding="utf-8",
            )
            service = RealtimeVoiceService(config=BackendConfig(config_path))
            with self.assertRaises(RuntimeError) as exc:
                service._resolve_google_settings(None)
            self.assertIn("Google API Key", str(exc.exception))

    def test_realtime_google_settings_do_not_use_rest_models_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "api_keys": {"google_api_key": "test-key"},
                        "api_urls": {"Google": "https://generativelanguage.googleapis.com/v1beta"},
                        "default_models": {"Google": {"default": "gemini-3.1-flash-live-preview", "available": []}},
                    }
                ),
                encoding="utf-8",
            )
            service = RealtimeVoiceService(config=BackendConfig(config_path))
            with (
                patch.object(realtime_voice_module, "genai", object()),
                patch.object(realtime_voice_module, "types", object()),
            ):
                settings = service._resolve_google_settings(None)
            self.assertEqual(settings["base_url"], "")
            self.assertEqual(settings["model"], "gemini-3.1-flash-live-preview")

    def test_google_text_uses_interactions_default_when_url_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "api_keys": {"google_api_key": "test-key"},
                        "api_urls": {"Google": ""},
                        "default_models": {
                            "Google": {
                                "default": "gemini-2.5-flash",
                                "available": ["gemini-2.5-flash"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            service = LLMService(config=BackendConfig(config_path))

            settings = service._resolve_settings("Google", None)

            self.assertEqual(settings["base_url"], GOOGLE_INTERACTIONS_BASE_URL)
            self.assertEqual(settings["model"], "gemini-2.5-flash")

    def test_settings_response_keeps_google_url_blank_for_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            service = SettingsService(config=BackendConfig(config_path))

            response = service.get_settings()

            self.assertEqual(response["settings"]["api_urls"]["Google"], "")

    def test_realtime_google_settings_strip_default_interactions_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "api_keys": {"google_api_key": "test-key"},
                        "api_urls": {"Google": ""},
                        "default_models": {
                            "Google": {
                                "default": "gemini-3.1-flash-live-preview",
                                "available": [],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            service = RealtimeVoiceService(config=BackendConfig(config_path))
            with (
                patch.object(realtime_voice_module, "genai", object()),
                patch.object(realtime_voice_module, "types", object()),
            ):
                settings = service._resolve_google_settings(None)

            self.assertEqual(settings["base_url"], "")
            self.assertEqual(settings["model"], "gemini-3.1-flash-live-preview")

    def test_desktop_web_app_routes_serve_built_frontend(self) -> None:
        app_routes = {getattr(route, "path", ""): route for route in self.app.routes}
        self.assertIn("/app", app_routes)
        self.assertIn("/app/", app_routes)

        app_index_route = app_routes["/app/"]
        self.assertIsInstance(app_index_route, Route)

        response = asyncio.run(app_index_route.endpoint())
        self.assertEqual(
            Path(getattr(response, "path", "")),
            Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html",
        )

    def test_desktop_root_assets_alias_serves_bundles(self) -> None:
        frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
        index_html = frontend_dist / "index.html"
        self.assertTrue(index_html.is_file())
        html = index_html.read_text(encoding="utf-8")

        script_match = re.search(r'src="(\.?/assets/[^"]+)"', html)
        style_match = re.search(r'href="(\.?/assets/[^"]+)"', html)
        self.assertIsNotNone(script_match)
        self.assertIsNotNone(style_match)
        script_path = script_match.group(1) if script_match else ""
        style_path = style_match.group(1) if style_match else ""
        assets_dir = frontend_dist / "assets"
        self.assertTrue((assets_dir / script_path.removeprefix("./assets/").removeprefix("/assets/")).is_file())
        self.assertTrue((assets_dir / style_path.removeprefix("./assets/").removeprefix("/assets/")).is_file())

        asset_mount_paths = {
            route.path
            for route in self.app.routes
            if isinstance(route, Mount)
        }
        self.assertIn("/assets", asset_mount_paths)
        self.assertIn("/app/assets", asset_mount_paths)

    def test_request_id_passthrough(self) -> None:
        request_id = "req-smoke-001"
        response = self._request("GET", "/health", headers={"X-Request-ID": request_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-request-id"), request_id)

    def test_error_log_contains_request_id(self) -> None:
        async def fake_generate_audio(
            text: str,
            voice: str | None,
            rate: str = "+0%",
            engine: str = "edge",
        ) -> tuple[str, str, bool]:
            _ = (text, voice, rate, engine)
            raise ValueError("Text is empty after cleanup.")

        request_id = "req-error-log-001"
        with patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio):
            with self.assertLogs("voicespirit.error", level="ERROR") as logs:
                response = self._request(
                    "GET",
                    "/api/tts/speak",
                    params={"text": "hello"},
                    headers={"X-Request-ID": request_id},
                )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(logs.output)
        last_line = logs.output[-1].split(":", maxsplit=2)[-1].strip()
        payload = json.loads(last_line)
        self.assertEqual(payload["event"], "http_error")
        self.assertEqual(payload["request_id"], request_id)
        self.assertEqual(payload["status"], 400)

    def test_tts_voices_endpoint(self) -> None:
        async def fake_list_voices(locale: str | None = None, engine: str = "edge", model: str | None = None) -> list[dict[str, Any]]:
            _ = (locale, engine, model)
            return [{"name": "zh-CN-XiaoxiaoNeural", "short_name": "Xiaoxiao", "locale": "zh-CN", "gender": "Female"}]

        with patch.object(tts_router.tts_service, "list_voices", new=fake_list_voices):
            response = self._request("GET", "/api/tts/voices")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["voices"][0]["name"], "zh-CN-XiaoxiaoNeural")

    def test_tts_voices_endpoint_supports_qwen_flash_engine(self) -> None:
        response = self._request("GET", "/api/tts/voices", params={"engine": "qwen_flash"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreater(payload["count"], 0)
        self.assertEqual(payload["voices"][0]["name"], "Cherry")

    def test_auth_token_protection(self) -> None:
        async def fake_list_voices(locale: str | None = None, engine: str = "edge", model: str | None = None) -> list[dict[str, Any]]:
            _ = (locale, engine, model)
            return [{"name": "zh-CN-XiaoxiaoNeural", "short_name": "Xiaoxiao", "locale": "zh-CN", "gender": "Female"}]

        async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "provider": "DashScope",
                "model": "qwen-plus",
                "reply": "ok",
                "raw": {"id": "auth-test"},
            }

        with patch.dict(os.environ, {"VOICESPIRIT_API_TOKEN": "test-token"}, clear=False):
            with patch.object(tts_router.tts_service, "list_voices", new=fake_list_voices):
                # Read endpoints remain available without token in write-only mode.
                read_ok = self._request("GET", "/api/tts/voices")
                self.assertEqual(read_ok.status_code, 200)

            with patch.object(chat_router.llm_service, "chat_completion", new=fake_chat_completion):
                missing = self._request(
                    "POST",
                    "/api/chat/completions",
                    json={"provider": "DashScope", "messages": [{"role": "user", "content": "hello"}]},
                    default_auth=False,
                )
                self.assertEqual(missing.status_code, 401)
                self.assertEqual(missing.json()["detail"]["code"], "AUTH_TOKEN_MISSING")
                self.assertTrue(bool(missing.json()["detail"].get("meta", {}).get("request_id")))
                self.assertTrue(bool(missing.headers.get("x-request-id")))

                invalid = self._request(
                    "POST",
                    "/api/chat/completions",
                    headers={"Authorization": "Bearer wrong-token"},
                    json={"provider": "DashScope", "messages": [{"role": "user", "content": "hello"}]},
                )
                self.assertEqual(invalid.status_code, 403)
                self.assertEqual(invalid.json()["detail"]["code"], "AUTH_TOKEN_INVALID")

                ok = self._request(
                    "POST",
                    "/api/chat/completions",
                    headers={"Authorization": "Bearer test-token"},
                    json={"provider": "DashScope", "messages": [{"role": "user", "content": "hello"}]},
                )
                self.assertEqual(ok.status_code, 200)

    def test_settings_admin_token_protection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            test_service = SettingsService(config=BackendConfig(config_path))

            original_service = settings_router.settings_service
            settings_router.settings_service = test_service
            try:
                with patch.dict(
                    os.environ,
                    {
                        "VOICESPIRIT_API_TOKEN": "user-token",
                        "VOICESPIRIT_ADMIN_TOKEN": "admin-token",
                    },
                    clear=False,
                ):
                    missing = self._request(
                        "PUT",
                        "/api/settings/",
                        json={"merge": True, "settings": {"general_settings": {"log_level": "INFO"}}},
                        default_auth=False,
                    )
                    self.assertEqual(missing.status_code, 401)
                    self.assertEqual(missing.json()["detail"]["code"], "AUTH_ADMIN_TOKEN_MISSING")

                    user = self._request(
                        "PUT",
                        "/api/settings/",
                        headers={"Authorization": "Bearer user-token"},
                        json={"merge": True, "settings": {"general_settings": {"log_level": "DEBUG"}}},
                    )
                    self.assertEqual(user.status_code, 403)
                    self.assertEqual(user.json()["detail"]["code"], "AUTH_ADMIN_TOKEN_INVALID")

                    admin = self._request(
                        "PUT",
                        "/api/settings/",
                        headers={"Authorization": "Bearer admin-token"},
                        json={"merge": True, "settings": {"general_settings": {"log_level": "WARNING"}}},
                    )
                    self.assertEqual(admin.status_code, 200)
                    self.assertEqual(
                        admin.json()["settings"]["general_settings"]["log_level"], "WARNING"
                    )
            finally:
                settings_router.settings_service = original_service

    def test_user_register_login_and_admin_write_access(self) -> None:
        async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "provider": "DashScope",
                "model": "qwen-plus",
                "reply": "ok",
                "raw": {"id": "user-auth-test"},
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            db_path = Path(tmp_dir) / "voice_spirit_auth.db"
            original_db_path = user_auth_service.db_path
            original_config = user_auth_service.config
            original_settings_service = settings_router.settings_service
            user_auth_service.db_path = db_path
            user_auth_service.config = BackendConfig(config_path)
            user_auth_service._init_db()
            settings_router.settings_service = SettingsService(config=BackendConfig(config_path))
            try:
                with patch.dict(
                    os.environ,
                    {
                        "VOICESPIRIT_API_TOKEN": "",
                        "VOICESPIRIT_ADMIN_TOKEN": "",
                        "VOICESPIRIT_JWT_SECRET": "test-jwt-secret",
                    },
                    clear=False,
                ):
                    registered = self._request(
                        "POST",
                        "/api/auth/register",
                        json={"email": "owner@example.com", "password": "pass1234"},
                    )
                    self.assertEqual(registered.status_code, 200)
                    register_payload = registered.json()
                    self.assertEqual(register_payload["user"]["email"], "owner@example.com")
                    self.assertTrue(register_payload["user"]["is_admin"])
                    token = register_payload["access_token"]

                    me = self._request(
                        "GET",
                        "/api/auth/me",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    self.assertEqual(me.status_code, 200)
                    self.assertEqual(me.json()["email"], "owner@example.com")

                    with patch.object(chat_router.llm_service, "chat_completion", new=fake_chat_completion):
                        missing = self._request(
                            "POST",
                            "/api/chat/completions",
                            json={"provider": "DashScope", "messages": [{"role": "user", "content": "hello"}]},
                        )
                        self.assertEqual(missing.status_code, 401)

                        ok = self._request(
                            "POST",
                            "/api/chat/completions",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"provider": "DashScope", "messages": [{"role": "user", "content": "hello"}]},
                        )
                        self.assertEqual(ok.status_code, 200)

                    saved = self._request(
                        "PUT",
                        "/api/settings/",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"merge": True, "settings": {"general_settings": {"log_level": "WARNING"}}},
                    )
                    self.assertEqual(saved.status_code, 200)

                    logged_in = self._request(
                        "POST",
                        "/api/auth/login",
                        json={"email": "owner@example.com", "password": "pass1234"},
                    )
                    self.assertEqual(logged_in.status_code, 200)
                    self.assertEqual(logged_in.json()["user"]["email"], "owner@example.com")
            finally:
                user_auth_service.db_path = original_db_path
                user_auth_service.config = original_config
                user_auth_service._init_db()
                settings_router.settings_service = original_settings_service

    def test_tts_speak_endpoint(self) -> None:
        async def fake_generate_audio(
            text: str,
            voice: str | None,
            rate: str = "+0%",
            engine: str = "edge",
        ) -> tuple[str, str, bool]:
            _ = (text, voice, rate, engine)
            raise ValueError("Text is empty after cleanup.")

        with patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio):
            response = self._request("GET", "/api/tts/speak", params={"text": "hello"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Text is empty after cleanup", response.text)

    def test_tts_speak_endpoint_passes_engine(self) -> None:
        async def fake_generate_audio(
            text: str,
            voice: str | None,
            rate: str = "+0%",
            engine: str = "edge",
        ) -> TTSAudioResult:
            self.assertEqual(text, "hello")
            self.assertEqual(voice, "female-shaonv")
            self.assertEqual(rate, "+10%")
            self.assertEqual(engine, "minimax")
            tmp_dir = tempfile.mkdtemp()
            file_path = Path(tmp_dir) / "test.mp3"
            file_path.write_bytes(b"ID3")
            return TTSAudioResult(
                file_path=str(file_path),
                voice="female-shaonv",
                engine="minimax",
                media_type="audio/mpeg",
                filename="tts_output.mp3",
                cache_hit=False,
            )

        with patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio):
            response = self._request(
                "GET",
                "/api/tts/speak",
                params={
                    "text": "hello",
                    "voice": "female-shaonv",
                    "rate": "+10%",
                    "engine": "minimax",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-tts-engine"), "minimax")
        self.assertEqual(response.headers.get("content-type"), "audio/mpeg")

    def test_tts_stream_with_timestamps_reports_missing_sdk(self) -> None:
        with patch.object(tts_service_module, "speechsdk", None):
            response = self._request(
                "POST",
                "/api/tts/stream-with-timestamps",
                json={"text": "hello", "voice": "zh-CN-YunxiNeural"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        self.assertIn("azure-cognitiveservices-speech not installed", response.text)

    def test_tts_speak_endpoint_uses_result_media_type(self) -> None:
        async def fake_generate_audio(
            text: str,
            voice: str | None,
            rate: str = "+0%",
            engine: str = "edge",
        ) -> TTSAudioResult:
            _ = (text, voice, rate, engine)
            tmp_dir = tempfile.mkdtemp()
            file_path = Path(tmp_dir) / "test.wav"
            file_path.write_bytes(b"RIFF....WAVE")
            return TTSAudioResult(
                file_path=str(file_path),
                voice="2",
                engine="chattts",
                media_type="audio/wav",
                filename="tts_output.wav",
                cache_hit=False,
            )

        with patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio):
            response = self._request(
                "GET",
                "/api/tts/speak",
                params={"text": "hello", "voice": "2", "engine": "chattts"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("audio/wav", response.headers.get("content-type", ""))
        self.assertEqual(response.headers.get("x-tts-engine"), "chattts")

    def test_tts_dialogue_endpoint_passes_engine_b(self) -> None:
        async def fake_generate_dialogue_audio(
            text: str,
            voice_a: str | None,
            voice_b: str | None,
            rate: str = "+0%",
            engine: str = "edge",
            engine_b: str | None = None,
        ) -> TTSAudioResult:
            self.assertEqual(text, "A: hi\nB: hello")
            self.assertEqual(voice_a, "zh-CN-XiaoxiaoNeural")
            self.assertEqual(voice_b, "2")
            self.assertEqual(rate, "+0%")
            self.assertEqual(engine, "edge")
            self.assertEqual(engine_b, "chattts")
            tmp_dir = tempfile.mkdtemp()
            file_path = Path(tmp_dir) / "dialogue.mp3"
            file_path.write_bytes(b"ID3")
            return TTSAudioResult(
                file_path=str(file_path),
                voice="zh-CN-XiaoxiaoNeural + 2",
                engine="edge + chattts",
                media_type="audio/mpeg",
                filename="tts_dialogue.mp3",
                cache_hit=False,
            )

        with patch.object(tts_router.tts_service, "generate_dialogue_audio", new=fake_generate_dialogue_audio):
            response = self._request(
                "GET",
                "/api/tts/speak",
                params={
                    "text": "A: hi\nB: hello",
                    "voice": "zh-CN-XiaoxiaoNeural",
                    "voice_b": "2",
                    "engine": "edge",
                    "engine_b": "chattts",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-tts-engine"), "edge + chattts")

    def test_tts_speak_endpoint_with_memory_header(self) -> None:
        async def fake_generate_audio(
            text: str,
            voice: str | None,
            rate: str = "+0%",
            engine: str = "edge",
        ) -> TTSAudioResult:
            _ = (text, voice, rate, engine)
            tmp_dir = tempfile.mkdtemp()
            file_path = Path(tmp_dir) / "test.mp3"
            file_path.write_bytes(b"ID3")
            return TTSAudioResult(
                file_path=str(file_path),
                voice="zh-CN-XiaoxiaoNeural",
                engine="edge",
                media_type="audio/mpeg",
                filename="tts_output.mp3",
                cache_hit=True,
            )

        class FakeEverMemService:
            async def add_memory(self, **kwargs: Any) -> dict[str, Any] | None:
                _ = kwargs
                return {"status": "success"}

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/tts/speak",
                "headers": [
                    (b"x-evermem-enabled", b"true"),
                    (b"x-evermem-key", b"test-key"),
                ],
            }
        )
        with patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio):
            with patch.object(EverMemConfig, "get_service", return_value=FakeEverMemService()):
                response = asyncio.run(
                    tts_router.speak(
                        request=request,
                        text="hello",
                        voice="zh-CN-XiaoxiaoNeural",
                        rate="+0%",
                    )
                )
        self.assertIn("audio/mpeg", response.media_type)
        self.assertEqual(response.headers.get("x-tts-voice"), "zh-CN-XiaoxiaoNeural")
        self.assertEqual(response.headers.get("x-cache"), "HIT")
        self.assertEqual(response.headers.get("x-evermem-saved"), "true")

    def test_transcription_service_extracts_multimodal_text(self) -> None:
        payload = {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"text": "第一句"},
                                {"text": "第二句"},
                            ]
                        }
                    }
                ]
            }
        }

        text = TranscriptionService._extract_text(payload)
        self.assertEqual(text, "第一句\n第二句")

    def test_transcription_service_rejects_unsupported_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "demo.txt"
            file_path.write_text("not-audio", encoding="utf-8")

            with self.assertRaises(ValueError):
                asyncio.run(TranscriptionService().prepare_long_transcription_job(file_path))

    def test_transcription_service_persists_async_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            audio_path = Path(tmp_dir) / "meeting.wav"
            audio_path.write_bytes(b"RIFFdemo")

            service = TranscriptionService(config=BackendConfig(config_path))
            service.jobs_dir = Path(tmp_dir) / "jobs"
            service.jobs_dir.mkdir(parents=True, exist_ok=True)

            job = asyncio.run(service.prepare_long_transcription_job(audio_path))
            self.assertEqual(job.status, "queued")
            self.assertTrue(bool(job.job_id))

            loaded = service.get_job(job.job_id or "")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, "queued")
            self.assertEqual(loaded.file_path, str(audio_path.resolve()))

            updated = service.update_job(job.job_id or "", status="running")
            self.assertEqual(updated.status, "running")

    def test_transcription_service_submit_and_refresh_async_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            service = TranscriptionService(config=BackendConfig(config_path))
            service.jobs_dir = Path(tmp_dir) / "jobs"
            service.jobs_dir.mkdir(parents=True, exist_ok=True)

            job = asyncio.run(
                service.prepare_long_transcription_url_job("https://example.com/audio/meeting.wav")
            )

            async def fake_submit(file_url: str, provider: str | None = None) -> str:
                self.assertEqual(file_url, "https://example.com/audio/meeting.wav")
                return "remote-task-001"

            async def fake_status(remote_job_id: str) -> dict[str, Any]:
                self.assertEqual(remote_job_id, "remote-task-001")
                return {
                    "task_status": "SUCCEEDED",
                    "transcript": "会议转写完成",
                }

            with patch.object(service, "_submit_remote_job_from_url", new=fake_submit):
                submitted = asyncio.run(service.submit_long_transcription_job(job.job_id or ""))
            self.assertEqual(submitted.status, "submitted")
            self.assertEqual(submitted.remote_job_id, "remote-task-001")

            with patch.object(service, "_fetch_remote_job_status", new=fake_status):
                completed = asyncio.run(service.refresh_long_transcription_job(job.job_id or ""))
            self.assertEqual(completed.status, "completed")
            self.assertTrue(bool(completed.transcript_path))
            transcript_path = Path(completed.transcript_path or "")
            self.assertTrue(transcript_path.is_file())
            self.assertEqual(transcript_path.read_text(encoding="utf-8"), "会议转写完成")

    def test_transcription_service_lists_jobs_by_status_and_recency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            service = TranscriptionService(config=BackendConfig(config_path))
            service.jobs_dir = Path(tmp_dir) / "jobs"
            service.jobs_dir.mkdir(parents=True, exist_ok=True)

            first = asyncio.run(
                service.prepare_long_transcription_url_job("https://example.com/audio/first.wav")
            )
            second = asyncio.run(
                service.prepare_long_transcription_url_job("https://example.com/audio/second.wav")
            )

            service.update_job(first.job_id or "", status="failed", error="boom")
            service.update_job(second.job_id or "", status="completed")

            completed = service.list_jobs(statuses={"completed"}, limit=10)
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].job_id, second.job_id)

            all_jobs = service.list_jobs(limit=10)
            self.assertEqual(len(all_jobs), 2)
            self.assertEqual(all_jobs[0].job_id, second.job_id)
            self.assertEqual(all_jobs[1].job_id, first.job_id)

    def test_transcription_service_publishes_local_job_with_public_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"transcription_settings": {"public_base_url": "https://files.example.com"}}),
                encoding="utf-8",
            )
            audio_path = Path(tmp_dir) / "meeting.wav"
            audio_path.write_bytes(b"RIFFdemo")

            service = TranscriptionService(config=BackendConfig(config_path))
            service.jobs_dir = Path(tmp_dir) / "jobs"
            service.jobs_dir.mkdir(parents=True, exist_ok=True)

            job = asyncio.run(service.prepare_long_transcription_job(audio_path))
            published = service.publish_local_job_for_async(job.job_id or "")

            self.assertTrue(bool(published.source_url))
            self.assertIn("/public/transcription/", published.source_url or "")
            published_name = Path(urlparse(published.source_url or "").path).name
            self.assertTrue((service.published_dir / published_name).is_file())

    def test_transcription_publisher_disables_unsupported_upload_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "transcription_settings": {
                            "public_base_url": "https://files.example.com",
                            "upload_mode": "oss",
                        }
                    }
                ),
                encoding="utf-8",
            )
            publisher = build_transcription_publisher(
                BackendConfig(config_path),
                published_dir=Path(tmp_dir) / "published",
            )
            self.assertFalse(publisher.is_enabled())
            with self.assertRaises(ValueError):
                publisher.publish(
                    job_id="tx_demo",
                    source_path=Path(tmp_dir) / "missing.wav",
                )

    def test_transcription_publisher_disables_s3_mode_without_boto3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "transcription_settings": {
                            "upload_mode": "s3",
                            "public_base_url": "https://cdn.example.com/transcription",
                            "s3_bucket": "voicespirit-assets",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "services.transcription_publish_adapter._is_boto3_available",
                return_value=False,
            ):
                publisher = build_transcription_publisher(
                    BackendConfig(config_path),
                    published_dir=Path(tmp_dir) / "published",
                )
            self.assertFalse(publisher.is_enabled())

    def test_transcription_publisher_supports_s3_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "transcription_settings": {
                            "upload_mode": "s3",
                            "public_base_url": "https://cdn.example.com/transcription",
                            "s3_bucket": "voicespirit-assets",
                            "s3_region": "us-east-1",
                            "s3_endpoint_url": "https://s3.example.com",
                            "s3_access_key_id": "key-id",
                            "s3_secret_access_key": "secret",
                            "s3_key_prefix": "voice-jobs",
                        }
                    }
                ),
                encoding="utf-8",
            )
            audio_path = Path(tmp_dir) / "meeting.wav"
            audio_path.write_bytes(b"RIFFdemo")
            upload_calls: list[tuple[str, str, str, dict[str, Any]]] = []

            class FakeS3Client:
                def upload_file(self, file_name: str, bucket: str, key: str, ExtraArgs: dict[str, Any]):
                    upload_calls.append((file_name, bucket, key, ExtraArgs))

            with patch(
                "services.transcription_publish_adapter._is_boto3_available",
                return_value=True,
            ):
                with patch(
                    "services.transcription_publish_adapter._create_s3_client",
                    return_value=FakeS3Client(),
                ):
                    publisher = build_transcription_publisher(
                        BackendConfig(config_path),
                        published_dir=Path(tmp_dir) / "published",
                    )
                    published = publisher.publish(job_id="tx_demo", source_path=audio_path)

            self.assertTrue(publisher.is_enabled())
            self.assertEqual(len(upload_calls), 1)
            file_name, bucket, key, extra_args = upload_calls[0]
            self.assertEqual(file_name, str(audio_path))
            self.assertEqual(bucket, "voicespirit-assets")
            self.assertEqual(key, "voice-jobs/tx_demo.wav")
            self.assertEqual(extra_args["ContentType"], "audio/x-wav")
            self.assertEqual(
                published.source_url,
                "https://cdn.example.com/transcription/voice-jobs/tx_demo.wav",
            )

    def test_transcription_sync_endpoint(self) -> None:
        async def fake_transcribe_file(file_path: str | Path, **kwargs: Any) -> dict:
            self.assertTrue(Path(file_path).is_file())
            return {"text": "同步转写成功", "duration_seconds": 12.5}

        async def fake_save_memory(**kwargs: Any) -> bool:
            self.assertIn("同步转写成功", kwargs["transcript_text"])
            return True

        with patch.object(transcription_router.transcription_service, "transcribe_file", new=fake_transcribe_file):
            with patch.object(transcription_router.transcription_service, "maybe_save_memory", new=fake_save_memory):
                response = self._request(
                    "POST",
                    "/api/transcription/",
                    headers={
                        "X-EverMem-Enabled": "true",
                        "X-EverMem-Key": "test-key",
                    },
                    files={"file": ("demo.wav", b"RIFFdemo", "audio/wav")},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript"], "同步转写成功")
        self.assertTrue(response.json()["memory_saved"])

    def test_transcription_upload_rejects_files_above_size_limit(self) -> None:
        oversized = b"RIFF" + b"x" * 64
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                with patch.object(
                    transcription_router, "MAX_TRANSCRIPTION_UPLOAD_BYTES", 32
                ):
                    response = self._request(
                        "POST",
                        "/api/transcription/",
                        files={"file": ("big.wav", oversized, "audio/wav")},
                    )
                self.assertEqual(response.status_code, 413)
                detail = response.json()["detail"]
                self.assertEqual(detail["code"], "TRANSCRIPTION_FILE_TOO_LARGE")
                # No partial upload file may remain on disk.
                uploads_dir = jobs_dir / "uploads"
                leftovers = list(uploads_dir.glob("*")) if uploads_dir.exists() else []
                self.assertEqual(leftovers, [])
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_async_job_saves_memory_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                async def fake_submit_remote_job_from_url(file_url: str, provider: str | None = None) -> str:
                    return "remote-url-job-001"

                async def fake_fetch_status(remote_job_id: str) -> dict[str, Any]:
                    return {"task_status": "SUCCEEDED", "transcript": "异步转写记忆测试"}

                save_calls = {"count": 0}

                async def fake_save_memory(**kwargs: Any) -> bool:
                    save_calls["count"] += 1
                    return True

                with patch.object(
                    transcription_router.transcription_service,
                    "_submit_remote_job_from_url",
                    new=fake_submit_remote_job_from_url,
                ):
                    created = self._request(
                        "POST",
                        "/api/transcription/jobs/from-url",
                        json={"file_url": "https://example.com/audio/demo.wav"},
                    )
                job_id = created.json()["job_id"]

                with patch.object(
                    transcription_router.transcription_service,
                    "_fetch_remote_job_status",
                    new=fake_fetch_status,
                ):
                    with patch.object(
                        transcription_router.transcription_service,
                        "maybe_save_memory",
                        new=fake_save_memory,
                    ):
                        first = self._request(
                            "GET",
                            f"/api/transcription/jobs/{job_id}",
                            headers={
                                "X-EverMem-Enabled": "true",
                                "X-EverMem-Key": "test-key",
                            },
                        )
                        second = self._request(
                            "GET",
                            f"/api/transcription/jobs/{job_id}",
                            headers={
                                "X-EverMem-Enabled": "true",
                                "X-EverMem-Key": "test-key",
                            },
                        )
                self.assertEqual(first.status_code, 200)
                self.assertTrue(first.json()["memory_saved"])
                self.assertEqual(second.status_code, 200)
                self.assertTrue(second.json()["memory_saved"])
                self.assertEqual(save_calls["count"], 1)
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_async_job_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                spawned: list[str] = []

                def fake_spawn(coro, job_id: str = "") -> None:
                    # Record that the local chunked pipeline was requested;
                    # close the coroutine so the test never runs ffmpeg.
                    spawned.append((coro.__qualname__, job_id))
                    coro.close()

                with patch.object(
                    transcription_router, "_spawn_background_task", new=fake_spawn
                ):
                    created = self._request(
                        "POST",
                        "/api/transcription/jobs",
                        files={"file": ("meeting.wav", b"RIFFdemo", "audio/wav")},
                    )
                self.assertEqual(created.status_code, 200)
                payload = created.json()
                # Without a public publisher the upload no longer stalls as
                # "uploaded" — it is handed to the local chunked pipeline.
                self.assertEqual(payload["status"], "running")
                job_id = payload["job_id"]
                self.assertIsNone(payload["provider"])
                self.assertEqual(len(spawned), 1)
                self.assertIn("process_local_chunked_job", spawned[0][0])
                # The pipeline task is registered so deletion can cancel it.
                self.assertEqual(spawned[0][1], job_id)

                loaded = self._request("GET", f"/api/transcription/jobs/{job_id}")
                self.assertEqual(loaded.status_code, 200)
                loaded_payload = loaded.json()
                self.assertEqual(loaded_payload["status"], "running")
                self.assertIsNone(loaded_payload["transcript"])
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_async_job_endpoint_auto_submits_when_public_base_url_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"transcription_settings": {"public_base_url": "https://files.example.com"}}),
                encoding="utf-8",
            )

            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            original_config = transcription_router.transcription_service.config
            transcription_router.transcription_service.jobs_dir = jobs_dir
            transcription_router.transcription_service.config = BackendConfig(config_path)
            try:
                async def fake_submit_remote_job_from_url(file_url: str, provider: str | None = None) -> str:
                    self.assertTrue(file_url.startswith("https://files.example.com/public/transcription/"))
                    return "remote-uploaded-job-001"

                with patch.object(
                    transcription_router.transcription_service,
                    "_submit_remote_job_from_url",
                    new=fake_submit_remote_job_from_url,
                ):
                    created = self._request(
                        "POST",
                        "/api/transcription/jobs",
                        files={"file": ("meeting.wav", b"RIFFdemo", "audio/wav")},
                    )
                self.assertEqual(created.status_code, 200)
                payload = created.json()
                self.assertEqual(payload["status"], "submitted")
                self.assertEqual(payload["remote_job_id"], "remote-uploaded-job-001")
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir
                transcription_router.transcription_service.config = original_config

    def test_transcription_job_list_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                first = asyncio.run(
                    transcription_router.transcription_service.prepare_long_transcription_url_job(
                        "https://example.com/audio/failed.wav"
                    )
                )
                second = asyncio.run(
                    transcription_router.transcription_service.prepare_long_transcription_url_job(
                        "https://example.com/audio/completed.wav"
                    )
                )
                transcription_router.transcription_service.update_job(
                    first.job_id or "",
                    status="failed",
                    error="network error",
                )
                second_transcript = jobs_dir / f"{second.job_id}.txt"
                second_transcript.write_text("完整转写内容", encoding="utf-8")
                transcription_router.transcription_service.update_job(
                    second.job_id or "",
                    status="completed",
                    transcript_path=str(second_transcript),
                )

                response = self._request(
                    "GET",
                    "/api/transcription/jobs",
                    params={"status": "completed,failed", "limit": 10},
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["count"], 2)
                self.assertEqual(payload["jobs"][0]["job_id"], second.job_id)
                self.assertEqual(payload["jobs"][1]["job_id"], first.job_id)
                # List responses omit transcript text (metadata only) but must
                # keep has_transcript so the UI can offer the detail view.
                self.assertIsNone(payload["jobs"][0]["transcript"])
                self.assertTrue(payload["jobs"][0]["has_transcript"])
                self.assertIsNone(payload["jobs"][1]["transcript"])
                self.assertFalse(payload["jobs"][1]["has_transcript"])

                # The single-job endpoint still returns the full transcript.
                detail = self._request(
                    "GET",
                    f"/api/transcription/jobs/{second.job_id}",
                    params={"refresh": "false"},
                )
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["transcript"], "完整转写内容")
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_retry_url_job_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                job = asyncio.run(
                    transcription_router.transcription_service.prepare_long_transcription_url_job(
                        "https://example.com/audio/demo.wav"
                    )
                )
                transcript_path = jobs_dir / "stale.txt"
                transcript_path.write_text("stale transcript", encoding="utf-8")
                transcription_router.transcription_service.update_job(
                    job.job_id or "",
                    status="failed",
                    transcript_path=str(transcript_path),
                    error="previous failure",
                    remote_job_id="remote-old",
                    memory_saved=True,
                )

                async def fake_submit_remote_job_from_url(file_url: str, provider: str | None = None) -> str:
                    self.assertEqual(file_url, "https://example.com/audio/demo.wav")
                    return "remote-new"

                with patch.object(
                    transcription_router.transcription_service,
                    "_submit_remote_job_from_url",
                    new=fake_submit_remote_job_from_url,
                ):
                    response = self._request(
                        "POST",
                        f"/api/transcription/jobs/{job.job_id}/retry",
                    )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "submitted")
                self.assertEqual(payload["remote_job_id"], "remote-new")
                self.assertFalse(payload["memory_saved"])
                self.assertIsNone(payload["transcript"])
                self.assertFalse(payload["has_transcript"])
                self.assertFalse(transcript_path.exists())
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_job_transcript_download_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                job = asyncio.run(
                    transcription_router.transcription_service.prepare_long_transcription_url_job(
                        "https://example.com/audio/demo.wav"
                    )
                )
                transcript_path = jobs_dir / f"{job.job_id}.txt"
                transcript_path.write_text("已完成 transcript", encoding="utf-8")
                transcription_router.transcription_service.update_job(
                    job.job_id or "",
                    status="completed",
                    transcript_path=str(transcript_path),
                )

                loaded = self._request("GET", f"/api/transcription/jobs/{job.job_id}")
                self.assertEqual(loaded.status_code, 200)
                payload = loaded.json()
                self.assertTrue(payload["has_transcript"])
                self.assertEqual(
                    payload["transcript_download_url"],
                    f"/api/transcription/jobs/{job.job_id}/transcript.txt",
                )
                self.assertEqual(payload["source_url"], "https://example.com/audio/demo.wav")

                download = self._request(
                    "GET",
                    f"/api/transcription/jobs/{job.job_id}/transcript.txt",
                )
                self.assertEqual(download.status_code, 200)
                self.assertIn("text/plain", download.headers.get("content-type", ""))
                self.assertIn("已完成 transcript", download.text)
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_job_audio_download_uses_original_mime_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            audio_path = Path(tmp_dir) / "meeting.m4a"
            audio_path.write_bytes(b"m4a-demo")
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                job = asyncio.run(
                    transcription_router.transcription_service.prepare_long_transcription_job(
                        audio_path,
                        "meeting.m4a",
                    )
                )

                loaded = self._request("GET", f"/api/transcription/jobs/{job.job_id}")
                self.assertEqual(loaded.status_code, 200)
                self.assertEqual(
                    loaded.json()["source_url"],
                    f"/api/transcription/jobs/{job.job_id}/audio",
                )

                audio = self._request("GET", f"/api/transcription/jobs/{job.job_id}/audio")
                self.assertEqual(audio.status_code, 200)
                self.assertIn("audio/mp4", audio.headers.get("content-type", ""))
                # Default is inline so <audio>/<video> can stream it.
                self.assertTrue(
                    audio.headers.get("content-disposition", "").startswith("inline;")
                )

                # ?download=1 flips it to attachment for the download button.
                attachment = self._request(
                    "GET", f"/api/transcription/jobs/{job.job_id}/audio?download=1"
                )
                self.assertEqual(attachment.status_code, 200)
                disposition = attachment.headers.get("content-disposition", "")
                self.assertTrue(disposition.startswith("attachment;"))
                self.assertIn("meeting.m4a", disposition)
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_job_audio_download_handles_non_ascii_filename(self) -> None:
        """A Chinese filename must survive as filename*, and the latin-1 fallback
        must still be a usable name rather than a bare ".m4a" dotfile."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            audio_path = Path(tmp_dir) / "meeting.m4a"
            audio_path.write_bytes(b"m4a-demo")
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                job = asyncio.run(
                    transcription_router.transcription_service.prepare_long_transcription_job(
                        audio_path,
                        "会议录音.m4a",
                    )
                )

                attachment = self._request(
                    "GET", f"/api/transcription/jobs/{job.job_id}/audio?download=1"
                )
                self.assertEqual(attachment.status_code, 200)
                disposition = attachment.headers.get("content-disposition", "")
                self.assertTrue(disposition.startswith("attachment;"))
                # Real name carried percent-encoded via RFC 5987.
                self.assertIn("filename*=UTF-8''", disposition)
                self.assertIn(quote("会议录音.m4a"), disposition)
                # ASCII fallback keeps a stem instead of collapsing to ".m4a".
                self.assertIn('filename="audio.m4a"', disposition)
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_async_url_job_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jobs_dir = Path(tmp_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            original_jobs_dir = transcription_router.transcription_service.jobs_dir
            transcription_router.transcription_service.jobs_dir = jobs_dir
            try:
                async def fake_submit_remote_job_from_url(file_url: str, provider: str | None = None) -> str:
                    self.assertEqual(file_url, "https://example.com/audio/demo.wav")
                    return "remote-url-job-001"

                with patch.object(
                    transcription_router.transcription_service,
                    "_submit_remote_job_from_url",
                    new=fake_submit_remote_job_from_url,
                ):
                    created = self._request(
                        "POST",
                        "/api/transcription/jobs/from-url",
                        json={"file_url": "https://example.com/audio/demo.wav"},
                    )
                self.assertEqual(created.status_code, 200)
                payload = created.json()
                self.assertEqual(payload["status"], "submitted")
                self.assertEqual(payload["remote_job_id"], "remote-url-job-001")
            finally:
                transcription_router.transcription_service.jobs_dir = original_jobs_dir

    def test_transcription_service_normalizes_async_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "api_keys": {"dashscope_api_key": "test-key"},
                        "api_urls": {"DashScope": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
                    }
                ),
                encoding="utf-8",
            )
            service = TranscriptionService(config=BackendConfig(config_path))
            self.assertEqual(
                service._dashscope_async_base_url(),
                "https://dashscope.aliyuncs.com/api/v1",
            )

    def test_chat_completion_endpoint(self) -> None:
        async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "provider": "DashScope",
                "model": "qwen-plus",
                "reply": "ok",
                "raw": {"id": "test"},
            }

        with patch.object(chat_router.llm_service, "chat_completion", new=fake_chat_completion):
            response = self._request(
                "POST",
                "/api/chat/completions",
                json={
                    "provider": "DashScope",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "ok")

    def test_chat_stream_endpoint(self) -> None:
        async def fake_stream(**kwargs: Any):
            _ = kwargs
            yield {"type": "meta", "provider": "DashScope", "model": "qwen-plus"}
            yield {"type": "delta", "content": "he"}
            yield {"type": "delta", "content": "llo"}
            yield {"type": "done", "provider": "DashScope", "model": "qwen-plus", "reply": "hello", "memories_retrieved": 0, "memory_saved": True}

        with patch.object(chat_router.llm_service, "chat_completion_stream", new=fake_stream):
            response = self._request(
                "POST",
                "/api/chat/completions/stream",
                json={
                    "provider": "DashScope",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                headers={
                    "X-EverMem-Enabled": "true",
                    "X-EverMem-Key": "test-key"
                }
            )
        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn("event: delta", text)
        self.assertIn('"content": "he"', text)
        self.assertIn("event: done", text)
        self.assertIn('memory_saved', text)

    def test_create_evermem_conversation_meta_endpoint(self) -> None:
        case = self

        class FakeService:
            async def create_conversation_meta(self, **kwargs: Any) -> dict[str, Any]:
                case.assertEqual(kwargs["user_id"], "scope-main")
                return {"group_id": "group-chat-001", "user_id": "scope-main"}

        headers = {
            "X-EverMem-Enabled": "true",
            "X-EverMem-Key": "test-key",
            "X-EverMem-Scope": "scope-main",
        }
        with patch.object(
            evermem_router.EverMemConfig,
            "get_service",
            return_value=FakeService(),
        ):
            response = self._request(
                "POST",
                "/api/evermem/conversation-meta",
                json={},
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"group_id": "group-chat-001", "user_id": "scope-main"},
        )

    def test_translate_endpoint(self) -> None:
        async def fake_translate_text(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {"provider": "DashScope", "model": "qwen-plus", "translated_text": "Hello"}

        with patch.object(translate_router.llm_service, "translate_text", new=fake_translate_text):
            response = self._request(
                "POST",
                "/api/translate/",
                json={
                    "text": "你好",
                    "target_language": "English",
                    "provider": "DashScope",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["translated_text"], "Hello")

    def test_translate_image_endpoint(self) -> None:
        async def fake_translate_image(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "provider": "DashScope",
                "model": "qwen-vl-max",
                "translated_text": "Hello from image",
            }

        with patch.object(translate_router.llm_service, "translate_image", new=fake_translate_image):
            response = self._request(
                "POST",
                "/api/translate/image",
                files={"image_file": ("demo.png", b"fake-image", "image/png")},
                data={
                    "target_language": "English",
                    "source_language": "auto",
                    "provider": "DashScope",
                    "model": "qwen-vl-max",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["translated_text"], "Hello from image")

    def test_voices_endpoints(self) -> None:
        async def fake_create_voice_design(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "voice": "voice_design_x",
                "type": "voice_design",
                "target_model": "qwen3-tts-vd-realtime-2025-12-16",
                "preferred_name": "demo",
                "language": "zh",
                "preview_audio_data": "",
            }

        async def fake_create_voice_clone(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "voice": "voice_clone_x",
                "type": "voice_clone",
                "target_model": "qwen3-tts-vc-realtime-2025-11-27",
                "preferred_name": "demo",
            }

        async def fake_list_voices(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "voice_type": "voice_design",
                "count": 1,
                "voices": [{"voice": "voice_design_x", "type": "voice_design", "target_model": "qwen3-tts-vd-realtime-2025-12-16"}],
            }

        async def fake_delete_voice(**kwargs: Any) -> dict[str, Any]:
            voice_name = kwargs.get("voice_name", "")
            voice_type = kwargs.get("voice_type", "voice_design")
            return {"voice": str(voice_name), "type": str(voice_type), "deleted": True}

        with patch.object(voices_router.qwen_voice_service, "create_voice_design", new=fake_create_voice_design):
            r_design = self._request(
                "POST",
                "/api/voices/design",
                json={
                    "voice_prompt": "warm",
                    "preview_text": "hello",
                    "preferred_name": "demo",
                    "language": "zh",
                },
            )
        self.assertEqual(r_design.status_code, 200)
        self.assertEqual(r_design.json()["voice"], "voice_design_x")

        with patch.object(voices_router.qwen_voice_service, "create_voice_clone", new=fake_create_voice_clone):
            r_clone = self._request(
                "POST",
                "/api/voices/clone",
                data={"preferred_name": "demo"},
                files={"audio_file": ("demo.wav", b"RIFFdata", "audio/wav")},
            )
        self.assertEqual(r_clone.status_code, 200)
        self.assertEqual(r_clone.json()["voice"], "voice_clone_x")

        with patch.object(voices_router.qwen_voice_service, "list_voices", new=fake_list_voices):
            r_list = self._request("GET", "/api/voices/?voice_type=voice_design")
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(r_list.json()["count"], 1)

        with patch.object(voices_router.qwen_voice_service, "delete_voice", new=fake_delete_voice):
            r_delete = self._request("DELETE", "/api/voices/voice_design_x?voice_type=voice_design")
        self.assertEqual(r_delete.status_code, 200)
        self.assertTrue(r_delete.json()["deleted"])

    def test_gpt_sovits_clone_sanitizes_name_and_preserves_extension(self) -> None:
        async def fake_transcribe_local_clone(audio_path: str) -> str:
            self.assertTrue(audio_path.endswith(".mp3"))
            return "hello prompt"

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"APPDATA": tmp_dir}, clear=False):
                with patch.object(voices_router, "_transcribe_local_clone", new=fake_transcribe_local_clone):
                    response = self._request(
                        "POST",
                        "/api/voices/clone",
                        data={"preferred_name": "../bad name", "provider": "gpt_sovits"},
                        files={"audio_file": ("demo.mp3", b"ID3demo", "audio/mpeg")},
                    )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["voice"], "gpt_sovits_bad_name")
                voices_dir = Path(tmp_dir) / "Echo" / "gpt_sovits_voices"
                self.assertTrue((voices_dir / "bad_name.mp3").is_file())
                self.assertEqual((voices_dir / "bad_name.txt").read_text(encoding="utf-8"), "hello prompt")
                self.assertFalse((Path(tmp_dir) / "Echo" / "bad name.wav").exists())

    def test_gpt_sovits_voice_design_is_rejected(self) -> None:
        response = self._request(
            "POST",
            "/api/voices/design",
            json={
                "voice_prompt": "warm narrator",
                "preview_text": "hello there",
                "preferred_name": "local_design",
                "language": "zh",
                "provider": "gpt_sovits",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("does not support voice design", response.text)

    def test_settings_get_and_update_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            test_service = SettingsService(config=BackendConfig(config_path))

            original_service = settings_router.settings_service
            settings_router.settings_service = test_service
            try:
                r_get = self._request("GET", "/api/settings/")
                self.assertEqual(r_get.status_code, 200)
                self.assertIn("settings", r_get.json())

                r_put = self._request(
                    "PUT",
                    "/api/settings/",
                    json={
                        "merge": True,
                        "settings": {
                            "api_keys": {"dashscope_api_key": "test-key"},
                            "default_models": {
                                "DashScope": {
                                    "default": "qwen-plus",
                                    "available": ["qwen-plus", "qwen-turbo"],
                                }
                            },
                        },
                    },
                )
                self.assertEqual(r_put.status_code, 200)
                payload = r_put.json()
                # Credentials are masked in API responses; the real value only
                # exists on disk.
                self.assertEqual(
                    payload["settings"]["api_keys"]["dashscope_api_key"],
                    MASKED_SECRET,
                )
                self.assertEqual(payload["settings"]["default_models"]["DashScope"]["default"], "qwen-plus")
                stored = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["api_keys"]["dashscope_api_key"], "test-key")

                # Round-tripping the masked placeholder must keep the stored key.
                r_put_masked = self._request(
                    "PUT",
                    "/api/settings/",
                    json={
                        "merge": True,
                        "settings": {"api_keys": {"dashscope_api_key": MASKED_SECRET}},
                    },
                )
                self.assertEqual(r_put_masked.status_code, 200)
                stored = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["api_keys"]["dashscope_api_key"], "test-key")

                # The eye-toggle reveal endpoint hands back the real credential
                # on explicit request but refuses non-secret fields.
                r_reveal = self._request(
                    "POST",
                    "/api/settings/reveal-secret",
                    json={"section": "api_keys", "key": "dashscope_api_key"},
                )
                self.assertEqual(r_reveal.status_code, 200)
                self.assertEqual(r_reveal.json()["value"], "test-key")

                r_reveal_unknown_field = self._request(
                    "POST",
                    "/api/settings/reveal-secret",
                    json={"section": "api_keys", "key": "default_model"},
                )
                self.assertEqual(r_reveal_unknown_field.status_code, 404)

                r_reveal_unknown_provider = self._request(
                    "POST",
                    "/api/settings/reveal-secret",
                    json={"section": "custom_providers", "provider_id": "missing_id"},
                )
                self.assertEqual(r_reveal_unknown_provider.status_code, 404)
            finally:
                settings_router.settings_service = original_service

    def test_google_fetch_models_uses_gemini_rest_shape(self) -> None:
        captured: dict[str, Any] = {}

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {
                    "models": [
                        {"name": "models/gemini-3.5-flash"},
                        {"baseModelId": "gemini-3.5-pro"},
                    ]
                }

        class FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                captured["client_kwargs"] = kwargs

            async def __aenter__(self) -> "FakeAsyncClient":
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def get(self, url: str, headers: dict[str, str]) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"api_keys": {"google_api_key": "test-key"}, "api_urls": {"Google": ""}}),
                encoding="utf-8",
            )
            test_service = SettingsService(config=BackendConfig(config_path))

            original_service = settings_router.settings_service
            settings_router.settings_service = test_service
            try:
                with patch("httpx.AsyncClient", FakeAsyncClient):
                    response = asyncio.run(
                        settings_router.fetch_models(
                            "Google",
                            settings_router.FetchModelsRequest(),
                        )
                    )

                self.assertEqual(
                    captured["url"],
                    "https://generativelanguage.googleapis.com/v1beta/models",
                )
                self.assertEqual(captured["headers"]["x-goog-api-key"], "test-key")
                self.assertNotIn("Authorization", captured["headers"])
                self.assertEqual(
                    response.models,
                    [
                        "gemini-2.5-flash",
                        "gemini-2.5-pro",
                        "gemini-3.1-flash-lite",
                        "gemini-3.1-flash-live-preview",
                        "gemini-3.5-flash",
                        "gemini-3.5-live-translate-preview",
                        "gemini-3.5-pro",
                        "gemini-3.5-transcribe",
                        "gemini-3.5-transcribe-live",
                        "gemini-3.7-flash",
                    ],
                )
            finally:
                settings_router.settings_service = original_service

    def test_settings_memory_aliases_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            test_service = SettingsService(config=BackendConfig(config_path))

            original_service = settings_router.settings_service
            settings_router.settings_service = test_service
            try:
                r_put = self._request(
                    "PUT",
                    "/api/settings/",
                    json={
                        "merge": True,
                        "settings": {
                            "memory_settings": {
                                "enabled": True,
                                "url": "https://api.example.test",
                                "key": "memory-key",
                                "tempSession": True,
                                "sceneChat": False,
                                "sceneVoiceChat": True,
                                "sceneTranscription": False,
                                "scenePodcast": True,
                                "sceneTts": True,
                            },
                        },
                    },
                )
                self.assertEqual(r_put.status_code, 200)
                payload = r_put.json()["settings"]["memory_settings"]
                self.assertEqual(payload["api_url"], "https://api.example.test")
                self.assertEqual(payload["api_key"], MASKED_SECRET)
                self.assertTrue(payload["temporary_session"])
                self.assertFalse(payload["remember_chat"])
                self.assertTrue(payload["remember_voice_chat"])
                self.assertFalse(payload["remember_recordings"])
                self.assertTrue(payload["remember_podcast"])
                self.assertTrue(payload["remember_tts"])
            finally:
                settings_router.settings_service = original_service

    def test_settings_ollama_provider_can_be_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            test_service = SettingsService(config=BackendConfig(config_path))

            original_service = settings_router.settings_service
            settings_router.settings_service = test_service
            try:
                r_put = self._request(
                    "PUT",
                    "/api/settings/",
                    json={
                        "merge": True,
                        "settings": {
                            "api_keys": {"ollama_api_key": ""},
                            "api_urls": {"Ollama": "http://127.0.0.1:11434/v1"},
                            "default_models": {
                                "Ollama": {
                                    "default": "qwen2.5:latest",
                                    "available": ["qwen2.5:latest", "deepseek-r1:7b"],
                                    "enabled": ["qwen2.5:latest"]
                                }
                            },
                        },
                    },
                )
                self.assertEqual(r_put.status_code, 200)
                payload = r_put.json()
                self.assertEqual(payload["settings"]["api_urls"]["Ollama"], "http://127.0.0.1:11434/v1")
                self.assertEqual(payload["settings"]["default_models"]["Ollama"]["default"], "qwen2.5:latest")
            finally:
                settings_router.settings_service = original_service

    def test_fetch_models_ollama_native_api(self) -> None:
        from unittest.mock import AsyncMock, MagicMock
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={
            "models": [
                {"name": "qwen2.5:latest"},
                {"name": "deepseek-r1:7b"}
            ]
        })
        mock_response.raise_for_status = lambda: None

        with patch("httpx.AsyncClient.get", return_value=mock_response) as mock_get:
            response = self._request(
                "POST",
                "/api/settings/providers/Ollama/fetch-models",
                json={"api_key": "", "base_url": "http://localhost:11434/v1"}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["provider"], "Ollama")
            self.assertEqual(data["models"], ["deepseek-r1:7b", "qwen2.5:latest"])
            mock_get.assert_called_once_with(
                "http://localhost:11434/api/tags",
                headers={"Accept": "application/json"}
            )

    def test_fetch_models_rejects_non_ascii_api_key(self) -> None:
        response = self._request(
            "POST",
            "/api/settings/providers/Doubao/fetch-models",
            json={"api_key": "火山引擎APIKey测试说明文本", "base_url": "https://ark.cn-beijing.volces.com/api/v3"}
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["detail"]["code"], "INVALID_API_KEY_ENCODING")

    def test_fetch_models_doubao_fallback_on_http_error(self) -> None:
        import httpx
        request = httpx.Request("GET", "https://ark.cn-beijing.volces.com/api/v3/models")
        mock_response = httpx.Response(404, request=request)
        exc = httpx.HTTPStatusError("Not Found", request=request, response=mock_response)
        with patch("httpx.AsyncClient.get", side_effect=exc):
            response = self._request(
                "POST",
                "/api/settings/providers/Doubao/fetch-models",
                json={"api_key": "valid_doubao_key_123", "base_url": "https://ark.cn-beijing.volces.com/api/v3"}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["provider"], "Doubao")
            self.assertIn("doubao-realtime", data["models"])

    def test_desktop_status_endpoint_returns_preflight_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_dir = Path(tmp_dir) / "Echo"
            diagnostics_dir = runtime_dir / "diagnostics"
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            (diagnostics_dir / "desktop_preflight_latest.json").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-10T22:45:02+0800",
                        "ok": False,
                        "checks": [
                            {"name": "frontend_dist", "ok": True, "detail": "ok"},
                            {"name": "desktop_app_route", "ok": False, "detail": "/app route is not reachable"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (diagnostics_dir / "desktop_launch_error_latest.json").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-10T22:46:00+0800",
                        "error_type": "RuntimeError",
                        "message": "Backend is up, but /app is not reachable.",
                    }
                ),
                encoding="utf-8",
            )

            original_service = settings_router.desktop_diagnostics_service
            patched_service = settings_router.DesktopDiagnosticsService()
            patched_service.runtime_dir = runtime_dir
            patched_service.diagnostics_dir = diagnostics_dir
            patched_service.preflight_path = diagnostics_dir / "desktop_preflight_latest.json"
            patched_service.launch_error_path = diagnostics_dir / "desktop_launch_error_latest.json"
            settings_router.desktop_diagnostics_service = patched_service
            try:
                response = self._request("GET", "/api/settings/desktop-status")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertFalse(payload["preflight"]["ok"])
                self.assertEqual(payload["preflight"]["failed_count"], 1)
                self.assertEqual(payload["preflight"]["failed_checks"][0]["name"], "desktop_app_route")
                self.assertTrue(payload["latest_error"]["available"])
                self.assertEqual(payload["latest_error"]["error_type"], "RuntimeError")
                self.assertIn("确认 backend/main.py 仍挂载了 /app 和 /assets", payload["latest_error"]["recovery_hints"])
                self.assertIn("必要时清理桌面缓存：python run_web_desktop.py --clear-webview", payload["latest_error"]["recovery_hints"])
            finally:
                settings_router.desktop_diagnostics_service = original_service

    def test_audio_overview_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "voice_spirit_test.db"
            output_dir = Path(tmp_dir) / "audio_out"
            test_service = AudioOverviewService(db_path=db_path, output_dir=output_dir)
            original_service = audio_overview_router.audio_overview_service
            audio_overview_router.audio_overview_service = test_service
            try:
                async def fake_generate_script(
                    *,
                    topic: str,
                    language: str = "zh",
                    turn_count: int = 10,
                    provider: str = "DashScope",
                    model: str | None = None,
                    request_headers: dict[str, Any] | None = None,
                ) -> dict[str, Any]:
                    _ = model
                    headers = request_headers or {}
                    return {
                        "topic": topic,
                        "language": language,
                        "turn_count": turn_count,
                        "provider": provider,
                        "model": "qwen-plus",
                        "script_lines": [
                            {"role": "A", "text": "欢迎来到节目"},
                            {"role": "B", "text": "今天我们聊 AI"},
                        ],
                        "raw_reply": "",
                        "memories_retrieved": 2 if headers.get("x-evermem-enabled") == "true" else 0,
                        "memory_saved": headers.get("x-evermem-key") == "test-key",
                    }

                async def fake_synthesize(
                    podcast_id: int,
                    *,
                    voice_a: str | None = None,
                    voice_b: str | None = None,
                    rate: str = "+0%",
                    language: str | None = None,
                    gap_ms: int = 250,
                    merge_strategy: str = "auto",
                    intro_music: bool = False,
                    intro_music_style: str = "warm",
                    intro_music_duration_ms: int = 2500,
                ) -> dict[str, Any]:
                    _ = (voice_a, voice_b, language, merge_strategy)
                    audio_file = output_dir / f"podcast_{podcast_id}.mp3"
                    audio_file.parent.mkdir(parents=True, exist_ok=True)
                    audio_file.write_bytes(b"ID3test-audio")
                    test_service.update_podcast(podcast_id, audio_path=str(audio_file))
                    return {
                        "podcast_id": podcast_id,
                        "audio_path": str(audio_file),
                        "line_count": 2,
                        "voice_a": "zh-CN-YunxiNeural",
                        "voice_b": "zh-CN-XiaoxiaoNeural",
                        "rate": rate,
                        "cache_hits": 1,
                        "gap_ms": gap_ms,
                        "gap_ms_applied": 0,
                        "merge_strategy": "ffmpeg",
                        "intro_music": intro_music,
                        "intro_music_style": intro_music_style if intro_music else "off",
                        "intro_music_duration_ms": intro_music_duration_ms if intro_music else 0,
                    }

                r_create = self._request(
                    "POST",
                    "/api/audio-overview/podcasts",
                    json={
                        "topic": "AI Podcast Demo",
                        "language": "zh",
                        "script_lines": [
                            {"role": "A", "text": "你好"},
                            {"role": "B", "text": "你好，很高兴见到你"},
                        ],
                    },
                )
                self.assertEqual(r_create.status_code, 200)
                created = r_create.json()
                self.assertEqual(created["topic"], "AI Podcast Demo")
                podcast_id = created["id"]

                r_list = self._request("GET", "/api/audio-overview/podcasts?limit=10")
                self.assertEqual(r_list.status_code, 200)
                self.assertEqual(r_list.json()["count"], 1)

                r_get = self._request("GET", f"/api/audio-overview/podcasts/{podcast_id}")
                self.assertEqual(r_get.status_code, 200)
                self.assertEqual(len(r_get.json()["script_lines"]), 2)

                r_script = self._request(
                    "PUT",
                    f"/api/audio-overview/podcasts/{podcast_id}/script",
                    json={
                        "script_lines": [
                            {"role": "A", "text": "更新后的第一句"},
                            {"role": "B", "text": "更新后的第二句"},
                            {"role": "A", "text": "更新后的第三句"},
                        ]
                    },
                )
                self.assertEqual(r_script.status_code, 200)
                self.assertEqual(len(r_script.json()["script_lines"]), 3)

                with patch.object(test_service, "generate_script", new=fake_generate_script):
                    r_generate = self._request(
                        "POST",
                        "/api/audio-overview/scripts/generate",
                        headers={
                            "X-EverMem-Enabled": "true",
                            "X-EverMem-Key": "test-key",
                        },
                        json={
                            "topic": "AI Podcast Demo",
                            "language": "zh",
                            "turn_count": 6,
                            "provider": "DashScope",
                        },
                    )
                self.assertEqual(r_generate.status_code, 200)
                self.assertEqual(len(r_generate.json()["script_lines"]), 2)
                self.assertEqual(r_generate.json()["memories_retrieved"], 2)
                self.assertTrue(r_generate.json()["memory_saved"])

                with patch.object(test_service, "synthesize_podcast_audio", new=fake_synthesize):
                    r_synth = self._request(
                        "POST",
                        f"/api/audio-overview/podcasts/{podcast_id}/synthesize",
                        json={
                            "voice_a": "zh-CN-YunxiNeural",
                            "voice_b": "zh-CN-XiaoxiaoNeural",
                            "gap_ms": 300,
                            "merge_strategy": "auto",
                            "intro_music": True,
                            "intro_music_style": "bright",
                            "intro_music_duration_ms": 3200,
                        },
                    )
                self.assertEqual(r_synth.status_code, 200)
                self.assertIn("/api/audio-overview/podcasts/", r_synth.json()["audio_download_url"])
                self.assertEqual(r_synth.json()["gap_ms"], 300)
                self.assertTrue(r_synth.json()["intro_music"])
                self.assertEqual(r_synth.json()["intro_music_style"], "bright")
                self.assertEqual(r_synth.json()["intro_music_duration_ms"], 3200)

                async def fake_synthesize_error(
                    podcast_id: int,
                    *,
                    voice_a: str | None = None,
                    voice_b: str | None = None,
                    rate: str = "+0%",
                    language: str | None = None,
                    gap_ms: int = 250,
                    merge_strategy: str = "auto",
                    intro_music: bool = False,
                    intro_music_style: str = "warm",
                    intro_music_duration_ms: int = 2500,
                ) -> dict[str, Any]:
                    _ = (
                        podcast_id,
                        voice_a,
                        voice_b,
                        rate,
                        language,
                        gap_ms,
                        merge_strategy,
                        intro_music,
                        intro_music_style,
                        intro_music_duration_ms,
                    )
                    raise AudioOverviewServiceError(
                        code="AUDIO_MERGE_STRATEGY_INVALID",
                        message="Unsupported merge strategy: invalid",
                        meta={"strategy": "invalid"},
                    )

                with patch.object(test_service, "synthesize_podcast_audio", new=fake_synthesize_error):
                    r_synth_error = self._request(
                        "POST",
                        f"/api/audio-overview/podcasts/{podcast_id}/synthesize",
                        json={"merge_strategy": "invalid"},
                    )
                self.assertEqual(r_synth_error.status_code, 400)
                detail = r_synth_error.json()["detail"]
                self.assertEqual(detail["code"], "AUDIO_MERGE_STRATEGY_INVALID")

                async def fake_intro_synthesize_error(
                    podcast_id: int,
                    *,
                    voice_a: str | None = None,
                    voice_b: str | None = None,
                    rate: str = "+0%",
                    language: str | None = None,
                    gap_ms: int = 250,
                    merge_strategy: str = "auto",
                    intro_music: bool = False,
                    intro_music_style: str = "warm",
                    intro_music_duration_ms: int = 2500,
                ) -> dict[str, Any]:
                    _ = (
                        podcast_id,
                        voice_a,
                        voice_b,
                        rate,
                        language,
                        gap_ms,
                        merge_strategy,
                        intro_music,
                        intro_music_style,
                        intro_music_duration_ms,
                    )
                    raise AudioOverviewServiceError(
                        code="AUDIO_INTRO_MUSIC_EXPORT_FAILED",
                        message="Intro music export failed.",
                        meta={"style": "bright"},
                    )

                with patch.object(test_service, "synthesize_podcast_audio", new=fake_intro_synthesize_error):
                    r_intro_error = self._request(
                        "POST",
                        f"/api/audio-overview/podcasts/{podcast_id}/synthesize",
                        json={"intro_music": True, "intro_music_style": "bright"},
                    )
                self.assertEqual(r_intro_error.status_code, 503)
                self.assertEqual(r_intro_error.json()["detail"]["code"], "AUDIO_INTRO_MUSIC_EXPORT_FAILED")

                r_audio = self._request("GET", f"/api/audio-overview/podcasts/{podcast_id}/audio")
                self.assertEqual(r_audio.status_code, 200)
                self.assertIn("audio/mpeg", r_audio.headers.get("content-type", ""))

                r_latest = self._request("GET", "/api/audio-overview/podcasts/latest")
                self.assertEqual(r_latest.status_code, 200)
                self.assertEqual(r_latest.json()["id"], podcast_id)

                r_delete = self._request("DELETE", f"/api/audio-overview/podcasts/{podcast_id}")
                self.assertEqual(r_delete.status_code, 200)
                self.assertTrue(r_delete.json()["deleted"])
            finally:
                audio_overview_router.audio_overview_service = original_service

    def test_audio_agent_run_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "voice_spirit_test.db"
            test_service = AudioAgentService(db_path=db_path)
            original_service = audio_agent_router.audio_agent_service
            audio_agent_router.audio_agent_service = test_service
            try:
                r_create = self._request(
                    "POST",
                    "/api/audio-agent/runs",
                    json={
                        "topic": "做一期关于睡眠习惯的播客",
                        "language": "zh",
                        "provider": "DashScope",
                        "use_memory": False,
                        "turn_count": 6,
                        "source_urls": ["https://example.com/a", "https://example.com/b"],
                        "source_text": "用户希望内容更贴近年轻上班族。",
                        "auto_execute": False,
                    },
                )
                self.assertEqual(r_create.status_code, 200)
                created = r_create.json()
                self.assertEqual(created["topic"], "做一期关于睡眠习惯的播客")
                self.assertEqual(created["status"], "queued")
                self.assertEqual(created["current_step"], "retrieve")
                self.assertEqual(created["language"], "zh")
                self.assertEqual(len(created["steps"]), 1)
                self.assertEqual(created["steps"][0]["step_name"], "prepare")
                run_id = created["id"]

                async def fake_generate_script(
                    *,
                    topic: str,
                    language: str,
                    turn_count: int,
                    provider: str,
                    model: str | None,
                    sources: list[dict[str, Any]],
                    generation_constraints: str = "",
                ) -> dict[str, Any]:
                    _ = (model, generation_constraints)
                    return {
                        "provider": provider,
                        "model": "qwen-plus",
                        "reply": "A: 开场\nB: 回应\nA: 深入\nB: 总结",
                        "script_lines": [
                            {"role": "A", "text": f"欢迎来到节目，今天聊{topic}。"},
                            {"role": "B", "text": "年轻上班族的睡眠问题，常常和压力、作息紊乱有关。"},
                            {"role": "A", "text": f"这次我们按 {turn_count} 轮的结构来展开。"},
                            {"role": "B", "text": f"本次草稿参考了 {len(sources)} 条线索。"},
                        ],
                        "evidence_summary": "1. 用户希望内容更贴近年轻上班族。",
                        "research_brief": "Source mix: manual_text=1, manual_url=2",
                    }

                async def fake_collect_sources(
                    *,
                    topic: str,
                    use_memory: bool,
                    source_urls: list[str] | None = None,
                    source_text: str | None = None,
                    request_headers: dict[str, Any] | None = None,
                ) -> list[dict[str, Any]]:
                    _ = (topic, use_memory, request_headers)
                    sources: list[dict[str, Any]] = []
                    if source_text:
                        sources.append(
                            {
                                "source_type": "manual_text",
                                "title": "User provided context",
                                "uri": "",
                                "snippet": source_text[:280],
                                "content": source_text,
                                "score": 1.0,
                                "meta": {"origin": "user_input"},
                            }
                        )
                    for idx, url in enumerate(source_urls or [], start=1):
                        sources.append(
                            {
                                "source_type": "manual_url",
                                "title": f"Manual source {idx}",
                                "uri": url,
                                "snippet": f"摘录 {idx}",
                                "content": f"网页正文 {idx}",
                                "score": 0.75,
                                "meta": {"origin": "user_url", "fetch_status": "ok"},
                            }
                        )
                    return sources

                with (
                    patch.object(test_service.retrieval_service, "collect_sources", new=fake_collect_sources),
                    patch.object(test_service.script_writer, "generate_script", new=fake_generate_script),
                ):
                    r_execute = self._request(
                        "POST",
                        f"/api/audio-agent/runs/{run_id}/execute",
                    )
                    self.assertEqual(r_execute.status_code, 200)
                    executed = r_execute.json()
                    self.assertIn(executed["status"], {"queued", "running", "draft_ready"})

                    loaded = executed
                    for _ in range(20):
                        loaded_response = self._request("GET", f"/api/audio-agent/runs/{run_id}")
                        self.assertEqual(loaded_response.status_code, 200)
                        loaded = loaded_response.json()
                        if loaded["status"] == "draft_ready":
                            break
                        time.sleep(0.05)
                self.assertEqual(loaded["status"], "draft_ready")
                self.assertTrue(bool(loaded["podcast_id"]))
                self.assertEqual(len(loaded["sources"]), 3)
                self.assertEqual(loaded["result_payload"]["provider"], "DashScope")
                self.assertIn("research_brief", loaded["result_payload"])
                self.assertEqual(len(loaded["result_payload"]["script_lines"]), 4)
                podcast_id = int(loaded["podcast_id"])

                async def fake_run_synthesize(
                    podcast_id: int,
                    *,
                    voice_a: str | None = None,
                    voice_b: str | None = None,
                    rate: str = "+0%",
                    language: str | None = None,
                    gap_ms: int = 250,
                    merge_strategy: str = "auto",
                    intro_music: bool = False,
                    intro_music_style: str = "warm",
                    intro_music_duration_ms: int = 2500,
                ) -> dict[str, Any]:
                    _ = (voice_a, voice_b, language)
                    audio_file = Path(tmp_dir) / "audio_out" / f"agent_podcast_{podcast_id}.mp3"
                    audio_file.parent.mkdir(parents=True, exist_ok=True)
                    audio_file.write_bytes(b"ID3agent-audio")
                    test_service.audio_overview_service.update_podcast(podcast_id, audio_path=str(audio_file))
                    return {
                        "podcast_id": podcast_id,
                        "audio_path": str(audio_file),
                        "line_count": 4,
                        "voice_a": "zh-CN-YunxiNeural",
                        "voice_b": "zh-CN-XiaoxiaoNeural",
                        "rate": rate,
                        "cache_hits": 2,
                        "gap_ms": gap_ms,
                        "gap_ms_applied": 0,
                        "merge_strategy": merge_strategy,
                        "intro_music": intro_music,
                        "intro_music_style": intro_music_style if intro_music else "off",
                        "intro_music_duration_ms": intro_music_duration_ms if intro_music else 0,
                    }

                with patch.object(
                    test_service.audio_overview_service,
                    "synthesize_podcast_audio",
                    new=fake_run_synthesize,
                ):
                    r_run_synth = self._request(
                        "POST",
                        f"/api/audio-agent/runs/{run_id}/synthesize",
                        json={
                            "voice_a": "zh-CN-YunxiNeural",
                            "voice_b": "zh-CN-XiaoxiaoNeural",
                            "gap_ms": 300,
                            "merge_strategy": "auto",
                            "intro_music": True,
                            "intro_music_style": "calm",
                            "intro_music_duration_ms": 2800,
                        },
                    )
                self.assertEqual(r_run_synth.status_code, 200)
                synthesized = r_run_synth.json()
                self.assertEqual(synthesized["status"], "completed")
                self.assertEqual(synthesized["current_step"], "synthesize_audio")
                self.assertEqual(synthesized["result_payload"]["cache_hits"], 2)
                self.assertTrue(synthesized["result_payload"]["intro_music"])
                self.assertEqual(synthesized["result_payload"]["intro_music_style"], "calm")
                self.assertEqual(synthesized["result_payload"]["intro_music_duration_ms"], 2800)
                self.assertEqual(synthesized["podcast_id"], podcast_id)

                self.assertEqual(loaded["id"], run_id)
                self.assertFalse(loaded["use_memory"])
                self.assertEqual(loaded["input_payload"]["turn_count"], 6)

                r_list = self._request("GET", "/api/audio-agent/runs?limit=10")
                self.assertEqual(r_list.status_code, 200)
                listed = r_list.json()
                self.assertEqual(listed["count"], 1)
                self.assertEqual(listed["runs"][0]["id"], run_id)

                r_events = self._request("GET", f"/api/audio-agent/runs/{run_id}/events")
                self.assertEqual(r_events.status_code, 200)
                events = r_events.json()
                self.assertGreaterEqual(events["count"], 2)
                event_types = [item["event_type"] for item in events["events"]]
                self.assertIn("run_created", event_types)
                self.assertIn("draft_created", event_types)
                self.assertIn("research_brief_created", event_types)
                self.assertIn("podcast_saved", event_types)
                self.assertIn("synthesis_completed", event_types)
                self.assertIn("execution_deferred", event_types)

                async def fake_run_intro_error(
                    podcast_id: int,
                    *,
                    voice_a: str | None = None,
                    voice_b: str | None = None,
                    rate: str = "+0%",
                    language: str | None = None,
                    gap_ms: int = 250,
                    merge_strategy: str = "auto",
                    intro_music: bool = False,
                    intro_music_style: str = "warm",
                    intro_music_duration_ms: int = 2500,
                ) -> dict[str, Any]:
                    _ = (
                        podcast_id,
                        voice_a,
                        voice_b,
                        rate,
                        language,
                        gap_ms,
                        merge_strategy,
                        intro_music,
                        intro_music_style,
                        intro_music_duration_ms,
                    )
                    raise AudioOverviewServiceError(
                        code="AUDIO_INTRO_MUSIC_UNAVAILABLE",
                        message="Intro music generation requires pydub and an audio backend.",
                        meta={"reason": "missing pydub.generators"},
                    )

                with patch.object(
                    test_service.audio_overview_service,
                    "synthesize_podcast_audio",
                    new=fake_run_intro_error,
                ):
                    r_run_intro_error = self._request(
                        "POST",
                        f"/api/audio-agent/runs/{run_id}/synthesize",
                        json={"intro_music": True},
                    )
                self.assertEqual(r_run_intro_error.status_code, 502)
                intro_error_detail = r_run_intro_error.json()["detail"]
                self.assertEqual(intro_error_detail["code"], "AUDIO_INTRO_MUSIC_UNAVAILABLE")
                failed_run = self._request("GET", f"/api/audio-agent/runs/{run_id}").json()
                self.assertEqual(failed_run["status"], "failed")
                self.assertEqual(failed_run["error_code"], "AUDIO_INTRO_MUSIC_UNAVAILABLE")

                r_missing = self._request("GET", "/api/audio-agent/runs/999999")
                self.assertEqual(r_missing.status_code, 404)
                self.assertEqual(r_missing.json()["detail"]["code"], "AUDIO_AGENT_RUN_NOT_FOUND")
            finally:
                audio_agent_router.audio_agent_service = original_service

    def test_audio_agent_cancel_retry_and_stream_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "voice_spirit_test.db"
            test_service = AudioAgentService(db_path=db_path)

            def no_schedule(run_id: int, headers: Any) -> None:
                _ = (run_id, headers)

            with (
                patch.object(audio_agent_router, "audio_agent_service", test_service),
                patch.object(audio_agent_router, "_schedule_run_execution", new=no_schedule),
            ):
                r_create = self._request(
                    "POST",
                    "/api/audio-agent/runs",
                    json={
                        "topic": "取消重试测试",
                        "language": "zh",
                        "provider": "DashScope",
                        "auto_execute": False,
                    },
                )
                self.assertEqual(r_create.status_code, 200)
                run_id = int(r_create.json()["id"])

                r_cancel = self._request("POST", f"/api/audio-agent/runs/{run_id}/cancel")
                self.assertEqual(r_cancel.status_code, 200)
                self.assertEqual(r_cancel.json()["status"], "cancelled")
                self.assertEqual(r_cancel.json()["error_code"], "AUDIO_AGENT_RUN_CANCELLED")

                r_stream = self._request("GET", f"/api/audio-agent/runs/{run_id}/stream")
                self.assertEqual(r_stream.status_code, 200)
                self.assertIn("text/event-stream", r_stream.headers.get("content-type", ""))
                self.assertIn("run_cancelled", r_stream.text)

                r_retry = self._request("POST", f"/api/audio-agent/runs/{run_id}/retry")
                self.assertEqual(r_retry.status_code, 200)
                self.assertEqual(r_retry.json()["status"], "pending")
                self.assertEqual(r_retry.json()["error_code"], "")

                r_retry_again = self._request("POST", f"/api/audio-agent/runs/{run_id}/retry")
                self.assertEqual(r_retry_again.status_code, 400)
                self.assertEqual(
                    r_retry_again.json()["detail"]["code"],
                    "AUDIO_AGENT_RUN_NOT_RETRYABLE",
                )


class _StubRealtimeAsrSession:
    """Offline stand-in for the DashScope streaming ASR session."""

    async def start(self) -> None:
        pass

    async def send_audio(self, data: bytes) -> None:
        pass

    async def finish(self) -> None:
        pass

    async def events(self):
        return
        yield  # pragma: no cover - makes this an async generator

    async def close(self) -> None:
        pass


class ApiAuthHardeningTests(unittest.TestCase):
    """P0 hardening: WebSocket handshake auth + GET /api/settings guard."""

    def setUp(self) -> None:
        self._auth_env_patcher = patch.dict(
            os.environ,
            {
                "VOICESPIRIT_API_TOKEN": "test-api-token",
                "VOICESPIRIT_ADMIN_TOKEN": "test-admin-token",
            },
            clear=False,
        )
        self._auth_env_patcher.start()
        self.app = create_app()

    def tearDown(self) -> None:
        self._auth_env_patcher.stop()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async def runner() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(runner())

    # -- GET /api/settings guard -------------------------------------------

    def test_get_settings_requires_auth(self) -> None:
        response = self._request("GET", "/api/settings/")
        self.assertEqual(response.status_code, 401)

    def test_get_settings_rejects_non_admin_token(self) -> None:
        response = self._request(
            "GET",
            "/api/settings/",
            headers={"Authorization": "Bearer test-api-token"},
        )
        self.assertEqual(response.status_code, 403)

    def test_get_settings_allows_admin_token(self) -> None:
        response = self._request(
            "GET",
            "/api/settings/",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("settings", response.json())

    # -- voice-chat WebSocket handshake auth -------------------------------

    def test_voice_chat_ws_rejects_missing_token(self) -> None:
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        client = TestClient(self.app)
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect("/api/voice-chat/ws?provider=NoSuchProvider") as ws:
                ws.receive_json()

    def test_voice_chat_ws_rejects_invalid_token(self) -> None:
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        client = TestClient(self.app)
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/voice-chat/ws?provider=NoSuchProvider&token=wrong-token"
            ) as ws:
                ws.receive_json()

    def test_voice_chat_ws_accepts_valid_token(self) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(self.app)
        # An unsupported provider makes the server answer with a structured
        # error and close 1003 *after* accepting — proving the handshake got
        # past the auth gate without touching any real upstream.
        with client.websocket_connect(
            "/api/voice-chat/ws?provider=NoSuchProvider&token=test-api-token"
        ) as ws:
            payload = ws.receive_json()
            self.assertEqual(payload.get("type"), "error")

    def test_voice_chat_ws_doubao_credential_validation(self) -> None:
        from fastapi.testclient import TestClient
        from unittest.mock import AsyncMock

        client = TestClient(self.app)

        # 1. 全双工实时语音只需 API Key;仅凭证缺失时报结构化错误(APP ID 已不参与校验)。
        with patch.object(BackendConfig, "get_setting") as mock_get_setting:
            mock_get_setting.side_effect = lambda k, default="": {
                "doubao_access_token": "",
                "doubao_api_key": "",
            }.get(k, default)
            with client.websocket_connect(
                "/api/voice-chat/ws?provider=Doubao&token=test-api-token"
            ) as ws:
                payload = ws.receive_json()
                self.assertEqual(payload.get("type"), "error")
                self.assertIn("Doubao API Key", payload.get("missing", []))

        # 2. Doubao with valid credentials in api_keys
        with patch.object(BackendConfig, "get_setting") as mock_get_setting, \
             patch.object(voice_chat_router.voice_chat_service, "stream_doubao_session", new_callable=AsyncMock) as mock_stream:
            mock_get_setting.side_effect = lambda k, default="": {
                "doubao_access_token": "valid-api-key",
                "doubao_app_id": "",
            }.get(k, default)
            with client.websocket_connect(
                "/api/voice-chat/ws?provider=Doubao&token=test-api-token"
            ) as ws:
                mock_stream.assert_awaited_once()

    # -- realtime transcription WebSocket handshake auth -------------------

    def test_transcription_realtime_ws_rejects_missing_token(self) -> None:
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        client = TestClient(self.app)
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect("/api/transcription/realtime") as ws:
                ws.receive_json()

    def test_transcription_realtime_ws_accepts_valid_token(self) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(self.app)
        original_factory = transcription_router.build_streaming_asr_session
        transcription_router.build_streaming_asr_session = (
            lambda *args, **kwargs: _StubRealtimeAsrSession()
        )
        try:
            with client.websocket_connect(
                "/api/transcription/realtime?token=test-admin-token"
            ) as ws:
                ws.send_json({"type": "config"})
                started = ws.receive_json()
                self.assertEqual(started.get("type"), "started")
                finished = ws.receive_json()
                self.assertEqual(finished.get("type"), "finished")
        finally:
            transcription_router.build_streaming_asr_session = original_factory


if __name__ == "__main__":
    unittest.main()
