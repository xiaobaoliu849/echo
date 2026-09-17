import json
import tempfile
import unittest
from pathlib import Path

from services.config_loader import BackendConfig
from services.llm_service import LLMService
from services.realtime_constants import (
    DEFAULT_GOOGLE_REALTIME_VOICE,
    DEFAULT_VERCEL_REALTIME_MODEL,
    DEFAULT_VERCEL_REALTIME_VOICE,
    VERCEL_GEMINI_3_8_LIVE,
    VERCEL_GEMINI_3_8_LIVE_EXTENDED_THINKING,
    _is_vercel_realtime_model,
)
from services.realtime_vercel_provider import (
    VercelRealtimeMixin,
    _normalize_vercel_voice,
)
from services.realtime_voice_service import RealtimeVoiceService
from routers.settings import VERCEL_MODEL_LIST_SUPPLEMENTS


class VercelGemini38LiveTests(unittest.TestCase):
    """Tests for Gemini 3.8 Live & Extended Thinking on Vercel AI Gateway."""

    def _config(self, initial: dict | None = None, **overrides) -> BackendConfig:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        config_path = Path(tmp_dir.name) / "config.json"
        config_path.write_text(json.dumps(initial or {}), encoding="utf-8")
        cfg = BackendConfig(config_path=config_path)
        cfg.reload(force=True)
        if overrides:
            cfg.update(overrides)
        return cfg

    def test_model_constants_and_detection(self):
        self.assertEqual(VERCEL_GEMINI_3_8_LIVE, "google/gemini-3.8-live")
        self.assertEqual(VERCEL_GEMINI_3_8_LIVE_EXTENDED_THINKING, "google/gemini-3.8-live-extended-thinking")

        # Models with 'live' under creator/model-name format are identified as Vercel realtime models
        self.assertTrue(_is_vercel_realtime_model("google/gemini-3.8-live"))
        self.assertTrue(_is_vercel_realtime_model("google/gemini-3.8-live-extended-thinking"))
        self.assertTrue(_is_vercel_realtime_model("openai/gpt-realtime-2"))
        self.assertTrue(_is_vercel_realtime_model("spacexai/grok-voice-think-fast-1.0"))

        # Non-realtime or non-gateway models
        self.assertFalse(_is_vercel_realtime_model("google/gemini-2.5-flash"))
        self.assertFalse(_is_vercel_realtime_model("openai/gpt-4o"))
        self.assertFalse(_is_vercel_realtime_model("gemini-3.8-live"))  # missing provider prefix
        self.assertFalse(_is_vercel_realtime_model(""))

    def test_settings_supplements_include_gemini_3_8_live(self):
        self.assertIn("google/gemini-3.8-live", VERCEL_MODEL_LIST_SUPPLEMENTS)
        self.assertIn("google/gemini-3.8-live-extended-thinking", VERCEL_MODEL_LIST_SUPPLEMENTS)

    def test_normalize_vercel_voice(self):
        # Google Gemini models require Google voices (default Puck)
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live", ""), DEFAULT_GOOGLE_REALTIME_VOICE)
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live", "alloy"), DEFAULT_GOOGLE_REALTIME_VOICE)
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live", "Zephyr"), "Zephyr")
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live-extended-thinking", "Aoede"), "Aoede")
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live-extended-thinking", "invalid-voice"), DEFAULT_GOOGLE_REALTIME_VOICE)

        # OpenAI models require OpenAI voices (default alloy)
        self.assertEqual(_normalize_vercel_voice("openai/gpt-realtime-2", ""), DEFAULT_VERCEL_REALTIME_VOICE)
        self.assertEqual(_normalize_vercel_voice("openai/gpt-realtime-2", "Puck"), DEFAULT_VERCEL_REALTIME_VOICE)
        self.assertEqual(_normalize_vercel_voice("openai/gpt-realtime-2", "echo"), "echo")
        self.assertEqual(_normalize_vercel_voice("openai/gpt-realtime-2", "invalid-voice"), DEFAULT_VERCEL_REALTIME_VOICE)

    def test_vercel_ws_url_resolution(self):
        service = RealtimeVoiceService(config=self._config(api_keys={"vercel_api_key": "test-key"}))

        # Bare origin
        settings = {"base_url": "https://ai-gateway.vercel.sh", "model": "google/gemini-3.8-live"}
        ws_url = service._vercel_ws_url(settings)
        self.assertEqual(
            ws_url,
            "wss://ai-gateway.vercel.sh/v4/ai/realtime-model?ai-model-id=google%2Fgemini-3.8-live",
        )

        # Origin with /v1
        settings_v1 = {"base_url": "https://ai-gateway.vercel.sh/v1", "model": "google/gemini-3.8-live-extended-thinking"}
        ws_url_v1 = service._vercel_ws_url(settings_v1)
        self.assertEqual(
            ws_url_v1,
            "wss://ai-gateway.vercel.sh/v4/ai/realtime-model?ai-model-id=google%2Fgemini-3.8-live-extended-thinking",
        )

    def test_llm_service_vercel_chat_url(self):
        # Bare base URL gets /v1/chat/completions
        url = LLMService._build_chat_completions_url("Vercel", "https://ai-gateway.vercel.sh")
        self.assertEqual(url, "https://ai-gateway.vercel.sh/v1/chat/completions")

        # Base URL already ending with /v1 gets /chat/completions without duplicate /v1
        url_with_v1 = LLMService._build_chat_completions_url("Vercel", "https://ai-gateway.vercel.sh/v1")
        self.assertEqual(url_with_v1, "https://ai-gateway.vercel.sh/v1/chat/completions")

        # Other providers are unchanged
        url_deepseek = LLMService._build_chat_completions_url("DeepSeek", "https://api.deepseek.com/v1")
        self.assertEqual(url_deepseek, "https://api.deepseek.com/v1/chat/completions")

    def test_vercel_tool_declarations_contains_render_canvas(self):
        from services.realtime_tool_protocol import vercel_tool_declarations
        tools = vercel_tool_declarations()
        self.assertTrue(isinstance(tools, list))
        self.assertTrue(len(tools) >= 3)
        tool_names = [t.get("name") for t in tools]
        self.assertIn("render_canvas", tool_names)
        self.assertIn("search_web", tool_names)
        self.assertIn("recall_memory", tool_names)

        canvas_tool = next(t for t in tools if t.get("name") == "render_canvas")
        self.assertEqual(canvas_tool.get("type"), "function")
        params = canvas_tool.get("parameters", {})
        self.assertEqual(params.get("type"), "object")
        props = params.get("properties", {})
        self.assertIn("code", props)
        self.assertIn("mode", props)
        self.assertEqual(props["mode"].get("enum"), ["react", "html"])
        self.assertIn("code", params.get("required", []))

    def test_build_realtime_instructions_includes_canvas_rule(self):
        inst = RealtimeVoiceService._build_realtime_instructions()
        self.assertIn("render_canvas", inst)
        self.assertIn("HTML or React", inst)


