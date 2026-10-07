"""Recalled memory must reach the reply it was recalled for, without stalling turns."""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, patch

from services.evermem_service import EverMemService
from services.realtime_memory_injector import RealtimeMemoryInjector
from services.realtime_memory_session import RealtimeMemorySession
from services.realtime_voice_service import RealtimeVoiceService
from services.interruption_classifier import InterruptionDecisionCoordinator

RECALL_QUERY = "你还记得我之前默认用什么声音吗？"


def _configured_session() -> RealtimeMemorySession:
    session = RealtimeMemorySession()
    session.configure({
        "enabled": True,
        "api_url": "https://memory.example.com",
        "api_key": "memory-key",
        "scope_id": "voice-demo",
    })
    return session


async def _settle(rounds: int = 20) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


class _IsolatedCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self._saved_path = RealtimeMemorySession._PENDING_CACHE_PATH
        RealtimeMemorySession._PENDING_CACHE_PATH = Path(self.temp_dir.name) / "pending.json"
        RealtimeMemorySession._PENDING_MEMORY_CACHE.clear()

    def tearDown(self) -> None:
        RealtimeMemorySession._PENDING_CACHE_PATH = self._saved_path
        RealtimeMemorySession._PENDING_MEMORY_CACHE.clear()
        self.temp_dir.cleanup()


class PrefetchTests(_IsolatedCache):
    async def test_final_turn_reuses_the_prefetch_started_from_interim_asr(self) -> None:
        session = _configured_session()
        search = AsyncMock(return_value=[{"content": "[语音偏好] 默认使用中文女声播报", "score": 0.9}])
        with patch.object(EverMemService, "search_memories", new=search):
            task = session.prefetch_partial("你还记得我之前默认用", "item-1")
            self.assertIsNotNone(task)
            # Later interim frames of the same utterance do not search again.
            self.assertIsNone(session.prefetch_partial("你还记得我之前默认用什么", "item-1"))
            session.note_user_transcript(RECALL_QUERY)
            result = await session.retrieve_memory_context("item-1", query=RECALL_QUERY)

        self.assertEqual(search.await_count, 1)
        self.assertTrue(result["prefetched"])
        self.assertIn("默认使用中文女声播报", result["context"])

    async def test_prefetch_from_another_utterance_is_not_reused(self) -> None:
        session = _configured_session()
        search = AsyncMock(return_value=[{"content": "[任务] 当前重点是比赛提交", "score": 0.9}])
        with patch.object(EverMemService, "search_memories", new=search):
            session.prefetch_partial("你还记得之前的任务吗", "item-1")
            session.note_user_transcript(RECALL_QUERY)
            result = await session.retrieve_memory_context("item-2", query=RECALL_QUERY)
            await _settle()

        self.assertEqual(search.await_count, 2)
        self.assertNotIn("prefetched", result)

    async def test_empty_partial_result_is_searched_again_with_the_full_sentence(self) -> None:
        session = _configured_session()
        search = AsyncMock(side_effect=[[], [{"content": "[语音偏好] 默认使用中文女声播报", "score": 0.9}]])
        with patch.object(EverMemService, "search_memories", new=search):
            session.prefetch_partial("你还记得我之前", "item-1")
            session.note_user_transcript(RECALL_QUERY)
            result = await session.retrieve_memory_context("item-1", query=RECALL_QUERY)

        self.assertEqual(search.await_count, 2)
        self.assertEqual(result["memories_retrieved"], 1)

    async def test_trivial_interim_text_does_not_search(self) -> None:
        session = _configured_session()
        with patch.object(EverMemService, "search_memories", new=AsyncMock(return_value=[])) as search:
            self.assertIsNone(session.prefetch_partial("嗯好的", "item-1"))
        search.assert_not_awaited()

    async def test_lookup_after_flush_still_uses_the_utterance(self) -> None:
        # flush_turn() clears the current text when the reply finishes, which
        # can happen before a background lookup gets to run.
        session = _configured_session()
        session.note_user_transcript(RECALL_QUERY)
        await session.flush_turn()
        search = AsyncMock(return_value=[{"content": "[语音偏好] 默认使用中文女声播报", "score": 0.9}])
        with patch.object(EverMemService, "search_memories", new=search):
            result = await session.retrieve_memory_context(query=RECALL_QUERY)
        self.assertEqual(result["memories_retrieved"], 1)


class WarmUpTests(_IsolatedCache):
    async def test_configuring_memory_opens_the_everos_connection_early(self) -> None:
        warm_up = AsyncMock(return_value=None)
        with patch.object(EverMemService, "warm_up", new=warm_up):
            session = _configured_session()
            await _settle()
            await session.drain()
        warm_up.assert_awaited_once()


