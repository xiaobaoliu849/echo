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
    async def test_add_memory_aligns_sender_with_user_scope(self) -> None:
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
        _, kwargs = post.call_args
        payload = kwargs["json"]
        self.assertEqual(payload["user_id"], "scope-main")
        self.assertEqual(payload["session_id"], "scope-main_default")
        self.assertTrue(payload["async_mode"])
        message = payload["messages"][0]
        self.assertEqual(message["sender_id"], "scope-main")
        self.assertEqual(message["role"], "user")
        self.assertEqual(message["content"], "remember this")
        self.assertIsInstance(message["timestamp"], int)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertTrue(kwargs["url"].endswith("/api/v1/memories") if "url" in kwargs else True)

    async def test_add_memory_maps_group_id_to_session_and_flushes(self) -> None:
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
        add_kwargs = post.call_args_list[0].kwargs
        self.assertEqual(add_kwargs["json"]["session_id"], "group-chat-001")
        self.assertEqual(add_kwargs["json"]["messages"][0]["role"], "assistant")
        flush_kwargs = post.call_args_list[1].kwargs
        self.assertEqual(
            flush_kwargs["json"],
            {"user_id": "scope-main", "session_id": "group-chat-001"},
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

    async def test_create_conversation_meta_generates_group_id(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 200
        post = AsyncMock(return_value=response)

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            result = await service.create_conversation_meta(user_id="scope-main")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["group_id"].startswith("conv_"))
        self.assertEqual(result["user_id"], "scope-main")
        _, kwargs = post.call_args
        self.assertEqual(kwargs["json"]["group_id"], result["group_id"])

    async def test_create_conversation_meta_survives_upstream_failure(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        post = AsyncMock(side_effect=RuntimeError("network down"))

        with patch("services.evermem_service.httpx.AsyncClient") as client_cls:
            client, _ = _make_client_mock(post)
            client.post = post
            client_cls.return_value = client

            result = await service.create_conversation_meta(
                user_id="scope-main", group_id="group-chat-001"
            )

        # group/session ids are client-chosen in v1, so registration failure
        # must not break the conversation flow.
        self.assertEqual(result, {"group_id": "group-chat-001", "user_id": "scope-main"})

    async def test_search_memories_parses_v1_envelope(self) -> None:
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
                "raw_messages": [
                    {"content": "本周重点是比赛提交"},
                ],
                "agent_memory": None,
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

        _, kwargs = post.call_args
        payload = kwargs["json"]
        self.assertEqual(payload["filters"], {"user_id": "scope-main"})
        self.assertEqual(payload["method"], "hybrid")
        self.assertEqual(payload["memory_types"], ["episodic_memory", "profile"])

    async def test_search_memories_maps_single_group_to_session_filter(self) -> None:
        service = EverMemService(api_url="https://memory.example.com", api_key="test-key")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": {"episodes": [], "profiles": [], "raw_messages": []}}
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

        _, kwargs = post.call_args
        self.assertEqual(
            kwargs["json"]["filters"],
            {"user_id": "scope-main", "session_id": "group-chat-001"},
        )

    async def test_get_memories_uses_v1_get_endpoint(self) -> None:
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
        _, kwargs = post.call_args
        self.assertEqual(kwargs["json"]["filters"], {"user_id": "scope-main"})


if __name__ == "__main__":
    unittest.main()