try:
    from test_realtime_provider_replay import CollectingWebSocket, FakeMemorySession, RecordingToolSession
except ImportError:
    from tests.test_realtime_provider_replay import CollectingWebSocket, FakeMemorySession, RecordingToolSession

from unittest.mock import MagicMock
from services.interruption_classifier import InterruptionDecisionCoordinator
from services.realtime_session_recorder import VoiceAgentSessionRecorder


class FakeVercelWs:
    def __init__(self, events: list[dict]):
        self.events = list(events)
        self.sent: list[dict] = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return json.dumps(self.events.pop(0))

    async def send(self, data: str):
        self.sent.append(json.loads(data))


class VercelGeminiInterruptionReplayTests(unittest.IsolatedAsyncioTestCase):
    """Adversarial replays verifying Gemini 3.8 Live interruption handling on Vercel AI Gateway."""

    async def asyncSetUp(self):
        self.service = RealtimeVoiceService()
        self.ws = CollectingWebSocket()
        self.memory = FakeMemorySession()
        self.tools = RecordingToolSession(active=False)
        self.recorder = VoiceAgentSessionRecorder(repository=MagicMock(), session_id="vercel-test")
        await self.recorder.note_user_transcript("Tell me a long story")
        await self.recorder.note_assistant_text("Once upon a time")
        self.old_turn = self.recorder.current_turn_id
        self.coordinator = InterruptionDecisionCoordinator()
        self.state = {"response_active": True}

    async def replay(self, events: list[dict], model: str = "google/gemini-3.8-live"):
        vercel_ws = FakeVercelWs(events)
        await self.service._vercel_to_client_loop(
            self.ws,
            vercel_ws,
            self.memory,
            self.tools,
            self.recorder,
            interruption=self.coordinator,
            state=self.state,
            model=model,
        )
        return vercel_ws

    async def test_server_vad_speech_started_cancels_and_stops_assistant_immediately(self):
        self.coordinator.active_response_id = "resp-101"
        vercel_ws = await self.replay([
            {"type": "speech-started"},
        ])
        # Sent response-cancel to Vercel Gateway immediately
        cancel_msgs = [m for m in vercel_ws.sent if m.get("type") == "response-cancel"]
        self.assertEqual(len(cancel_msgs), 1)
        self.assertEqual(cancel_msgs[0].get("responseId"), "resp-101")

        # Emitted interruption_decision with provider_interrupted and TRUE_BARGE_IN
        decision = next(e for e in self.ws.events if e["type"] == "interruption_decision")
        self.assertEqual(decision["rule"], "provider_interrupted")
        self.assertEqual(decision["classification"], "TRUE_BARGE_IN")

        # Emitted interrupted event to stop audio playback in browser immediately
        interrupted = next(e for e in self.ws.events if e["type"] == "interrupted")
        self.assertTrue(interrupted["interrupted"])
        self.assertEqual(interrupted["turn_id"], self.old_turn)

        # No turn_complete should be emitted
        self.assertFalse(any(e["type"] == "turn_complete" for e in self.ws.events))

    async def test_suppress_in_flight_audio_and_consume_cancelled_terminal(self):
        self.coordinator.active_response_id = "resp-101"
        vercel_ws = await self.replay([
            {"type": "speech-started"},
            {"type": "audio-delta", "responseId": "resp-101", "delta": "c3RhbGU="},
            {"type": "audio-transcript-delta", "responseId": "resp-101", "delta": "stale text"},
            {"type": "response-done", "responseId": "resp-101", "status": "cancelled"},
        ])
        # Audio and text deltas arriving after speech-started must be discarded
        self.assertFalse(any(e["type"] == "assistant_audio" for e in self.ws.events))
        self.assertFalse(any(e["type"] == "assistant_text" for e in self.ws.events))

        # Cancelled terminal must be consumed, NOT emit turn_complete
        self.assertFalse(any(e["type"] == "turn_complete" for e in self.ws.events))
        self.assertFalse(self.state["response_active"])

    async def test_subsequent_transcription_starts_new_turn_cleanly(self):
        self.coordinator.active_response_id = "resp-101"
        vercel_ws = await self.replay([
            {"type": "speech-started"},
            {"type": "response-done", "responseId": "resp-101", "status": "cancelled"},
            {"type": "input-transcription-completed", "transcript": "Wait, tell me a joke instead"},
            {"type": "response-created", "responseId": "resp-102"},
            {"type": "audio-delta", "responseId": "resp-102", "delta": "bmV3"},
            {"type": "response-done", "responseId": "resp-102", "status": "completed"},
        ])
        # First turn was interrupted
        interrupted = next(e for e in self.ws.events if e["type"] == "interrupted")
        self.assertEqual(interrupted["turn_id"], self.old_turn)

        # New user transcript emitted for second turn
        user_events = [e for e in self.ws.events if e["type"] == "user_transcript"]
        self.assertEqual(len(user_events), 1)
        self.assertEqual(user_events[0]["text"], "Wait, tell me a joke instead")
        self.assertNotEqual(user_events[0]["turn_id"], self.old_turn)

        # response-create was triggered on Vercel
        response_creates = [m for m in vercel_ws.sent if m.get("type") == "response-create"]
        self.assertTrue(len(response_creates) >= 1)

        # New audio played
        audio_events = [e for e in self.ws.events if e["type"] == "assistant_audio"]
        self.assertEqual(len(audio_events), 1)
        self.assertEqual(audio_events[0]["audio"], "bmV3")
        self.assertEqual(audio_events[0]["turn_id"], user_events[0]["turn_id"])

        # Completed terminal completes new turn
        complete_events = [e for e in self.ws.events if e["type"] == "turn_complete"]
        self.assertEqual(len(complete_events), 1)
        self.assertEqual(complete_events[0]["turn_id"], user_events[0]["turn_id"])

    async def test_short_opener_following_interruption_not_dropped(self):
        self.coordinator.active_response_id = "resp-101"
        vercel_ws = await self.replay([
            {"type": "speech-started"},
            {"type": "input-transcription-completed", "transcript": "Stop"},
        ])
        # Interrupted
        self.assertTrue(any(e["type"] == "interrupted" for e in self.ws.events))

        # "Stop" is preserved as user transcript rather than discarded by regex classifier
        user_events = [e for e in self.ws.events if e["type"] == "user_transcript"]
        self.assertEqual(len(user_events), 1)
        self.assertEqual(user_events[0]["text"], "Stop")
        self.assertEqual(self.memory.user_texts, ["Stop"])

    async def test_speech_activity_started_ignored_in_client_loop(self):
        ws = CollectingWebSocket(inbound=[
            {"type": "websocket.receive", "text": json.dumps({"type": "speech_activity_started"})},
            {"type": "websocket.disconnect"},
        ])
        vercel_ws = FakeVercelWs([])
        await self.service._client_to_vercel_loop(
            ws,
            vercel_ws,
            self.memory,
            self.tools,
            self.recorder,
            interruption=self.coordinator,
            state=self.state,
            model="google/gemini-3.8-live",
        )
        # Should not send any error or pending interruption
        self.assertFalse(any(e["type"] == "interruption_pending" for e in ws.events))

    async def test_active_tool_cancelled_on_server_vad_interruption(self):
        self.tools.active = True
        self.coordinator.active_response_id = "resp-101"
        await self.replay([
            {"type": "speech-started"},
        ])
        self.assertEqual(self.tools.cancel_count, 1)
        self.assertTrue(any(e["type"] == "interrupted" for e in self.ws.events))

    async def test_duplicate_speech_started_does_not_duplicate_interruption(self):
        self.coordinator.active_response_id = "resp-101"
        await self.replay([
            {"type": "speech-started"},
            {"type": "speech-started"},
        ])
        interrupted_events = [e for e in self.ws.events if e["type"] == "interrupted"]
        self.assertEqual(len(interrupted_events), 1)


