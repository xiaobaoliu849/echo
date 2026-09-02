"""Tests for Gradium TTS and Realtime Voice Provider."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.gradium_tts_provider import (
    DEFAULT_GRADIUM_BASE_URL,
    DEFAULT_GRADIUM_MODEL,
    DEFAULT_GRADIUM_VOICE,
    GRADIUM_VOICES,
    fetch_gradium_voices,
    gradium_headers,
    gradium_tts_synthesize,
    is_gradium_voice,
)
from services.realtime_constants import (
    DEFAULT_GRADIUM_REALTIME_MODEL,
    DEFAULT_GRADIUM_REALTIME_VOICE,
    GRADIUM_REALTIME_VOICES,
)
from services.realtime_gradium_provider import (
    GradiumRealtimeMixin,
    _GradiumSessionState,
    _GradiumTurn,
)


class DummyGradiumService(GradiumRealtimeMixin):
    def __init__(self):
        self.config = MagicMock()
        self._finalize_realtime_turn = AsyncMock()
        self._create_voice_session_recorder = AsyncMock(return_value=None)
        self._run_duplex_tasks = AsyncMock()
        self._build_realtime_instructions = MagicMock(return_value="You are an assistant.")
        self._handle_common_client_command = AsyncMock(return_value=None)

    async def _send_event(self, websocket, event_type, **payload):
        await websocket.send_json({"type": event_type, **payload})

    async def _deliver_assistant_output(self, websocket, event, *, memory_session, recorder, record_memory=True):
        await websocket.send_json(event)


class CollectingWebSocket:
    def __init__(self, inbound: list[dict] | None = None):
        self.events: list[dict] = []
        self.inbound = list(inbound or [])

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))

    async def receive(self) -> dict:
        if self.inbound:
            return self.inbound.pop(0)
        return {"type": "websocket.disconnect"}


class FakeWs:
    def __init__(self, events: list[dict] | None = None):
        self.sent: list[str] = []
        self._events = list(events or [])

    async def send(self, data) -> None:
        self.sent.append(data if isinstance(data, str) else data.decode("utf-8", errors="replace"))

    async def recv(self) -> str:
        if self._events:
            return json.dumps(self._events.pop(0))
        return json.dumps({"type": "ready", "sample_rate": 48000})

    async def __aiter__(self):
        for ev in self._events:
            yield json.dumps(ev)
        while True:
            await asyncio.sleep(3600)


class TestGradiumTtsProvider(unittest.TestCase):
    def test_voice_identification(self):
        self.assertTrue(is_gradium_voice("YTpq7expH9539ERJ"))
        self.assertTrue(is_gradium_voice("3jUdJyOi9pgbxBTK"))
        self.assertTrue(is_gradium_voice("custom_voice_12345678"))
        self.assertFalse(is_gradium_voice(""))
        self.assertFalse(is_gradium_voice("short"))

    def test_edge_voices_are_not_gradium(self):
        # Edge TTS voice names ("en-US-AvaNeural", "zh-CN-XiaoxiaoNeural", ...)
        # must not match the Gradium opaque-token regex, otherwise an Edge
        # request gets misrouted to the Gradium provider and fails with
        # "Embeddings not found for en-US-AvaNeural".
        for edge_voice in (
            "en-US-AvaNeural",
            "zh-CN-XiaoxiaoNeural",
            "ja-JP-NanamiNeural",
            "en-GB-LibbyNeural",
            "ru-RU-SvetlanaNeural",
            "zh-TW-HsiaoChenNeural",
        ):
            self.assertFalse(
                is_gradium_voice(edge_voice),
                f"Edge voice {edge_voice!r} must not be treated as a Gradium voice",
            )

    def test_headers(self):
        h = gradium_headers("test-key")
        self.assertEqual(h["x-api-key"], "test-key")
        self.assertEqual(h["Content-Type"], "application/json")

    def test_constants(self):
        self.assertIn(DEFAULT_GRADIUM_VOICE, [v["name"] for v in GRADIUM_VOICES])
        self.assertEqual(DEFAULT_GRADIUM_BASE_URL, "https://api.gradium.ai")
        self.assertEqual(DEFAULT_GRADIUM_MODEL, "default")
        self.assertEqual(DEFAULT_GRADIUM_REALTIME_MODEL, "gradium-realtime")


class TestGradiumRealtimeSettings(unittest.TestCase):
    def setUp(self):
        self.svc = DummyGradiumService()

    def test_settings_resolution_success(self):
        self.svc.config.get_provider_settings.side_effect = lambda prov, m=None: {
            "Gradium": {
                "api_key": "gsk_test",
                "base_url": "https://api.gradium.ai",
                "realtime_base_url": "wss://api.gradium.ai",
                "model": "gradium-realtime",
            },
            "DeepSeek": {
                "api_key": "ds_test",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
            },
        }.get(prov, {"api_key": "", "base_url": "", "model": ""})
        self.svc.config.get_all.return_value = {}

        settings = self.svc._resolve_gradium_settings("gradium-realtime")
        self.assertEqual(settings["api_key"], "gsk_test")
        self.assertEqual(settings["ws_base"], "wss://api.gradium.ai")
        self.assertEqual(settings["llm_provider"], "DeepSeek")
        self.assertEqual(settings["llm_model"], "deepseek-v4-flash")

    def test_settings_resolution_missing_key(self):
        self.svc.config.get_provider_settings.return_value = {"api_key": "", "base_url": ""}
        with self.assertRaises(RuntimeError) as ctx:
            self.svc._resolve_gradium_settings(None)
        self.assertIn("Gradium API Key 未配置", str(ctx.exception))


class TestGradiumBargeIn(unittest.IsolatedAsyncioTestCase):
    async def test_barge_in_cancels_turn(self):
        svc = DummyGradiumService()
        ws = CollectingWebSocket()
        state = _GradiumSessionState(
            tts_model="default",
            voice=DEFAULT_GRADIUM_VOICE,
            llm_model="deepseek-v4-flash",
            api_key="gsk_test",
            ws_base="wss://api.gradium.ai",
        )

        async def long_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(long_task())
        state.active = _GradiumTurn(seq=1, user_text="Hello", task=task)
        state.history.append({"role": "user", "content": "Hello"})

        memory_session = MagicMock()
        await svc._gradium_barge_in(ws, state, memory_session, recorder=None, notify=True)

        self.assertTrue(task.cancelled())
        self.assertIsNone(state.active)
        self.assertEqual(len(state.history), 0)
        self.assertTrue(any(e["type"] == "interrupted" for e in ws.events))


class TestGradiumClientLoop(unittest.IsolatedAsyncioTestCase):
    async def test_text_input_starts_turn(self):
        svc = DummyGradiumService()
        svc._gradium_start_turn = AsyncMock()
        ws = CollectingWebSocket(inbound=[
            {"text": json.dumps({"type": "text_input", "text": "Hello bot"})}
        ])
        state = _GradiumSessionState(
            tts_model="default",
            voice=DEFAULT_GRADIUM_VOICE,
            llm_model="deepseek-v4-flash",
            api_key="gsk_test",
            ws_base="wss://api.gradium.ai",
        )
        llm = MagicMock()
        mem = MagicMock()
        tool = MagicMock()
        await svc._gradium_client_loop(ws, state, llm, "DeepSeek", mem, tool, None)
        svc._gradium_start_turn.assert_awaited_once()

    async def test_audio_bytes_forwarded_as_base64_json(self):
        svc = DummyGradiumService()
        raw_pcm = b"\x01\x02\x03\x04"
        ws = CollectingWebSocket(inbound=[
            {"bytes": raw_pcm}
        ])
        fake_stt_ws = FakeWs()
        state = _GradiumSessionState(
            tts_model="default",
            voice=DEFAULT_GRADIUM_VOICE,
            llm_model="deepseek-v4-flash",
            api_key="gsk_test",
            ws_base="wss://api.gradium.ai",
            stt_ws=fake_stt_ws,
        )
        llm = MagicMock()
        mem = MagicMock()
        tool = MagicMock()
        await svc._gradium_client_loop(ws, state, llm, "DeepSeek", mem, tool, None)

        self.assertEqual(len(fake_stt_ws.sent), 1)
        payload = json.loads(fake_stt_ws.sent[0])
        self.assertEqual(payload["type"], "audio")
        import base64
        self.assertEqual(payload["audio"], base64.b64encode(raw_pcm).decode("utf-8"))


class TestGradiumTtsChunking(unittest.TestCase):
    def test_split_gradium_tts_chunks(self):
        from services.realtime_gradium_provider import _split_gradium_tts_chunks

        # Partial streaming chunks
        chunks, remaining = _split_gradium_tts_chunks("Hello world, this is", is_final=False)
        self.assertEqual(chunks, ["Hello", "world,", "this"])
        self.assertEqual(remaining, "is")

        # Final chunk flushes remaining
        chunks2, remaining2 = _split_gradium_tts_chunks("is a test.", is_final=True)
        self.assertEqual(chunks2, ["is", "a", "test."])
        self.assertEqual(remaining2, "")


class TestGradiumTranscriptJoining(unittest.TestCase):
    def test_join_transcript_pieces(self):
        from services.realtime_gradium_provider import _join_transcript_pieces

        # English words
        en = _join_transcript_pieces(["Hello,", "how", "is", "the", "weather", "today?"])
        self.assertEqual(en, "Hello, how is the weather today?")

        # Chinese words
        zh = _join_transcript_pieces(["你好", "，", "今天", "天气", "怎么样", "？"])
        self.assertEqual(zh, "你好，今天天气怎么样？")

        # Single word
        self.assertEqual(_join_transcript_pieces(["Hello"]), "Hello")
        self.assertEqual(_join_transcript_pieces([]), "")


class TestGradiumSttLoop(unittest.IsolatedAsyncioTestCase):
    async def test_stt_loop_emits_interim_transcripts_smoothly(self):
        svc = DummyGradiumService()
        svc._gradium_start_turn = AsyncMock()

        events = [
            {"type": "text", "text": "take"},
            {"type": "text", "text": "a"},
            {"type": "text", "text": "chat."},
        ]
        fake_stt_ws = FakeWs(events=events)
        client_ws = CollectingWebSocket()
        state = _GradiumSessionState(
            tts_model="default",
            voice=DEFAULT_GRADIUM_VOICE,
            llm_model="deepseek-v4-flash",
            api_key="gsk_test",
            ws_base="wss://api.gradium.ai",
            stt_ws=fake_stt_ws,
        )

        mock_llm = MagicMock()
        mock_mem = MagicMock()
        mock_tool = MagicMock()
        stt_task = asyncio.create_task(
            svc._gradium_stt_loop(client_ws, state, mock_llm, "DeepSeek", mock_mem, mock_tool, None)
        )
        # Give loop time to process events and let flush timer fire
        await asyncio.sleep(1.2)
        stt_task.cancel()
        try:
            await stt_task
        except asyncio.CancelledError:
            pass

        # Check that interim transcripts were sent with interim=True
        interim_events = [e for e in client_ws.events if e.get("type") == "user_transcript" and e.get("interim") is True]
        self.assertTrue(len(interim_events) >= 3)
        self.assertEqual(interim_events[0]["text"], "take")
        self.assertEqual(interim_events[1]["text"], "take a")
        self.assertEqual(interim_events[2]["text"], "take a chat.")

        # Turn was started with full text
        svc._gradium_start_turn.assert_awaited_with(
            client_ws, state, "take a chat.", mock_llm, "DeepSeek", mock_mem, mock_tool, None
        )


class TestGradiumSessionEntryPoint(unittest.IsolatedAsyncioTestCase):
    @patch("websockets.connect")
    async def test_stream_gradium_session_starts_and_validates_voice(self, mock_ws_connect):
        fake_ws = FakeWs()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = fake_ws
        mock_ws_connect.return_value = mock_ctx

        svc = DummyGradiumService()
        svc._resolve_gradium_settings = MagicMock(return_value={
            "api_key": "gsk_test",
            "ws_base": "wss://api.gradium.ai",
            "tts_model": "default",
            "llm_model": "deepseek-v4-flash",
            "llm_provider": "DeepSeek",
            "session_model": "gradium-realtime",
        })
        client_ws = CollectingWebSocket()

        # Test with invalid voice string (e.g. "Tina") to verify fallback
        await svc.stream_gradium_session(client_ws, model="gradium-realtime", voice="Tina")
        svc._run_duplex_tasks.assert_awaited_once()
        self.assertTrue(any(e["type"] == "session_open" for e in client_ws.events))


if __name__ == "__main__":
    unittest.main()

