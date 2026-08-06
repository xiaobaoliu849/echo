"""Tests for Doubao / Volcengine Realtime voice provider mixin."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.interruption_classifier import InterruptionDecisionCoordinator
from services.realtime_voice_service import RealtimeVoiceService
from services.realtime_constants import (
    DEFAULT_DOUBAO_REALTIME_ENDPOINT,
    DEFAULT_DOUBAO_REALTIME_MODEL,
    DEFAULT_DOUBAO_REALTIME_VOICE,
)


class CollectingWebSocket:
    """Collects every JSON payload sent to the client."""

    def __init__(self, inbound: list[dict] | None = None) -> None:
        self.events: list[dict] = []
        self.bytes_sent: list[bytes] = []
        self.inbound = list(inbound or [])

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))

    async def send_bytes(self, payload: bytes) -> None:
        self.bytes_sent.append(payload)

    async def receive(self) -> dict:
        if self.inbound:
            return self.inbound.pop(0)
        return {"type": "websocket.disconnect"}


class FakeDoubaoWs:
    """Fake Doubao-side WebSocket."""

    def __init__(self, events: list[dict] | None = None) -> None:
        self.sent: list[str] = []
        self._events = list(events or [])

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str:
        if self._events:
            ev = self._events.pop(0)
            return json.dumps(ev)
        # Block until cancelled once events run out
        await asyncio.sleep(3600)
        return ""


class TestRealtimeDoubaoProvider(unittest.TestCase):

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    def test_resolve_doubao_settings_success(self) -> None:
        fake_config = MagicMock()
        fake_config.get_provider_settings.side_effect = lambda provider, model: {
            "Doubao": {"api_key": "volc-secret-key", "model": "doubao-realtime", "realtime_base_url": ""},
            "Volcengine": {"api_key": "", "model": "", "realtime_base_url": ""},
        }[provider]
        self.service.config = fake_config

        settings = self.service._resolve_doubao_settings("doubao-realtime", "zh_female_shuangkuailiangli")
        self.assertEqual(settings["api_key"], "volc-secret-key")
        self.assertEqual(settings["model"], "doubao-realtime")
        self.assertEqual(settings["voice"], "zh_female_shuangkuailiangli")
        self.assertEqual(settings["endpoint"], DEFAULT_DOUBAO_REALTIME_ENDPOINT)

    def test_resolve_doubao_settings_missing_key_raises(self) -> None:
        fake_config = MagicMock()
        fake_config.get_provider_settings.return_value = {"api_key": "", "model": "", "realtime_base_url": ""}
        self.service.config = fake_config

        with self.assertRaises(RuntimeError) as ctx:
            self.service._resolve_doubao_settings(None, None)
        self.assertIn("Doubao / Volcengine API Key 未配置", str(ctx.exception))

    def test_client_to_doubao_text_input(self) -> None:
        async def run_test():
            client_ws = CollectingWebSocket(inbound=[
                {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": "你好，豆包"})},
            ])
            doubao_ws = FakeDoubaoWs()
            mem_session = MagicMock()
            tool_session = MagicMock()

            await self.service._client_to_doubao_loop(
                client_ws, doubao_ws, mem_session, tool_session
            )
            self.assertEqual(len(doubao_ws.sent), 2)
            item_create = json.loads(doubao_ws.sent[0])
            resp_create = json.loads(doubao_ws.sent[1])
            self.assertEqual(item_create["type"], "conversation.item.create")
            self.assertEqual(item_create["item"]["content"][0]["text"], "你好，豆包")
            self.assertEqual(resp_create["type"], "response.create")

        asyncio.run(run_test())

    def test_doubao_to_client_audio_stream(self) -> None:
        async def run_test():
            client_ws = CollectingWebSocket()
            doubao_events = [
                {"type": "response.created", "response": {"id": "resp_001"}},
                {"type": "response.audio_transcript.delta", "delta": "你好"},
                {"type": "response.audio.delta", "delta": "QUJD"},  # base64 "ABC"
                {"type": "response.done"},
            ]
            doubao_ws = FakeDoubaoWs(events=doubao_events)
            mem_session = MagicMock()
            tool_session = MagicMock()

            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(
                    client_ws, doubao_ws, mem_session, tool_session
                )
            )
            await asyncio.sleep(0.1)
            loop_task.cancel()

            audio_events = [e for e in client_ws.events if e.get("type") == "assistant_audio"]
            self.assertEqual(len(audio_events), 1)
            self.assertEqual(audio_events[0]["audio"], "QUJD")

            text_events = [e for e in client_ws.events if e.get("type") == "assistant_text"]
            self.assertTrue(len(text_events) >= 1)
            self.assertIn("你好", text_events[-1]["text"])

        asyncio.run(run_test())

    def test_doubao_session_recorder_methods(self) -> None:
        async def run_test():
            fake_repo = MagicMock()
            from services.realtime_session_recorder import VoiceAgentSessionRecorder
            recorder = VoiceAgentSessionRecorder(fake_repo, "session_123")
            await recorder.record_turn_completed()
            await recorder.complete_session()
            self.assertTrue(fake_repo.finish_session.called)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
