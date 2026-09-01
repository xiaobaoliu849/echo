"""
EverMemOS Service (EverOS Cloud API v1)
Service for interacting with EverMemOS long-term memory system.

Targets the Cloud v1 endpoints (``/api/v1/...``): v0 was removed upstream on
2026-06-17, and this account is gated to v1 (v2 returns VERSION_NOT_ALLOWED).
Supports both Cloud (https://api.evermind.ai) and compatible self-hosted
instances.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx # type: ignore

logger = logging.getLogger(__name__)


class EverMemService:
    def __init__(self, api_url: str, api_key: str | None = None):
        self.api_url = (api_url or "https://api.evermind.ai").rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _session_id_for(user_id: str, group_id: str | None) -> str:
        """Map the legacy group_id concept onto the v1 session_id partition."""
        resolved_group = str(group_id or "").strip()
        return resolved_group or f"{user_id}_default"

    async def add_memory(
        self,
        content: str,
        user_id: str = "guest",
        sender: str | None = None,
        sender_name: str = "User",
        flush: bool = False,
        group_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Add a memory message to EverOS (v1 personal memories endpoint)."""
        if not self.api_key:
            logger.warning("EverMemService: Missing API key. Cannot add memory.")
            return None

        session_id = self._session_id_for(user_id, group_id)
        # EverOS uses sender_id as memory ownership internally.
        # Keep it aligned with user_id/scope so writes and reads land in the same namespace.
        role = "assistant" if str(sender_name).strip().lower() == "assistant" else "user"
        message: dict[str, Any] = {
            "sender_id": user_id,
            "role": role,
            "timestamp": int(time.time() * 1000),
            "content": content,
        }
        if str(sender_name).strip():
            message["sender_name"] = str(sender_name).strip()

        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "async_mode": True,
            "messages": [message],
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.api_url}/api/v1/memories",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code not in (200, 201, 202):
                    logger.error(
                        "Failed to add memory to EverOS: %s %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return None
                if flush:
                    flush_resp = await client.post(
                        f"{self.api_url}/api/v1/memories/flush",
                        headers=self._headers(),
                        json={"user_id": user_id, "session_id": session_id},
                    )
                    if flush_resp.status_code != 200:
                        logger.warning(
                            "EverOS flush returned %s: %s",
                            flush_resp.status_code,
                            flush_resp.text[:200],
                        )
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Failed to add memory to EverOS: {e}")
            return None

    async def create_conversation_meta(
        self,
        *,
        user_id: str = "guest",
        group_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Register a conversation group (v1 groups endpoint, best-effort).

        v1 group/session identifiers are client-chosen, so a usable
        ``group_id`` is always returned even if the upstream registration
        fails (e.g. the group already exists) — writes/reads only need the id.
        """
        if not self.api_key:
            logger.warning("EverMemService: Missing API key. Cannot create conversation meta.")
            return None

        resolved_group_id = str(group_id or "").strip() or f"conv_{uuid.uuid4().hex[:16]}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.api_url}/api/v1/groups",
                    headers=self._headers(),
                    json={
                        "group_id": resolved_group_id,
                        "name": f"Echo conversation {resolved_group_id}",
                        "description": "Realtime voice / chat conversation group",
                    },
                )
                if resp.status_code not in (200, 201, 202, 409):
                    logger.warning(
                        "EverOS group registration returned %s: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except Exception as e:
            logger.warning(f"EverOS group registration failed (continuing anyway): {e}")

        return {"group_id": resolved_group_id, "user_id": user_id}

    async def search_memories(
        self,
        query: str,
        user_id: str = "guest",
        min_score: float = 0.3,
        *,
        group_ids: list[str] | None = None,
        memory_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for relevant memories in EverOS (v1 search endpoint)."""
        if not self.api_key:
            logger.warning("EverMemService: Missing API key. Cannot search memories.")
            return []

        filters: dict[str, Any] = {"user_id": user_id}
        resolved_group_ids = [str(g).strip() for g in (group_ids or []) if str(g).strip()]
        if len(resolved_group_ids) == 1:
            filters["session_id"] = resolved_group_ids[0]

        payload: dict[str, Any] = {
            "query": query,
            "filters": filters,
            "method": "hybrid",
            "top_k": 5,
        }
        if memory_types:
            payload["memory_types"] = memory_types

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.api_url}/api/v1/memories/search",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.error(f"EverOS search returned {resp.status_code}: {resp.text[:200]}")
                    return []
                body = resp.json()

            data = body.get("data") or body.get("result") or {}
            if not isinstance(data, dict):
                return []

            episodes_list = data.get("episodes") or data.get("memories") or []
            profiles_list = data.get("profiles") or []
            raw_messages = data.get("raw_messages") or data.get("pending_messages") or []

            extracted_memories: list[dict[str, Any]] = []

            for profile in profiles_list:
                if not isinstance(profile, dict):
                    continue
                desc = profile.get("description")
                if not desc and isinstance(profile.get("profile_data"), dict):
                    pairs = [
                        f"{k}: {v}"
                        for k, v in list(profile["profile_data"].items())[:8]
                    ]
                    desc = "；".join(pairs)
                if desc:
                    extracted_memories.append(
                        {
                            "content": f"[用户画像] {desc}",
                            "type": "profile",
                            "score": profile.get("score", 1.0),
                        }
                    )

            for mem in episodes_list:
                if not isinstance(mem, dict):
                    continue
                score = mem.get("score", 1.0)
                if isinstance(score, (int, float)) and score < min_score:
                    continue
                mem_type = mem.get("memory_type", "episodic_memory")
                content = (
                    mem.get("episode")
                    or mem.get("summary")
                    or mem.get("subject")
                    or mem.get("content")
                )
                if content:
                    type_label = {
                        "episodic_memory": "历史对话",
                        "episode": "历史对话",
                        "foresight": "提醒/行动",
                        "profile": "用户画像",
                    }.get(mem_type, "记忆")
                    extracted_memories.append(
                        {"content": f"[{type_label}] {content}", "type": mem_type, "score": score}
                    )

            for pending in raw_messages:
                if not isinstance(pending, dict):
                    continue
                content = str(pending.get("content", "")).strip()
                if content:
                    extracted_memories.append(
                        {
                            "content": f"[待处理消息] {content}",
                            "type": "pending_message",
                            "score": 1.0,
                        }
                    )

            return extracted_memories
        except Exception as e:
            logger.error(f"Failed to search memories in EverOS: {e}")
            return []

    async def get_memories(self, user_id: str = "guest") -> list[dict[str, Any]]:
        """Get episodic memories for a user (v1 get endpoint)."""
        if not self.api_key:
            logger.warning("EverMemService: Missing API key. Cannot get memories.")
            return []

        payload = {
            "filters": {"user_id": user_id},
            "memory_type": "episodic_memory",
            "page": 1,
            "page_size": 20,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.api_url}/api/v1/memories/get",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code != 200:
                    return []
                body = resp.json()

            data = body.get("data") or body.get("result") or {}
            if not isinstance(data, dict):
                return []

            episodes_list = data.get("episodes") or data.get("memories") or []
            extracted_memories = []
            for mem in episodes_list:
                if not isinstance(mem, dict):
                    continue
                content = mem.get("episode") or mem.get("summary") or mem.get("content")
                if content:
                    extracted_memories.append({"content": content})
            return extracted_memories
        except Exception as e:
            logger.error(f"Failed to get memories from EverOS: {e}")
            return []

    _SKIP_PATTERNS = {
        "你好",
        "hello",
        "hi",
        "hey",
        "嗨",
        "哈喽",
        "早上好",
        "晚上好",
        "下午好",
        "好的",
        "ok",
        "okay",
        "嗯",
        "嗯嗯",
        "好",
        "行",
        "可以",
        "明白",
        "了解",
        "谢谢",
        "thanks",
        "thank you",
        "thx",
        "感谢",
        "多谢",
        "哈哈",
        "哈哈哈",
        "lol",
        "😂",
        "👍",
        "666",
        "厉害",
        "不错",
        "太棒了",
        "棒",
        "nice",
        "great",
        "cool",
        "wow",
        "再见",
        "拜拜",
        "bye",
        "晚安",
        "good night",
    }

    def should_skip_memory(self, user_msg: str) -> bool:
        """Lightweight local check to skip memory retrieval for trivial messages."""
        msg = user_msg.strip().lower().rstrip("!！~.。？?")
        if len(msg) <= 2:
            return True
        if msg in self._SKIP_PATTERNS:
            return True
        return False
