"""Adversarial Gemini Live replays: cancellation must not depend on ASR."""
import asyncio
import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.interruption_classifier import InterruptionDecisionCoordinator
from services.realtime_session_recorder import VoiceAgentSessionRecorder
from services.realtime_voice_service import RealtimeVoiceService
from test_realtime_provider_replay import (
    BlockingGoogleSession, CollectingWebSocket, FakeGoogleSession,
    FakeMemorySession, RecordingToolSession, ReplayComplete, google_response,
)


class GoogleNativeInterruptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = RealtimeVoiceService()
        self.ws = CollectingWebSocket()
        self.memory = FakeMemorySession()
        self.tools = RecordingToolSession(active=False)
        self.recorder = VoiceAgentSessionRecorder(repository=MagicMock(), session_id="native-test")
        await self.recorder.note_user_transcript("Tell me a long story")
        await self.recorder.note_assistant_text("Once upon a time")
        self.old_turn = self.recorder.current_turn_id
        self.coordinator = InterruptionDecisionCoordinator()

    async def replay(self, responses, model="gemini-3.8-live"):
        session = FakeGoogleSession([responses])
        with self.assertRaises(ReplayComplete):
            await self.service._google_to_client_loop(
                self.ws, session, self.memory, self.tools, self.recorder,
                interruption=self.coordinator, model=model,
            )

    async def test_native_signal_stops_before_any_transcription_or_timeout(self):
        session = BlockingGoogleSession(google_response(interrupted=True))
        task = asyncio.create_task(self.service._google_to_client_loop(
            self.ws, session, self.memory, self.tools, self.recorder,
            interruption=self.coordinator, model="gemini-3.8-live",
        ))
        try:
            await asyncio.wait_for(session.response_processed.wait(), 2)
            self.assertIsNone(self.coordinator.pending)
            decision = next(e for e in self.ws.events if e["type"] == "interruption_decision")
            self.assertEqual(decision["rule"], "provider_interrupted")
            self.assertEqual(decision["classification"], "TRUE_BARGE_IN")
            self.assertTrue(any(e["type"] == "interrupted" for e in self.ws.events))
            self.assertFalse(any(e["type"] == "turn_complete" for e in self.ws.events))
        finally:
            session.release_receive.set()
            with self.assertRaises(ReplayComplete):
                await task

    async def test_mixed_event_and_late_audio_are_discarded_new_turn_survives(self):
        await self.replay([
            SimpleNamespace(data=b"stale", text="stale", server_content=SimpleNamespace(
                interrupted=True,
                output_transcription=SimpleNamespace(text="stale", finished=True),
                input_transcription=SimpleNamespace(text="Well", finished=False),
            )),
            SimpleNamespace(data=b"late", text="late", server_content=None),
            google_response(turn_complete=True, interaction_status="IN_PROGRESS"),
            google_response(input_transcription=SimpleNamespace(text="tell me about cats", finished=True)),
            SimpleNamespace(data=b"new", text="Cats are great", server_content=None),
            google_response(turn_complete=True, interaction_status="IDLE"),
        ], model="gemini-3.8-live-extended-thinking")
        audio = [e for e in self.ws.events if e["type"] == "assistant_audio"]
        self.assertEqual([e["audio"] for e in audio], [base64.b64encode(b"new").decode()])
        self.assertNotEqual(audio[0]["turn_id"], self.old_turn)
        self.assertEqual(self.memory.user_texts, ["Well tell me about cats"])
        complete = [e for e in self.ws.events if e["type"] == "turn_complete"]
        self.assertEqual(len(complete), 1)
        self.assertEqual(complete[0]["turn_id"], audio[0]["turn_id"])
        self.assertEqual(self.memory.assistant_texts, ["Cats are great"])

    async def test_short_backchannel_does_not_reverse_provider_cancellation(self):
        await self.replay([
            google_response(interrupted=True, turn_complete=True),
            google_response(input_transcription=SimpleNamespace(text="yeah", finished=True)),
            SimpleNamespace(data=b"new", text="Yes?", server_content=None),
            google_response(turn_complete=True),
        ])
        decisions = [e for e in self.ws.events if e["type"] == "interruption_decision"]
        self.assertEqual([e["classification"] for e in decisions], ["TRUE_BARGE_IN"])
        self.assertEqual(self.memory.user_texts, ["yeah"])
        self.assertEqual(self.memory.assistant_texts, ["Yes?"])

    async def test_repeated_interruptions_and_duplicate_marker_do_not_poison_next_turn(self):
        await self.replay([
            google_response(interrupted=True),
            google_response(interrupted=True),
            google_response(turn_complete=True),
            google_response(input_transcription=SimpleNamespace(text="Try again", finished=True)),
            SimpleNamespace(data=b"second", text=None, server_content=None),
            google_response(input_transcription=SimpleNamespace(text="Actually stop", finished=True)),
            google_response(interrupted=True, turn_complete=True),
            SimpleNamespace(data=b"third", text=None, server_content=None),
            google_response(turn_complete=True),
        ])
        interruptions = [e for e in self.ws.events if e["type"] == "interrupted"]
        self.assertEqual(len(interruptions), 2)
        self.assertNotEqual(interruptions[0]["turn_id"], interruptions[1]["turn_id"])
        audio = [e for e in self.ws.events if e["type"] == "assistant_audio"]
        self.assertEqual(interruptions[1]["turn_id"], audio[0]["turn_id"])
        self.assertEqual(len([e for e in self.ws.events if e["type"] == "turn_complete"]), 1)

    async def test_microphone_keeps_streaming_during_active_tool(self):
        self.tools.active = True
        self.ws.inbound = [{"type": "websocket.receive", "bytes": b"\x00\x01" * 100}]
        session = SimpleNamespace(send_realtime_input=AsyncMock())
        await self.service._client_to_google_loop(
            self.ws, session, self.memory, self.tools, self.recorder,
            interruption=self.coordinator,
        )
        audio = session.send_realtime_input.await_args.kwargs["audio"]
        self.assertEqual(audio.data, b"\x00\x01" * 100)
        self.assertEqual(audio.mime_type, "audio/pcm;rate=16000")

    async def test_input_asr_before_native_marker_keeps_old_playback_turn_addressable(self):
        await self.replay([
            google_response(input_transcription=SimpleNamespace(text="Hold on", finished=False)),
            google_response(input_transcription=SimpleNamespace(text="tell me about cats", finished=True)),
            google_response(interrupted=True, turn_complete=True),
            SimpleNamespace(data=b"new", text="Cats", server_content=None),
            google_response(turn_complete=True),
        ])
        stopped = next(e for e in self.ws.events if e["type"] == "interrupted")
        self.assertEqual(stopped["turn_id"], self.old_turn)
        user_events = [e for e in self.ws.events if e["type"] == "user_transcript"]
        self.assertTrue(user_events)
        self.assertTrue(all(e["turn_id"] != self.old_turn for e in user_events))
        self.assertEqual(self.memory.user_texts, ["Hold on tell me about cats"])
        self.assertEqual(self.memory.assistant_texts, ["Cats"])

    async def test_asr_before_normal_terminal_waits_for_previous_turn_to_complete(self):
        await self.replay([
            google_response(input_transcription=SimpleNamespace(text="Next question", finished=True)),
            google_response(turn_complete=True),
            SimpleNamespace(data=b"new", text="Next answer", server_content=None),
            google_response(turn_complete=True),
        ])
        complete = [e for e in self.ws.events if e["type"] == "turn_complete"]
        self.assertEqual(len(complete), 2)
        self.assertEqual(complete[0]["turn_id"], self.old_turn)
        self.assertNotEqual(complete[1]["turn_id"], self.old_turn)
        self.assertEqual(self.memory.user_texts, ["Next question"])

    async def test_finished_asr_is_published_after_interruption_even_without_a_reply(self):
        await self.replay([
            google_response(input_transcription=SimpleNamespace(text="Stop talking", finished=True)),
            google_response(interrupted=True),
            google_response(turn_complete=True),
        ])
        user_events = [e for e in self.ws.events if e["type"] == "user_transcript"]
        self.assertEqual([e["text"] for e in user_events], ["Stop talking"])
        self.assertNotEqual(user_events[0]["turn_id"], self.old_turn)
        self.assertEqual(self.memory.user_texts, ["Stop talking"])
        self.assertFalse(any(e["type"] == "turn_complete" for e in self.ws.events))

    async def test_native_cancellation_cancels_active_tool_without_transcript(self):
        self.tools.active = True
        await self.replay([google_response(interrupted=True, turn_complete=True)])
        self.assertEqual(self.tools.cancel_count, 1)
        self.assertIsNone(self.coordinator.pending)