class BackgroundPersistTests(_IsolatedCache):
    async def test_flush_turn_does_not_wait_for_the_cloud_write(self) -> None:
        session = _configured_session()
        session.note_user_transcript("以后默认都用中文女声来播报。")
        release = asyncio.Event()

        async def slow_add(*_args: Any, **_kwargs: Any) -> dict:
            await release.wait()
            return {"status": "success"}

        with patch.object(EverMemService, "add_memory", new=slow_add), patch.object(
            EverMemService, "flush_pending_memories", new=AsyncMock(return_value=None)
        ):
            immediate = await asyncio.wait_for(session.flush_turn(), timeout=1)
            self.assertEqual(immediate["reason"], "saving")
            self.assertEqual(immediate["attempted_count"], 1)
            # Retrievable locally before the cloud answers.
            self.assertEqual(immediate["local_pending_count"], 1)
            task = session.take_persist_task()
            self.assertIsNotNone(task)
            self.assertIsNone(session.take_persist_task())
            release.set()
            outcome = await task
        self.assertEqual(outcome["saved_count"], 1)

    async def test_memory_write_follow_up_reports_the_cloud_outcome(self) -> None:
        service = RealtimeVoiceService.__new__(RealtimeVoiceService)
        sent: list[dict[str, Any]] = []

        class _Socket:
            async def send_json(self, data: dict[str, Any]) -> None:
                sent.append(data)

        session = _configured_session()
        session.note_user_transcript("以后默认都用中文女声来播报。")
        with patch.object(EverMemService, "add_memory", new=AsyncMock(return_value={"status": "success"})), patch.object(
            EverMemService, "flush_pending_memories", new=AsyncMock(return_value=None)
        ):
            result = await session.flush_turn()
            await service._send_memory_write(_Socket(), session, result)
            await _settle()

        writes = [event for event in sent if event["type"] == "memory_write"]
        self.assertEqual([event["reason"] for event in writes], ["saving", ""])
        self.assertNotIn("followup", writes[0])
        self.assertTrue(writes[1]["followup"])
        self.assertEqual(writes[1]["saved_count"], 1)


class _InjectorHarness:
    def __init__(self, memory: RealtimeMemorySession) -> None:
        self.pushed: list[str] = []
        self.events: list[tuple[str, dict[str, Any]]] = []

        async def push(instructions: str) -> None:
            self.pushed.append(instructions)

        async def send(event_type: str, payload: dict[str, Any]) -> None:
            self.events.append((event_type, payload))

        self.injector = RealtimeMemoryInjector(
            memory,
            build_instructions=lambda context: f"BASE|{context}" if context else "BASE",
            build_recall_miss=lambda query: f"MISS|{query}",
            push_instructions=push,
            send_event=send,
        )


