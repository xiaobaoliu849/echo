"""Tests for Qwen-Audio native realtime voice path (raw WebSocket, bypasses DashScope SDK).

Covers:
  - ``is_qwen_audio_model`` model detection
  - ``_build_qwen_audio_instructions`` with/without memory context
  - ``_qwen_audio_to_client_loop`` function_call gating (multi-call, finalize)
  - ``_handle_qwen_audio_function_call`` tool execution and response.create ordering

Bug-reproduction tests (TDD red phase):
  * test_multiple_function_calls_in_one_turn_waits_for_all_outputs  (P0)
  * test_function_call_round_does_not_finalize_turn                  (P0)
  * test_function_call_cancelled_response_not_finalized              (P0 variant)
"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.interruption_classifier import InterruptionDecisionCoordinator
from services.realtime_voice_service import RealtimeVoiceService
from services.voice_agent_tools import VoiceAgentToolSession, VoiceToolRequest


# ---------------------------------------------------------------------------
# Fakes / helpers (aligned with test_realtime_provider_replay.py patterns)
# ---------------------------------------------------------------------------


class CollectingWebSocket:
    """Collects every JSON payload sent to the client."""

    def __init__(self, inbound: list[dict] | None = None) -> None:
        self.events: list[dict] = []
        self.inbound = list(inbound or [])

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))

    async def receive(self) -> dict:
        if self.inbound:
            return self.inbound.pop(0)
        return {"type": "websocket.disconnect"}


class FakeDashWs:
    """Fake DashScope-side WebSocket.

    ``send`` collects every JSON string sent upstream;
    ``recv`` yields pre-programmed events then raises to break the loop.
    """

    def __init__(self, events: list[dict] | None = None) -> None:
        self.sent: list[str] = []
        self._events = list(events or [])

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str:
        if self._events:
            return json.dumps(self._events.pop(0))
        raise ConnectionError("no more events")

    def sent_payloads(self) -> list[dict]:
        """Return all sent payloads parsed back to dicts."""
        return [json.loads(s) for s in self.sent]


class FakeMemorySession:
    """Minimal stand-in for ``RealtimeMemorySession``."""

    def __init__(self) -> None:
        self.user_texts: list[str] = []
        self.assistant_texts: list[str] = []
        self._config = SimpleNamespace(
            memory_scope="",
            group_id="",
            get_service=lambda: None,
        )

    def note_user_transcript(self, text: str) -> None:
        self.user_texts.append(text)

    def note_assistant_text(self, text: str, *, cumulative: bool = False) -> None:
        self.assistant_texts.append(text)

    async def retrieve_memory_context(self) -> dict:
        return {
            "context": "",
            "memories_retrieved": 0,
            "local_pending_count": 0,
            "cloud_count": 0,
            "attempted": False,
        }

    async def flush_turn(self) -> dict:
        return {
            "attempted_count": 0,
            "saved_count": 0,
            "failed_count": 0,
            "local_pending_count": 0,
            "reason": "disabled",
        }

    def is_forced_recall_query(self, _text: str) -> bool:
        return False

    def configure(self, _cfg) -> None:
        pass

    async def drain(self) -> None:
        pass

    def discard_turn(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestQwenAudioRealtime(unittest.IsolatedAsyncioTestCase):
    """Qwen-Audio native function-calling realtime path tests."""

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    # ---- helpers -----------------------------------------------------------

    def _make_tool_session(self) -> VoiceAgentToolSession:
        """Return a real VoiceAgentToolSession whose service.run_tool is mocked."""
        ts = VoiceAgentToolSession()
        ts.service = MagicMock()
        ts.service.run_tool = AsyncMock(return_value={
            "tool_name": "search_web",
            "query": "test",
            "answer": "ok",
            "sources": [],
            "source_count": 0,
            "elapsed_ms": 10,
        })
        ts.service.extract_tool_request = MagicMock(return_value=None)
        return ts

    def _make_loop_deps(self, dash_events: list[dict]):
        """Build the standard collaborator set for ``_qwen_audio_to_client_loop``."""
        ws = CollectingWebSocket()
        dash_ws = FakeDashWs(dash_events)
        memory = FakeMemorySession()
        tool_session = self._make_tool_session()
        interruption = InterruptionDecisionCoordinator()
        return ws, dash_ws, memory, tool_session, interruption

    # ---- 1-3: correct-behavior regression baseline -------------------------

    def test_is_qwen_audio_model_detection(self):
        """is_qwen_audio_model returns True for qwen-audio* models, False otherwise."""
        svc = RealtimeVoiceService
        # True cases
        self.assertTrue(svc.is_qwen_audio_model("qwen-audio-3.0-realtime-plus"))
        self.assertTrue(svc.is_qwen_audio_model("QWEN-AUDIO-flash"))
        self.assertTrue(svc.is_qwen_audio_model("qwen-audio"))
        # False cases
        self.assertFalse(svc.is_qwen_audio_model("qwen-realtime"))
        self.assertFalse(svc.is_qwen_audio_model(None))
        self.assertFalse(svc.is_qwen_audio_model(""))
        self.assertFalse(svc.is_qwen_audio_model("gpt-4o"))

    def test_build_instructions_without_memory(self):
        """_build_qwen_audio_instructions returns non-empty string containing 小云."""
        result = RealtimeVoiceService._build_qwen_audio_instructions()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)
        self.assertIn("小云", result)

    def test_build_instructions_with_memory_appends_context(self):
        """_build_qwen_audio_instructions appends memory context when provided."""
        memory_ctx = "用户喜欢喝拿铁，住在北京"
        result = RealtimeVoiceService._build_qwen_audio_instructions(memory_ctx)
        self.assertIn("小云", result)
        self.assertIn(memory_ctx, result)

    # ---- 4: P0 bug – multiple concurrent function calls --------------------

    async def test_multiple_function_calls_in_one_turn_waits_for_all_outputs(self):
        """Two function_calls in one turn: response.create must wait for BOTH outputs.

        Expected (correct) behavior:
          - function_call_output for call_1 AND call_2 are sent BEFORE response.create
          - exactly ONE response.create is sent for the second round
          - no turn_complete is emitted on the function_call round's response.done

        Current bug: the loop fires response.create after the FIRST arguments.done
        and ``gated_native_fc_call_id`` is a single string that cannot track two
        concurrent calls.
        """
        events = [
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "call_1", "name": "search_web"}},
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "call_2", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "call_1", "name": "search_web", "arguments": '{"query":"a"}'},
            {"type": "response.function_call_arguments.done",
             "call_id": "call_2", "name": "search_web", "arguments": '{"query":"b"}'},
            {"type": "response.done",
             "response": {"id": "resp_1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        payloads = dash_ws.sent_payloads()

        # Collect all function_call_output sends and response.create sends
        fc_outputs = [
            p for p in payloads
            if p.get("type") == "conversation.item.create"
            and (p.get("item") or {}).get("type") == "function_call_output"
        ]
        response_creates = [p for p in payloads if p.get("type") == "response.create"]

        # There should be exactly 2 function_call_output items
        self.assertEqual(len(fc_outputs), 2,
                         f"Expected 2 function_call_output sends, got {len(fc_outputs)}. "
                         f"All sent: {payloads}")

        # There should be exactly 1 response.create (the second round)
        self.assertEqual(len(response_creates), 1,
                         f"Expected exactly 1 response.create, got {len(response_creates)}. "
                         f"All sent: {payloads}")

        # The single response.create must come AFTER both function_call_outputs
        fc_output_indices = [
            i for i, p in enumerate(payloads)
            if p.get("type") == "conversation.item.create"
            and (p.get("item") or {}).get("type") == "function_call_output"
        ]
        response_create_indices = [
            i for i, p in enumerate(payloads)
            if p.get("type") == "response.create"
        ]
        if fc_output_indices and response_create_indices:
            first_rc = response_create_indices[0]
            self.assertTrue(
                all(idx < first_rc for idx in fc_output_indices),
                f"All function_call_output sends (indices {fc_output_indices}) must come "
                f"before response.create (index {first_rc}). Payloads: {payloads}"
            )

        # The call_ids written back must cover both call_1 and call_2
        written_call_ids = {
            (p.get("item") or {}).get("call_id", "")
            for p in fc_outputs
        }
        self.assertEqual(written_call_ids, {"call_1", "call_2"},
                         f"Both call_1 and call_2 outputs must be written back. "
                         f"Got: {written_call_ids}")

        # No turn_complete should be sent for the function_call round
        client_event_types = [e.get("type") for e in ws.events]
        self.assertNotIn("turn_complete", client_event_types,
                         f"turn_complete must NOT be sent on function_call round. "
                         f"Client events: {client_event_types}")

    # ---- 5: P0 bug – function_call round must not finalize turn ------------

    async def test_function_call_round_does_not_finalize_turn(self):
        """A response.done for a round containing function_call must NOT send turn_complete.

        After function_call_arguments.done the service sends response.create for
        the second round; the turn is NOT finished yet.  The client should not
        receive ``turn_complete`` until the *second* response.done arrives.
        """
        events = [
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c1", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "c1", "name": "search_web", "arguments": '{"query":"x"}'},
            {"type": "response.done",
             "response": {"id": "resp_fc", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        client_event_types = [e.get("type") for e in ws.events]

        # turn_complete must NOT appear — the turn is not done (second round pending)
        self.assertNotIn(
            "turn_complete", client_event_types,
            f"turn_complete must NOT be sent after a function_call round. "
            f"Client events: {client_event_types}"
        )

        # response.create should have been sent to trigger the second round
        payloads = dash_ws.sent_payloads()
        response_creates = [p for p in payloads if p.get("type") == "response.create"]
        self.assertGreaterEqual(
            len(response_creates), 1,
            f"At least 1 response.create expected (second round). Sent: {payloads}"
        )

        # function_call_output should have been written back
        fc_outputs = [
            p for p in payloads
            if p.get("type") == "conversation.item.create"
            and (p.get("item") or {}).get("type") == "function_call_output"
        ]
        self.assertEqual(len(fc_outputs), 1)
        self.assertEqual(fc_outputs[0]["item"]["call_id"], "c1")

    # ---- 6: P0 bug variant – cancelled function_call response ---------------

    async def test_function_call_cancelled_response_not_finalized(self):
        """A function_call followed by response.done with status=cancelled.

        Expected behavior:
          - The function_call_output IS written back (tool already ran).
          - NO turn_complete is sent (response was cancelled, turn not completed).
          - No memory_write either (cancelled responses skip finalize).
        """
        events = [
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c1", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "c1", "name": "search_web", "arguments": '{"query":"x"}'},
            {"type": "response.done",
             "response": {"id": "resp_cancel", "status": "cancelled"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        client_event_types = [e.get("type") for e in ws.events]

        # turn_complete must NOT be sent for a cancelled response
        self.assertNotIn(
            "turn_complete", client_event_types,
            f"turn_complete must NOT be sent for cancelled function_call response. "
            f"Client events: {client_event_types}"
        )

        # memory_write must NOT be sent either (cancelled → skip finalize)
        self.assertNotIn(
            "memory_write", client_event_types,
            f"memory_write must NOT be sent for cancelled response. "
            f"Client events: {client_event_types}"
        )

        # function_call_output should still have been written back
        payloads = dash_ws.sent_payloads()
        fc_outputs = [
            p for p in payloads
            if p.get("type") == "conversation.item.create"
            and (p.get("item") or {}).get("type") == "function_call_output"
        ]
        self.assertEqual(len(fc_outputs), 1)
        self.assertEqual(fc_outputs[0]["item"]["call_id"], "c1")

        # response.create should have been sent (to continue conversation)
        response_creates = [p for p in payloads if p.get("type") == "response.create"]
        self.assertGreaterEqual(
            len(response_creates), 1,
            f"response.create expected after writing function_call_output. Sent: {payloads}"
        )

    # ---- 7-8: Review edge cases – trigger_response=False error paths ---------

    async def test_unknown_tool_in_multi_call_sends_single_response_create(self):
        """Unknown tool name in a multi-call turn must not double-fire response.create.

        The unknown-tool branch writes an error function_call_output WITHOUT sending
        its own response.create (trigger_response=False); the loop sends exactly one
        response.create after ALL pending calls (including the valid one) resolve.
        """
        events = [
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "call_bad", "name": "fly_to_moon"}},
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "call_ok", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "call_bad", "name": "fly_to_moon", "arguments": '{}'},
            {"type": "response.function_call_arguments.done",
             "call_id": "call_ok", "name": "search_web", "arguments": '{"query":"a"}'},
            {"type": "response.done",
             "response": {"id": "resp_mix", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        payloads = dash_ws.sent_payloads()
        fc_outputs = [
            p for p in payloads
            if p.get("type") == "conversation.item.create"
            and (p.get("item") or {}).get("type") == "function_call_output"
        ]
        response_creates = [p for p in payloads if p.get("type") == "response.create"]

        # Both call_bad (error) and call_ok (real) outputs written back
        self.assertEqual(len(fc_outputs), 2,
                         f"Both error + real outputs must be written. Sent: {payloads}")
        written_ids = {(p.get("item") or {}).get("call_id") for p in fc_outputs}
        self.assertEqual(written_ids, {"call_bad", "call_ok"})

        # Exactly ONE response.create even though unknown-tool branch ran
        self.assertEqual(len(response_creates), 1,
                         f"Expected exactly 1 response.create, got {len(response_creates)}. "
                         f"Sent: {payloads}")

        # Error output for unknown tool
        bad = next(p for p in fc_outputs if (p.get("item") or {}).get("call_id") == "call_bad")
        self.assertIn("error", bad["item"]["output"])

        # No premature finalize
        client_event_types = [e.get("type") for e in ws.events]
        self.assertNotIn("turn_complete", client_event_types)

    async def test_missing_query_param_in_multi_call_sends_single_response_create(self):
        """A function_call with a missing required query writes an error output and
        still defers response.create to the loop (single fire for the whole turn)."""
        events = [
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c_empty", "name": "search_web"}},
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c_good", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "c_empty", "name": "search_web", "arguments": '{"query":"  "}'},
            {"type": "response.function_call_arguments.done",
             "call_id": "c_good", "name": "search_web", "arguments": '{"query":"real"}'},
            {"type": "response.done",
             "response": {"id": "resp_mix2", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        payloads = dash_ws.sent_payloads()
        fc_outputs = [
            p for p in payloads
            if p.get("type") == "conversation.item.create"
            and (p.get("item") or {}).get("type") == "function_call_output"
        ]
        response_creates = [p for p in payloads if p.get("type") == "response.create"]

        self.assertEqual(len(fc_outputs), 2, f"Sent: {payloads}")
        self.assertEqual(len(response_creates), 1,
                         f"Expected exactly 1 response.create, got {len(response_creates)}. "
                         f"Sent: {payloads}")
        empty = next(p for p in fc_outputs if (p.get("item") or {}).get("call_id") == "c_empty")
        self.assertIn("error", empty["item"]["output"])
        client_event_types = [e.get("type") for e in ws.events]
        self.assertNotIn("turn_complete", client_event_types)
    # ---- 9: regression – ws URL must come from realtime_base_url -------------

    async def test_audio_session_uses_configured_workspace_realtime_url(self):
        """stream_dashscope_audio_session must dial settings['realtime_base_url'].

        Regression: the raw-WebSocket path previously read a non-existent
        ``settings['region']`` key (KeyError: 'region') and hard-coded the
        public dashscope.aliyuncs.com domain, while qwen-audio-3.0-realtime
        only works on the cn-beijing workspace maas URL.
        """
        workspace_url = "wss://ws-abc123.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
        service = self.service
        service._resolve_dashscope_settings = MagicMock(return_value={
            "api_key": "sk-test",
            "model": "qwen-audio-3.0-realtime-flash",
            "realtime_base_url": workspace_url,
        })
        service._create_voice_session_recorder = AsyncMock(return_value=None)

        dash_ws = FakeDashWs([
            {"type": "session.created", "session": {"id": "sess-1"}},
        ])  # handshake succeeds; subsequent recv raises ConnectionError

        class _FakeConnect:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            def __call__(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return self

            async def __aenter__(self):
                return dash_ws

            async def __aexit__(self, *exc):
                return False

        fake_connect = _FakeConnect()
        with patch("services.realtime_qwen_audio_provider.websockets") as ws_module:
            ws_module.connect = fake_connect
            client_ws = CollectingWebSocket()
            await service.stream_dashscope_audio_session(
                client_ws,
                model="qwen-audio-3.0-realtime-flash",
                voice="longanqian",
            )

        self.assertEqual(len(fake_connect.calls), 1)
        dialed_url = fake_connect.calls[0][0]
        self.assertEqual(
            dialed_url,
            f"{workspace_url}?model=qwen-audio-3.0-realtime-flash",
            f"Must dial the configured workspace realtime URL. Got: {dialed_url}",
        )
        # The KeyError: 'region' regression surfaced as an error event whose
        # message was literally "'region'"; session_open proves we got past
        # URL construction and session.update instead.
        event_types = [e.get("type") for e in client_ws.events]
        self.assertIn("session_open", event_types,
                      f"session_open expected; events: {client_ws.events}")
        error_messages = [str(e.get("message", "")) for e in client_ws.events
                          if e.get("type") == "error"]
        self.assertFalse(any("'region'" in m for m in error_messages),
                         f"KeyError 'region' regression: {error_messages}")

    # ---- 10: handshake surfaces server error events --------------------------

    async def test_audio_session_handshake_surfaces_server_error_event(self):
        """A server `error` event during handshake must reach the client verbatim.

        Previously the handshake read one message and ignored its content, so a
        server-side rejection (bad voice/param/workspace) looked like a random
        later failure instead of the real reason.
        """
        workspace_url = "wss://ws-abc123.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
        service = self.service
        service._resolve_dashscope_settings = MagicMock(return_value={
            "api_key": "sk-test",
            "model": "qwen-audio-3.0-realtime-flash",
            "realtime_base_url": workspace_url,
        })
        service._create_voice_session_recorder = AsyncMock(return_value=None)

        dash_ws = FakeDashWs([
            {"type": "error", "error": {"message": "model not enabled for workspace"}},
        ])

        class _FakeConnect:
            def __call__(self, url, **kwargs):
                return self

            async def __aenter__(self):
                return dash_ws

            async def __aexit__(self, *exc):
                return False

        with patch("services.realtime_qwen_audio_provider.websockets") as ws_module:
            ws_module.connect = _FakeConnect()
            client_ws = CollectingWebSocket()
            await service.stream_dashscope_audio_session(
                client_ws,
                model="qwen-audio-3.0-realtime-flash",
                voice="longanqian",
            )

        event_types = [e.get("type") for e in client_ws.events]
        self.assertNotIn("session_open", event_types)
        error_messages = [str(e.get("message", "")) for e in client_ws.events
                          if e.get("type") == "error"]
        self.assertTrue(
            any("model not enabled for workspace" in m for m in error_messages),
            f"Server error detail must reach the client. Events: {client_ws.events}",
        )

    async def test_audio_session_handshake_timeout_has_explicit_message(self):
        """A silent server must produce an explicit timeout error, not an empty one.

        Regression: the bare TimeoutError from wait_for has an empty str(), which
        reached the client as 'Qwen-Audio 实时会话启动失败: ' with no detail.
        """
        workspace_url = "wss://ws-abc123.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
        service = self.service
        service._resolve_dashscope_settings = MagicMock(return_value={
            "api_key": "sk-test",
            "model": "qwen-audio-3.0-realtime-flash",
            "realtime_base_url": workspace_url,
        })
        service._create_voice_session_recorder = AsyncMock(return_value=None)

        class _HangingDashWs(FakeDashWs):
            async def recv(self) -> str:
                await asyncio.sleep(60)
                raise AssertionError("unreachable")

        dash_ws = _HangingDashWs()

        class _FakeConnect:
            def __call__(self, url, **kwargs):
                return self

            async def __aenter__(self):
                return dash_ws

            async def __aexit__(self, *exc):
                return False

        import time as real_time_module
        monotonic_state = {"calls": 0}

        def fake_monotonic() -> float:
            # First call computes the 15s handshake deadline; later calls
            # simulate the deadline having expired.
            monotonic_state["calls"] += 1
            return 0.0 if monotonic_state["calls"] == 1 else 100.0

        with patch("services.realtime_qwen_audio_provider.websockets") as ws_module, \
                patch("services.realtime_qwen_audio_provider.time", wraps=real_time_module) as fake_time:
            ws_module.connect = _FakeConnect()
            fake_time.monotonic = fake_monotonic
            client_ws = CollectingWebSocket()
            await service.stream_dashscope_audio_session(
                client_ws,
                model="qwen-audio-3.0-realtime-flash",
                voice="longanqian",
            )

        error_messages = [str(e.get("message", "")) for e in client_ws.events
                          if e.get("type") == "error"]
        self.assertTrue(error_messages, f"Expected an error event. Events: {client_ws.events}")
        self.assertTrue(
            all(m.strip() and not m.rstrip().endswith(":") for m in error_messages),
            f"Error message must not be empty. Events: {client_ws.events}",
        )
        self.assertTrue(
            any("session.created" in m for m in error_messages),
            f"Timeout message should mention session.created. Events: {client_ws.events}",
        )
    # ---- 11: no manual response.create on transcription.completed -------------

    async def test_transcription_completed_does_not_send_response_create(self):
        """With server-side turn detection (server_vad/smart_turn), the server
        auto-creates the response after finalizing the transcript. The backend
        must NOT send its own response.create — it races ongoing speech and the
        server rejects it with 'Cannot create response while user is speaking'.
        """
        events = [
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "你好"},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        payloads = dash_ws.sent_payloads()
        response_creates = [p for p in payloads if p.get("type") == "response.create"]
        self.assertEqual(response_creates, [],
                         f"No response.create expected on transcription.completed. "
                         f"Sent: {payloads}")
        # The transcript itself must still be forwarded to the client.
        user_transcripts = [e for e in ws.events if e.get("type") == "user_transcript"]
        self.assertEqual(len(user_transcripts), 1)
        self.assertEqual(user_transcripts[0].get("text"), "你好")

    # ---- 12: duplicate text/audio_transcript delta streams --------------------

    async def test_duplicate_text_streams_forwarded_once(self):
        """With modalities [text,audio] the model streams identical content over
        response.text.delta AND response.audio_transcript.delta; only ONE family
        may be forwarded or the client transcript duplicates every sentence, and
        the clean text family is preferred over the audio transcript.
        """
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "你好呀"},
            {"type": "response.text.delta", "response_id": "r1", "delta": "你好呀"},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "！今天过得怎么样"},
            {"type": "response.text.delta", "response_id": "r1",
             "delta": "！今天过得怎么样"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual(assistant_texts, ["你好呀", "！今天过得怎么样"],
                         f"Only one delta family may be forwarded. Got: {assistant_texts}")

    async def test_text_delta_family_preferred_over_degraded_audio_transcript(self):
        """The audio_transcript family is a server-side ASR of the model's own TTS
        audio and degrades for accented non-native speech (e.g. a Chinese voice
        speaking English). When both families stream DIFFERENT content, the clean
        text family must win even though audio_transcript arrived first.
        """
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            # Garbled audio transcript arrives first...
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "raining data"},
            # ...but the clean text delta claims the response.
            {"type": "response.text.delta", "response_id": "r1",
             "delta": "training data"},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": " might have influenced"},
            {"type": "response.text.delta", "response_id": "r1",
             "delta": " might have influenced"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual(assistant_texts, ["training data", " might have influenced"],
                         f"Only the clean text family may be forwarded. Got: {assistant_texts}")

    async def test_audio_transcript_only_stream_forwarded_after_hold(self):
        """When no text.delta exists at all, the audio_transcript family must still
        be forwarded: the first delta is held for one event, the second delta locks
        the family and replays the held delta in order.
        """
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "第一句。"},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "第二句。"},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "第三句。"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual(assistant_texts, ["第一句。", "第二句。", "第三句。"],
                         f"Audio-transcript-only stream must be forwarded in order. Got: {assistant_texts}")

    async def test_single_held_audio_delta_flushed_on_response_done(self):
        """A lone audio_transcript delta (held awaiting the family decision) must
        be flushed when response.done arrives, not dropped."""
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "你好", "item_id": "msg_1"},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "只有一句"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual(assistant_texts, ["只有一句"],
                         f"Held delta must be flushed on response.done. Got: {assistant_texts}")
        event_types = [e.get("type") for e in ws.events]
        self.assertLess(event_types.index("assistant_text"), event_types.index("turn_complete"),
                        f"assistant_text must come before turn_complete. Events: {event_types}")

    # ---- 13: benign server errors must not kill the session -------------------

    async def test_benign_response_create_race_error_does_not_end_session(self):
        """'Cannot create response while user is speaking' is a benign race with
        the server's turn management; the loop must ignore it and keep going
        instead of forwarding an error and tearing the session down.
        """
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "error",
             "error": {"message": "Cannot create response while user is speaking."}},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "继续回答"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        client_event_types = [e.get("type") for e in ws.events]
        self.assertNotIn("error", client_event_types,
                         f"Benign race error must not reach the client. Events: {ws.events}")
        # The session kept processing: the delta after the error was forwarded.
        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual(assistant_texts, ["继续回答"])
        self.assertIn("turn_complete", client_event_types)

    async def test_tool_events_not_delayed_by_pending_transcript(self):
        """When a native function_call fires before the ASR transcript, tool events
        (tool_call_started, agent_progress, tool_call_completed, agent_result) must
        be forwarded IMMEDIATELY — not buffered behind the final transcript.

        Regression test for the "工具调用半天了桌面上才显示" bug: buffering tool
        events until the (often late) server_vad transcript left the desktop UI
        silent for the entire search. Tool events are status chrome; the user's
        live interim transcript already occupies the user bubble, so forwarding
        them instantly cannot scramble the conversation order. AI text/audio is
        still held until the final transcript so the reply stays below the user
        bubble.
        """
        events = [
            # User speech starts (resets the per-turn transcript flag)
            {"type": "input_audio_buffer.speech_started"},
            # response.created starts buffering AI output
            {"type": "response.created", "response": {"id": "r1"}},
            # function_call fires BEFORE transcript
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c1", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "c1", "name": "search_web", "arguments": '{"query":"test"}'},
            # Simulate tool result → response.create
            {"type": "response.created", "response": {"id": "r2"}},
            # Now the transcript finally arrives
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "帮我搜索一下", "item_id": "msg_1"},
            # AI text follows
            {"type": "response.audio_transcript.delta", "response_id": "r2",
             "delta": "搜索结果显示"},
            {"type": "response.done", "response": {"id": "r2", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        # run_tool sends tool_call_started/agent_progress/tool_call_completed/agent_result
        tool_session.service.run_tool = AsyncMock()
        async def run_tool_side_effect(request, *, send_event, turn_id):
            await send_event("tool_call_started",
                {"tool_name": "search_web", "query": "test", "turn_id": turn_id})
            await send_event("agent_progress",
                {"stage": "search", "message": "found 1 result", "turn_id": turn_id})
            await send_event("tool_call_completed",
                {"tool_name": "search_web", "query": "test", "turn_id": turn_id, "source_count": 1})
            await send_event("agent_result",
                {"tool_name": "search_web", "query": "test", "answer": "ok", "sources": [],
                 "source_count": 1, "turn_id": turn_id})
            return {"tool_name": "search_web", "query": "test", "answer": "ok",
                    "sources": [], "source_count": 1}
        tool_session.service.run_tool.side_effect = run_tool_side_effect

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]
        user_idx = event_types.index("user_transcript") if "user_transcript" in event_types else -1
        tool_started_idx = event_types.index("tool_call_started") if "tool_call_started" in event_types else -1
        agent_result_idx = event_types.index("agent_result") if "agent_result" in event_types else -1
        assistant_idx = event_types.index("assistant_text") if "assistant_text" in event_types else -1

        self.assertGreater(user_idx, -1, "user_transcript must be emitted")
        self.assertGreater(tool_started_idx, -1, "tool_call_started must be emitted")
        self.assertGreater(agent_result_idx, -1, "agent_result must be emitted")
        self.assertGreater(assistant_idx, -1, "assistant_text must be emitted")

        # NEW guarantee: tool events reach the UI the moment the tool runs,
        # even though the final transcript hasn't arrived yet.
        self.assertLess(tool_started_idx, user_idx,
            f"tool_call_started must be forwarded immediately, before the late "
            f"user_transcript. Events: {event_types}")
        # Conversation content order is preserved: reply still below user bubble.
        self.assertLess(user_idx, assistant_idx,
            f"user_transcript must come before assistant_text. Events: {event_types}")
        self.assertLess(agent_result_idx, assistant_idx,
            f"agent_result must come before assistant_text. Events: {event_types}")

    async def test_pending_output_flush_order_tool_before_ai(self):
        """Flush order: user_transcript → tool events → AI output."""
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            # No function_call this time - just AI text
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "你好", "item_id": "msg_1"},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "你好！有什么可以帮助你的吗？"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]
        # Verify user_transcript comes before assistant_text
        user_idx = event_types.index("user_transcript")
        assistant_idx = event_types.index("assistant_text") if "assistant_text" in event_types else -1
        turn_complete_idx = event_types.index("turn_complete") if "turn_complete" in event_types else -1

        self.assertLess(user_idx, assistant_idx,
            f"user_transcript ({user_idx}) must come before assistant_text ({assistant_idx})")
        self.assertLess(assistant_idx, turn_complete_idx,
            f"assistant_text ({assistant_idx}) must come before turn_complete ({turn_complete_idx})")

    async def test_native_fc_occurred_flag_prevents_regex_double_trigger(self):
        """When a native function call has already occurred this turn, the transcript
        handler must skip the regex tool extraction path entirely — no response_gated,
        no response.cancel, no duplicate tool execution.
        """
        events = [
            # Turn starts
            {"type": "response.created", "response": {"id": "r1"}},
            # Native function call fires
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c1", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "c1", "name": "search_web", "arguments": '{"query":"test"}'},
            # Tool completes, response.create triggers follow-up
            {"type": "response.created", "response": {"id": "r2"}},
            # Transcript arrives — must NOT trigger regex path
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "帮我搜索一下", "item_id": "msg_1"},
            {"type": "response.audio_transcript.delta", "response_id": "r2",
             "delta": "根据搜索结果"},
            {"type": "response.done", "response": {"id": "r2", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        # Mock run_tool so native FC works
        tool_session.service.run_tool = AsyncMock(return_value={
            "tool_name": "search_web", "query": "test", "answer": "ok",
            "sources": [], "source_count": 0, "elapsed_ms": 10,
        })
        # Make extract_tool_request return a match so we can verify it's NOT called
        extract_calls = []
        orig_extract = tool_session.service.extract_tool_request
        def tracking_extract(text):
            extract_calls.append(text)
            return orig_extract(text)
        tool_session.service.extract_tool_request = MagicMock(side_effect=tracking_extract)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]
        # Must NOT emit response_gated (regex path was skipped)
        self.assertNotIn("response_gated", event_types,
            f"response_gated must NOT be emitted when native FC already occurred. Events: {event_types}")
        # Must NOT send response.cancel (no double execution)
        cancel_sent = any(
            json.loads(s).get("type") == "response.cancel"
            for s in dash_ws.sent
        )
        self.assertFalse(cancel_sent,
            f"response.cancel must NOT be sent when native FC already occurred. Sent: {dash_ws.sent}")
        # extract_tool_request must NOT be called (regex path skipped entirely)
        self.assertEqual(len(extract_calls), 0,
            f"extract_tool_request must NOT be called. Was called with: {extract_calls}")
        # user_transcript must still be emitted
        self.assertIn("user_transcript", event_types)

    async def test_native_fc_flag_reset_on_new_speech(self):
        """After a native FC turn completes, new user speech must reset the flag
        so that the regex path can work again on the next turn (if needed).
        """
        events = [
            # First turn: native FC occurs
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c1", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "c1", "name": "search_web", "arguments": '{"query":"t1"}'},
            {"type": "response.created", "response": {"id": "r2"}},
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "搜索 t1", "item_id": "msg_1"},
            {"type": "response.done", "response": {"id": "r2", "status": "completed"}},
            # New user speech starts (must reset flag)
            {"type": "input_audio_buffer.speech_started"},
            # Second turn: no native FC this time, regex SHOULD fire
            {"type": "response.created", "response": {"id": "r3"}},
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "搜索 t2", "item_id": "msg_2"},
            {"type": "response.done", "response": {"id": "r3", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        # run_tool for native FC in turn 1
        tool_session.service.run_tool = AsyncMock(return_value={
            "tool_name": "search_web", "query": "t1", "answer": "ok",
            "sources": [], "source_count": 0,
        })
        # extract_tool_request should match "搜索 t2" in turn 2
        from services.voice_agent_tools import VoiceAgentToolService, VoiceToolRequest
        extract_count = {"count": 0}
        def smart_extract(text):
            extract_count["count"] += 1
            if "t2" in text:
                return VoiceToolRequest(
                    tool_name="search_web", query="t2",
                    display_name="搜索网页资料",
                )
            return None
        tool_session.service.extract_tool_request = MagicMock(side_effect=smart_extract)
        # handle_user_transcript must handle the tool request for turn 2
        async def handle_transcript(text, *, send_event, on_result):
            req = smart_extract(text)
            if req is None:
                return ""
            return "voice-tool-turn2"
        tool_session.service.handle_user_transcript = MagicMock()
        tool_session.handle_user_transcript = AsyncMock(side_effect=handle_transcript)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]
        # Turn 1 must NOT have response_gated (native FC prevented regex)
        # Turn 2 SHOULD have response_gated (flag was reset, regex fires)
        # We can verify by checking extract_tool_request was called
        self.assertGreaterEqual(extract_count["count"], 1,
            f"extract_tool_request must be called at least once for turn 2. Count: {extract_count['count']}")


    # ---- 14: P0 bug – response.done arrives BEFORE ASR transcript ------------

    async def test_response_done_before_transcript_defers_turn_complete(self):
        """When response.done arrives before the ASR transcript, the turn must NOT
        be finalized until the transcript arrives.  The frontend must receive events
        in the correct order: user_transcript → assistant_text → turn_complete.

        This is the core bug: Qwen-Audio server_vad mode sends response.done before
        conversation.item.input_audio_transcription.completed because ASR runs
        asynchronously and doesn't block model inference.
        """
        events = [
            # User speech starts first (production server_vad sequence)
            {"type": "input_audio_buffer.speech_started"},
            # Model starts responding
            {"type": "response.created", "response": {"id": "r1"}},
            # Model streams text
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "你好呀！我是小云"},
            # Model finishes BEFORE the ASR transcript arrives
            {"type": "response.done",
             "response": {"id": "r1", "status": "completed"}},
            # ASR transcript finally arrives (late!)
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "Hello, can you hear me?", "item_id": "msg_1"},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]

        # user_transcript MUST be present
        self.assertIn("user_transcript", event_types,
            f"user_transcript must be emitted. Events: {event_types}")
        # assistant_text MUST be present
        self.assertIn("assistant_text", event_types,
            f"assistant_text must be emitted. Events: {event_types}")
        # turn_complete MUST be present
        self.assertIn("turn_complete", event_types,
            f"turn_complete must be emitted. Events: {event_types}")

        user_idx = event_types.index("user_transcript")
        assistant_idx = event_types.index("assistant_text")
        turn_complete_idx = event_types.index("turn_complete")

        # Correct ordering: user_transcript → assistant_text → turn_complete
        self.assertLess(user_idx, assistant_idx,
            f"user_transcript (idx={user_idx}) must come BEFORE assistant_text "
            f"(idx={assistant_idx}). Events: {event_types}")
        self.assertLess(assistant_idx, turn_complete_idx,
            f"assistant_text (idx={assistant_idx}) must come BEFORE turn_complete "
            f"(idx={turn_complete_idx}). Events: {event_types}")

        # Verify the transcript text is correct
        user_event = next(e for e in ws.events if e.get("type") == "user_transcript")
        self.assertEqual(user_event.get("text"), "Hello, can you hear me?")

    async def test_response_done_before_transcript_with_audio(self):
        """Same as above but with audio deltas — both text and audio must be
        buffered and flushed after the user transcript."""
        events = [
            {"type": "input_audio_buffer.speech_started"},
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.audio.delta", "response_id": "r1",
             "delta": "AAAA"},  # base64 audio
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "你好"},
            {"type": "response.done",
             "response": {"id": "r1", "status": "completed"}},
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "你好", "item_id": "msg_1"},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]
        user_idx = event_types.index("user_transcript")
        # Both assistant_text and assistant_audio must come after user_transcript
        for evt_type in ("assistant_text", "assistant_audio"):
            if evt_type in event_types:
                idx = event_types.index(evt_type)
                self.assertLess(user_idx, idx,
                    f"user_transcript must come before {evt_type}. Events: {event_types}")

    # ---- 15: tool call ordering when response.done arrives first -------------

    async def test_tool_events_immediate_when_response_done_first(self):
        """When a native function_call fires and response.done arrives before the
        ASR transcript, tool events are forwarded the moment they happen (UI
        progress), while the AI reply still waits for the user transcript.

        Sequence: speech_started → response.created → function_call
                  → response.done(fc round) → response.created(r2) → transcript
                  → audio → response.done(r2)
        """
        events = [
            {"type": "input_audio_buffer.speech_started"},
            # First response round: function call
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c1", "name": "search_web"}},
            {"type": "response.function_call_arguments.done",
             "call_id": "c1", "name": "search_web", "arguments": '{"query":"FIFA World Cup"}'},
            # FC round response.done (intermediate — must NOT finalize)
            {"type": "response.done",
             "response": {"id": "r1", "status": "completed"}},
            # Second response round: model answers from tool result
            {"type": "response.created", "response": {"id": "r2"}},
            # ASR transcript finally arrives
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "帮我搜索FIFA世界杯决赛", "item_id": "msg_1"},
            # Model streams the answer
            {"type": "response.audio_transcript.delta", "response_id": "r2",
             "delta": "根据搜索结果"},
            {"type": "response.done",
             "response": {"id": "r2", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        # Make run_tool emit tool events
        tool_session.service.run_tool = AsyncMock()
        async def run_tool_side_effect(request, *, send_event, turn_id):
            await send_event("tool_call_started",
                {"tool_name": "search_web", "query": "FIFA World Cup", "turn_id": turn_id})
            await send_event("tool_call_completed",
                {"tool_name": "search_web", "query": "FIFA World Cup", "turn_id": turn_id,
                 "source_count": 3})
            return {"tool_name": "search_web", "query": "FIFA World Cup", "answer": "ok",
                    "sources": [], "source_count": 3}
        tool_session.service.run_tool.side_effect = run_tool_side_effect

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]

        self.assertIn("user_transcript", event_types,
            f"user_transcript must be emitted. Events: {event_types}")
        self.assertIn("tool_call_started", event_types,
            f"tool_call_started must be emitted. Events: {event_types}")

        user_idx = event_types.index("user_transcript")
        tool_idx = event_types.index("tool_call_started")

        # Tool progress is instant — it must NOT wait for the late transcript.
        self.assertLess(tool_idx, user_idx,
            f"tool_call_started (idx={tool_idx}) must be forwarded immediately, "
            f"before the late user_transcript (idx={user_idx}). Events: {event_types}")

        # No premature turn_complete on the FC round
        # turn_complete should only appear once (after r2)
        turn_complete_count = event_types.count("turn_complete")
        self.assertEqual(turn_complete_count, 1,
            f"Exactly 1 turn_complete expected. Events: {event_types}")

    # ---- 16: timeout safety valve for deferred response.done -----------------

    async def test_transcript_timeout_flushes_deferred_response_done(self):
        """When the ASR transcript never arrives, the deferred response.done must
        be processed after TRANSCRIPT_WAIT_TIMEOUT, so the session doesn't hang."""
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "你好！"},
            {"type": "response.done",
             "response": {"id": "r1", "status": "completed"}},
            # No transcription.completed event — transcript never arrives!
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]

        # Even without a transcript, the AI output and turn_complete must be emitted
        # (after the timeout)
        self.assertIn("assistant_text", event_types,
            f"assistant_text must be emitted even without transcript. Events: {event_types}")
        self.assertIn("turn_complete", event_types,
            f"turn_complete must be emitted even without transcript. Events: {event_types}")

    # ---- 17: new speech flushes stale deferred response.done -----------------

    async def test_new_speech_flushes_stale_deferred_response_done(self):
        """When new speech starts while a response.done is still deferred (transcript
        never arrived), the stale deferred must be flushed and finalized before
        processing the new turn."""
        events = [
            # First turn: response completes but no transcript
            {"type": "input_audio_buffer.speech_started"},
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": "第一轮回复"},
            {"type": "response.done",
             "response": {"id": "r1", "status": "completed"}},
            # New speech starts — must flush the stale deferred
            {"type": "input_audio_buffer.speech_started"},
            # Second turn: normal flow
            {"type": "response.created", "response": {"id": "r2"}},
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "第二轮你好", "item_id": "msg_2"},
            {"type": "response.audio_transcript.delta", "response_id": "r2",
             "delta": "第二轮回复"},
            {"type": "response.done",
             "response": {"id": "r2", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        event_types = [e.get("type") for e in ws.events]

        # Both turns must produce turn_complete
        turn_complete_count = event_types.count("turn_complete")
        self.assertEqual(turn_complete_count, 2,
            f"Both turns must finalize. Events: {event_types}")

        # First turn's assistant_text must be present (flushed by speech_started)
        self.assertIn("assistant_text", event_types,
            f"First turn's assistant_text must be emitted. Events: {event_types}")

        # Second turn's user_transcript must be present
        user_transcripts = [e for e in ws.events if e.get("type") == "user_transcript"]
        self.assertEqual(len(user_transcripts), 1,
            f"Exactly 1 user_transcript expected (second turn). Events: {event_types}")
        self.assertEqual(user_transcripts[0].get("text"), "第二轮你好")

    # ---- 18: Qwen punctuation and response modalities tests -----------------

    def test_qwen_instructions_include_punctuation_directive(self):
        """_build_qwen_audio_instructions must include punctuation directive for clear sentence segmentation."""
        instructions = RealtimeVoiceService._build_qwen_audio_instructions()
        self.assertIn("标点符号", instructions)
        self.assertIn("切句清晰", instructions)

    async def test_response_create_specifies_explicit_modalities(self):
        """Function call follow-up response.create must send modalities: ['text', 'audio']."""
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.output_item.added", "item": {
                "type": "function_call", "call_id": "call_123", "name": "search_web",
            }},
            {"type": "response.function_call_arguments.done",
             "call_id": "call_123", "name": "search_web",
             "arguments": json.dumps({"query": "英伟达 微软 开源模型"})},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        sent_payloads = dash_ws.sent_payloads()
        response_creates = [p for p in sent_payloads if p.get("type") == "response.create"]
        self.assertTrue(len(response_creates) > 0, "response.create must be sent after tool output")
        rc = response_creates[0]
        self.assertEqual(rc.get("response", {}).get("modalities"), ["text", "audio"],
            f"response.create must specify modalities: ['text', 'audio']. Sent: {sent_payloads}")

    async def test_cross_family_continuation_prevents_text_truncation(self):
        """When text.delta stops streaming early after the preamble, audio_transcript.delta
        must continue supplying novel text so long responses are never truncated."""
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            # text.delta claims the response with a preamble...
            {"type": "response.text.delta", "response_id": "r1", "delta": "Here are latest news:"},
            # audio_transcript sends duplicate preamble (ignored)...
            {"type": "response.audio_transcript.delta", "response_id": "r1", "delta": "Here are latest news:"},
            # text.delta STOPS streaming! audio_transcript continues with novel items...
            {"type": "response.audio_transcript.delta", "response_id": "r1", "delta": " 1. OpenAI model escaped sandbox."},
            {"type": "response.audio_transcript.delta", "response_id": "r1", "delta": " 2. Google released Cyber Defender."},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events if e.get("type") == "assistant_text"]
        full_text = "".join(assistant_texts)
        self.assertIn("Here are latest news:", full_text)
        self.assertIn("1. OpenAI model escaped sandbox.", full_text)
        self.assertIn("2. Google released Cyber Defender.", full_text)

    # ---- sub-word token streaming (reported bug: "一个单词被分开了") ----------

    async def test_subword_token_deltas_are_not_split_into_separate_words(self):
        """A word streamed as several BPE tokens must not gain a space.

        The model tokenises "wonderful" as "wonder" + "ful"; neither fragment
        carries a leading space because they continue the same word.  Trimming a
        delta and re-inserting a word-boundary space between two Latin
        alphanumerics turns it into "wonder ful", which is what the user sees on
        screen while the audio says "wonderful".
        """
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.text.delta", "response_id": "r1", "delta": "That is"},
            {"type": "response.text.delta", "response_id": "r1", "delta": " wonder"},
            {"type": "response.text.delta", "response_id": "r1", "delta": "ful"},
            {"type": "response.text.delta", "response_id": "r1", "delta": "!"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual("".join(assistant_texts), "That is wonderful!")

    async def test_partial_overlap_between_deltas_does_not_eat_characters(self):
        """A coincidental suffix/prefix overlap must not drop a character.

        "Hel" ends with "l" and "lo" starts with "l"; treating that as a repeated
        fragment and dropping it yields "Helo".  An ordered WebSocket never
        re-delivers a delta, so every byte it sends is real.
        """
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.text.delta", "response_id": "r1", "delta": "Hel"},
            {"type": "response.text.delta", "response_id": "r1", "delta": "lo"},
            {"type": "response.text.delta", "response_id": "r1", "delta": " there"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual("".join(assistant_texts), "Hello there")

    async def test_repeated_fragment_is_not_deduplicated_away(self):
        """Speech genuinely repeats fragments, so identical consecutive deltas
        from the owning family must both survive."""
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.text.delta", "response_id": "r1", "delta": "ha"},
            {"type": "response.text.delta", "response_id": "r1", "delta": "ha"},
            {"type": "response.text.delta", "response_id": "r1", "delta": "ha"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual("".join(assistant_texts), "hahaha")

    async def test_cross_family_continuation_preserves_the_word_boundary_space(self):
        """The novel cross-family delta is forwarded verbatim.

        Its leading space is the boundary against the preamble; deriving the
        emitted text from an overlap merge instead drops it whenever the
        preceding character is punctuation ("news:" + " 1." -> "news:1.").
        """
        events = [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.text.delta", "response_id": "r1",
             "delta": "Here are latest news:"},
            {"type": "response.audio_transcript.delta", "response_id": "r1",
             "delta": " 1. OpenAI model escaped sandbox."},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        ]
        ws, dash_ws, memory, tool_session, interruption = self._make_loop_deps(events)

        await self.service._qwen_audio_to_client_loop(
            ws, dash_ws, memory, "test-voice", tool_session, None, interruption,
        )

        assistant_texts = [e.get("text", "") for e in ws.events
                           if e.get("type") == "assistant_text"]
        self.assertEqual(
            "".join(assistant_texts),
            "Here are latest news: 1. OpenAI model escaped sandbox.",
        )


if __name__ == "__main__":
    unittest.main()

