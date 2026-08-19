"""Tests for Cartesia realtime voice provider mixin (Ink-2 STT → DeepSeek → Sonic TTS).

Covers:
  - Settings resolution (API key, DeepSeek key, WS URL derivation, defaults)
  - Barge-in (task cancellation, TTS cancel, history rollback)
  - STT loop event handling (turn.start, turn.end, error)
  - TTS loop event handling (chunk, done, error)
  - Per-turn generation (LLM stream → Sonic context, cancellation)
  - Client loop text_input routing
  - Session entry point (connection failure handling)
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.realtime_cartesia_provider import (
    CartesiaRealtimeMixin,
    _CartesiaSessionState,
    _CartesiaTurn,
    _TTS_TEXT_NOISE_RE,
)
from services.realtime_constants import (
    DEFAULT_CARTESIA_REALTIME_MODEL,
    DEFAULT_CARTESIA_REALTIME_VOICE,
    DEFAULT_CARTESIA_STT_MODEL,
)
from services.cartesia_tts_provider import (
    DEFAULT_CARTESIA_BASE_URL,
    DEFAULT_CARTESIA_MODEL,
    DEFAULT_CARTESIA_VOICE,
    infer_cartesia_language,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyCartesiaService(CartesiaRealtimeMixin):
    """Minimal concrete class that inherits the Cartesia mixin for testing.

    Unlike a simple MagicMock, this forwards _send_event and
    _deliver_assistant_output to the client websocket so that events
    can be collected by CollectingWebSocket.
    """

    def __init__(self):
        self.config = MagicMock()
        self._finalize_realtime_turn = AsyncMock()
        self._create_voice_session_recorder = AsyncMock(return_value=None)
        self._run_duplex_tasks = AsyncMock()
        self._build_realtime_instructions = MagicMock(return_value="You are a test assistant.")
        self._handle_common_client_command = AsyncMock(return_value=None)

    async def _send_event(self, websocket, event_type, **payload):
        """Mirrors RealtimeVoiceService._send_event so events land on the WS."""
        await websocket.send_json({"type": event_type, **payload})

    async def _deliver_assistant_output(self, websocket, event, *, memory_session, recorder, record_memory=True):
        """Mirrors the real method's event emission (simplified)."""
        await websocket.send_json(event)


class CollectingWebSocket:
    """Collects every JSON payload sent to the client WebSocket."""

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
    """Fake WebSocket for STT or TTS connections."""

    def __init__(self, events: list[dict] | None = None):
        self.sent: list[str] = []
        self._events = list(events or [])

    async def send(self, data) -> None:
        self.sent.append(data if isinstance(data, str) else data.decode("utf-8", errors="replace"))

    async def __aiter__(self):
        for ev in self._events:
            yield json.dumps(ev)
        while True:
            await asyncio.sleep(3600)


def _make_cartesia_config(
    cartesia_api_key: str = "csk-test-key",
    cartesia_base_url: str = DEFAULT_CARTESIA_BASE_URL,
    realtime_base_url: str = "",
    tts_default: str = "",
    deepseek_api_key: str = "ds-test-key",
    deepseek_model: str = "",
):
    """Create a MagicMock config that returns Cartesia + DeepSeek settings."""
    config = MagicMock()

    def get_provider_settings(provider, model=None):
        if provider == "Cartesia":
            return {
                "api_key": cartesia_api_key,
                "base_url": cartesia_base_url,
                "realtime_base_url": realtime_base_url,
                "model": "",
            }
        if provider == "DeepSeek":
            return {
                "api_key": deepseek_api_key,
                "model": deepseek_model,
            }
        return {}

    config.get_provider_settings.side_effect = get_provider_settings
    config.get_all.return_value = {
        "default_models": {
            "Cartesia": {"tts_default": tts_default} if tts_default else {}
        }
    }
    return config


# ---------------------------------------------------------------------------
# Settings resolution tests
# ---------------------------------------------------------------------------

