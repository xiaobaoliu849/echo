from __future__ import annotations

import asyncio
import json
from typing import Any
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.realtime_voice_service import (
    DashScopeAudioRealtimeConversation,
    DashScopeRealtimeCallback,
    RealtimeVoiceService,
)
from services.realtime_tool_protocol import tool_error_payload, tool_result_payload
from services.voice_agent_tools import VoiceAgentToolSession


class _ReplayComplete(Exception):
    pass


class _OneBatchGoogleSession:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.served = False
        self.function_responses = []

    def receive(self):
        if self.served:
            raise _ReplayComplete()
        self.served = True

        async def iterator():
            yield self.response

        return iterator()

    async def send_tool_response(self, *, function_responses) -> None:
        self.function_responses.append(function_responses)


class _FailingBatchGoogleSession(_OneBatchGoogleSession):
    def receive(self):
        if not self.served:
            return super().receive()

        async def iterator():
            await asyncio.sleep(0.02)
            raise _ReplayComplete()
            yield  # pragma: no cover

        return iterator()

    async def send_tool_response(self, *, function_responses) -> None:
        self.function_responses.append(function_responses)
        raise RuntimeError("batch delivery failed")

    async def close(self) -> None:
        return None


class _GoogleSequenceSession:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = responses
        self.served = False

    def receive(self):
        if self.served:
            raise _ReplayComplete()
        self.served = True

        async def iterator():
            for response in self.responses:
                yield response
                await asyncio.sleep(0)

        return iterator()


class _ImmediateNativeToolSession:
    has_active_task = False
    current_turn_id = ""

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.requests = []
        self.tool_index = 0
        self.result_tasks: list[asyncio.Task[None]] = []

    def reserve_tool_call_id(self) -> str:
        self.tool_index += 1
        return f"voice-tool-{self.tool_index}"

    def has_seen_provider_call(self, call_id: str) -> bool:
        return call_id in self.seen

    def mark_provider_call_seen(self, call_id: str) -> None:
        self.seen.add(call_id)

    async def handle_request(self, request, **kwargs) -> str:
        call_id = kwargs["provider_call_id"]
        self.seen.add(call_id)
        self.requests.append(request)
        result_task = asyncio.create_task(
            kwargs["on_result"](
                {"tool_name": request.tool_name, "query": request.query, "answer": "grounded", "sources": []}
            )
        )
        self.result_tasks.append(result_task)
        await asyncio.sleep(0)
        if result_task.done() or len(self.result_tasks) > 1:
            await asyncio.gather(*self.result_tasks)
        return kwargs["tool_call_id"]

    async def cancel_provider_call(self, *_args, **_kwargs) -> bool:
        return False


class _MemorySession:
    _config = SimpleNamespace(memory_scope="", group_id="")

    def note_user_transcript(self, _text: str) -> None:
        return None

    async def flush_turn(self) -> dict:
        return {}


class _FakeWebSocket:
    def __init__(self, inbound: list[dict[str, Any]] | None = None) -> None:
        self.inbound = list(inbound) if inbound is not None else []
        self.sent_events: list[dict[str, Any]] = []

    async def receive(self) -> dict[str, Any]:
        if self.inbound:
            return self.inbound.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent_events.append(data)


_FakeToolSession = _ImmediateNativeToolSession


