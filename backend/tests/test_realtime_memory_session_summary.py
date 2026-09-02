from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.realtime_memory_session import RealtimeMemorySession


class _FakeEverMemService:
    """Minimal stand-in for EverMemService (no network)."""

    def __init__(self, search_results: list[dict] | None = None) -> None:
        self.added: list[dict] = []
        self.flush_calls: list[dict] = []
        self.search_results = list(search_results or [])
        self.flush_error: Exception | None = None

    async def add_memory(self, **kwargs):
        self.added.append(kwargs)
        return {"status": "success"}

    async def flush_pending_memories(self, **kwargs):
        if self.flush_error is not None:
            raise self.flush_error
        self.flush_calls.append(kwargs)
        return {"status": "success"}

    async def search_memories(self, **kwargs):
        return list(self.search_results)

    def should_skip_memory(self, user_msg: str) -> bool:
        return len(user_msg.strip()) <= 2


class RealtimeMemorySessionTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._cache_path = Path(self._tmp.name) / "pending.json"
        RealtimeMemorySession._PENDING_MEMORY_CACHE = {}
        patcher = patch.object(RealtimeMemorySession, "_PENDING_CACHE_PATH", self._cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, RealtimeMemorySession, "_PENDING_MEMORY_CACHE", {})
        self.addCleanup(setattr, RealtimeMemorySession, "_STARTUP_INJECTION_ENABLED", False)

    def _make_session(self, service: _FakeEverMemService | None) -> RealtimeMemorySession:
        session = RealtimeMemorySession()
        session._config.enabled = service is not None
        session._config.key = "test-key" if service is not None else None
        session._config.memory_scope = "test_scope"
        session._config._service = service
        return session


class SessionSummaryTests(RealtimeMemorySessionTestBase):
    async def test_finalize_session_writes_summary_with_topics_and_entries(self) -> None:
        service = _FakeEverMemService()
        session = self._make_session(service)
        session.note_user_transcript("我最近在做的项目是语音助手，下周要提交上线版本")
        session.note_assistant_text("好的，我记住了，你的项目是语音助手。")
        await session.flush_turn()
        session.note_user_transcript("帮我安排一下明天的待办事项")
        session.note_assistant_text("明天先完成测试，再准备发布。")
        await session.flush_turn()

        result = await session.finalize_session()

        self.assertTrue(result["saved"])
        summary = result["summary"]
        self.assertIn("会话摘要", summary)
        self.assertIn("共 2 轮", summary)
        self.assertIn("用户谈到", summary)
        self.assertIn("语音助手", summary)
        # Written to cloud with flush=True under the session scope.
        self.assertEqual(len(service.added) >= 1, True)
        cloud_summary = service.added[-1]
        self.assertEqual(cloud_summary["content"], summary)
        self.assertEqual(cloud_summary["user_id"], "test_scope")
        self.assertTrue(cloud_summary["flush"])
        # Also queued into the local pending cache for offline retrieval.
        pending = RealtimeMemorySession._PENDING_MEMORY_CACHE.get("test_scope", [])
        self.assertTrue(any(item["content"] == summary for item in pending))

    async def test_finalize_session_skips_when_disabled_or_empty(self) -> None:
        disabled = self._make_session(None)
        disabled.note_user_transcript("你好，我们聊聊项目安排")
        await disabled.flush_turn()
        self.assertEqual((await disabled.finalize_session())["reason"], "disabled")

        service = _FakeEverMemService()
        empty = self._make_session(service)
        self.assertEqual((await empty.finalize_session())["reason"], "empty_session")
        self.assertEqual(service.added, [])

    async def test_finalize_session_is_idempotent(self) -> None:
        service = _FakeEverMemService()
        session = self._make_session(service)
        session.note_user_transcript("我们讨论一下项目计划安排")
        await session.flush_turn()
        first = await session.finalize_session()
        second = await session.finalize_session()
        self.assertTrue(first["saved"])
        self.assertEqual(second["reason"], "already_finalized")
        summary_writes = [item for item in service.added if item.get("flush")]
        self.assertEqual(len(summary_writes), 1)

    async def test_drain_triggers_finalize(self) -> None:
        service = _FakeEverMemService()
        session = self._make_session(service)
        session.note_user_transcript("我们继续讨论语音助手项目的上线计划")
        session.note_assistant_text("好的，继续。")
        await session.flush_turn()
        await session.drain()
        self.assertTrue(any(item.get("flush") for item in service.added))

    async def test_discarded_turn_is_not_recorded(self) -> None:
        service = _FakeEverMemService()
        session = self._make_session(service)
        session.note_user_transcript("这句话被打断了不应该记录")
        session.discard_turn()
        await session.flush_turn()
        self.assertEqual(session._session_user_excerpts, [])