class TestResolveCartesiaSettings(unittest.TestCase):

    def test_success_with_defaults(self):
        service = DummyCartesiaService()
        service.config = _make_cartesia_config()
        settings = service._resolve_cartesia_settings(None)
        self.assertEqual(settings["api_key"], "csk-test-key")
        self.assertEqual(settings["tts_model"], DEFAULT_CARTESIA_MODEL)
        self.assertEqual(settings["llm_model"], "deepseek-v4-flash")
        self.assertEqual(settings["session_model"], DEFAULT_CARTESIA_REALTIME_MODEL)

    def test_ws_base_derived_from_http_base_url(self):
        service = DummyCartesiaService()
        service.config = _make_cartesia_config(cartesia_base_url="https://api.cartesia.ai")
        settings = service._resolve_cartesia_settings(None)
        self.assertEqual(settings["ws_base"], "wss://api.cartesia.ai")

    def test_realtime_base_url_overrides_derivation(self):
        service = DummyCartesiaService()
        service.config = _make_cartesia_config(
            realtime_base_url="wss://custom-realtime.cartesia.ai/",
        )
        settings = service._resolve_cartesia_settings(None)
        self.assertEqual(settings["ws_base"], "wss://custom-realtime.cartesia.ai")

    def test_custom_tts_model_from_config(self):
        service = DummyCartesiaService()
        service.config = _make_cartesia_config(tts_default="sonic-3.5")
        settings = service._resolve_cartesia_settings(None)
        self.assertEqual(settings["tts_model"], "sonic-3.5")

    def test_custom_llm_model(self):
        service = DummyCartesiaService()
        service.config = _make_cartesia_config(deepseek_model="deepseek-v3")
        settings = service._resolve_cartesia_settings(None)
        self.assertEqual(settings["llm_model"], "deepseek-v3")

    def test_session_model_from_param(self):
        service = DummyCartesiaService()
        service.config = _make_cartesia_config()
        settings = service._resolve_cartesia_settings("my-custom-model")
        self.assertEqual(settings["session_model"], "my-custom-model")

    def test_missing_cartesia_api_key_raises(self):
        service = DummyCartesiaService()
        service.config = _make_cartesia_config(cartesia_api_key="")
        with self.assertRaises(RuntimeError) as ctx:
            service._resolve_cartesia_settings(None)
        self.assertIn("Cartesia API Key 未配置", str(ctx.exception))

    def test_missing_deepseek_api_key_raises(self):
        service = DummyCartesiaService()
        service.config = _make_cartesia_config(deepseek_api_key="")
        with self.assertRaises(RuntimeError) as ctx:
            service._resolve_cartesia_settings(None)
        self.assertIn("DeepSeek API Key 未配置", str(ctx.exception))


# ---------------------------------------------------------------------------
# Barge-in tests
# ---------------------------------------------------------------------------

