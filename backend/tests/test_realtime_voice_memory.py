from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from services.evermem_service import EverMemService
from services.realtime_voice_service import (
    RealtimeMemorySession,
    RealtimeVoiceService,
    _is_google_live_translate_model,
)
from services.voice_agent_tools import VoiceAgentToolSession


class _FakeAudioTranscriptionConfig:
    pass


class _FakeTranslationConfig:
    def __init__(self, target_language_code: str, echo_target_language: bool) -> None:
        self.target_language_code = target_language_code
        self.echo_target_language = echo_target_language


class _FakeLiveConnectConfig:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakePrebuiltVoiceConfig:
    def __init__(self, voice_name: str) -> None:
        self.voice_name = voice_name


class _FakeVoiceConfig:
    def __init__(self, prebuilt_voice_config=None) -> None:
        self.prebuilt_voice_config = prebuilt_voice_config


class _FakeSpeechConfig:
    def __init__(self, voice_config=None) -> None:
        self.voice_config = voice_config


class _FakeGoogleTypes:
    AudioTranscriptionConfig = _FakeAudioTranscriptionConfig
    TranslationConfig = _FakeTranslationConfig
    LiveConnectConfig = _FakeLiveConnectConfig
    SpeechConfig = _FakeSpeechConfig
    VoiceConfig = _FakeVoiceConfig
    PrebuiltVoiceConfig = _FakePrebuiltVoiceConfig


class _FakeGoogleResponse:
    def __init__(self, server_content) -> None:
        self.server_content = server_content


class _FakeTextInputWebSocket:
    def __init__(self) -> None:
        self._messages = [
            {"text": '{"type":"text_input","text":"hello"}'},
            {"text": '{"type":"stop"}'},
        ]
        self.events: list[dict[str, object]] = []

    async def receive(self) -> dict[str, object]:
        return self._messages.pop(0)

    async def send_json(self, payload: dict[str, object]) -> None:
        self.events.append(payload)


class _FakeTranscriptObject:
    def __init__(self, text: str | None, finished: bool | None = None, language_code: str = "ja") -> None:
        self.text = text
        self.finished = finished
        self.language_code = language_code