class TestRealtimeNativeToolDelivery(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    async def test_duplex_runner_cancels_peer_after_normal_disconnect(self) -> None:
        peer_cancelled = asyncio.Event()

        async def disconnected_client() -> None:
            await asyncio.sleep(0)
            return None

        async def provider_receiver() -> None:
            try:
                await asyncio.Future()
            finally:
                peer_cancelled.set()

        client_task = asyncio.create_task(disconnected_client())
        provider_task = asyncio.create_task(provider_receiver())
        await self.service._run_duplex_tasks(client_task, provider_task)

        self.assertTrue(provider_task.cancelled())
        self.assertTrue(peer_cancelled.is_set())

    def test_dashscope_settings_require_current_model_and_workspace_endpoint(self) -> None:
        config = MagicMock()
        config.get_provider_settings.return_value = {
            "api_key": "test_key",
            "model": "qwen3.5-omni-plus-realtime",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "realtime_base_url": "wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
        }
        self.service.config = config

        settings = self.service._resolve_dashscope_settings(None)

        self.assertEqual(settings["model"], "qwen3.5-omni-plus-realtime")
        self.assertEqual(
            settings["realtime_base_url"],
            "wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
        )

    def test_dashscope_settings_reject_old_model_without_fallback(self) -> None:
        config = MagicMock()
        config.get_provider_settings.return_value = {
            "api_key": "test_key",
            "model": "qwen3-omni-flash-realtime-2025-12-01",
            "base_url": "",
            "realtime_base_url": "wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
        }
        self.service.config = config

        with self.assertRaisesRegex(RuntimeError, "qwen3.5-omni-plus-realtime"):
            self.service._resolve_dashscope_settings(None)

    def test_dashscope_settings_accept_qwen_audio_beijing_workspace_endpoint(self) -> None:
        config = MagicMock()
        config.get_provider_settings.return_value = {
            "api_key": "test_key",
            "model": "qwen-audio-3.0-realtime-plus",
            "base_url": "",
            "realtime_base_url": "wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
        }
        self.service.config = config

        settings = self.service._resolve_dashscope_settings(None)

        self.assertEqual(settings["model"], "qwen-audio-3.0-realtime-plus")

    def test_dashscope_settings_reject_qwen_audio_non_beijing_endpoint(self) -> None:
        config = MagicMock()
        config.get_provider_settings.return_value = {
            "api_key": "test_key",
            "model": "qwen-audio-3.0-realtime-plus",
            "base_url": "",
            "realtime_base_url": "wss://workspace.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/realtime",
        }
        self.service.config = config

        with self.assertRaisesRegex(RuntimeError, "北京地域"):
            self.service._resolve_dashscope_settings(None)

    def test_qwen_audio_session_update_uses_server_vad_with_voiceprint(self) -> None:
        conversation = DashScopeAudioRealtimeConversation(
            model="qwen-audio-3.0-realtime-plus",
            api_key="test_key",
            url="wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
            callback=MagicMock(),
            voiceprint_audio_urls=["https://example.com/voice.wav"],
        )
        sent = []
        conversation._send_event = sent.append  # type: ignore[method-assign]

        conversation.update_session(voice="invalid-ignored-by-test", instructions="first", tools=[])
        conversation.update_session(voice="invalid-ignored-by-test", instructions="second", tools=[])

        first_session = sent[0]["session"]
        second_session = sent[1]["session"]
        self.assertEqual(first_session["turn_detection"]["type"], "server_vad")
        self.assertEqual(first_session["turn_detection"]["threshold"], 0.3)
        self.assertEqual(first_session["turn_detection"]["silence_duration_ms"], 5000)
        self.assertEqual(first_session["turn_detection"]["voiceprint_audio_urls"], ["https://example.com/voice.wav"])
        self.assertNotIn("turn_detection", second_session)
        self.assertEqual(second_session["instructions"], "second")

    async def test_google_tool_result_uses_typed_function_response(self) -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        session = MagicMock()
        session.send_tool_response = AsyncMock()
        result = {
            "tool_name": "search_web",
            "query": "voice agent",
            "answer": "summary",
            "sources": [{"title": "Source", "uri": "https://example.com", "snippet": "content"}],
        }

        await self.service._send_google_tool_response(
            websocket,
            session,
            provider_call_id="call-google-1",
            tool_name="search_web",
            response_payload=tool_result_payload(result),
            result=result,
        )

        session.send_tool_response.assert_awaited_once()
        function_response = session.send_tool_response.await_args.kwargs["function_responses"][0]
        self.assertEqual(function_response.id, "call-google-1")
        self.assertEqual(function_response.name, "search_web")
        self.assertTrue(function_response.response["output"]["ok"])
        self.assertFalse(hasattr(session, "send") and session.send.called)
        websocket.send_json.assert_awaited_once()
        self.assertEqual(websocket.send_json.await_args.args[0]["type"], "tool_result_delivered")

    async def test_google_tool_error_is_typed_and_correlated(self) -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        session = MagicMock()
        session.send_tool_response = AsyncMock()

        await self.service._send_google_tool_response(
            websocket,
            session,
            provider_call_id="call-google-error",
            tool_name="search_web",
            response_payload=tool_error_payload("search failed"),
        )

        function_response = session.send_tool_response.await_args.kwargs["function_responses"][0]
        self.assertEqual(function_response.id, "call-google-error")
        self.assertFalse(function_response.response["error"]["ok"])

    async def test_google_tool_delivery_failure_closes_session(self) -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        session = MagicMock()
        session.send_tool_response = AsyncMock(side_effect=RuntimeError("transport closed"))
        session.close = AsyncMock()

        with self.assertRaisesRegex(RuntimeError, "transport closed"):
            await self.service._send_google_tool_response(
                websocket,
                session,
                provider_call_id="call-google-fail",
                tool_name="search_web",
                response_payload=tool_error_payload("failed"),
            )

        session.close.assert_awaited_once()
        self.assertTrue(
            any(call.args[0].get("type") == "error" for call in websocket.send_json.await_args_list)
        )

    async def test_google_loop_handles_top_level_tool_call_without_server_content(self) -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        tools = _ImmediateNativeToolSession()
        session = _OneBatchGoogleSession(
            SimpleNamespace(
                data=None,
                text=None,
                server_content=None,
                tool_call=SimpleNamespace(
                    function_calls=[
                        SimpleNamespace(id="call-top-level", name="search_web", args={"query": "latest news"})
                    ]
                ),
                tool_call_cancellation=None,
            )
        )

        with self.assertRaises(_ReplayComplete):
            await self.service._google_to_client_loop(
                websocket,
                session,
                _MemorySession(),
                tools,
            )

        self.assertEqual([request.query for request in tools.requests], ["latest news"])
        self.assertEqual(len(session.function_responses), 1)
        self.assertEqual(session.function_responses[0][0].id, "call-top-level")

    async def test_google_loop_batches_multiple_function_responses_with_stable_ids(self) -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        tools = _ImmediateNativeToolSession()
        recorder = MagicMock()
        recorder.current_turn_id = "voice-turn-canonical"
        recorder.record_tool_event = AsyncMock()
        session = _OneBatchGoogleSession(
            SimpleNamespace(
                data=None,
                text=None,
                server_content=None,
                tool_call=SimpleNamespace(
                    function_calls=[
                        SimpleNamespace(id="call-search", name="search_web", args={"query": "news"}),
                        SimpleNamespace(
                            id="call-translate",
                            name="translate_text",
                            args={"text": "hello", "target_language": "中文"},
                        ),
                    ]
                ),
                tool_call_cancellation=None,
            )
        )

        with self.assertRaises(_ReplayComplete):
            await self.service._google_to_client_loop(
                websocket,
                session,
                _MemorySession(),
                tools,
                recorder,
            )

        self.assertEqual(len(session.function_responses), 1)
        self.assertEqual(
            [response.id for response in session.function_responses[0]],
            ["call-search", "call-translate"],
        )
        delivered = [
            call.args[0]
            for call in websocket.send_json.await_args_list
            if call.args[0].get("type") == "tool_result_delivered"
        ]
        self.assertEqual(
            [
                (event["turn_id"], event["provider_call_id"], event["tool_call_id"])
                for event in delivered
            ],
            [
                ("voice-turn-canonical", "call-search", "voice-tool-1"),
                ("voice-turn-canonical", "call-translate", "voice-tool-2"),
            ],
        )

    async def test_google_batch_delivery_failure_fails_every_child_call(self) -> None:
        class ImmediateToolService:
            async def run_tool(self, request, *, send_event, turn_id):
                await send_event(
                    "tool_call_completed",
                    {"tool_name": request.tool_name, "query": request.query, "turn_id": turn_id},
                )
                return {"tool_name": request.tool_name, "query": request.query, "sources": []}

        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        tools = VoiceAgentToolSession(service=ImmediateToolService())  # type: ignore[arg-type]
        session = _FailingBatchGoogleSession(
            SimpleNamespace(
                data=None,
                text=None,
                server_content=None,
                tool_call=SimpleNamespace(
                    function_calls=[
                        SimpleNamespace(id="call-one", name="search_web", args={"query": "one"}),
                        SimpleNamespace(id="call-two", name="search_web", args={"query": "two"}),
                    ]
                ),
                tool_call_cancellation=None,
            )
        )

        with self.assertRaises(_ReplayComplete):
            await self.service._google_to_client_loop(websocket, session, _MemorySession(), tools)
        await tools.drain()

        events = [call.args[0] for call in websocket.send_json.await_args_list]
        failed_ids = {
            event.get("provider_call_id")
            for event in events
            if event.get("type") == "tool_result_delivery_failed"
        }
        completed_ids = {
            event.get("provider_call_id")
            for event in events
            if event.get("type") == "tool_call_completed"
        }
        self.assertEqual(failed_ids, {"call-one", "call-two"})
        self.assertEqual(completed_ids, set())

    async def test_google_provider_cancellation_stops_matching_native_call(self) -> None:
        class HangingToolService:
            async def run_tool(self, request, *, send_event, turn_id):
                await send_event(
                    "tool_call_started",
                    {"tool_name": request.tool_name, "query": request.query, "turn_id": turn_id},
                )
                await asyncio.Future()

        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        tools = VoiceAgentToolSession(service=HangingToolService())  # type: ignore[arg-type]
        session = _GoogleSequenceSession(
            [
                SimpleNamespace(
                    data=None,
                    text=None,
                    server_content=None,
                    tool_call=SimpleNamespace(
                        function_calls=[
                            SimpleNamespace(id="call-cancel", name="search_web", args={"query": "cancel me"})
                        ]
                    ),
                    tool_call_cancellation=None,
                ),
                SimpleNamespace(
                    data=None,
                    text=None,
                    server_content=None,
                    tool_call=None,
                    tool_call_cancellation=SimpleNamespace(ids=["call-cancel"]),
                ),
            ]
        )

        with self.assertRaises(_ReplayComplete):
            await self.service._google_to_client_loop(websocket, session, _MemorySession(), tools)

        cancelled = [
            call.args[0]
            for call in websocket.send_json.await_args_list
            if call.args[0].get("type") == "tool_call_cancelled"
        ]
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0]["provider_call_id"], "call-cancel")
        self.assertEqual(cancelled[0]["reason"], "provider_cancelled")

    async def test_dashscope_tool_result_uses_function_call_output_then_response_create(self) -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        conversation = MagicMock()
        result = {"tool_name": "search_web", "query": "voice agent", "answer": "summary", "sources": []}

        await self.service._send_dashscope_tool_response(
            websocket,
            conversation,
            provider_call_id="call-qwen-1",
            tool_name="search_web",
            response_payload=tool_result_payload(result),
            result=result,
        )

        raw_event = json.loads(conversation.send_raw.call_args.args[0])
        self.assertEqual(raw_event["type"], "conversation.item.create")
        self.assertEqual(raw_event["item"]["type"], "function_call_output")
        self.assertEqual(raw_event["item"]["call_id"], "call-qwen-1")
        self.assertTrue(json.loads(raw_event["item"]["output"])["ok"])
        conversation.create_response.assert_called_once_with()
        websocket.send_json.assert_awaited_once()

    async def test_dashscope_tool_delivery_failure_closes_conversation(self) -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        conversation = MagicMock()
        conversation.send_raw.side_effect = RuntimeError("transport closed")

        with self.assertRaisesRegex(RuntimeError, "transport closed"):
            await self.service._send_dashscope_tool_response(
                websocket,
                conversation,
                provider_call_id="call-qwen-fail",
                tool_name="search_web",
                response_payload=tool_error_payload("failed"),
            )

        conversation.close.assert_called_once_with()
        self.assertTrue(
            any(call.args[0].get("type") == "error" for call in websocket.send_json.await_args_list)
        )

    async def test_dashscope_callback_distinguishes_function_phase_terminal(self) -> None:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        callback = DashScopeRealtimeCallback(loop=asyncio.get_running_loop(), queue=queue)
        callback.on_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "response-tool",
                "call_id": "call-qwen-1",
                "name": "search_web",
                "arguments": '{"query":"latest news"}',
            }
        )
        callback.on_event(
            {
                "type": "response.done",
                "response": {"id": "response-tool", "status": "completed", "output": [{"type": "function_call"}]},
            }
        )

        function_event = await queue.get()
        terminal_event = await queue.get()
        self.assertEqual(function_event["type"], "function_call")
        self.assertEqual(function_event["provider_call_id"], "call-qwen-1")
        self.assertEqual(terminal_event["type"], "tool_phase_complete")