class TestCartesiaBargeIn(unittest.TestCase):

    def test_no_active_turn_returns_early(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            await service._cartesia_barge_in(ws, state, MagicMock(), None, notify=True)
            self.assertEqual(ws.events, [])
            self.assertIsNone(state.active)
        asyncio.run(run())

    def test_cancels_active_task_and_sends_interrupted(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            turn = _CartesiaTurn(seq=1, context_id="ctx-1", user_text="hello")
            turn.task = asyncio.create_task(asyncio.sleep(10))
            state.active = turn

            await service._cartesia_barge_in(ws, state, MagicMock(), None, notify=True)

            self.assertIsNone(state.active)
            self.assertTrue(turn.task.cancelled())
            events = [e for e in ws.events if e.get("type") == "interrupted"]
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["interrupted"])
        asyncio.run(run())

    def test_rolls_back_user_history_when_user_is_last(self):
        """The rollback only fires when the user turn is the LAST history entry
        (meaning the assistant hasn't replied yet — the unanswered question."""
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            turn = _CartesiaTurn(seq=1, context_id="ctx-1", user_text="hello")
            turn.task = asyncio.create_task(asyncio.sleep(0))
            state.active = turn
            state.history.append({"role": "user", "content": "hello"})

            await service._cartesia_barge_in(ws, state, MagicMock(), None, notify=False)

            self.assertEqual(len(state.history), 0)
        asyncio.run(run())

    def test_rolls_back_not_triggered_when_assistant_already_replied(self):
        """If the assistant already replied, the user turn is NOT the last entry
        and the rollback condition does not match — history is preserved."""
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            turn = _CartesiaTurn(seq=1, context_id="ctx-1", user_text="hello")
            turn.task = asyncio.create_task(asyncio.sleep(0))
            state.active = turn
            state.history.append({"role": "user", "content": "hello"})
            state.history.append({"role": "assistant", "content": "Hi there!"})

            await service._cartesia_barge_in(ws, state, MagicMock(), None, notify=False)

            # History unchanged — rollback only matches when user is the last entry
            self.assertEqual(len(state.history), 2)
        asyncio.run(run())

    def test_sends_cancel_to_tts_ws(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            tts_ws = FakeWs()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", tts_ws=tts_ws)
            turn = _CartesiaTurn(seq=1, context_id="ctx-1", user_text="hello")
            turn.task = asyncio.create_task(asyncio.sleep(0))
            state.active = turn

            await service._cartesia_barge_in(ws, state, MagicMock(), None, notify=False)

            self.assertEqual(len(tts_ws.sent), 1)
            cancel_msg = json.loads(tts_ws.sent[0])
            self.assertEqual(cancel_msg["context_id"], "ctx-1")
            self.assertTrue(cancel_msg["cancel"])
        asyncio.run(run())

    def test_notify_false_skips_interrupted_event(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            turn = _CartesiaTurn(seq=1, context_id="ctx-1", user_text="hello")
            turn.task = asyncio.create_task(asyncio.sleep(0))
            state.active = turn

            await service._cartesia_barge_in(ws, state, MagicMock(), None, notify=False)

            events = [e for e in ws.events if e.get("type") == "interrupted"]
            self.assertEqual(len(events), 0)
        asyncio.run(run())


# ---------------------------------------------------------------------------
# Start turn tests
# ---------------------------------------------------------------------------

class TestCartesiaStartTurn(unittest.TestCase):

    def test_empty_text_is_noop(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            mem = MagicMock()
            tool = MagicMock()
            llm = MagicMock()
            await service._cartesia_start_turn(ws, state, "  ", llm, mem, tool, None)
            self.assertIsNone(state.active)
            self.assertEqual(state.history, [])
        asyncio.run(run())

    def test_appends_user_text_and_creates_turn(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            mem = MagicMock()
            mem.note_user_transcript = MagicMock()
            mem.retrieve_memory_context = AsyncMock(return_value={"attempted": False})
            tool = MagicMock()
            llm = MagicMock()
            service._cartesia_generate = AsyncMock()

            await service._cartesia_start_turn(ws, state, "Hello cartesia", llm, mem, tool, None)

            self.assertEqual(len(state.history), 1)
            self.assertEqual(state.history[0], {"role": "user", "content": "Hello cartesia"})
            self.assertIsNotNone(state.active)
            self.assertEqual(state.active.user_text, "Hello cartesia")
            self.assertEqual(state.active.seq, 1)
            self.assertTrue(state.active.context_id.startswith("vs-1-"))
        asyncio.run(run())

    def test_calls_barge_in_before_new_turn(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            old_turn = _CartesiaTurn(seq=1, context_id="ctx-old", user_text="old")
            old_turn.task = asyncio.create_task(asyncio.sleep(0))
            state.active = old_turn
            mem = MagicMock()
            mem.note_user_transcript = MagicMock()
            mem.retrieve_memory_context = AsyncMock(return_value={"attempted": False})
            tool = MagicMock()
            llm = MagicMock()
            service._cartesia_generate = AsyncMock()

            await service._cartesia_start_turn(ws, state, "new question", llm, mem, tool, None)

            self.assertNotEqual(state.active.context_id, "ctx-old")
            self.assertEqual(state.active.user_text, "new question")
        asyncio.run(run())

    def test_sends_user_transcript_event(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            mem = MagicMock()
            mem.note_user_transcript = MagicMock()
            mem.retrieve_memory_context = AsyncMock(return_value={"attempted": False})
            tool = MagicMock()
            llm = MagicMock()
            service._cartesia_generate = AsyncMock()

            await service._cartesia_start_turn(ws, state, "test input", llm, mem, tool, None)

            transcripts = [e for e in ws.events if e.get("type") == "user_transcript"]
            self.assertEqual(len(transcripts), 1)
            self.assertEqual(transcripts[0]["text"], "test input")
            self.assertTrue(transcripts[0]["final"])
        asyncio.run(run())

    def test_retrieves_memory_context(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
            mem = MagicMock()
            mem.note_user_transcript = MagicMock()
            mem.retrieve_memory_context = AsyncMock(
                return_value={"attempted": True, "memories_retrieved": 3, "local_pending_count": 1, "cloud_count": 2}
            )
            tool = MagicMock()
            llm = MagicMock()
            service._cartesia_generate = AsyncMock()

            await service._cartesia_start_turn(ws, state, "recall something", llm, mem, tool, None)

            mem_events = [e for e in ws.events if e.get("type") == "memory_context"]
            self.assertEqual(len(mem_events), 1)
            self.assertEqual(mem_events[0]["memories_retrieved"], 3)
        asyncio.run(run())


# ---------------------------------------------------------------------------
# TTS loop tests
# ---------------------------------------------------------------------------

class TestCartesiaTtsLoop(unittest.TestCase):

    def test_chunk_delivered_for_active_context(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            tts_ws = FakeWs(events=[
                {"type": "chunk", "audio": "dGVzdA==", "context_id": "ctx-1"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", tts_ws=tts_ws)
            turn = _CartesiaTurn(seq=1, context_id="ctx-1", user_text="hello")
            state.active = turn

            task = asyncio.create_task(
                service._cartesia_tts_loop(ws, state, MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            audio_events = [e for e in ws.events if e.get("type") == "assistant_audio"]
            self.assertEqual(len(audio_events), 1)
            self.assertEqual(audio_events[0]["audio"], "dGVzdA==")
            self.assertEqual(audio_events[0]["encoding"], "pcm_s16le")
            self.assertEqual(audio_events[0]["sample_rate"], 24000)
        asyncio.run(run())

    def test_chunk_delivered_with_data_field(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            tts_ws = FakeWs(events=[
                {"type": "chunk", "data": "ZGF0YXRlc3Q=", "context_id": "ctx-1"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", tts_ws=tts_ws)
            turn = _CartesiaTurn(seq=1, context_id="ctx-1", user_text="hello")
            state.active = turn

            task = asyncio.create_task(
                service._cartesia_tts_loop(ws, state, MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            audio_events = [e for e in ws.events if e.get("type") == "assistant_audio"]
            self.assertEqual(len(audio_events), 1)
            self.assertEqual(audio_events[0]["audio"], "ZGF0YXRlc3Q=")
            self.assertEqual(audio_events[0]["encoding"], "pcm_s16le")
            self.assertEqual(audio_events[0]["sample_rate"], 24000)
        asyncio.run(run())

    def test_chunk_dropped_for_wrong_context(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            tts_ws = FakeWs(events=[
                {"type": "chunk", "audio": "abc", "context_id": "ctx-old"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", tts_ws=tts_ws)
            turn = _CartesiaTurn(seq=2, context_id="ctx-new", user_text="new")
            state.active = turn

            task = asyncio.create_task(
                service._cartesia_tts_loop(ws, state, MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            audio_events = [e for e in ws.events if e.get("type") == "assistant_audio"]
            self.assertEqual(len(audio_events), 0)
        asyncio.run(run())

    def test_done_event_finalizes_turn(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            tts_ws = FakeWs(events=[
                {"type": "done", "context_id": "ctx-1"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", tts_ws=tts_ws)
            turn = _CartesiaTurn(seq=1, context_id="ctx-1", user_text="hello")
            state.active = turn
            state.generation_done_seq = 1

            task = asyncio.create_task(
                service._cartesia_tts_loop(ws, state, MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            self.assertIsNone(state.active)
            service._finalize_realtime_turn.assert_called_once()
        asyncio.run(run())

    def test_done_ignored_when_generation_not_finished(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            tts_ws = FakeWs(events=[
                {"type": "done", "context_id": "ctx-1"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", tts_ws=tts_ws)
            turn = _CartesiaTurn(seq=2, context_id="ctx-1", user_text="hello")
            state.active = turn
            state.generation_done_seq = 0

            task = asyncio.create_task(
                service._cartesia_tts_loop(ws, state, MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            self.assertIsNotNone(state.active)
        asyncio.run(run())

    def test_error_event_forwarded(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            tts_ws = FakeWs(events=[
                {"type": "error", "message": "rate limited", "context_id": "ctx-1"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", tts_ws=tts_ws)

            task = asyncio.create_task(
                service._cartesia_tts_loop(ws, state, MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            error_events = [e for e in ws.events if e.get("type") == "error"]
            self.assertEqual(len(error_events), 1)
            self.assertIn("rate limited", error_events[0]["message"])
        asyncio.run(run())


# ---------------------------------------------------------------------------
# STT loop tests
# ---------------------------------------------------------------------------

class TestCartesiaSttLoop(unittest.TestCase):

    def test_turn_end_triggers_start_turn(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            stt_ws = FakeWs(events=[
                {"type": "turn.end", "transcript": "Hello cartesia"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", stt_ws=stt_ws)
            service._cartesia_start_turn = AsyncMock()

            task = asyncio.create_task(
                service._cartesia_stt_loop(ws, state, MagicMock(), MagicMock(), MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            service._cartesia_start_turn.assert_called_once()
            call_args = service._cartesia_start_turn.call_args
            self.assertEqual(call_args[0][2], "Hello cartesia")
        asyncio.run(run())

    def test_turn_end_with_empty_transcript_ignored(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            stt_ws = FakeWs(events=[
                {"type": "turn.end", "transcript": ""},
                {"type": "turn.end", "transcript": "  "},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", stt_ws=stt_ws)
            service._cartesia_start_turn = AsyncMock()

            task = asyncio.create_task(
                service._cartesia_stt_loop(ws, state, MagicMock(), MagicMock(), MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            service._cartesia_start_turn.assert_not_called()
        asyncio.run(run())

    def test_turn_start_triggers_barge_in(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            stt_ws = FakeWs(events=[
                {"type": "turn.start"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", stt_ws=stt_ws)
            service._cartesia_barge_in = AsyncMock()

            task = asyncio.create_task(
                service._cartesia_stt_loop(ws, state, MagicMock(), MagicMock(), MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            service._cartesia_barge_in.assert_called_once()
        asyncio.run(run())

    def test_stt_error_forwarded(self):
        async def run():
            service = DummyCartesiaService()
            ws = CollectingWebSocket()
            stt_ws = FakeWs(events=[
                {"type": "error", "message": "model not found"},
            ])
            state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l", stt_ws=stt_ws)

            task = asyncio.create_task(
                service._cartesia_stt_loop(ws, state, MagicMock(), MagicMock(), MagicMock(), None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            error_events = [e for e in ws.events if e.get("type") == "error"]
            self.assertEqual(len(error_events), 1)
            self.assertIn("Cartesia STT", error_events[0]["message"])
            self.assertIn("model not found", error_events[0]["message"])
        asyncio.run(run())


# ---------------------------------------------------------------------------
# TTS text noise stripping
# ---------------------------------------------------------------------------

class TestCartesiaTtsNoiseStripping(unittest.TestCase):

    def test_stars_and_hashes_stripped(self):
        self.assertEqual(_TTS_TEXT_NOISE_RE.sub("", "**bold** #heading"), "bold heading")

    def test_backticks_stripped(self):
        self.assertEqual(_TTS_TEXT_NOISE_RE.sub("", "code `inline`"), "code inline")

    def test_clean_text_unchanged(self):
        self.assertEqual(_TTS_TEXT_NOISE_RE.sub("", "Hello world!"), "Hello world!")


# ---------------------------------------------------------------------------
# Turn dataclass tests
# ---------------------------------------------------------------------------

class TestCartesiaTurnDataclass(unittest.TestCase):

    def test_default_task_is_none(self):
        turn = _CartesiaTurn(seq=1, context_id="c", user_text="t")
        self.assertIsNone(turn.task)

    def test_next_seq_increments(self):
        state = _CartesiaSessionState(tts_model="m", voice="v", llm_model="l")
        self.assertEqual(state.next_seq(), 1)
        self.assertEqual(state.next_seq(), 2)
        self.assertEqual(state.next_seq(), 3)


# ---------------------------------------------------------------------------
# Cartesia language inference
# ---------------------------------------------------------------------------

class TestInferCartesiaLanguage(unittest.TestCase):

    def test_chinese_returns_zh(self):
        self.assertEqual(infer_cartesia_language("你好世界"), "zh")

    def test_japanese_returns_ja(self):
        self.assertEqual(infer_cartesia_language("こんにちは"), "ja")

    def test_korean_returns_ko(self):
        self.assertEqual(infer_cartesia_language("안녕하세요"), "ko")

    def test_english_returns_en(self):
        self.assertEqual(infer_cartesia_language("Hello world"), "en")

    def test_mixed_cjk_latin_returns_cjk(self):
        self.assertEqual(infer_cartesia_language("Hello 你好"), "zh")


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

class TestCartesiaConstants(unittest.TestCase):

    def test_default_model(self):
        self.assertTrue(DEFAULT_CARTESIA_REALTIME_MODEL)

    def test_default_voice_is_uuid(self):
        uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
        self.assertTrue(uuid_re.match(DEFAULT_CARTESIA_REALTIME_VOICE))

    def test_stt_model(self):
        self.assertEqual(DEFAULT_CARTESIA_STT_MODEL, "ink-2")

    def test_tts_provider_voice_matches_constant(self):
        self.assertEqual(DEFAULT_CARTESIA_REALTIME_VOICE, DEFAULT_CARTESIA_VOICE)


if __name__ == "__main__":
    unittest.main()
