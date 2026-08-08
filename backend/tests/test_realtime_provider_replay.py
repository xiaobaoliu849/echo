import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.interruption_classifier import InterruptionDecisionCoordinator
from services.realtime_voice_service import (
    DashScopeRealtimeCallback,
    RealtimeVoiceService,
    VoiceAgentSessionRecorder,
)
from services.voice_agent_session_repository import VoiceAgentSessionRepository


class ReplayComplete(Exception):
    pass


class FakeClock:
    def __init__(self) -> None:
        self.values = iter((10.0, 10.037))

    def __call__(self) -> float:
        return next(self.values)


class CollectingWebSocket:
    def __init__(self, inbound: list[dict] | None = None) -> None:
        self.events: list[dict] = []
        self.inbound = list(inbound or [])

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))

    async def receive(self) -> dict:
        if self.inbound:
            return self.inbound.pop(0)
        return {"type": "websocket.disconnect"}


class BlockingDecisionWebSocket(CollectingWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.decision_started = asyncio.Event()
        self.release_decision = asyncio.Event()

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))
        if payload.get("type") == "interruption_decision":
            self.decision_started.set()
            await self.release_decision.wait()


class FakeMemorySession:
    def __init__(self) -> None:
        self.user_texts: list[str] = []
        self.assistant_texts: list[str] = []
        self._config = SimpleNamespace(memory_scope="", group_id="")

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


class RecordingToolSession:
    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.cancel_count = 0
        self.cancel_reasons: list[str] = []
        self.handled_texts: list[str] = []

    @property
    def has_active_task(self) -> bool:
        return self.active

    @property
    def current_turn_id(self) -> str:
        return "existing-tool" if self.active else ""

    async def cancel(self, *, send_event, reason: str = "cancelled") -> None:
        if not self.active:
            return
        self.cancel_count += 1
        self.cancel_reasons.append(reason)
        self.active = False
        await send_event(
            "tool_call_cancelled",
            {
                "tool_name": "search_web",
                "turn_id": "existing-tool",
                "query": "original query",
                "reason": reason,
                "elapsed_ms": 37,
            },
        )

    async def handle_user_transcript(self, text: str, **_kwargs) -> str:
        self.handled_texts.append(text)
        return ""


class FakeGoogleSession:
    def __init__(self, batches: list[list[SimpleNamespace]]) -> None:
        self.batches = list(batches)
        self.sent: list[dict] = []

    def receive(self):
        if not self.batches:
            raise ReplayComplete()
        batch = self.batches.pop(0)

        async def iterator():
            for item in batch:
                yield item

        return iterator()

    async def send(self, **payload) -> None:
        self.sent.append(dict(payload))


class BlockingGoogleSession(FakeGoogleSession):
    def __init__(self, response: SimpleNamespace) -> None:
        super().__init__([])
        self.response = response
        self.response_processed = asyncio.Event()
        self.release_receive = asyncio.Event()
        self._served = False

    def receive(self):
        if self._served:
            raise ReplayComplete()
        self._served = True

        async def iterator():
            yield self.response
            self.response_processed.set()
            await self.release_receive.wait()

        return iterator()


class FakeOpenAIWebSocket:
    def __init__(self, events: list[dict]) -> None:
        self.events = list(events)
        self.sent: list[dict] = []

    def __aiter__(self):
        async def iterator():
            for event in self.events:
                yield json.dumps(event)

        return iterator()

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


def google_response(**server_content_fields) -> SimpleNamespace:
    return SimpleNamespace(
        data=None,
        text=None,
        server_content=SimpleNamespace(**server_content_fields),
    )


class RealtimeProviderReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = VoiceAgentSessionRepository(Path(self.temp_dir.name) / "voice.db")
        self.service = RealtimeVoiceService(voice_session_repository=self.repository)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def _recorder(self, provider: str, *, active_turn: bool = True) -> VoiceAgentSessionRecorder:
        session = self.repository.create_session(
            provider=provider,
            model=f"{provider.lower()}-replay",
            voice="test-voice",
            meta={"transport": "websocket"},
        )
        recorder = VoiceAgentSessionRecorder(self.repository, session["id"])
        await recorder.start(
            {
                "provider": provider,
                "model": f"{provider.lower()}-replay",
                "voice": "test-voice",
                "status": "open",
                "meta": {"transport": "websocket"},
            }
        )
        if active_turn:
            await recorder.note_user_transcript("请解释实时语音")
            await recorder.note_assistant_text("这是还没有说完的回答")
        return recorder

    async def _replay(
        self,
        provider: str,
        transcript: str,
        *,
        true_barge_in: bool,
        active_turn: bool = True,
        terminal_before_transcript: bool = False,
    ) -> dict:
        websocket = CollectingWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=true_barge_in)
        recorder = await self._recorder(provider, active_turn=active_turn)
        provider_sent: list[dict] = []

        coordinator_factory = lambda: InterruptionDecisionCoordinator(clock=FakeClock())
        _provider_modules = (
            "services.realtime_google_provider",
            "services.realtime_dashscope_provider",
            "services.realtime_openai_provider",
            "services.realtime_qwen_audio_provider",
        )
        with contextlib.ExitStack() as stack:
            for _mod in _provider_modules:
                stack.enter_context(
                    patch(f"{_mod}.InterruptionDecisionCoordinator", side_effect=coordinator_factory)
                )
            if provider == "DashScope":
                queue: asyncio.Queue[dict] = asyncio.Queue()
                callback = DashScopeRealtimeCallback(loop=asyncio.get_running_loop(), queue=queue)
                if active_turn:
                    callback.on_event({"type": "response.created", "response": {"id": "response-1"}})
                callback.on_event(
                    {
                        "type": "input_audio_buffer.speech_started",
                        "event_id": "vad-1",
                        "item_id": "item-1",
                        "audio_start_ms": 100,
                    }
                )
                if active_turn:
                    callback.on_event(
                        {
                            "type": "response.audio.delta",
                            "response_id": "response-1",
                            "delta": "Q0FORElEQVRF",
                        }
                    )
                    callback.on_event(
                        {
                            "type": "response.audio_transcript.delta",
                            "response_id": "response-1",
                            "delta": "候选期间尾部",
                        }
                    )
                if active_turn and terminal_before_transcript:
                    callback.on_event(
                        {"type": "response.done", "response": {"id": "response-1", "status": "completed"}}
                    )
                callback.on_event(
                    {
                        "type": "conversation.item.input_audio_transcription.completed",
                        "item_id": "item-1",
                        "transcript": transcript,
                    }
                )
                if active_turn and terminal_before_transcript and not true_barge_in:
                    callback.on_event(
                        {
                            "type": "input_audio_buffer.speech_started",
                            "item_id": "item-after-complete",
                            "audio_start_ms": 400,
                        }
                    )
                if active_turn and true_barge_in:
                    callback.on_event(
                        {
                            "type": "response.audio.delta",
                            "response_id": "response-1",
                            "delta": "TEFURQ==",
                        }
                    )
                    callback.on_event(
                        {
                            "type": "response.audio_transcript.delta",
                            "response_id": "response-1",
                            "delta": "不应下发的迟到内容",
                        }
                    )
                    callback.on_event(
                        {"type": "response.done", "response": {"id": "response-1", "status": "cancelled"}}
                    )
                elif active_turn and not terminal_before_transcript:
                    callback.on_event(
                        {"type": "response.done", "response": {"id": "response-1", "status": "completed"}}
                    )
                callback.on_close(1000, "replay complete")
                conversation = MagicMock()
                await self.service._dashscope_to_client_loop(
                    websocket,
                    queue,
                    memory,
                    conversation,
                    "test-voice",
                    tools,
                    recorder,
                )
                provider_stop_count = conversation.cancel_response.call_count
                provider_sent = [
                    {"name": call[0], "args": call[1], "kwargs": call[2]}
                    for call in conversation.method_calls
                ]
            elif provider == "OpenAI":
                raw_events = []
                if active_turn:
                    raw_events.extend([
                        {"type": "response.created", "response": {"id": "response-1"}},
                        {"type": "input_audio_buffer.speech_started", "item_id": "item-1"},
                        {
                            "type": "response.audio.delta",
                            "response_id": "response-1",
                            "delta": "Q0FORElEQVRF",
                        },
                        {
                            "type": "response.audio_transcript.delta",
                            "response_id": "response-1",
                            "delta": "候选期间尾部",
                        },
                    ])
                else:
                    raw_events.append({"type": "input_audio_buffer.speech_started", "item_id": "item-1"})
                if active_turn and terminal_before_transcript:
                    raw_events.append(
                        {"type": "response.done", "response": {"id": "response-1", "status": "completed"}}
                    )
                raw_events.append(
                    {
                        "type": "conversation.item.input_audio_transcription.completed",
                        "item_id": "item-1",
                        "transcript": transcript,
                    }
                )
                if active_turn and terminal_before_transcript and not true_barge_in:
                    raw_events.append(
                        {"type": "input_audio_buffer.speech_started", "item_id": "item-after-complete"}
                    )
                if active_turn and true_barge_in:
                    raw_events.extend(
                        [
                            {
                                "type": "response.audio.delta",
                                "response_id": "response-1",
                                "delta": "TEFURQ==",
                            },
                            {
                                "type": "response.audio_transcript.delta",
                                "response_id": "response-1",
                                "delta": "不应下发的迟到内容",
                            },
                            {"type": "response.done", "response": {"id": "response-1", "status": "cancelled"}},
                        ]
                    )
                elif active_turn and not terminal_before_transcript:
                    raw_events.append(
                        {"type": "response.done", "response": {"id": "response-1", "status": "completed"}}
                    )
                upstream = FakeOpenAIWebSocket(raw_events)
                await self.service._openai_to_client_loop(
                    websocket,
                    upstream,
                    memory,
                    tools,
                    recorder,
                )
                provider_stop_count = sum(item.get("type") == "response.cancel" for item in upstream.sent)
                provider_sent = upstream.sent
            else:
                interruption = coordinator_factory()
                if active_turn:
                    await self.service._begin_interruption(
                        websocket,
                        interruption,
                        provider="Google",
                        provider_event_type="client_vad.speech_started",
                        recorder=recorder,
                        tool_session=tools,
                    )
                batches = []
                if active_turn:
                    batches.append(
                        [SimpleNamespace(data=b"CANDIDATE", text="候选期间尾部", server_content=None)]
                    )
                if active_turn and terminal_before_transcript:
                    batches.append([google_response(turn_complete=True)])
                batches.append(
                    [
                        google_response(
                            input_transcription=SimpleNamespace(text=transcript, finished=True)
                        )
                    ]
                )
                if active_turn and true_barge_in:
                    batches.extend(
                        [
                            [SimpleNamespace(data=b"LATE", text="不应下发的迟到内容", server_content=None)],
                            [google_response(turn_complete=True)],
                        ]
                    )
                elif active_turn and not terminal_before_transcript:
                    batches.append([google_response(turn_complete=True)])
                session = FakeGoogleSession(batches)
                with self.assertRaises(ReplayComplete):
                    await self.service._google_to_client_loop(
                        websocket,
                        session,
                        memory,
                        tools,
                        recorder,
                        False,
                        interruption,
                    )
                provider_stop_count = 0
                provider_sent = session.sent

        await recorder.finish()
        return {
            "events": websocket.events,
            "timeline": self.repository.build_timeline(recorder.session_id),
            "turns": self.repository.list_turns(recorder.session_id),
            "tool_cancel_count": tools.cancel_count,
            "provider_stop_count": provider_stop_count,
            "provider_sent": provider_sent,
            "handled_texts": tools.handled_texts,
        }

    async def test_google_live_translate_finishes_pair_from_transcription_markers(self) -> None:
        websocket = CollectingWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder("Google", active_turn=False)
        session = FakeGoogleSession(
            [[
                google_response(
                    input_transcription=SimpleNamespace(text="Hello there.", finished=True),
                    output_transcription=SimpleNamespace(text="你好。", finished=True),
                )
            ]]
        )

        with self.assertRaises(ReplayComplete):
            await self.service._google_to_client_loop(
                websocket,
                session,
                memory,
                tools,
                recorder,
                True,
            )

        event_types = [event["type"] for event in websocket.events]
        self.assertEqual(event_types[-2:], ["assistant_text", "turn_complete"])
        self.assertEqual(
            [event.get("text") for event in websocket.events if event["type"] == "user_transcript"],
            ["Hello there.", "Hello there."],
        )
        self.assertEqual(
            [event.get("text") for event in websocket.events if event["type"] == "assistant_text"],
            ["你好。"],
        )
        self.assertEqual(len(self.repository.list_turns(recorder.session_id)), 1)

    @staticmethod
    def _canonical_timeline(timeline: list[dict]) -> list[dict]:
        canonical = []
        for event in timeline:
            payload = event.get("payload", {})
            canonical.append(
                {
                    "event_type": event["event_type"],
                    "turn_id": event.get("turn_id", ""),
                    "text": event.get("text", ""),
                    "classification": payload.get("classification"),
                    "decision": payload.get("decision"),
                    "rule": payload.get("rule"),
                    "elapsed_ms": (
                        payload.get("elapsed_ms")
                        if event["event_type"] == "interruption_decision"
                        else None
                    ),
                    "interrupted": payload.get("interrupted"),
                    "status": payload.get("status"),
                }
            )
        return canonical

    async def test_backchannel_keeps_answer_and_canonical_timeline_consistent(self) -> None:
        results = {
            provider: await self._replay(provider, "嗯嗯", true_barge_in=False)
            for provider in ("Google", "DashScope", "OpenAI")
        }
        for provider, result in results.items():
            with self.subTest(provider=provider):
                event_types = [event["type"] for event in result["events"]]
                self.assertIn("interruption_pending", event_types)
                self.assertIn("interruption_decision", event_types)
                self.assertNotIn("interrupted", event_types)
                decision = next(event for event in result["events"] if event["type"] == "interruption_decision")
                self.assertEqual(decision["classification"], "BACKCHANNEL")
                self.assertEqual(decision["elapsed_ms"], 37)
                self.assertEqual(result["tool_cancel_count"], 0)
                self.assertEqual(result["provider_stop_count"], 0)
                self.assertEqual(result["handled_texts"], [])
                self.assertEqual(len(result["turns"]), 1)
                self.assertFalse(result["turns"][0]["interrupted"])
                self.assertLess(event_types.index("interruption_decision"), event_types.index("assistant_text"))
                self.assertIn(
                    "候选期间尾部",
                    [event.get("text") for event in result["events"] if event["type"] == "assistant_text"],
                )
                delivered_audio = [
                    event.get("audio") for event in result["events"] if event["type"] == "assistant_audio"
                ]
                self.assertEqual(delivered_audio, ["Q0FORElEQVRF"])
                timeline_decision = next(
                    event for event in result["timeline"] if event["event_type"] == "interruption_decision"
                )
                self.assertEqual(timeline_decision["provider"], provider)
                self.assertEqual(timeline_decision["transport"], "websocket")
                self.assertEqual(timeline_decision["payload"]["decision_latency_ms"], 37)
                self.assertTrue(str(timeline_decision["payload"]["rule"]).startswith("backchannel_pattern:"))
        self.assertEqual(results["Google"]["provider_sent"], [])
        canonical = [self._canonical_timeline(result["timeline"]) for result in results.values()]
        self.assertEqual(canonical[0], canonical[1])
        self.assertEqual(canonical[1], canonical[2])

    async def test_true_barge_in_stops_answer_cancels_tools_and_preserves_boundary(self) -> None:
        results = {
            provider: await self._replay(provider, "等一下", true_barge_in=True)
            for provider in ("Google", "DashScope", "OpenAI")
        }
        for provider, result in results.items():
            with self.subTest(provider=provider):
                event_types = [event["type"] for event in result["events"]]
                self.assertLess(event_types.index("interruption_pending"), event_types.index("interruption_decision"))
                self.assertLess(event_types.index("interruption_decision"), event_types.index("interrupted"))
                decision = next(event for event in result["events"] if event["type"] == "interruption_decision")
                self.assertEqual(decision["classification"], "TRUE_BARGE_IN")
                # "等一下" is an explicit interrupt command (Layer 1). Assert the semantic
                # rule family rather than the exact internal pattern string.
                self.assertTrue(str(decision["rule"]).startswith("explicit_barge_in"))
                self.assertEqual(decision["provider"], provider)
                self.assertEqual(decision["interrupted_turn_id"], "voice-turn-1")
                self.assertEqual(decision["decision_latency_ms"], 37)
                self.assertEqual(result["tool_cancel_count"], 1)
                self.assertEqual(result["provider_stop_count"], 0 if provider == "Google" else 1)
                self.assertEqual(
                    result["handled_texts"],
                    ["等一下"] if provider == "OpenAI" else [],
                )
                self.assertEqual(len(result["turns"]), 2)
                self.assertTrue(result["turns"][0]["interrupted"])
                self.assertEqual(result["turns"][0]["assistant_text"], "这是还没有说完的回答")
                self.assertEqual(result["turns"][1]["user_text"], "等一下")
                delivered_text = "".join(
                    str(event.get("text", ""))
                    for event in result["events"]
                    if event["type"] == "assistant_text"
                )
                self.assertNotIn("候选期间尾部", delivered_text)
                self.assertNotIn("不应下发的迟到内容", delivered_text)
                self.assertNotIn("assistant_audio", event_types)
        canonical = [self._canonical_timeline(result["timeline"]) for result in results.values()]
        self.assertEqual(canonical[0], canonical[1])
        self.assertEqual(canonical[1], canonical[2])

    async def test_terminal_before_transcript_is_deferred_then_finalized(self) -> None:
        for provider in ("Google", "DashScope", "OpenAI"):
            with self.subTest(provider=provider):
                result = await self._replay(
                    provider,
                    "嗯嗯",
                    true_barge_in=False,
                    terminal_before_transcript=True,
                )
                event_types = [event["type"] for event in result["events"]]
                self.assertLess(event_types.index("interruption_decision"), event_types.index("assistant_text"))
                self.assertIn("turn_complete", event_types)
                self.assertTrue(result["turns"][0]["completed"])
                self.assertEqual(event_types.count("interruption_pending"), 1)

    async def test_true_barge_in_when_terminal_before_transcript_does_not_cancel_provider(self) -> None:
        for provider in ("Google", "DashScope", "OpenAI"):
            with self.subTest(provider=provider):
                result = await self._replay(
                    provider,
                    "等一下",
                    true_barge_in=True,
                    terminal_before_transcript=True,
                )
                self.assertEqual(result["provider_stop_count"], 0)
                event_types = [event["type"] for event in result["events"]]
                self.assertIn("interruption_decision", event_types)
                decision = next(event for event in result["events"] if event["type"] == "interruption_decision")
                self.assertEqual(decision["classification"], "TRUE_BARGE_IN")

    async def test_idle_noise_never_creates_a_turn(self) -> None:
        for provider in ("Google", "DashScope", "OpenAI"):
            with self.subTest(provider=provider):
                result = await self._replay(
                    provider,
                    "。！？",
                    true_barge_in=False,
                    active_turn=False,
                )
                self.assertEqual(result["turns"], [])
                self.assertNotIn("user_transcript", [event["type"] for event in result["events"]])

    async def test_google_waits_for_finished_transcription_before_classifying(self) -> None:
        websocket = CollectingWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=True)
        recorder = await self._recorder("Google")
        clock = FakeClock()
        interruption = InterruptionDecisionCoordinator(clock=clock)
        await self.service._begin_interruption(
            websocket,
            interruption,
            provider="Google",
            provider_event_type="client_vad.speech_started",
            recorder=recorder,
            tool_session=tools,
        )
        session = FakeGoogleSession(
            [
                [google_response(input_transcription=SimpleNamespace(text="嗯", finished=False))],
                [google_response(input_transcription=SimpleNamespace(text="，等一下", finished=True))],
                [google_response(turn_complete=True)],
            ]
        )
        with self.assertRaises(ReplayComplete):
            await self.service._google_to_client_loop(
                websocket,
                session,
                memory,
                tools,
                recorder,
                False,
                interruption,
            )
        decisions = [event for event in websocket.events if event["type"] == "interruption_decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["classification"], "TRUE_BARGE_IN")
        self.assertEqual(decisions[0]["transcript"], "嗯，等一下")

    async def test_google_client_vad_command_drives_shared_provider_decision(self) -> None:
        websocket = CollectingWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "speech_activity_started"}),
                }
            ]
        )
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder("Google")
        interruption = InterruptionDecisionCoordinator(clock=FakeClock())
        session = FakeGoogleSession(
            [[google_response(input_transcription=SimpleNamespace(text="嗯嗯", finished=True))]]
        )

        await self.service._client_to_google_loop(
            websocket,
            session,
            memory,
            tools,
            recorder,
            False,
            interruption,
        )
        self.assertIsNotNone(interruption.pending)
        self.assertEqual(interruption.pending.provider, "Google")
        self.assertEqual(interruption.pending.provider_event_type, "client_vad.speech_started")
        self.assertEqual(interruption.pending.interrupted_turn_id, "voice-turn-1")

        with self.assertRaises(ReplayComplete):
            await self.service._google_to_client_loop(
                websocket,
                session,
                memory,
                tools,
                recorder,
                False,
                interruption,
            )

        decisions = [event for event in websocket.events if event["type"] == "interruption_decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["classification"], "BACKCHANNEL")
        self.assertIsNone(interruption.pending)

    async def test_google_provider_interrupted_timeout_does_not_start_synthetic_turn(self) -> None:
        websocket = CollectingWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {"type": "interruption_timeout", "candidate_id": "interruption-1"}
                    ),
                }
            ]
        )
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder("Google")
        interruption = InterruptionDecisionCoordinator(clock=FakeClock())
        session = BlockingGoogleSession(google_response(interrupted=True))

        provider_task = asyncio.create_task(
            self.service._google_to_client_loop(
                websocket,
                session,
                memory,
                tools,
                recorder,
                False,
                interruption,
            )
        )
        await session.response_processed.wait()
        self.assertIsNotNone(interruption.pending)
        self.assertIsNone(interruption.resume_provider)

        await self.service._client_to_google_loop(
            websocket,
            session,
            memory,
            tools,
            recorder,
            False,
            interruption,
        )

        self.assertEqual(session.sent, [])
        self.assertIsNone(interruption.pending)
        session.release_receive.set()
        with self.assertRaises(ReplayComplete):
            await provider_task

    async def test_google_output_transcription_wins_over_response_text(self) -> None:
        websocket = CollectingWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder("Google")
        response_with_both_channels = SimpleNamespace(
            data=None,
            text="So, you could send those pieces?",
            server_content=SimpleNamespace(
                output_transcription=SimpleNamespace(text="你可以把这些内容发过来。", finished=True)
            ),
        )
        session = FakeGoogleSession(
            [[response_with_both_channels], [google_response(turn_complete=True)]]
        )

        with self.assertRaises(ReplayComplete):
            await self.service._google_to_client_loop(
                websocket, session, memory, tools, recorder
            )

        assistant_texts = [
            event.get("text") for event in websocket.events if event["type"] == "assistant_text"
        ]
        self.assertEqual(assistant_texts, ["你可以把这些内容发过来。"])

    async def test_google_response_text_is_used_only_as_turn_fallback(self) -> None:
        websocket = CollectingWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder("Google")
        session = FakeGoogleSession(
            [
                [SimpleNamespace(data=None, text="Fallback answer.", server_content=None)],
                [google_response(turn_complete=True)],
            ]
        )

        with self.assertRaises(ReplayComplete):
            await self.service._google_to_client_loop(
                websocket, session, memory, tools, recorder
            )

        assistant_texts = [
            event.get("text") for event in websocket.events if event["type"] == "assistant_text"
        ]
        self.assertEqual(assistant_texts, ["Fallback answer."])

    async def test_google_output_transcription_emits_only_novel_overlapping_text(self) -> None:
        websocket = CollectingWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder("Google")
        session = FakeGoogleSession(
            [
                [google_response(output_transcription=SimpleNamespace(text="So, you could send"))],
                [google_response(output_transcription=SimpleNamespace(text="send those pieces?", finished=True))],
                [google_response(turn_complete=True)],
            ]
        )

        with self.assertRaises(ReplayComplete):
            await self.service._google_to_client_loop(
                websocket, session, memory, tools, recorder
            )

        assistant_text = "".join(
            str(event.get("text", ""))
            for event in websocket.events
            if event["type"] == "assistant_text"
        )
        self.assertEqual(assistant_text, "So, you could send those pieces?")

    async def test_google_native_interrupted_true_barge_in_does_not_swallow_new_turn_terminal(self) -> None:
        websocket = CollectingWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder("Google")
        interruption = InterruptionDecisionCoordinator(clock=FakeClock())
        session = FakeGoogleSession(
            [
                [google_response(interrupted=True)],
                [google_response(input_transcription=SimpleNamespace(text="等一下", finished=True))],
                [SimpleNamespace(data=None, text="新的回答", server_content=None)],
                [google_response(turn_complete=True)],
            ]
        )

        with self.assertRaises(ReplayComplete):
            await self.service._google_to_client_loop(
                websocket,
                session,
                memory,
                tools,
                recorder,
                False,
                interruption,
            )

        decisions = [event for event in websocket.events if event["type"] == "interruption_decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["classification"], "TRUE_BARGE_IN")
        self.assertIn(
            "新的回答",
            [event.get("text") for event in websocket.events if event["type"] == "assistant_text"],
        )
        completed = [event for event in websocket.events if event["type"] == "turn_complete"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["turn_id"], "voice-turn-2")

    async def test_missing_transcription_timeout_resolves_pending_candidate_for_all_providers(self) -> None:
        for provider in ("Google", "DashScope", "OpenAI"):
            with self.subTest(provider=provider):
                websocket = CollectingWebSocket(
                    [
                        {
                            "type": "websocket.receive",
                            "text": json.dumps(
                                {"type": "interruption_timeout", "candidate_id": "stale-candidate"}
                            ),
                        },
                        {
                            "type": "websocket.receive",
                            "text": json.dumps(
                                {"type": "interruption_timeout", "candidate_id": "interruption-1"}
                            ),
                        }
                    ]
                )
                memory = FakeMemorySession()
                tools = RecordingToolSession(active=False)
                recorder = await self._recorder(provider)
                interruption = InterruptionDecisionCoordinator(clock=FakeClock())
                await self.service._begin_interruption(
                    websocket,
                    interruption,
                    provider=provider,
                    provider_event_type="test.speech_started",
                    recorder=recorder,
                    tool_session=tools,
                )

                if provider == "Google":
                    await self.service._client_to_google_loop(
                        websocket,
                        FakeGoogleSession([]),
                        memory,
                        tools,
                        recorder,
                        False,
                        interruption,
                    )
                elif provider == "DashScope":
                    await self.service._client_to_dashscope_loop(
                        websocket,
                        MagicMock(),
                        memory,
                        tools,
                        recorder,
                        interruption,
                    )
                else:
                    await self.service._client_to_openai_loop(
                        websocket,
                        FakeOpenAIWebSocket([]),
                        memory,
                        tools,
                        recorder,
                        interruption,
                    )

                decisions = [event for event in websocket.events if event["type"] == "interruption_decision"]
                self.assertEqual(len(decisions), 1)
                self.assertEqual(decisions[0]["classification"], "NOISE_OR_SILENCE")
                self.assertIsNone(interruption.pending)

    async def test_timeout_resolution_is_atomic_with_concurrent_transcript_and_output(self) -> None:
        websocket = BlockingDecisionWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        interruption = InterruptionDecisionCoordinator(clock=FakeClock())
        interruption.begin(
            provider="OpenAI",
            interrupted_turn_id="voice-turn-1",
            provider_event_type="input_audio_buffer.speech_started",
        )

        timeout_task = asyncio.create_task(
            self.service._decide_interruption(
                websocket,
                interruption,
                "",
                memory_session=memory,
                tool_session=tools,
                recorder=None,
                expected_candidate_id="interruption-1",
            )
        )
        await websocket.decision_started.wait()
        self.assertIsNotNone(interruption.pending)

        late_transcript_task = asyncio.create_task(
            self.service._decide_interruption(
                websocket,
                interruption,
                "等一下",
                memory_session=memory,
                tool_session=tools,
                recorder=None,
            )
        )
        output_task = asyncio.create_task(
            self.service._emit_assistant_output(
                websocket,
                interruption,
                {"type": "assistant_text", "text": "timeout期间的尾部"},
                memory_session=memory,
                recorder=None,
            )
        )
        await asyncio.sleep(0)
        self.assertFalse(late_transcript_task.done())
        self.assertFalse(output_task.done())

        websocket.release_decision.set()
        timeout_result, late_transcript_result, _ = await asyncio.gather(
            timeout_task,
            late_transcript_task,
            output_task,
        )

        self.assertEqual(timeout_result[0], False)
        self.assertEqual(late_transcript_result, (True, None))
        self.assertIsNone(interruption.pending)
        event_types = [event["type"] for event in websocket.events]
        self.assertLess(event_types.index("interruption_decision"), event_types.index("assistant_text"))

    async def test_stale_timeout_cannot_resolve_a_new_candidate_after_waiting_for_lock(self) -> None:
        clock_values = iter((1.0, 1.1, 2.0))
        interruption = InterruptionDecisionCoordinator(clock=lambda: next(clock_values))
        interruption.begin(provider="OpenAI", interrupted_turn_id="voice-turn-1")
        await interruption.decision_lock.acquire()
        try:
            timeout_task = asyncio.create_task(
                self.service._decide_interruption(
                    CollectingWebSocket(),
                    interruption,
                    "",
                    memory_session=FakeMemorySession(),
                    tool_session=RecordingToolSession(active=False),
                    recorder=None,
                    expected_candidate_id="interruption-1",
                )
            )
            await asyncio.sleep(0)
            self.assertFalse(timeout_task.done())
            interruption.decide("嗯嗯")
            interruption.complete_decision()
            interruption.begin(provider="OpenAI", interrupted_turn_id="voice-turn-2")
        finally:
            interruption.decision_lock.release()

        self.assertEqual(await timeout_task, (True, None))
        self.assertIsNotNone(interruption.pending)
        self.assertEqual(interruption.pending.candidate_id, "interruption-2")
        self.assertEqual(interruption.pending.interrupted_turn_id, "voice-turn-2")

    async def test_late_openai_transcript_after_timeout_is_reclassified_as_new_candidate(self) -> None:
        websocket = CollectingWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {"type": "interruption_timeout", "candidate_id": "interruption-1"}
                    ),
                }
            ]
        )
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder("OpenAI")
        clock_values = iter((5.0, 5.05, 6.0, 6.04))
        interruption = InterruptionDecisionCoordinator(clock=lambda: next(clock_values))
        interruption.active_response_id = "response-1"
        await self.service._begin_interruption(
            websocket,
            interruption,
            provider="OpenAI",
            provider_event_type="input_audio_buffer.speech_started",
            recorder=recorder,
            tool_session=tools,
        )
        upstream = FakeOpenAIWebSocket([])

        await self.service._client_to_openai_loop(
            websocket,
            upstream,
            memory,
            tools,
            recorder,
            interruption,
        )
        upstream.events = [
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "late-item",
                "transcript": "等一下",
            },
            {"type": "response.done", "response": {"id": "response-1", "status": "cancelled"}},
        ]
        await self.service._openai_to_client_loop(
            websocket,
            upstream,
            memory,
            tools,
            recorder,
            interruption,
        )

        decisions = [event for event in websocket.events if event["type"] == "interruption_decision"]
        self.assertEqual(
            [event["classification"] for event in decisions],
            ["NOISE_OR_SILENCE", "TRUE_BARGE_IN"],
        )
        self.assertEqual(
            [event["candidate_id"] for event in decisions],
            ["interruption-1", "interruption-2"],
        )
        self.assertTrue(decisions[0]["timeout_resolution"])
        self.assertEqual(decisions[1]["supersedes_candidate_id"], "interruption-1")
        self.assertTrue(any(payload.get("type") == "response.cancel" for payload in upstream.sent))

    async def test_client_stop_metric_is_persisted_for_all_provider_commands(self) -> None:
        for provider in ("Google", "DashScope", "OpenAI"):
            with self.subTest(provider=provider):
                websocket = CollectingWebSocket(
                    [
                        {
                            "type": "websocket.receive",
                            "text": json.dumps(
                                {
                                    "type": "interruption_client_stopped",
                                    "candidate_id": "interruption-7",
                                    "turn_id": "voice-turn-1",
                                    "stop_latency_ms": 63,
                                }
                            ),
                        }
                    ]
                )
                recorder = await self._recorder(provider)
                memory = FakeMemorySession()
                tools = RecordingToolSession(active=False)
                interruption = InterruptionDecisionCoordinator()
                if provider == "Google":
                    await self.service._client_to_google_loop(
                        websocket,
                        FakeGoogleSession([]),
                        memory,
                        tools,
                        recorder,
                        False,
                        interruption,
                    )
                elif provider == "DashScope":
                    await self.service._client_to_dashscope_loop(
                        websocket,
                        MagicMock(),
                        memory,
                        tools,
                        recorder,
                        interruption,
                    )
                else:
                    await self.service._client_to_openai_loop(
                        websocket,
                        FakeOpenAIWebSocket([]),
                        memory,
                        tools,
                        recorder,
                        interruption,
                    )
                persisted = [
                    event
                    for event in self.repository.list_session_events(recorder.session_id)
                    if event["event_type"] == "interruption_client_stopped"
                ]
                self.assertEqual(len(persisted), 1)
                self.assertEqual(persisted[0]["payload"]["provider"], provider)
                self.assertEqual(persisted[0]["payload"]["stop_latency_ms"], 63)

    async def test_noise_does_not_create_a_turn_or_cancel_answer(self) -> None:
        results = {
            provider: await self._replay(provider, "。！？", true_barge_in=False)
            for provider in ("Google", "DashScope", "OpenAI")
        }
        for provider, result in results.items():
            with self.subTest(provider=provider):
                decision = next(event for event in result["events"] if event["type"] == "interruption_decision")
                self.assertEqual(decision["classification"], "NOISE_OR_SILENCE")
                self.assertNotIn("interrupted", [event["type"] for event in result["events"]])
                self.assertEqual(result["tool_cancel_count"], 0)
                self.assertEqual(result["provider_stop_count"], 0)
                self.assertEqual(result["handled_texts"], [])
                self.assertEqual(len(result["turns"]), 1)
        canonical = [self._canonical_timeline(result["timeline"]) for result in results.values()]
        self.assertEqual(canonical[0], canonical[1])
        self.assertEqual(canonical[1], canonical[2])


