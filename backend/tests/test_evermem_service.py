from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.evermem_service import EverMemService


def _make_client_mock(method_mock: AsyncMock) -> tuple[Mock, AsyncMock]:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    return client, method_mock


class EverMemServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_memory_uses_v2_endpoint_and_session_id(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 202
        post = AsyncMock(return_value=response)

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            result = await service.add_memory(
                content="remember this",
                user_id="scope-main",
                sender="scope-main_chat",
                sender_name="VoiceSpirit",
            )

        self.assertEqual(result, {"status": "success"})
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/api/v2/memory/add"))
        payload = kwargs["json"]
        # v2 does not send user_id in the add body — only session_id
        self.assertNotIn("user_id", payload)
        self.assertEqual(payload["session_id"], "scope-main_default")
        self.assertTrue(payload["async_mode"])
        message = payload["messages"][0]
        self.assertEqual(message["sender_id"], "scope-main")
        self.assertEqual(message["role"], "user")
        self.assertEqual(message["content"], "remember this")
        self.assertIsInstance(message["timestamp"], int)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")

    async def test_add_memory_maps_group_id_to_session_and_flushes_v2(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 202
        flush_response = Mock()
        flush_response.status_code = 200
        post = AsyncMock(side_effect=[response, flush_response])

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            await service.add_memory(
                content="remember this",
                user_id="scope-main",
                sender_name="Assistant",
                group_id="group-chat-001",
                flush=True,
            )

        self.assertEqual(post.call_count, 2)
        # First call: add
        add_args, add_kwargs = post.call_args_list[0]
        self.assertTrue(add_args[0].endswith("/api/v2/memory/add"))
        self.assertEqual(add_kwargs["json"]["session_id"], "group-chat-001")
        self.assertEqual(add_kwargs["json"]["messages"][0]["role"], "assistant")
        # Second call: flush — v2 uses session_id only, no user_id
        flush_args, flush_kwargs = post.call_args_list[1]
        self.assertTrue(flush_args[0].endswith("/api/v2/memory/flush"))
        self.assertEqual(
            flush_kwargs["json"],
            {"session_id": "group-chat-001"},
        )

    async def test_add_memory_returns_none_on_upstream_error(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 401
        response.text = "unauthorized"
        post = AsyncMock(return_value=response)

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            result = await service.add_memory(content="x", user_id="scope-main")

        self.assertIsNone(result)

    async def test_flush_pending_memories_posts_to_v2_flush_endpoint(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 200
        post = AsyncMock(return_value=response)

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            result = await service.flush_pending_memories(
                user_id="scope-main", session_id="group-chat-001"
            )

        self.assertEqual(result, {"status": "success"})
        self.assertEqual(post.await_count, 1)
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/api/v2/memory/flush"))
        # v2 flush body uses session_id only, not user_id
        self.assertEqual(
            kwargs["json"],
            {"session_id": "group-chat-001"},
        )

    async def test_flush_pending_memories_returns_none_on_error(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 500
        response.text = "internal error"
        post = AsyncMock(return_value=response)

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            result = await service.flush_pending_memories(
                user_id="scope-main", session_id="group-chat-001"
            )

        self.assertIsNone(result)

    async def test_flush_pending_memories_without_api_key_returns_none(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key=None)

        result = await service.flush_pending_memories(user_id="scope-main")

        self.assertIsNone(result)

    async def test_create_conversation_meta_generates_group_id(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        # v2 has no group-registration endpoint; create_conversation_meta is
        # a pure local id generator.
        result = await service.create_conversation_meta(user_id="scope-main")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["group_id"].startswith("conv_"))
        self.assertEqual(result["user_id"], "scope-main")

    async def test_create_conversation_meta_returns_provided_group_id(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        result = await service.create_conversation_meta(
            user_id="scope-main", group_id="group-chat-001"
        )

        self.assertEqual(result, {"group_id": "group-chat-001", "user_id": "scope-main"})

    async def test_search_memories_parses_v2_envelope(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "data": {
                "episodes": [
                    {"episode": "上次讨论了项目上线计划", "score": 0.9},
                    {"episode": "低分内容", "score": 0.1},
                ],
                "profiles": [
                    {"profile_data": {"preference": "黑咖啡", "trait": "早起"}},
                ],
                "unprocessed_messages": [
                    {"content": "本周重点是比赛提交"},
                ],
                "agent_cases": [],
                "agent_skills": [],
            }
        }
        post = AsyncMock(return_value=response)

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            result = await service.search_memories(
                query="本周重点工作是什么",
                user_id="scope-main",
                memory_types=["episodic_memory", "profile"],
            )

        contents = [item["content"] for item in result]
        self.assertTrue(any("项目上线计划" in c for c in contents))
        self.assertFalse(any("低分内容" in c for c in contents))
        self.assertTrue(any("用户画像" in c and "黑咖啡" in c for c in contents))
        self.assertTrue(any("待处理消息" in c for c in contents))

        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/api/v2/memory/search"))
        payload = kwargs["json"]
        # v2: user_id is top-level, not in filters
        self.assertEqual(payload["user_id"], "scope-main")
        self.assertNotIn("filters", payload)  # no group_id given
        self.assertEqual(payload["method"], "hybrid")
        # v2 does not accept memory_types on search
        self.assertNotIn("memory_types", payload)

    async def test_search_memories_maps_single_group_to_session_filter(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "data": {"episodes": [], "profiles": [], "unprocessed_messages": []}
        }
        post = AsyncMock(return_value=response)

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            await service.search_memories(
                query="继续昨天的任务",
                user_id="scope-main",
                group_ids=["group-chat-001"],
            )

        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/api/v2/memory/search"))
        # v2: user_id top-level, session_id in filters
        self.assertEqual(kwargs["json"]["user_id"], "scope-main")
        self.assertEqual(kwargs["json"]["filters"], {"session_id": "group-chat-001"})

    async def test_get_memories_uses_v2_get_endpoint(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "data": {"episodes": [{"episode": "讨论了语音助手项目"}], "total_count": 1}
        }
        post = AsyncMock(return_value=response)

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            result = await service.get_memories(user_id="scope-main")

        self.assertEqual(result, [{"content": "讨论了语音助手项目"}])
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/api/v2/memory/get"))
        # v2: user_id is top-level, memory_type is "episode" (not "episodic_memory")
        self.assertEqual(kwargs["json"]["user_id"], "scope-main")
        self.assertEqual(kwargs["json"]["memory_type"], "episode")


if __name__ == "__main__":
    unittest.main()
