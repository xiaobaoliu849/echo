"""
EverMemOS Service (EverOS Memory API v2)
Service for interacting with EverOS long-term memory system.

Targets the unified v2 endpoints (``/api/v2/memory/*``): these are shared
across Cloud and self-hosted (OSS) deployments with identical request/response
contracts.  v1 paths are legacy and kept only for migration reference.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import weakref
from typing import Any, AsyncIterator

import httpx # type: ignore

logger = logging.getLogger(__name__)

# One pooled client per event loop. A fresh client per call paid a new TLS
# handshake every time: measured from the dev machine, 0.88 s per search
# versus 0.30 s on a reused connection, which matters for realtime recall.
# Keyed weakly by loop because an httpx client is bound to the loop it was
# first used on.
_SHARED_CLIENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = (
    weakref.WeakKeyDictionary()
)


@contextlib.asynccontextmanager
async def _pooled_client() -> AsyncIterator[httpx.AsyncClient]:
    loop = asyncio.get_running_loop()
    client = _SHARED_CLIENTS.get(loop)
    if client is None or client.is_closed is True:
        # httpx drops idle connections after 5 s by default, but voice recalls
        # are often minutes apart; keep the connection (and its TLS session)
        # warm much longer. The server may still close it, which httpx handles.
        client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(keepalive_expiry=300.0))
        _SHARED_CLIENTS[loop] = client
    yield client


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
        """Resolve the v2 ``session_id`` partition for a write/flush call.

        v2 ``add`` and ``flush`` key on ``session_id`` (not ``user_id``) —
        ``user_id`` is derived from the API key at the server side.  Echo still
        passes ``group_id`` from its config; in v2 this maps directly to
        ``session_id``.  When absent, fall back to a stable per-user default so
        writes and flushes land in the same session.
        """
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
        sync: bool = False,
    ) -> dict[str, Any] | None:
        """Add a memory message to EverOS (v2 add endpoint).

        v2 keys on ``session_id``; ``user_id`` is NOT sent in the request body
        (the server derives it from the API key + sender_id).  Returns
        ``{"status": "success"}`` on HTTP 202 (async) or 200 (sync).

        ``sync`` (implied by ``flush``) waits for the message to be accepted:
        per the v2 docs, a flush right after a queued (202) add can run before
        the message lands and return ``no_extraction``.
        """
        if not self.api_key:
            logger.warning("EverMemService: Missing API key. Cannot add memory.")
            return None

        session_id = self._session_id_for(user_id, group_id)
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
            "session_id": session_id,
            "async_mode": not (sync or flush),
            "messages": [message],
        }

        try:
            async with _pooled_client() as client:
                resp = await client.post(
                    f"{self.api_url}/api/v2/memory/add",
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
                        f"{self.api_url}/api/v2/memory/flush",
                        headers=self._headers(),
                        json={"session_id": session_id},
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

    async def flush_pending_memories(
        self,
        user_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Force EverOS to extract a session's pending messages.

        Without a flush, freshly written messages stay in the session's
        in-flight buffer (``unprocessed_messages``) and are only reachable
        via session-pinned search — never as extracted episodes.  v2
        ``flush`` keys on ``session_id`` only (``user_id`` is derived
        server-side from the API key).

        Failures are logged and return ``None`` (fail-open): a failed flush
        must not block the write path — the pending buffer is retried on the
        next turn's flush or the session's background extraction.
        """
        if not self.api_key:
            logger.warning("EverMemService: Missing API key. Cannot flush memories.")
            return None

        resolved_session = self._session_id_for(user_id, session_id)
        payload = {"session_id": resolved_session}
        try:
            async with _pooled_client() as client:
                resp = await client.post(
                    f"{self.api_url}/api/v2/memory/flush",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "EverOS flush returned %s: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return None
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Failed to flush memories in EverOS: {e}")
            return None

    async def create_conversation_meta(
        self,
        *,
        user_id: str = "guest",
        group_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a usable session/group id for v2 conversations.

        v2 does not have a separate group-registration endpoint (the v1
        ``/api/v1/groups`` endpoint is legacy and not carried into v2).
        Session ids are client-chosen, so we simply return the provided or
        generated id — writes and reads only need the ``session_id``.
        """
        import uuid

        resolved_group_id = str(group_id or "").strip() or f"conv_{uuid.uuid4().hex[:16]}"
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
        """Search for relevant memories in EverOS (v2 search endpoint).

        v2 moves ``user_id`` to the top level (out of ``filters``).  Session
        scoping uses ``filters.session_id`` — pinning a single session is also
        the only way to retrieve ``unprocessed_messages`` (the in-flight buffer
        of not-yet-extracted raw messages).

        v2 does not accept a ``memory_types`` array on search. Profiles are
        only returned with ``include_profile`` (default false per the v2
        docs), so it is sent whenever profiles are wanted: ``memory_types``
        unset (all types) or containing ``"profile"``.
        """
        if not self.api_key:
            logger.warning("EverMemService: Missing API key. Cannot search memories.")
            return []

        filters: dict[str, Any] = {}
        resolved_group_ids = [str(g).strip() for g in (group_ids or []) if str(g).strip()]
        if len(resolved_group_ids) == 1:
            filters["session_id"] = resolved_group_ids[0]

        payload: dict[str, Any] = {
            "query": query,
            "user_id": user_id,
            "method": "hybrid",
            "top_k": 5,
        }
        if memory_types is None or "profile" in memory_types:
            payload["include_profile"] = True
        if filters:
            payload["filters"] = filters

        try:
            async with _pooled_client() as client:
                resp = await client.post(
                    f"{self.api_url}/api/v2/memory/search",
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

            episodes_list = data.get("episodes") or []
            profiles_list = data.get("profiles") or []
            raw_messages = data.get("unprocessed_messages") or data.get("raw_messages") or []

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
                content = (
                    mem.get("episode")
                    or mem.get("summary")
                    or mem.get("subject")
                    or mem.get("content")
                )
                if content:
                    extracted_memories.append(
                        {"content": f"[历史对话] {content}", "type": "episodic_memory", "score": score}
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

    async def warm_up(self) -> None:
        """Open the pooled connection ahead of the first realtime recall.

        The TLS handshake is most of a cold search (~0.6 s of ~0.95 s
        measured); any response, even a 404, leaves a reusable connection.
        """
        if not self.api_key:
            return
        try:
            async with _pooled_client() as client:
                await client.get(self.api_url, timeout=5.0)
        except Exception as exc:
            logger.debug("EverOS warm-up skipped: %s", exc)

    async def get_memories(self, user_id: str = "guest") -> list[dict[str, Any]]:
        """Get episodic memories for a user (v2 get endpoint).

        v2 moves ``user_id`` to the top level and renames ``memory_type`` from
        the v1 ``episodic_memory`` to the v2 ``episode``.
        """
        if not self.api_key:
            logger.warning("EverMemService: Missing API key. Cannot get memories.")
            return []

        payload = {
            "user_id": user_id,
            "memory_type": "episode",
            "page": 1,
            "page_size": 20,
        }

        try:
            async with _pooled_client() as client:
                resp = await client.post(
                    f"{self.api_url}/api/v2/memory/get",
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