class _StubOmniConversation:
    """Minimal stand-in for the SDK OmniRealtimeConversation."""

    def __init__(self) -> None:
        self.update_session_calls: list[dict[str, object]] = []
        self.raw_payloads: list[dict[str, object]] = []

    def update_session(self, **kwargs) -> None:
        self.update_session_calls.append(kwargs)

    def send_raw(self, payload: str) -> None:
        self.raw_payloads.append(json.loads(payload))


class TestDashScopeOmniSessionConfig(unittest.TestCase):
    """Regression tests for the qwen3.5-omni "listening forever" fix.

    Verified against the live API (2026-08-08):
    - create_response=False in turn_detection makes the server never
      auto-respond after VAD speech_stopped.
    - Re-sending the FULL session.update (voice/turn_detection) mid-session
      leaves the session deaf for later audio; follow-ups must be
      instructions-only.
    """

    def test_first_config_allows_server_auto_response(self) -> None:
        service = RealtimeVoiceService.__new__(RealtimeVoiceService)
        conversation = _StubOmniConversation()

        service._configure_dashscope_conversation(conversation, voice="Tina", instructions="hello")

        self.assertEqual(len(conversation.update_session_calls), 1)
        kwargs = conversation.update_session_calls[0]
        turn_param = kwargs.get("turn_detection_param") or {}
        self.assertNotEqual(turn_param.get("create_response"), False)
        self.assertIs(turn_param.get("interrupt_response"), False)
        self.assertTrue(conversation._vs_omni_session_configured)

    def test_followup_config_sends_instructions_only(self) -> None:
        service = RealtimeVoiceService.__new__(RealtimeVoiceService)
        conversation = _StubOmniConversation()

        service._configure_dashscope_conversation(conversation, voice="Tina", instructions="first")
        service._configure_dashscope_conversation(conversation, voice="Tina", instructions="second")

        # No second full update_session...
        self.assertEqual(len(conversation.update_session_calls), 1)
        # ...instead an instructions-only session.update via send_raw.
        self.assertEqual(len(conversation.raw_payloads), 1)
        event = conversation.raw_payloads[0]
        self.assertEqual(event["type"], "session.update")
        self.assertEqual(event["session"], {"instructions": "second"})

    def test_qwen_audio_raw_client_keeps_full_then_lite_pattern(self) -> None:
        service = RealtimeVoiceService.__new__(RealtimeVoiceService)
        # Real instance (exact-type routing) with mocked transport methods.
        conversation = DashScopeAudioRealtimeConversation(
            model="qwen-audio-3.0-realtime-plus",
            api_key="test-key",
            url="wss://example.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
            callback=None,  # type: ignore[arg-type]
        )
        conversation.update_session = MagicMock()  # type: ignore[method-assign]
        conversation.send_raw = MagicMock()  # type: ignore[method-assign]

        service._configure_dashscope_conversation(conversation, voice="longanqian", instructions="hi")

        conversation.update_session.assert_called_once()
        kwargs = conversation.update_session.call_args.kwargs
        # Must go through the raw-client branch (voice/instructions/tools only);
        # if the isinstance routing were deleted, the SDK branch would pass
        # SDK-only kwargs instead and these assertions would fail.
        self.assertEqual(set(kwargs), {"voice", "instructions", "tools"})
        self.assertEqual(kwargs["voice"], "longanqian")
        self.assertEqual(kwargs["instructions"], "hi")
        # The raw client manages its own first-full/later-lite counter; the
        # mixin must not short-circuit it via send_raw.
        conversation.send_raw.assert_not_called()

    def test_client_to_dashscope_text_input(self) -> None:
        async def run_test() -> None:
            service = RealtimeVoiceService.__new__(RealtimeVoiceService)
            conversation = _StubOmniConversation()
            client_ws = _FakeWebSocket(
                inbound=[
                    {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": "你好通义千问"})},
                ]
            )
            mem_session = _MemorySession()
            tool_session = _FakeToolSession()

            await service._client_to_dashscope_loop(
                client_ws, conversation, mem_session, tool_session
            )
            self.assertEqual(len(conversation.raw_payloads), 2)
            item_create = conversation.raw_payloads[0]
            resp_create = conversation.raw_payloads[1]
            self.assertEqual(item_create["type"], "conversation.item.create")
            self.assertEqual(item_create["item"]["content"][0]["text"], "你好通义千问")
            self.assertEqual(resp_create["type"], "response.create")

        asyncio.run(run_test())

    def test_client_to_dashscope_media_input(self) -> None:
        async def run_test() -> None:
            service = RealtimeVoiceService.__new__(RealtimeVoiceService)
            conversation = _StubOmniConversation()
            client_ws = _FakeWebSocket(
                inbound=[
                    {"type": "websocket.receive", "text": json.dumps({"type": "media_input", "text": "帮我看这张图片", "data": "QUJD"})},
                ]
            )
            mem_session = _MemorySession()
            tool_session = _FakeToolSession()

            await service._client_to_dashscope_loop(
                client_ws, conversation, mem_session, tool_session
            )
            self.assertEqual(len(conversation.raw_payloads), 2)
            item_create = conversation.raw_payloads[0]
            resp_create = conversation.raw_payloads[1]
            self.assertEqual(item_create["type"], "conversation.item.create")
            self.assertIn("帮我看这张图片", item_create["item"]["content"][0]["text"])
            self.assertEqual(resp_create["type"], "response.create")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
