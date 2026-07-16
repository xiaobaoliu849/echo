"""Tests for Qwen-Audio native realtime voice path (raw WebSocket, bypasses DashScope SDK).

Covers:
  - ``_is_qwen_audio_model`` model detection
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

# NOTE: ``VoiceToolRequest`` is imported at module level in realtime_voice_service.py.
# (Previously a test-side injection worked around a missing import; that NameError is
# now fixed in source, so tests import it directly and exercise the real import path.)


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

    def note_assistant_text(self, text: str) -> None:
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
        """_is_qwen_audio_model returns True for qwen-audio* models, False otherwise."""
        svc = RealtimeVoiceService
        # True cases
        self.assertTrue(svc._is_qwen_audio_model("qwen-audio-3.0-realtime-plus"))
        self.assertTrue(svc._is_qwen_audio_model("QWEN-AUDIO-flash"))
        self.assertTrue(svc._is_qwen_audio_model("qwen-audio"))
        # False cases
        self.assertFalse(svc._is_qwen_audio_model("qwen-realtime"))
        self.assertFalse(svc._is_qwen_audio_model(None))
        self.assertFalse(svc._is_qwen_audio_model(""))
        self.assertFalse(svc._is_qwen_audio_model("gpt-4o"))

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


if __name__ == "__main__":
    unittest.main()