class _FakeServerContent:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class RealtimeMemorySessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        RealtimeMemorySession._PENDING_CACHE_PATH = Path(self.temp_dir.name) / "pending.json"
        RealtimeMemorySession._PENDING_MEMORY_CACHE.clear()

    def tearDown(self) -> None:
        RealtimeMemorySession._PENDING_MEMORY_CACHE.clear()
        self.temp_dir.cleanup()

    async def test_flush_turn_persists_only_structured_voice_memory(self) -> None:
        session = RealtimeMemorySession()
        session.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
                "group_id": "voice-group-001",
            }
        )
        session.note_user_transcript("以后比赛提交阶段默认都用中文女声来播报。")
        session.note_assistant_text("好的，我们先检查记忆接入状态。")

        with patch.object(
            EverMemService,
            "add_memory",
            new=AsyncMock(return_value={"status": "success"}),
        ) as add_memory:
            result = await session.flush_turn()

        self.assertEqual(add_memory.await_count, 1)
        self.assertEqual(result["saved_count"], 1)
        self.assertEqual(result["local_pending_count"], 1)
        first_call = add_memory.await_args_list[0]
        self.assertEqual(first_call.kwargs["user_id"], "voice-demo")
        self.assertEqual(first_call.kwargs["sender"], "voice-demo")
        self.assertEqual(first_call.kwargs["group_id"], "voice-group-001")
        self.assertIn("语音偏好", first_call.kwargs["content"])

    async def test_trivial_question_does_not_persist_memory(self) -> None:
        session = RealtimeMemorySession()
        session.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
            }
        )
        session.note_user_transcript("现在几点了？")

        with patch.object(
            EverMemService,
            "add_memory",
            new=AsyncMock(return_value={"status": "success"}),
        ) as add_memory:
            result = await session.flush_turn()

        add_memory.assert_not_awaited()
        self.assertEqual(result["reason"], "no_candidate_memory")

    async def test_config_false_disables_memory_flush(self) -> None:
        session = RealtimeMemorySession()
        session.configure({"enabled": False})
        session.note_user_transcript("以后都用女声。")

        with patch.object(
            EverMemService,
            "add_memory",
            new=AsyncMock(return_value={"status": "success"}),
        ) as add_memory:
            result = await session.flush_turn()

        add_memory.assert_not_awaited()
        self.assertEqual(result["reason"], "disabled_or_empty")

    async def test_retrieve_memory_context_for_recall_query(self) -> None:
        session = RealtimeMemorySession()
        session.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
                "group_id": "voice-group-001",
            }
        )
        session.note_user_transcript("我之前默认用什么声音来着？")

        with patch.object(
            EverMemService,
            "search_memories",
            new=AsyncMock(
                return_value=[
                    {"content": "[语音偏好] 默认使用中文女声播报", "score": 0.91},
                    {"content": "[任务] 当前重点是比赛提交", "score": 0.72},
                ]
            ),
        ) as search_memories:
            result = await session.retrieve_memory_context()

        self.assertIn("默认使用中文女声播报", result["context"])
        self.assertEqual(result["memories_retrieved"], 2)
        self.assertEqual(result["cloud_count"], 2)
        self.assertEqual(result["local_pending_count"], 0)
        self.assertEqual(search_memories.await_count, 1)
        self.assertEqual(search_memories.await_args.kwargs["group_ids"], ["voice-group-001"])

    async def test_retrieve_memory_context_for_task_question(self) -> None:
        session = RealtimeMemorySession()
        session.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
            }
        )
        session.note_user_transcript("你帮我检索一下本周的重点工作是什么？")

        with patch.object(
            EverMemService,
            "search_memories",
            new=AsyncMock(
                return_value=[
                    {"content": "[任务] 当前重点是比赛提交", "score": 0.88},
                ]
            ),
        ) as search_memories:
            result = await session.retrieve_memory_context()

        self.assertIn("当前重点是比赛提交", result["context"])
        self.assertEqual(result["memories_retrieved"], 1)
        self.assertEqual(search_memories.await_count, 1)

    async def test_forced_recall_query_uses_longer_timeout_budget(self) -> None:
        session = RealtimeMemorySession()
        session.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
            }
        )
        session.note_user_transcript("帮我回忆一下我们刚才说的重点工作是什么？")

        captured_timeout: float | None = None

        async def fake_wait_for(awaitable, timeout):
            nonlocal captured_timeout
            captured_timeout = timeout
            return await awaitable

        with patch("services.realtime_voice_service.asyncio.wait_for", new=fake_wait_for):
            with patch.object(
                EverMemService,
                "search_memories",
                new=AsyncMock(return_value=[]),
            ):
                await session.retrieve_memory_context()

        self.assertEqual(captured_timeout, 0.35)

    async def test_retrieve_memory_context_skips_trivial_turns(self) -> None:
        session = RealtimeMemorySession()
        session.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
            }
        )
        session.note_user_transcript("你好")

        with patch.object(
            EverMemService,
            "search_memories",
            new=AsyncMock(return_value=[]),
        ) as search_memories:
            result = await session.retrieve_memory_context()

        self.assertEqual(result["context"], "")
        self.assertEqual(result["memories_retrieved"], 0)
        self.assertFalse(result["attempted"])
        search_memories.assert_not_awaited()

    def test_forced_recall_query_detection(self) -> None:
        session = RealtimeMemorySession()
        session.note_user_transcript("你还记得我们刚才说的重点工作是什么吗？")
        self.assertTrue(session.is_forced_recall_query())
        session.note_user_transcript("今天上海天气怎么样？")
        self.assertFalse(session.is_forced_recall_query())

    async def test_retrieve_memory_context_uses_local_pending_fallback(self) -> None:
        writer = RealtimeMemorySession()
        writer.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
                "group_id": "voice-group-001",
            }
        )
        writer.note_user_transcript("本周的重点是比赛提交，以后默认用中文回答。")

        with patch.object(
            EverMemService,
            "add_memory",
            new=AsyncMock(return_value={"status": "success"}),
        ):
            await writer.flush_turn()

        reader = RealtimeMemorySession()
        reader.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
                "group_id": "voice-group-001",
            }
        )
        reader.note_user_transcript("你还记得我们刚才说的本周重点工作是什么吗？")

        with patch.object(
            EverMemService,
            "search_memories",
            new=AsyncMock(return_value=[]),
        ):
            result = await reader.retrieve_memory_context()

        self.assertEqual(result["memories_retrieved"], 1)
        self.assertEqual(result["local_pending_count"], 1)
        self.assertEqual(result["cloud_count"], 0)
        self.assertIn("本地待同步记忆", result["context"])

    async def test_pending_cache_is_isolated_by_group_id(self) -> None:
        first = RealtimeMemorySession()
        first.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
                "group_id": "voice-group-001",
            }
        )
        first.note_user_transcript("本周重点是比赛提交。")

        with patch.object(
            EverMemService,
            "add_memory",
            new=AsyncMock(return_value={"status": "success"}),
        ):
            await first.flush_turn()

        second = RealtimeMemorySession()
        second.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
                "group_id": "voice-group-002",
            }
        )
        second.note_user_transcript("请继续比赛提交相关安排。")

        with patch.object(
            EverMemService,
            "search_memories",
            new=AsyncMock(return_value=[]),
        ):
            result = await second.retrieve_memory_context()

        self.assertEqual(result["local_pending_count"], 0)
        self.assertEqual(result["memories_retrieved"], 0)

    async def test_forced_recall_query_can_use_scope_pending_fallback_across_groups(self) -> None:
        first = RealtimeMemorySession()
        first.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
                "group_id": "voice-group-001",
            }
        )
        first.note_user_transcript("本周重点是比赛提交。")

        with patch.object(
            EverMemService,
            "add_memory",
            new=AsyncMock(return_value={"status": "success"}),
        ):
            await first.flush_turn()

        second = RealtimeMemorySession()
        second.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
                "group_id": "voice-group-002",
            }
        )
        second.note_user_transcript("你还记得我们刚才说的本周重点工作是什么吗？")

        with patch.object(
            EverMemService,
            "search_memories",
            new=AsyncMock(return_value=[]),
        ):
            result = await second.retrieve_memory_context()

        self.assertEqual(result["local_pending_count"], 1)
        self.assertEqual(result["memories_retrieved"], 1)
        self.assertIn("本地待同步记忆", result["context"])

    async def test_retrieve_memory_context_uses_persisted_pending_fallback_after_restart(self) -> None:
        writer = RealtimeMemorySession()
        writer.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
            }
        )
        writer.note_user_transcript("本周的重点是比赛提交，以后默认用中文回答。")

        with patch.object(
            EverMemService,
            "add_memory",
            new=AsyncMock(return_value={"status": "success"}),
        ):
            await writer.flush_turn()

        RealtimeMemorySession._PENDING_MEMORY_CACHE.clear()

        reader = RealtimeMemorySession()
        reader.configure(
            {
                "enabled": True,
                "api_url": "https://memory.example.com",
                "api_key": "memory-key",
                "scope_id": "voice-demo",
            }
        )
        reader.note_user_transcript("你还记得我们刚才说的本周重点工作是什么吗？")

        with patch.object(
            EverMemService,
            "search_memories",
            new=AsyncMock(return_value=[]),
        ):
            result = await reader.retrieve_memory_context()

        self.assertEqual(result["memories_retrieved"], 1)
        self.assertEqual(result["local_pending_count"], 1)
        self.assertEqual(result["cloud_count"], 0)
        self.assertIn("本地待同步记忆", result["context"])

    async def test_google_memory_prefill_sends_client_content(self) -> None:
        service = RealtimeVoiceService()
        fake_session = AsyncMock()

        await service._apply_google_memory_prefill(
            fake_session,
            "1. [语音偏好] 默认使用中文女声播报",
        )

        fake_session.send_client_content.assert_awaited_once()
        kwargs = fake_session.send_client_content.await_args.kwargs
        self.assertFalse(kwargs["turn_complete"])
        self.assertIn("默认使用中文女声播报", kwargs["turns"][0]["parts"][0]["text"])

    def test_google_live_translate_model_detection(self) -> None:
        self.assertTrue(_is_google_live_translate_model("gemini-3.5-live-translate-preview"))
        self.assertFalse(_is_google_live_translate_model("gemini-2.5-flash-native-audio-preview-12-2025"))

    def test_google_voice_config_uses_conversation_safe_endpointing(self) -> None:
        config = RealtimeVoiceService._build_live_config("Aoede")

        realtime_input = config.realtime_input_config
        self.assertIsNotNone(realtime_input)
        assert realtime_input is not None
        detection = realtime_input.automatic_activity_detection
        self.assertIsNotNone(detection)
        assert detection is not None
        self.assertEqual(detection.silence_duration_ms, 1500)
        self.assertEqual(str(realtime_input.activity_handling), "ActivityHandling.NO_INTERRUPTION")
        declarations = config.tools[0].function_declarations
        self.assertEqual(
            [declaration.name for declaration in declarations],
            ["search_web"],
        )

    def test_google_live_translate_config_uses_translation_settings_only(self) -> None:
        with patch("services.realtime_google_provider.types", new=_FakeGoogleTypes):
            config = RealtimeVoiceService._build_live_translate_config(
                "zh-Hans", True
            )

        self.assertEqual(config.kwargs["response_modalities"], ["AUDIO"])
        self.assertIn("input_audio_transcription", config.kwargs)
        self.assertIn("output_audio_transcription", config.kwargs)
        self.assertNotIn("system_instruction", config.kwargs)
        self.assertNotIn("speech_config", config.kwargs)
        self.assertNotIn("tools", config.kwargs)
        translation_config = config.kwargs["translation_config"]
        self.assertEqual(translation_config.target_language_code, "zh-Hans")
        self.assertTrue(translation_config.echo_target_language)

    async def test_google_live_translate_rejects_text_input(self) -> None:
        service = RealtimeVoiceService()
        websocket = _FakeTextInputWebSocket()
        session = AsyncMock()
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()

        await service._client_to_google_loop(
            websocket,  # type: ignore[arg-type]
            session,
            memory_session,
            tool_session,
            is_live_translate=True,
        )

        session.send.assert_not_awaited()
        self.assertEqual(websocket.events[0]["type"], "error")
        self.assertIn("仅支持实时音频输入", str(websocket.events[0]["message"]))

    def test_extract_transcript_text_ignores_empty_sdk_objects(self) -> None:
        content = _FakeServerContent(
            input_transcription=_FakeTranscriptObject(text=None, finished=None, language_code="ja")
        )

        extracted = RealtimeVoiceService._extract_transcript_text(
            content,
            ("input_transcription",),
        )

        self.assertEqual(extracted, "")

    def test_extract_transcript_text_reads_text_field_only(self) -> None:
        content = _FakeServerContent(
            input_transcription=_FakeTranscriptObject(text="あ、今日は外に旅行に行きたいです。", finished=True)
        )

        extracted = RealtimeVoiceService._extract_transcript_text(
            content,
            ("input_transcription",),
        )

        self.assertEqual(extracted, "あ、今日は外に旅行に行きたいです。")

    async def test_google_live_translate_inactivity_timeout(self) -> None:
        class _LocalFakeTurn:
            def __init__(self, responses) -> None:
                self.responses = responses
                self.yielded = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.responses:
                    return self.responses.pop(0)
                if not self.yielded:
                    self.yielded = True
                    # Sleep long enough for the 2.0 second inactivity timeout to trigger
                    await asyncio.sleep(2.5)
                raise StopAsyncIteration

        class _LocalFakeSession:
            def __init__(self, responses) -> None:
                self.responses = responses
                self.turn_yielded = False

            def receive(self):
                if not self.turn_yielded:
                    self.turn_yielded = True
                    return _LocalFakeTurn(self.responses)
                # Subsequent calls return empty turns that sleep to prevent busy looping
                return _LocalFakeTurn([])

        # Create a websocket that we can collect events from
        websocket = _FakeTextInputWebSocket()
        # Mock recorder and tool session
        recorder = AsyncMock()
        recorder.session_id = "test-session"
        recorder.current_assistant_text = ""
        recorder.complete_turn = AsyncMock(return_value="turn-123")

        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()

        # Prepare some responses from Gemini
        gemini_responses = [
            _FakeGoogleResponse(
                server_content=_FakeServerContent(
                    input_transcription=_FakeTranscriptObject(text="Hello", finished=True)
                )
            )
        ]

        fake_session = _LocalFakeSession(gemini_responses)
        service = RealtimeVoiceService()

        # Run the loop, but since it sleeps, we run it as a task and cancel it after 3 seconds
        loop_task = asyncio.create_task(
            service._google_to_client_loop(
                websocket,  # type: ignore[arg-type]
                fake_session,
                memory_session,
                tool_session,
                recorder=recorder,
                is_live_translate=True,
            )
        )

        # Wait for the timeout to trigger and send the turn_complete event
        await asyncio.sleep(3.0)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Check if the turn_complete event was sent
        turn_complete_events = [e for e in websocket.events if e.get("type") == "turn_complete"]
        self.assertEqual(len(turn_complete_events), 1)
        self.assertEqual(turn_complete_events[0]["turn_id"], "turn-123")


if __name__ == "__main__":
    unittest.main()