class DashScopeOmniTextDedupTests(unittest.IsolatedAsyncioTestCase):
    """Regression tests for qwen3.5-omni-*-realtime duplicated reply text.

    The DashScope omni loop forwards BOTH the incremental
    response.audio_transcript.delta deltas AND the full-text
    response.audio_transcript.done / response.text.done. When the final
    transcript differs from the accumulated deltas even slightly (trailing
    punctuation, spacing, re-transcribed words), the frontend merge cannot dedup
    it and the whole reply appears twice. The final full-text event must be
    suppressed once deltas were already streamed for that response.
    """

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = VoiceAgentSessionRepository(Path(self.temp_dir.name) / "voice.db")
        self.service = RealtimeVoiceService(voice_session_repository=self.repository)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def _run_loop(self, raw_events: list[dict]) -> CollectingWebSocket:
        websocket = CollectingWebSocket()
        memory = FakeMemorySession()
        tools = RecordingToolSession(active=False)
        recorder = await self._recorder(active_turn=False)
        queue: asyncio.Queue[dict] = asyncio.Queue()
        callback = DashScopeRealtimeCallback(loop=asyncio.get_running_loop(), queue=queue)
        for event in raw_events:
            callback.on_event(event)
        # The callback pushes via loop.call_soon_threadsafe; yield once so those
        # scheduled puts land in the queue BEFORE the "closed" sentinel.
        await asyncio.sleep(0)
        queue.put_nowait({"type": "closed"})
        conversation = MagicMock()
        await self.service._dashscope_to_client_loop(
            websocket,
            queue,
            memory,
            conversation,
            "test-voice",
            tools,
            recorder,
        )
        await recorder.finish()
        return websocket

    async def _recorder(self, *, active_turn: bool) -> VoiceAgentSessionRecorder:
        session = self.repository.create_session(
            provider="DashScope",
            model="qwen3.5-omni-plus-realtime-replay",
            voice="Tina",
            meta={"transport": "websocket"},
        )
        recorder = VoiceAgentSessionRecorder(self.repository, session["id"])
        await recorder.start(
            {
                "provider": "DashScope",
                "model": "qwen3.5-omni-plus-realtime-replay",
                "voice": "Tina",
                "status": "open",
                "meta": {"transport": "websocket"},
            }
        )
        if active_turn:
            await recorder.note_user_transcript("请解释实时语音")
            await recorder.note_assistant_text("这是还没有说完的回答")
        return recorder

    async def test_final_done_does_not_duplicate_streamed_delta(self) -> None:
        # The streaming delta and the final done transcript differ only in
        # punctuation (the model re-transcribes the completed output). Forwarding
        # both makes the frontend render the whole sentence twice.
        websocket = await self._run_loop(
            [
                {"type": "response.created", "response": {"id": "resp-1"}},
                {
                    "type": "response.audio_transcript.delta",
                    "response_id": "resp-1",
                    "delta": "Hello there how are you doing today?",
                },
                {
                    "type": "response.audio_transcript.done",
                    "response_id": "resp-1",
                    "transcript": "Hello there, how are you doing today?",
                },
                {"type": "response.done", "response": {"id": "resp-1", "status": "completed"}},
            ]
        )
        texts = [event["text"] for event in websocket.events if event["type"] == "assistant_text"]
        self.assertEqual(texts, ["Hello there how are you doing today?"])

    async def test_final_done_fallback_when_no_delta_streamed(self) -> None:
        # Ultra-fast single-shot reply where response.audio_transcript.done
        # arrives before any delta: the final text must be emitted once so the
        # user still sees the reply.
        websocket = await self._run_loop(
            [
                {"type": "response.created", "response": {"id": "resp-1"}},
                {
                    "type": "response.audio_transcript.done",
                    "response_id": "resp-1",
                    "transcript": "Hello world",
                },
                {"type": "response.done", "response": {"id": "resp-1", "status": "completed"}},
            ]
        )
        texts = [event["text"] for event in websocket.events if event["type"] == "assistant_text"]
        self.assertEqual(texts, ["Hello world"])

    async def test_second_response_standalone_final_still_emits(self) -> None:
        # Per-response tracking: suppressing response-1's done transcript (which
        # streamed deltas) must NOT suppress response-2's standalone final text,
        # even though the recorder's accumulated assistant text is still set.
        websocket = await self._run_loop(
            [
                {"type": "response.created", "response": {"id": "resp-1"}},
                {
                    "type": "response.audio_transcript.delta",
                    "response_id": "resp-1",
                    "delta": "One",
                },
                {
                    "type": "response.audio_transcript.done",
                    "response_id": "resp-1",
                    "transcript": "One",
                },
                {"type": "response.done", "response": {"id": "resp-1", "status": "completed"}},
                {"type": "response.created", "response": {"id": "resp-2"}},
                {
                    "type": "response.audio_transcript.done",
                    "response_id": "resp-2",
                    "transcript": "Two",
                },
                {"type": "response.done", "response": {"id": "resp-2", "status": "completed"}},
            ]
        )
        texts = [event["text"] for event in websocket.events if event["type"] == "assistant_text"]
        self.assertEqual(texts, ["One", "Two"])


if __name__ == "__main__":
    unittest.main()
