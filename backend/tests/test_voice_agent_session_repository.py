from __future__ import annotations

import asyncio
import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from services import realtime_session_recorder as recorder_module
from services.realtime_voice_service import RealtimeVoiceService, VoiceAgentSessionRecorder
from services.voice_agent_session_repository import VoiceAgentSessionRepository


class VoiceAgentSessionRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "voice_spirit_test.db"
        self.repository = VoiceAgentSessionRepository(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_persists_session_turn_and_tool_event(self) -> None:
        session = self.repository.create_session(
            provider="DashScope",
            model="qwen-realtime",
            voice="Cherry",
            meta={"transport": "websocket"},
        )

        self.repository.upsert_turn(
            session["id"],
            "voice-tool-1",
            user_text="帮我搜索语音 Agent",
        )
        self.repository.add_tool_event(
            session["id"],
            "agent_result",
            {
                "tool_name": "search_web",
                "turn_id": "voice-tool-1",
                "query": "语音 Agent",
                "answer": "已整理结果",
                "sources": [{"title": "Source", "uri": "https://example.com"}],
            },
        )
        self.repository.upsert_turn(
            session["id"],
            "voice-tool-1",
            assistant_text="这是基于来源的回答。",
            memory_payload={"saved_count": 1},
            completed=True,
        )
        self.repository.finish_session(session["id"])

        stored = self.repository.get_session(session["id"])
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "closed")

        turns = self.repository.list_turns(session["id"])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["turn_id"], "voice-tool-1")
        self.assertEqual(turns[0]["user_text"], "帮我搜索语音 Agent")
        self.assertEqual(turns[0]["assistant_text"], "这是基于来源的回答。")
        self.assertTrue(turns[0]["completed"])
        self.assertEqual(turns[0]["memory_payload"]["saved_count"], 1)

        events = self.repository.list_tool_events(session["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "agent_result")
        self.assertEqual(events[0]["tool_name"], "search_web")
        self.assertEqual(events[0]["payload"]["sources"][0]["title"], "Source")

        timeline = self.repository.build_timeline(session["id"])
        self.assertEqual(
            [event["event_type"] for event in timeline],
            [
                "session_open",
                "user_transcript",
                "agent_result",
                "assistant_response",
                "memory_commit",
                "turn_completed",
                "session_closed",
            ],
        )
        self.assertEqual(timeline[1]["text"], "帮我搜索语音 Agent")
        self.assertEqual(timeline[2]["source"], "tool_event")
        self.assertEqual(timeline[2]["payload"]["answer"], "已整理结果")
        self.assertEqual(timeline[3]["text"], "这是基于来源的回答。")
        self.assertEqual(timeline[4]["payload"]["saved_count"], 1)

    async def test_recorder_links_tool_events_to_current_transcript_turn(self) -> None:
        session = self.repository.create_session(
            provider="Google",
            model="gemini-live",
            voice="Puck",
        )
        recorder = VoiceAgentSessionRecorder(self.repository, session["id"])

        await recorder.note_user_transcript("帮我搜索 AI voice agent")
        await recorder.record_tool_event(
            "tool_call_started",
            {
                "tool_name": "search_web",
                "turn_id": "voice-tool-1",
                "query": "AI voice agent",
            },
        )
        await recorder.record_tool_event(
            "agent_result",
            {
                "tool_name": "search_web",
                "turn_id": "voice-tool-1",
                "query": "AI voice agent",
                "answer": "我查到这些信息。",
                "sources": [],
            },
        )
        await recorder.note_assistant_text("我查到这些信息。")
        await recorder.complete_turn({"attempted_count": 1, "saved_count": 0})

        turns = self.repository.list_turns(session["id"])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["turn_id"], "voice-tool-1")
        self.assertEqual(turns[0]["user_text"], "帮我搜索 AI voice agent")
        self.assertEqual(turns[0]["assistant_text"], "我查到这些信息。")
        self.assertTrue(turns[0]["completed"])
        self.assertEqual(turns[0]["memory_payload"]["attempted_count"], 1)

        events = self.repository.list_tool_events(session["id"])
        self.assertEqual([event["event_type"] for event in events], ["tool_call_started", "agent_result"])
        self.assertEqual(events[1]["payload"]["answer"], "我查到这些信息。")

    async def test_realtime_service_creates_session_recorder(self) -> None:
        service = RealtimeVoiceService(voice_session_repository=self.repository)

        recorder = await service._create_voice_session_recorder(
            provider="DashScope",
            model="qwen-realtime",
            voice="Cherry",
        )

        self.assertIsNotNone(recorder)
        assert recorder is not None
        stored = self.repository.get_session(recorder.session_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["provider"], "DashScope")
        self.assertEqual(stored["model"], "qwen-realtime")
        self.assertEqual(stored["voice"], "Cherry")
        self.assertEqual(stored["meta"]["transport"], "websocket")

    def test_migration_backfills_completed_legacy_turn_status(self) -> None:
        legacy_path = Path(self.tmpdir.name) / "legacy_voice.db"
        conn = sqlite3.connect(legacy_path)
        try:
            conn.execute(
                """
                CREATE TABLE voice_agent_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    user_text TEXT,
                    assistant_text TEXT,
                    memory_json TEXT NOT NULL DEFAULT '{}',
                    completed INTEGER NOT NULL DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    UNIQUE(session_id, turn_id)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO voice_agent_turns (
                    session_id, turn_id, user_text, assistant_text, completed, completed_at
                ) VALUES ('legacy-session', 'legacy-turn', '问题', '回答', 1, CURRENT_TIMESTAMP)
                """
            )
            conn.commit()
        finally:
            conn.close()

        migrated = VoiceAgentSessionRepository(db_path=legacy_path)
        turns = migrated.list_turns("legacy-session")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["completion_status"], "completed")
        self.assertFalse(turns[0]["interrupted"])

    def test_aggregates_cross_session_metrics_and_excludes_superseded_timeout(self) -> None:
        session = self.repository.create_session(
            provider="OpenAI",
            model="gpt-realtime",
            voice="alloy",
        )
        self.repository.upsert_turn(
            session["id"],
            "voice-turn-1",
            user_text="解释一下",
            assistant_text="回答",
            completed=True,
            interrupted=True,
            completion_status="interrupted",
        )
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE voice_agent_turns
                SET started_at = '2026-07-12 10:00:00', completed_at = '2026-07-12 10:00:02'
                WHERE session_id = ? AND turn_id = 'voice-turn-1'
                """,
                (session["id"],),
            )
            conn.commit()
        finally:
            conn.close()
        self.repository.add_session_event(
            session["id"],
            "assistant_audio_started",
            source="metric",
            turn_id="voice-turn-1",
            payload={"first_audio_ms": 120, "elapsed_ms": 120},
        )
        self.repository.add_session_event(
            session["id"],
            "interruption_decision",
            source="interruption",
            turn_id="voice-turn-1",
            payload={
                "candidate_id": "interruption-1",
                "classification": "NOISE_OR_SILENCE",
                "decision_latency_ms": 2500,
                "timeout_resolution": True,
            },
        )
        self.repository.add_session_event(
            session["id"],
            "interruption_decision",
            source="interruption",
            turn_id="voice-turn-1",
            payload={
                "candidate_id": "interruption-2",
                "supersedes_candidate_id": "interruption-1",
                "classification": "TRUE_BARGE_IN",
                "decision_latency_ms": 42,
            },
        )
        self.repository.add_session_event(
            session["id"],
            "interruption_client_stopped",
            source="metric",
            turn_id="voice-turn-1",
            payload={"candidate_id": "interruption-2", "stop_latency_ms": 55},
        )
        self.repository.add_session_event(
            session["id"],
            "interruption_client_stopped",
            source="metric",
            turn_id="voice-turn-1",
            payload={"candidate_id": "interruption-2", "stop_latency_ms": 999},
        )
        self.repository.add_session_event(
            session["id"],
            "interruption_client_stopped",
            source="metric",
            turn_id="voice-turn-1",
            payload={"candidate_id": "unknown-candidate", "stop_latency_ms": 888},
        )
        self.repository.add_session_event(
            session["id"],
            "user_transcript",
            source="turn",
            turn_id="voice-turn-1",
            text="解释一下",
        )
        self.repository.add_session_event(
            session["id"],
            "turn_interrupted",
            source="turn",
            turn_id="voice-turn-1",
            payload={"interrupted": True},
        )
        self.repository.add_session_event(
            session["id"],
            "turn_interrupted",
            source="turn",
            turn_id="voice-turn-1",
            payload={"interrupted": True, "duplicate": True},
        )
        conn = sqlite3.connect(self.db_path)
        try:
            event_ids = conn.execute(
                """
                SELECT id FROM voice_agent_session_events
                WHERE session_id = ? AND event_type IN ('user_transcript', 'turn_interrupted')
                ORDER BY id ASC
                """,
                (session["id"],),
            ).fetchall()
            conn.execute(
                "UPDATE voice_agent_session_events SET occurred_at = '2026-07-12T10:00:00.125Z' WHERE id = ?",
                (event_ids[0][0],),
            )
            conn.execute(
                "UPDATE voice_agent_session_events SET occurred_at = '2026-07-12T10:00:01.375Z' WHERE id = ?",
                (event_ids[1][0],),
            )
            conn.execute(
                "UPDATE voice_agent_session_events SET occurred_at = '2026-07-12T10:00:05.000Z' WHERE id = ?",
                (event_ids[2][0],),
            )
            conn.commit()
        finally:
            conn.close()

        summary = self.repository.summarize_metrics(limit=20)
        self.assertEqual(summary["session_count"], 1)
        self.assertEqual(summary["turn_count"], 1)
        self.assertEqual(summary["interrupted_turn_count"], 1)
        self.assertEqual(summary["decision_count"], 1)
        self.assertEqual(summary["classifications"]["TRUE_BARGE_IN"], 1)
        self.assertEqual(summary["classifications"]["NOISE_OR_SILENCE"], 0)
        self.assertEqual(summary["first_audio_ms"]["p50"], 120)
        self.assertEqual(summary["interruption_decision_ms"]["p95"], 42)
        self.assertEqual(summary["interruption_stop_ms"]["avg"], 55)
        self.assertEqual(summary["turn_completion_ms"]["p50"], 1250)
        self.assertEqual(summary["providers"][0]["provider"], "OpenAI")

        self.repository.create_session(provider="Google", model="gemini-live", voice="Puck")
        provider_summary = self.repository.summarize_metrics(limit=1, provider="openai")
        self.assertEqual(provider_summary["session_count"], 1)
        self.assertEqual(provider_summary["providers"][0]["provider"], "OpenAI")


class VoiceAgentSessionRecorderCoalescingTests(unittest.IsolatedAsyncioTestCase):
    """Covers the write-amplification fix: per-delta SQLite writes were
    coalesced into delayed flushes, redundant user_text rewrites removed,
    and audio frames no longer trigger turn writes."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "voice_spirit_test.db"
        self.repository = VoiceAgentSessionRepository(db_path=self.db_path)
        session = self.repository.create_session(
            provider="DashScope", model="qwen-realtime", voice="Cherry"
        )
        self.session_id = session["id"]

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _make_recorder(self) -> VoiceAgentSessionRecorder:
        return VoiceAgentSessionRecorder(self.repository, self.session_id)

    @staticmethod
    def _writes_with(spy, key: str) -> list:
        return [call for call in spy.call_args_list if call.kwargs.get(key)]

    async def test_assistant_deltas_coalesce_into_single_flush(self) -> None:
        recorder = self._make_recorder()
        with patch.object(
            self.repository, "upsert_turn", wraps=self.repository.upsert_turn
        ) as spy:
            await recorder.note_user_transcript("你好")
            for delta in ["这是", "一段", "流式", "回复。"]:
                await recorder.note_assistant_text(delta)
            await recorder.note_assistant_audio()
            await recorder.note_assistant_audio()
            # In-memory view is complete even before the delayed flush fires.
            self.assertEqual(recorder.current_assistant_text, "这是一段流式回复。")
            await recorder.complete_turn()

        # user_text persisted exactly once (no per-delta rewrites)...
        self.assertEqual(len(self._writes_with(spy, "user_text")), 1)
        # ...and all assistant deltas went down in one coalesced write.
        assistant_writes = self._writes_with(spy, "assistant_text")
        self.assertEqual(len(assistant_writes), 1)
        self.assertEqual(assistant_writes[0].kwargs["assistant_text"], "这是一段流式回复。")

        turns = self.repository.list_turns(self.session_id)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["assistant_text"], "这是一段流式回复。")
        self.assertTrue(turns[0]["completed"])

    async def test_delayed_flush_persists_mid_turn(self) -> None:
        recorder = self._make_recorder()
        await recorder.note_user_transcript("你好")
        with patch.object(recorder_module, "ASSISTANT_TEXT_FLUSH_SECONDS", 0.01):
            await recorder.note_assistant_text("先到的文本")
            await asyncio.sleep(0.05)
        turns = self.repository.list_turns(self.session_id)
        self.assertEqual(turns[0]["assistant_text"], "先到的文本")
        # More text after the mid-turn flush still lands, in order.
        await recorder.note_assistant_text("和后到的文本")
        await recorder.complete_turn()
        turns = self.repository.list_turns(self.session_id)
        self.assertEqual(turns[0]["assistant_text"], "先到的文本和后到的文本")

    async def test_barge_in_flushes_previous_turn_before_new_one(self) -> None:
        recorder = self._make_recorder()
        await recorder.note_user_transcript("第一句")
        await recorder.note_assistant_text("回答甲")
        # User barges in before the delayed flush fires.
        await recorder.note_user_transcript("第二句")
        await recorder.note_assistant_text("回答乙")
        await recorder.complete_turn()

        turns = self.repository.list_turns(self.session_id)
        self.assertEqual(len(turns), 2)
        first = next(turn for turn in turns if turn["user_text"] == "第一句")
        second = next(turn for turn in turns if turn["user_text"] == "第二句")
        self.assertEqual(first["assistant_text"], "回答甲")
        self.assertEqual(second["assistant_text"], "回答乙")

    async def test_interrupt_flushes_partial_assistant_text(self) -> None:
        recorder = self._make_recorder()
        await recorder.note_user_transcript("问题")
        await recorder.note_assistant_text("部分")
        await recorder.note_assistant_text("回答")
        await recorder.interrupt_current_turn()

        turns = self.repository.list_turns(self.session_id)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["assistant_text"], "部分回答")
        self.assertTrue(turns[0]["interrupted"])
        self.assertEqual(turns[0]["completion_status"], "interrupted")

    async def test_audio_frames_do_not_write_after_turn_open(self) -> None:
        recorder = self._make_recorder()
        await recorder.note_user_transcript("你好")
        with patch.object(
            self.repository, "upsert_turn", wraps=self.repository.upsert_turn
        ) as spy:
            for _ in range(5):
                await recorder.note_assistant_audio()
        self.assertEqual(spy.call_count, 0)


if __name__ == "__main__":
    unittest.main()