class InjectorTests(_IsolatedCache):
    async def test_memory_found_during_speech_is_pushed_before_the_reply_and_then_cleared(self) -> None:
        memory = _configured_session()
        harness = _InjectorHarness(memory)
        search = AsyncMock(return_value=[{"content": "[语音偏好] 默认使用中文女声播报", "score": 0.9}])
        with patch.object(EverMemService, "search_memories", new=search):
            harness.injector.on_partial("你还记得我之前默认用", "item-1")
            await _settle()
            # Pushed while the user is still speaking: the reply will see it.
            self.assertEqual(len(harness.pushed), 1)
            self.assertIn("默认使用中文女声播报", harness.pushed[0])
            memory.note_user_transcript(RECALL_QUERY)
            harness.injector.on_final(RECALL_QUERY, "item-1")
            await _settle()
            harness.injector.note_response_started()
            await harness.injector.on_turn_complete()

        self.assertEqual(search.await_count, 1)
        # No duplicate push for the reused result; base restored after the reply.
        self.assertEqual(harness.pushed[1:], ["BASE"])
        contexts = [payload for kind, payload in harness.events if kind == "memory_context"]
        # Announced once, after the final transcript: an announcement during
        # speech would be attributed to whichever turn the client has open.
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["memories_retrieved"], 1)

    async def test_memory_that_misses_the_reply_is_kept_for_the_next_reply(self) -> None:
        memory = _configured_session()
        harness = _InjectorHarness(memory)
        search = AsyncMock(return_value=[{"content": "[语音偏好] 默认使用中文女声播报", "score": 0.9}])
        with patch.object(EverMemService, "search_memories", new=search):
            harness.injector.note_response_started()  # server VAD already replying
            memory.note_user_transcript(RECALL_QUERY)
            harness.injector.on_final(RECALL_QUERY, "item-1")
            await _settle()
        self.assertIn("默认使用中文女声播报", harness.pushed[-1])

        await harness.injector.on_turn_complete()
        self.assertEqual(len(harness.pushed), 1, "late memory must survive the turn it missed")

        harness.injector.note_response_started()
        await harness.injector.on_turn_complete()
        self.assertEqual(harness.pushed[-1], "BASE")

    async def test_recall_with_no_match_pushes_the_recall_miss_prompt(self) -> None:
        memory = _configured_session()
        harness = _InjectorHarness(memory)
        with patch.object(EverMemService, "search_memories", new=AsyncMock(return_value=[])):
            memory.note_user_transcript(RECALL_QUERY)
            harness.injector.on_final(RECALL_QUERY, "item-1")
            await _settle()
        self.assertEqual(harness.pushed, [f"MISS|{RECALL_QUERY}"])

    async def test_late_recall_miss_prompt_is_not_carried_into_an_unrelated_reply(self) -> None:
        memory = _configured_session()
        harness = _InjectorHarness(memory)
        with patch.object(EverMemService, "search_memories", new=AsyncMock(return_value=[])):
            harness.injector.note_response_started()
            memory.note_user_transcript(RECALL_QUERY)
            harness.injector.on_final(RECALL_QUERY, "item-1")
            await _settle()
        self.assertEqual(harness.pushed, [f"MISS|{RECALL_QUERY}"])
        await harness.injector.on_turn_complete()
        self.assertEqual(harness.pushed[-1], "BASE")

    async def test_drain_cancels_speculative_searches_instead_of_waiting(self) -> None:
        memory = _configured_session()
        never = asyncio.Event()

        async def hanging_search(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            await never.wait()
            return []

        with patch.object(EverMemService, "search_memories", new=hanging_search):
            task = memory.prefetch_partial("你还记得我之前默认用", "item-1")
            await _settle()
            await asyncio.wait_for(memory.drain(), timeout=1)
        self.assertTrue(task.cancelled())

    async def test_turns_apply_in_order_even_when_an_earlier_lookup_is_slow(self) -> None:
        memory = _configured_session()
        harness = _InjectorHarness(memory)
        release = asyncio.Event()
        calls = 0

        async def search(*_args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            nonlocal calls
            calls += 1
            if calls == 1:
                await release.wait()
                return [{"content": "[任务] 第一轮的记忆", "score": 0.9}]
            return [{"content": "[任务] 第二轮的记忆", "score": 0.9}]

        with patch.object(EverMemService, "search_memories", new=search):
            harness.injector.on_final("你还记得第一个任务吗？", "item-1")
            await _settle()
            harness.injector.on_final("你还记得第二个任务吗？", "item-2")
            await _settle()
            self.assertEqual(harness.pushed, [])
            release.set()
            await _settle(40)
        self.assertEqual(len(harness.pushed), 2)
        self.assertIn("第一轮", harness.pushed[0])
        self.assertIn("第二轮", harness.pushed[1])


class DoubaoInjectionTests(_IsolatedCache):
    async def test_doubao_injects_recalled_memory_as_a_system_item(self) -> None:
        # The dispatcher used to reference an undefined ``doubao_ws``, so every
        # successful recall raised NameError and was logged as a failure.
        service = RealtimeVoiceService.__new__(RealtimeVoiceService)
        sent_client: list[dict[str, Any]] = []
        sent_upstream: list[dict[str, Any]] = []

        class _Socket:
            async def send_json(self, data: dict[str, Any]) -> None:
                sent_client.append(data)

        class _Upstream:
            async def send(self, raw: str) -> None:
                sent_upstream.append(json.loads(raw))

        memory = _configured_session()
        state: dict[str, Any] = {
            "active_turn_id": None, "active_response_id": None, "turn_finalized": False,
            "ai_acc": "", "user_acc": "", "suppressed_response_id": None,
            "tts_active": False, "user_final_sent": False, "websearch_notified": False,
        }
        search = AsyncMock(return_value=[{"content": "[语音偏好] 默认使用中文女声播报", "score": 0.9}])
        with patch.object(EverMemService, "search_memories", new=search):
            await service._doubao_duplex_dispatch(
                _Socket(),
                {"type": "conversation.item.input_audio_transcription.delta", "delta": "你还记得我之前默认用"},
                state, memory, None, InterruptionDecisionCoordinator(), doubao_ws=_Upstream(),
            )
            await _settle()
            await service._doubao_duplex_dispatch(
                _Socket(),
                {"type": "conversation.item.input_audio_transcription.completed", "transcript": RECALL_QUERY},
                state, memory, None, InterruptionDecisionCoordinator(), doubao_ws=_Upstream(),
            )
            await _settle()

        items = [event for event in sent_upstream if event["type"] == "conversation.item.create"]
        self.assertEqual(len(items), 1, "same memory must be injected once per utterance")
        self.assertIn("默认使用中文女声播报", items[0]["items"][0]["content"][0]["text"])
        transcript_index = next(
            i for i, event in enumerate(sent_client)
            if event["type"] == "user_transcript" and not event.get("interim")
        )
        self.assertEqual(sent_client[transcript_index]["text"], RECALL_QUERY)


if __name__ == "__main__":
    unittest.main()


class IdentityMemoryTests(_IsolatedCache):
    """Screenshot bug, 2026-10-07: "my name is Xiao Bao" was never stored and
    "do you know my name?" never recalled; the recall_memory tool always failed."""

    def test_name_statements_become_identity_entries(self) -> None:
        session = _configured_session()
        cases = {
            "I want you to remember my name is Xiao Bao. Could you do that?": "Xiao Bao",
            "Please call me Ada.": "Ada",
            "my name's Li Wei and I live in Beijing": "Li Wei",
            "记住，我叫小宝。": "小宝",
            "我的名字是王小明": "王小明",
            "以后叫我阿杰吧": "阿杰",
        }
        for text, name in cases.items():
            with self.subTest(text=text):
                entries = session._extract_memory_entries(text)
                self.assertTrue(entries and entries[0].startswith("用户身份: 用户的名字是 " + name + "（"), entries)

    def test_questions_and_non_names_are_not_stored_as_identity(self) -> None:
        session = _configured_session()
        for text in ("my name is not important", "我叫什么名字？", "我叫你小助手", "What's the name of that song?"):
            with self.subTest(text=text):
                self.assertFalse(any(e.startswith("用户身份") for e in session._extract_memory_entries(text)))

    def test_asking_for_their_name_is_an_explicit_recall(self) -> None:
        session = _configured_session()
        for text in ("Hello, do you know my name?", "Who am I?", "你还知道我叫什么吗"):
            with self.subTest(text=text):
                self.assertTrue(session.should_retrieve_context(text, quiet=True))
                self.assertTrue(session.is_forced_recall_query(text))

    async def test_local_identity_entry_answers_a_name_question_and_never_expires(self) -> None:
        session = _configured_session()
        scope = session._scope_pending_cache_key()
        session._queue_pending_entries(scope, ["用户身份: 用户的名字是 Old（the user's name is Old）"])
        session._queue_pending_entries(scope, ["用户身份: 用户的名字是 Xiao Bao（the user's name is Xiao Bao）"])
        # Age everything past the TTL and overflow the cap with newer entries.
        for item in RealtimeMemorySession._PENDING_MEMORY_CACHE[scope]:
            item["created_at"] = 0.0
        session._queue_pending_entries(scope, [f"用户偏好: 偏好 {i} 号方案的详细说明" for i in range(40)])

        hits = session._search_pending_entries(scope, "what is my name")
        self.assertIn("Xiao Bao", hits[0]["content"])
        identities = [
            item for item in RealtimeMemorySession._PENDING_MEMORY_CACHE[scope]
            if item["content"].startswith("用户身份")
        ]
        self.assertEqual(len(identities), 1, "a newly stated name replaces the old one")

    async def test_identity_question_adds_a_statement_form_cloud_query(self) -> None:
        session = _configured_session()
        queries: list[str] = []

        async def search(*_args: Any, query: str, **_kwargs: Any) -> list[dict[str, Any]]:
            queries.append(query)
            if query == RealtimeMemorySession._IDENTITY_EXPANSION_QUERY:
                return [{"content": "[历史对话] 用户表示希望系统记住自己的名字是 Xiao Bao", "score": 0.6}]
            return [{"content": "[历史对话] 用户询问助手是否知道自己的名字", "score": 0.4}]

        with patch.object(EverMemService, "search_memories", new=search):
            session.note_user_transcript("Hello, do you know my name?")
            result = await session.retrieve_memory_context(query="Hello, do you know my name?")

        self.assertIn(RealtimeMemorySession._IDENTITY_EXPANSION_QUERY, queries)
        first_line = result["context"].splitlines()[0]
        self.assertIn("Xiao Bao", first_line)
        self.assertIn("云端", first_line)

    async def test_recall_memory_tool_returns_memories_without_restaging_them(self) -> None:
        from services.voice_agent_tools import VoiceAgentToolSession

        session = _configured_session()
        tools = VoiceAgentToolSession(default_provider="Google", memory_session=session).service
        events: list[str] = []

        async def send(event_type: str, _payload: dict[str, Any]) -> None:
            events.append(event_type)

        search = AsyncMock(return_value=[{"content": "[历史对话] 用户的名字是 Xiao Bao", "score": 0.6}])
        with patch.object(EverMemService, "search_memories", new=search):
            result = await tools.run_recall_memory("name", send_event=send)

        self.assertIn("Xiao Bao", result["answer"])
        self.assertEqual(events[:2], ["tool_call_started", "tool_call_completed"])
        # The model already has these; injecting them again next turn would duplicate.
        self.assertEqual(session._pending_recall_context, "")