class StartupContextTests(RealtimeMemorySessionTestBase):
    async def test_startup_injection_disabled_by_default(self) -> None:
        """By default, kickoff does not launch a background cloud search."""
        service = _FakeEverMemService(
            search_results=[{"content": "[历史对话] 会话摘要: 上次讨论了语音助手上线计划", "score": 0.9}]
        )
        session = self._make_session(service)
        session.kickoff_startup_context()
        # No startup task is created when injection is disabled.
        self.assertIsNone(session._startup_task)
        # A trivial greeting yields no context — the session starts clean.
        session.note_user_transcript("你好")
        retrieval = await session.retrieve_memory_context()
        self.assertEqual(retrieval["context"], "")
        self.assertFalse(retrieval["attempted"])

    async def test_startup_context_injected_when_enabled_on_first_turn(self) -> None:
        service = _FakeEverMemService(
            search_results=[{"content": "[历史对话] 会话摘要: 上次讨论了语音助手上线计划", "score": 0.9}]
        )
        session = self._make_session(service)
        session._STARTUP_INJECTION_ENABLED = True
        session.kickoff_startup_context()
        self.assertIsNotNone(session._startup_task)
        await session._startup_task  # type: ignore[misc]

        # A trivial greeting would normally skip retrieval entirely.
        session.note_user_transcript("你好")
        retrieval = await session.retrieve_memory_context()

        self.assertTrue(retrieval["attempted"])
        self.assertIn("【上次对话以来的记忆】", retrieval["context"])
        self.assertIn("语音助手上线计划", retrieval["context"])
        self.assertEqual(retrieval["memories_retrieved"], 1)

        # One-shot: the second turn does not repeat the startup block.
        session.note_user_transcript("嗯")
        followup = await session.retrieve_memory_context()
        self.assertNotIn("【上次对话以来的记忆】", str(followup.get("context", "")))

    async def test_startup_context_combines_with_turn_retrieval_when_enabled(self) -> None:
        service = _FakeEverMemService(
            search_results=[{"content": "[历史对话] 会话摘要: 上次讨论了项目计划", "score": 0.9}]
        )
        session = self._make_session(service)
        session._STARTUP_INJECTION_ENABLED = True
        session.kickoff_startup_context()
        await session._startup_task  # type: ignore[misc]

        session.note_user_transcript("你还记得我们之前讨论的项目计划吗？")
        retrieval = await session.retrieve_memory_context()

        self.assertIn("【上次对话以来的记忆】", retrieval["context"])
        # Per-turn cloud hits are appended below the startup block.
        self.assertGreaterEqual(retrieval["memories_retrieved"], 1)

    async def test_kickoff_without_service_is_noop(self) -> None:
        session = self._make_session(None)
        session._STARTUP_INJECTION_ENABLED = True
        session.kickoff_startup_context()
        self.assertIsNone(session._startup_task)
        session.note_user_transcript("你好")
        retrieval = await session.retrieve_memory_context()
        self.assertEqual(retrieval["context"], "")

    async def test_disable_via_configure_clears_session_state(self) -> None:
        service = _FakeEverMemService()
        session = self._make_session(service)
        session.note_user_transcript("我们讨论一下项目计划安排")
        await session.flush_turn()
        session.configure({"enabled": False})
        self.assertEqual(session._session_user_excerpts, [])
        self.assertEqual((await session.finalize_session())["reason"], "disabled")


if __name__ == "__main__":
    unittest.main()
