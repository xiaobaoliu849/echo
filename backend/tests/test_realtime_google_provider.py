"""Unit tests for Google Gemini Live provider race conditions and turn lifecycle."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services.realtime_constants import _merge_streaming_text
from services.realtime_memory_session import RealtimeMemorySession
from services.realtime_session_recorder import VoiceAgentSessionRecorder
from services.realtime_voice_service import RealtimeVoiceService
from services.voice_agent_tools import VoiceAgentToolSession


class _MockWebSocket:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.events.append(payload)


class _MockGoogleResponse:
    def __init__(self, *, data: bytes | None = None, text: str | None = None, server_content=None) -> None:
        self.data = data
        self.text = text
        self.server_content = server_content


class _MockServerContent:
    def __init__(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _MockTranscriptObject:
    def __init__(self, text: str | None, finished: bool = True) -> None:
        self.text = text
        self.finished = finished


class _MockSession:
    def __init__(self, turns_list) -> None:
        self._turns = list(turns_list)

    def receive(self):
        if self._turns:
            return self._turns.pop(0)

        async def _sleeping_turn():
            await asyncio.sleep(60)
            if False:
                yield None

        return _sleeping_turn()


class _MockAsyncTurn:
    def __init__(self, responses) -> None:
        self._responses = list(responses)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._responses:
            return self._responses.pop(0)
        raise StopAsyncIteration


class GoogleRealtimeProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_first_delayed_asr_no_self_interruption(self) -> None:
        """Verify that when assistant audio arrives before user ASR, the delayed ASR
        is recognized as the current turn's prompt and does NOT trigger self-interruption.
        """
        service = RealtimeVoiceService()
        websocket = _MockWebSocket()

        from unittest.mock import MagicMock
        mock_repo = MagicMock()
        recorder = VoiceAgentSessionRecorder(repository=mock_repo, session_id="test-google-session")

        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()

        # Turn sequence simulating Gemini 2.5 Flash:
        # Chunk 1: Assistant audio & text arrives first (latency ~250ms)
        # Chunk 2: User input transcription arrives delayed (~600ms)
        # Chunk 3: Assistant finishes with turn_complete
        responses = [
            _MockGoogleResponse(
                data=b"\x00\x01" * 1600,
                text="Oh I'm sorry to hear that.",
            ),
            _MockGoogleResponse(
                server_content=_MockServerContent(
                    input_transcription=_MockTranscriptObject(
                        text="what is going on? I can't hear you and no response.",
                        finished=True,
                    )
                )
            ),
            _MockGoogleResponse(
                server_content=_MockServerContent(
                    turn_complete=True,
                )
            ),
        ]

        turn = _MockAsyncTurn(responses)
        mock_session = _MockSession([turn])

        # Run _google_to_client_loop with timeout protection
        loop_task = asyncio.create_task(
            service._google_to_client_loop(
                websocket,  # type: ignore[arg-type]
                mock_session,
                memory_session,
                tool_session,
                recorder=recorder,
            )
        )

        # Allow the loop to process the single turn
        await asyncio.sleep(0.3)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        event_types = [e["type"] for e in websocket.events]

        # 1. Must NOT send "interrupted" event to frontend
        self.assertNotIn("interrupted", event_types)

        # 2. Must receive assistant_audio and assistant_text
        self.assertIn("assistant_audio", event_types)
        self.assertIn("assistant_text", event_types)

        # 3. Must receive user_transcript with the user prompt
        user_transcript_events = [e for e in websocket.events if e["type"] == "user_transcript"]
        self.assertTrue(len(user_transcript_events) > 0)
        self.assertIn("what is going on", str(user_transcript_events[-1].get("text", "")))

        # 4. Turn ID must be consistent between assistant and user (no turn split)
        assistant_turn_id = next(e.get("turn_id") for e in websocket.events if e["type"] == "assistant_audio")
        final_user_turn_id = user_transcript_events[-1].get("turn_id")
        self.assertEqual(assistant_turn_id, final_user_turn_id)

        # 5. Must complete cleanly with turn_complete
        self.assertIn("turn_complete", event_types)
        complete_event = next(e for e in websocket.events if e["type"] == "turn_complete")
        self.assertFalse(complete_event.get("interrupted"))

    def test_word_space_merging_preserves_spaces(self) -> None:
        """Verify _merge_streaming_text properly separates English words and preserves CJK."""
        # Consecutive words without space in chunks
        text1, _ = _merge_streaming_text("", "what")
        text2, _ = _merge_streaming_text(text1, "is")
        text3, _ = _merge_streaming_text(text2, "going")
        text4, _ = _merge_streaming_text(text3, "on")
        self.assertEqual(text4, "what is going on")

        # Chunks with leading space
        text_a, _ = _merge_streaming_text("", "hello")
        text_b, _ = _merge_streaming_text(text_a, " world")
        self.assertEqual(text_b, "hello world")

        # CJK text should NOT add spaces
        cjk1, _ = _merge_streaming_text("", "你好")
        cjk2, _ = _merge_streaming_text(cjk1, "世界")
        self.assertEqual(cjk2, "你好世界")

    async def test_session_recorder_same_turn_backfill(self) -> None:
        """Verify recorder attaches user text to the active turn when assistant starts first."""
        from unittest.mock import MagicMock
        mock_repo = MagicMock()
        recorder = VoiceAgentSessionRecorder(repository=mock_repo, session_id="test-session")

        # Assistant audio arrives first -> creates turn 1
        turn_id_1, _ = await recorder.note_assistant_audio()
        self.assertEqual(turn_id_1, "voice-turn-1")

        # User transcript arrives delayed -> should attach to turn 1, NOT advance to turn 2
        turn_id_2 = await recorder.note_user_transcript("Delayed user question")
        self.assertEqual(turn_id_2, "voice-turn-1")
        self.assertEqual(recorder.current_turn_id, "voice-turn-1")

        # Verify DB upsert was called with user_text for voice-turn-1
        mock_repo.upsert_turn.assert_called()
        call_args = mock_repo.upsert_turn.call_args
        self.assertEqual(call_args.args[1], "voice-turn-1")
        self.assertEqual(call_args.kwargs.get("user_text"), "Delayed user question")

    async def test_genuine_server_interruption_still_works(self) -> None:
        """Verify that server_content.interrupted properly triggers barge-in."""
        service = RealtimeVoiceService()
        websocket = _MockWebSocket()

        from unittest.mock import MagicMock
        mock_repo = MagicMock()
        recorder = VoiceAgentSessionRecorder(repository=mock_repo, session_id="test-session")
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()

        # Turn where user starts speaking while assistant is playing -> Google sends server_content.interrupted
        responses = [
            _MockGoogleResponse(
                server_content=_MockServerContent(
                    input_transcription=_MockTranscriptObject(text="Initial question", finished=True)
                )
            ),
            _MockGoogleResponse(
                data=b"\x00\x01" * 1600,
                text="Long assistant reply...",
            ),
            _MockGoogleResponse(
                server_content=_MockServerContent(
                    interrupted=True,
                )
            ),
        ]

        turn = _MockAsyncTurn(responses)
        mock_session = _MockSession([turn])

        loop_task = asyncio.create_task(
            service._google_to_client_loop(
                websocket,  # type: ignore[arg-type]
                mock_session,
                memory_session,
                tool_session,
                recorder=recorder,
            )
        )

        await asyncio.sleep(0.3)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        event_types = [e["type"] for e in websocket.events]
        self.assertIn("interruption_pending", event_types)

    async def test_second_utterance_during_assistant_speech_triggers_barge_in(self) -> None:
        """Verify that when a second distinct utterance arrives while the assistant is already

        speaking and the initial prompt was already established, barge-in is triggered.
        """
        service = RealtimeVoiceService()
        websocket = _MockWebSocket()

        from unittest.mock import MagicMock
        mock_repo = MagicMock()
        recorder = VoiceAgentSessionRecorder(repository=mock_repo, session_id="test-bargein-session")
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()

        # Turn sequence:
        # 1. Initial prompt arrives -> finalized as turn prompt
        # 2. Assistant starts speaking
        # 3. Second utterance arrives while assistant is still outputting audio
        responses = [
            _MockGoogleResponse(
                server_content=_MockServerContent(
                    input_transcription=_MockTranscriptObject(text="Initial question", finished=True)
                )
            ),
            _MockGoogleResponse(
                data=b"\x00\x01" * 1600,
                text="The weather in Tokyo is sunny today.",
            ),
            _MockGoogleResponse(
                server_content=_MockServerContent(
                    input_transcription=_MockTranscriptObject(text="Wait stop talking and tell me the time instead.", finished=True)
                )
            ),
        ]

        turn = _MockAsyncTurn(responses)
        mock_session = _MockSession([turn])

        loop_task = asyncio.create_task(
            service._google_to_client_loop(
                websocket,  # type: ignore[arg-type]
                mock_session,
                memory_session,
                tool_session,
                recorder=recorder,
            )
        )

        await asyncio.sleep(0.3)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        event_types = [e["type"] for e in websocket.events]
        self.assertIn("interruption_pending", event_types)
        self.assertIn("interrupted", event_types)


if __name__ == "__main__":
    unittest.main()