from services.voice_agent_tools import VoiceAgentToolSession


class VercelGeminiCanvasToolReplayTests(unittest.IsolatedAsyncioTestCase):
    """Replay tests verifying Gemini 3.8 Live canvas and native tool calling on Vercel AI Gateway."""

    async def asyncSetUp(self):
        self.service = RealtimeVoiceService()
        self.ws = CollectingWebSocket()
        self.memory = FakeMemorySession()
        self.tools = VoiceAgentToolSession(default_provider="Vercel")
        self.recorder = VoiceAgentSessionRecorder(repository=MagicMock(), session_id="vercel-tool-test")
        await self.recorder.note_user_transcript("Draw a todo list app on the canvas")
        self.coordinator = InterruptionDecisionCoordinator()
        self.state = {"response_active": True}

    async def replay(self, events: list[dict], model: str = "google/gemini-3.8-live"):
        vercel_ws = FakeVercelWs(events)
        await self.service._vercel_to_client_loop(
            self.ws,
            vercel_ws,
            self.memory,
            self.tools,
            self.recorder,
            interruption=self.coordinator,
            state=self.state,
            model=model,
        )
        return vercel_ws

    async def test_render_canvas_tool_call_emits_canvas_artifact_and_responds(self):
        """Verify normalized tool-call event triggers render_canvas and returns function_call_output."""
        canvas_code = "export default function TodoApp() { return <div className='p-4'><h1>My Todos</h1></div>; }"
        vercel_ws = await self.replay([
            {
                "type": "tool-call",
                "toolCallId": "call-cv-101",
                "toolName": "render_canvas",
                "args": {
                    "code": canvas_code,
                    "mode": "react",
                    "title": "My Todo App",
                },
            },
            # Response done arriving while tool or post-tool speech executes
            {
                "type": "response-done",
                "responseId": "resp-cv-1",
                "status": "completed",
            },
        ])

        # 1. response_gated emitted
        gated_events = [e for e in self.ws.events if e.get("type") == "response_gated"]
        self.assertEqual(len(gated_events), 1)
        self.assertEqual(gated_events[0]["tool_name"], "render_canvas")
        self.assertEqual(gated_events[0]["provider"], "Vercel")

        # 2. tool_call_started, tool_call_completed, and agent_result emitted
        agent_results = [e for e in self.ws.events if e.get("type") == "agent_result"]
        self.assertEqual(len(agent_results), 1)
        res = agent_results[0]
        self.assertEqual(res["tool_name"], "render_canvas")
        self.assertEqual(res["query"], "My Todo App")
        artifact = res.get("artifact", {})
        self.assertEqual(artifact.get("type"), "canvas")
        self.assertEqual(artifact.get("artifact_type"), "canvas")
        self.assertEqual(artifact.get("mode"), "react")
        self.assertEqual(artifact.get("title"), "My Todo App")
        self.assertEqual(artifact.get("code"), canvas_code)

        # 3. conversation-item-create with function-call-output sent to Vercel Gateway
        function_outputs = [
            m for m in vercel_ws.sent
            if m.get("type") == "conversation-item-create"
            and isinstance(m.get("item"), dict)
            and m["item"].get("type") in {"function-call-output", "function_call_output"}
        ]
        self.assertEqual(len(function_outputs), 1)
        item = function_outputs[0]["item"]
        self.assertEqual(item.get("callId"), "call-cv-101")
        self.assertEqual(item.get("name"), "render_canvas")
        output_data = json.loads(item.get("output", "{}"))
        self.assertTrue(output_data.get("ok"))
        self.assertEqual(output_data.get("tool_name"), "render_canvas")

        # 4. response-create triggered
        response_creates = [m for m in vercel_ws.sent if m.get("type") == "response-create"]
        self.assertTrue(len(response_creates) >= 1)

    async def test_render_canvas_html_mode_via_output_item_done(self):
        """Verify OpenAI Realtime output_item.done format triggers HTML canvas rendering."""
        html_code = "<!DOCTYPE html><html><body><h1 class='text-blue-500'>Dashboard</h1></body></html>"
        vercel_ws = await self.replay([
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call-cv-102",
                    "name": "render_canvas",
                    "arguments": json.dumps({
                        "code": html_code,
                        "mode": "html",
                        "title": "HTML Dashboard",
                    }),
                },
            },
        ])

        agent_results = [e for e in self.ws.events if e.get("type") == "agent_result"]
        self.assertEqual(len(agent_results), 1)
        artifact = agent_results[0].get("artifact", {})
        self.assertEqual(artifact.get("mode"), "html")
        self.assertEqual(artifact.get("code"), html_code)
        self.assertEqual(artifact.get("title"), "HTML Dashboard")

        function_outputs = [
            m for m in vercel_ws.sent
            if m.get("type") == "conversation-item-create"
            and isinstance(m.get("item"), dict)
            and m["item"].get("type") in {"function-call-output", "function_call_output"}
        ]
        self.assertEqual(len(function_outputs), 1)
        self.assertEqual(function_outputs[0]["item"]["callId"], "call-cv-102")
        self.assertEqual(function_outputs[0]["item"]["name"], "render_canvas")

    async def test_render_canvas_inside_response_done_output(self):
        """Verify function_call items inside response-done are dispatched safely."""
        react_code = "export default function Counter() { return <button>0</button>; }"
        vercel_ws = await self.replay([
            {
                "type": "response-done",
                "responseId": "resp-nested-1",
                "status": "completed",
                "response": {
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-cv-103",
                            "name": "render_canvas",
                            "arguments": {
                                "code": react_code,
                                "mode": "react",
                                "title": "Interactive Counter",
                            },
                        }
                    ]
                },
            },
        ])

        agent_results = [e for e in self.ws.events if e.get("type") == "agent_result"]
        self.assertEqual(len(agent_results), 1)
        self.assertEqual(agent_results[0]["artifact"]["code"], react_code)

    async def test_tool_deduplication_between_added_and_done(self):
        """Verify duplicate output_item.added and output_item.done executes exactly once."""
        vercel_ws = await self.replay([
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "call_id": "call-dup-104",
                    "name": "render_canvas",
                    "arguments": {"code": "<div>Once</div>", "title": "Once"},
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call-dup-104",
                    "name": "render_canvas",
                    "arguments": {"code": "<div>Once</div>", "title": "Once"},
                },
            },
        ])

        agent_results = [e for e in self.ws.events if e.get("type") == "agent_result"]
        self.assertEqual(len(agent_results), 1)

        function_outputs = [
            m for m in vercel_ws.sent
            if m.get("type") == "conversation-item-create"
            and isinstance(m.get("item"), dict)
            and m["item"].get("type") in {"function-call-output", "function_call_output"}
        ]
        self.assertEqual(len(function_outputs), 1)

    async def test_tool_error_handling_does_not_crash_loop(self):
        """Verify invalid tool call returns structured error payload without raising."""
        vercel_ws = await self.replay([
            {
                "type": "tool-call",
                "toolCallId": "call-err-105",
                "toolName": "render_canvas",
                "args": {"code": ""},  # empty code violates schema
            },
        ])

        # Error payload sent back to provider
        function_outputs = [
            m for m in vercel_ws.sent
            if m.get("type") == "conversation-item-create"
            and isinstance(m.get("item"), dict)
            and m["item"].get("type") in {"function-call-output", "function_call_output"}
        ]
        self.assertEqual(len(function_outputs), 1)
        err_output = json.loads(function_outputs[0]["item"]["output"])
        self.assertFalse(err_output.get("ok"))
        self.assertIn("error", err_output)

    async def test_vercel_function_call_arguments_done_wire_event(self):
        """Verify actual Vercel AI Gateway wire event (function-call-arguments-done) triggers canvas."""
        canvas_code = "export default function City() { return <div>Cyber City</div>; }"
        vercel_ws = await self.replay([
            {
                "type": "function-call-arguments-done",
                "responseId": "google-resp-1",
                "itemId": "google-item-1",
                "callId": "call_wire_999",
                "name": "render_canvas",
                "arguments": json.dumps({
                    "code": canvas_code,
                    "mode": "react",
                    "title": "Cyber City Wire",
                }),
            },
        ])

        agent_results = [e for e in self.ws.events if e.get("type") == "agent_result"]
        self.assertEqual(len(agent_results), 1)
        self.assertEqual(agent_results[0]["artifact"]["title"], "Cyber City Wire")
        self.assertEqual(agent_results[0]["artifact"]["code"], canvas_code)

        function_outputs = [
            m for m in vercel_ws.sent
            if m.get("type") == "conversation-item-create"
            and isinstance(m.get("item"), dict)
            and m["item"].get("type") in {"function-call-output", "function_call_output"}
        ]
        self.assertEqual(len(function_outputs), 1)
        self.assertEqual(function_outputs[0]["item"]["callId"], "call_wire_999")
        self.assertEqual(function_outputs[0]["item"]["name"], "render_canvas")

    async def test_extended_thinking_in_progress_defers_turn_complete(self):
        """Verify response-done with interactionStatus IN_PROGRESS does not emit premature turn_complete."""
        # 1. Opener audio finished with interactionStatus IN_PROGRESS: turn_complete must NOT be emitted
        await self.replay([
            {
                "type": "response-done",
                "responseId": "google-resp-0",
                "status": "completed",
                "raw": {
                    "serverContent": {
                        "turnComplete": True,
                        "interactionStatus": "IN_PROGRESS",
                    }
                },
            },
        ])
        turn_completes = [e for e in self.ws.events if e.get("type") == "turn_complete"]
        self.assertEqual(len(turn_completes), 0)

        # 2. Standard response-done without IN_PROGRESS emits turn_complete
        await self.replay([
            {
                "type": "response-done",
                "responseId": "google-resp-1",
                "status": "completed",
                "raw": {
                    "serverContent": {
                        "turnComplete": True,
                    }
                },
            },
        ])
        turn_completes = [e for e in self.ws.events if e.get("type") == "turn_complete"]
        self.assertEqual(len(turn_completes), 1)


if __name__ == "__main__":
    unittest.main()
