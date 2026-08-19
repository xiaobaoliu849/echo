from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from .evermem_config import EverMemConfig
from .evermem_service import EverMemService

logger = logging.getLogger(__name__)


def _resolve_pending_cache_path() -> Path:
    app_name = "VoiceSpirit"
    if os.name == "nt":
        base_dir = Path(os.environ.get("APPDATA", str(Path.cwd())))
        preferred_dir = base_dir / app_name
    else:
        xdg_state_home = os.environ.get("XDG_STATE_HOME")
        base_dir = Path(xdg_state_home) if xdg_state_home else Path.home() / ".local" / "state"
        preferred_dir = base_dir / app_name

    fallback_dir = Path.cwd() / ".voicespirit-state" / app_name
    for candidate in (preferred_dir, fallback_dir):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate / "realtime_pending_memory.json"
        except OSError:
            continue

    return fallback_dir / "realtime_pending_memory.json"


def _merge_memory_text(previous: str, incoming: str) -> str:
    next_text = str(incoming or "").strip()
    if not next_text:
        return previous
    if not previous:
        return next_text
    if next_text.startswith(previous):
        return next_text
    if previous.endswith(next_text):
        return previous
    # Insert a word-boundary space between Latin tokens so memory text
    # doesn't run words together (e.g. "Hello" + "world" → "Hello world").
    if previous[-1:].isalnum() and next_text[:1].isalnum():
        # Only add space when the boundary looks like Latin script;
        # CJK tokens join directly without spaces.
        last = previous[-1]
        first = next_text[0]
        if (last.isascii() and last.isalpha()) or (first.isascii() and first.isalpha()):
            return f"{previous} {next_text}"
    return f"{previous}{next_text}"


class RealtimeMemorySession:
    _PREFERENCE_PATTERNS = (
        r"喜欢",
        r"偏好",
        r"默认",
        r"以后",
        r"尽量",
        r"不要",
        r"记住",
        r"prefer",
        r"default",
        r"always",
    )
    _PREFERENCE_ACTION_PATTERNS = (
        r"请用",
        r"用",
        r"使用",
        r"改成",
        r"切换到",
        r"保持",
        r"prefer",
        r"default to",
        r"always use",
    )
    _VOICE_PATTERNS = (
        r"音色",
        r"声音",
        r"语速",
        r"播客",
        r"朗读",
        r"配音",
        r"男声",
        r"女声",
        r"voice",
        r"rate",
    )
    _TASK_PATTERNS = (
        r"任务",
        r"待办",
        r"项目",
        r"计划",
        r"安排",
        r"需求",
        r"工作",
        r"重点",
        r"继续",
        r"今天",
        r"明天",
        r"deadline",
        r"todo",
        r"next step",
        r"milestone",
        r"比赛",
        r"提交",
    )
    _TASK_ACTION_PATTERNS = (
        r"先",
        r"需要",
        r"记得",
        r"继续",
        r"接下来",
        r"下一步",
        r"安排",
        r"计划",
        r"完成",
        r"推进",
        r"修复",
        r"上线",
        r"发布",
        r"准备",
        r"提交",
        r"todo",
        r"next step",
    )
    _TASK_CONTEXT_PATTERNS = (
        r"当前在做",
        r"现在在做",
        r"最近在做",
        r"主要在做",
        r"主要是",
        r"正在",
        r"项目是",
        r"主题是",
        r"负责",
        r"focus on",
        r"working on",
    )
    _CONSTRAINT_PATTERNS = (
        r"不要",
        r"别",
        r"不能",
        r"必须",
        r"只能",
        r"限制",
        r"约束",
        r"截至",
        r"截止",
        r"deadline",
        r"must",
        r"avoid",
    )
    _SUMMARY_PATTERNS = (
        r"^总结",
        r"^结论",
        r"^本次",
        r"^这次",
        r"^核心",
        r"^主要是",
        r"summary",
        r"in short",
    )
    _QUESTION_PATTERNS = (
        r"\?$",
        r"？$",
        r"^(什么|怎么|为啥|为什么|是否|能不能|可不可以)",
        r"^(what|why|how|should|can|could)\b",
        r"(吗|呢)[\s。！？!?]*$",
    )
    _MEMORY_LABELS = {
        "voice_preference": "语音偏好",
        "user_preference": "用户偏好",
        "constraint": "约束条件",
        "action_item": "待办事项",
        "task_context": "当前任务上下文",
        "session_summary": "会话摘要",
    }
    _RETRIEVE_HINT_PATTERNS = (
        r"之前",
        r"上次",
        r"刚才",
        r"刚刚",
        r"继续",
        r"还是",
        r"沿用",
        r"默认",
        r"记得",
        r"你还记得",
        r"previous",
        r"earlier",
        r"before",
        r"continue",
        r"still",
        r"same",
        r"remember",
        r"检索",
        r"搜索",
        r"回忆",
        r"想起",
        r"提到",
        r"刚才说",
        r"重点工作",
    )
    _RETRIEVE_TIMEOUT_SECONDS = 0.12
    _FORCED_RETRIEVE_TIMEOUT_SECONDS = 0.35
    _PENDING_MEMORY_TTL_SECONDS = 1800
    _PENDING_MEMORY_MAX_PER_SCOPE = 24
    _PENDING_MEMORY_CACHE: dict[str, list[dict[str, Any]]] = {}
    _PENDING_CACHE_PATH: Path = _resolve_pending_cache_path()

    def __init__(self) -> None:
        self._config = EverMemConfig()
        self._current_user_text = ""
        self._current_assistant_text = ""
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._last_retrieved_query = ""
        self._last_memory_context = ""
        self._last_memory_count = 0
        self._last_local_pending_count = 0
        self._last_cloud_count = 0
        self._last_retrieve_attempted = False

    def _pending_cache_key(self) -> str:
        return str(self._config.group_id or self._config.memory_scope).strip()

    def _scope_pending_cache_key(self) -> str:
        return str(self._config.memory_scope or "").strip()

    def configure(self, payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict) or not payload.get("enabled"):
            self._config = EverMemConfig()
            self._current_user_text = ""
            self._current_assistant_text = ""
            logger.info("voice_memory_config disabled")
            return

        self._config.update_from_headers(
            {
                "X-EverMem-Enabled": "true",
                "X-EverMem-Url": payload.get("api_url", ""),
                "X-EverMem-Key": payload.get("api_key", ""),
                "X-EverMem-Scope": payload.get("scope_id", ""),
                "X-EverMem-Group-ID": payload.get("group_id", ""),
            }
        )
        logger.info(
            "voice_memory_config enabled scope=%s group=%s url=%s",
            self._config.memory_scope,
            self._config.group_id,
            self._config.url,
        )

    def note_user_transcript(self, text: str) -> None:
        cleaned = str(text or "").strip()
        if cleaned != self._current_user_text:
            self._last_retrieved_query = ""
            self._last_memory_context = ""
            self._last_memory_count = 0
            self._last_local_pending_count = 0
            self._last_cloud_count = 0
            self._last_retrieve_attempted = False
        self._current_user_text = cleaned

    def note_assistant_text(self, text: str) -> None:
        self._current_assistant_text = _merge_memory_text(self._current_assistant_text, text)

    def discard_turn(self) -> None:
        """Drop an interrupted turn without writing partial content to long-term memory."""
        self._current_user_text = ""
        self._current_assistant_text = ""
        self._last_retrieved_query = ""
        self._last_memory_context = ""
        self._last_memory_count = 0
        self._last_local_pending_count = 0
        self._last_cloud_count = 0
        self._last_retrieve_attempted = False

    async def flush_turn(self) -> dict[str, Any]:
        service = self._config.get_service()
        user_text = self._current_user_text.strip()
        self._current_user_text = ""
        self._current_assistant_text = ""

        if not service or not user_text:
            logger.info(
                "voice_memory_write skipped reason=%s scope=%s text=%r",
                "disabled_or_empty",
                self._config.memory_scope,
                user_text[:120],
            )
            return {
                "enabled": bool(service),
                "attempted_count": 0,
                "saved_count": 0,
                "failed_count": 0,
                "reason": "disabled_or_empty",
            }

        memory_entries = self._extract_memory_entries(user_text)
        if not memory_entries:
            logger.info(
                "voice_memory_write skipped reason=%s scope=%s text=%r",
                "no_candidate_memory",
                self._config.memory_scope,
                user_text[:120],
            )
            return {
                "enabled": True,
                "attempted_count": 0,
                "saved_count": 0,
                "failed_count": 0,
                "reason": "no_candidate_memory",
            }

        cache_key = self._pending_cache_key()
        queued_count = self._queue_pending_entries(cache_key, memory_entries)
        scope_key = self._scope_pending_cache_key()
        if scope_key and scope_key != cache_key:
            self._queue_pending_entries(scope_key, memory_entries)
        result = await self._persist_entries(entries=memory_entries)
        result["enabled"] = True
        result["local_pending_count"] = queued_count
        logger.info(
            "voice_memory_write scope=%s group=%s attempted=%s saved=%s failed=%s local_pending=%s entries=%s",
            self._config.memory_scope,
            self._config.group_id,
            result.get("attempted_count", 0),
            result.get("saved_count", 0),
            result.get("failed_count", 0),
            queued_count,
            memory_entries,
        )
        return result

    async def drain(self) -> None:
        if not self._pending_tasks:
            return
        await asyncio.gather(*list(self._pending_tasks), return_exceptions=True)

    async def _persist_entries(self, *, entries: list[str]) -> dict[str, int]:
        service = self._config.get_service()
        if not service or not entries:
            return {"attempted_count": 0, "saved_count": 0, "failed_count": 0}

        scope = self._config.memory_scope
        saved_count = 0
        failed_count = 0
        for entry in entries:
            try:
                result = await service.add_memory(
                    content=entry,
                    user_id=scope,
                    sender=scope,
                    sender_name="User",
                    group_id=self._config.group_id or None,
                )
                if result:
                    saved_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        return {
            "attempted_count": len(entries),
            "saved_count": saved_count,
            "failed_count": failed_count,
        }

    def should_retrieve_context(self, text: str | None = None) -> bool:
        service = self._config.get_service()
        candidate = str(text or self._current_user_text or "").strip()
        if not service or not candidate:
            logger.info(
                "voice_memory_retrieve skipped reason=%s scope=%s query=%r",
                "disabled_or_empty",
                self._config.memory_scope,
                candidate[:120],
            )
            return False
        if service.should_skip_memory(candidate):
            logger.info(
                "voice_memory_retrieve skipped reason=%s scope=%s query=%r",
                "trivial_message",
                self._config.memory_scope,
                candidate[:120],
            )
            return False
        if self._matches_any(candidate, self._RETRIEVE_HINT_PATTERNS):
            logger.info(
                "voice_memory_retrieve trigger=hint scope=%s query=%r",
                self._config.memory_scope,
                candidate[:120],
            )
            return True

        for sentence in self._split_sentences(candidate):
            normalized = self._normalize_candidate(sentence)
            if not normalized:
                continue
            kind = self._classify_candidate(normalized)
            if kind in {"voice_preference", "user_preference", "constraint", "action_item", "task_context"}:
                logger.info(
                    "voice_memory_retrieve trigger=classified kind=%s scope=%s query=%r",
                    kind,
                    self._config.memory_scope,
                    candidate[:120],
                )
                return True

        if self._looks_like_question(candidate):
            question_targets_memory = (
                self._matches_any(candidate, self._TASK_PATTERNS)
                or self._matches_any(candidate, self._VOICE_PATTERNS)
                or self._matches_any(candidate, self._PREFERENCE_PATTERNS)
                or self._matches_any(candidate, self._CONSTRAINT_PATTERNS)
            )
            if question_targets_memory and len(candidate) >= 8:
                logger.info(
                    "voice_memory_retrieve trigger=question_target scope=%s query=%r",
                    self._config.memory_scope,
                    candidate[:120],
                )
                return True
            logger.info(
                "voice_memory_retrieve skipped reason=%s scope=%s query=%r",
                "question_without_memory_target",
                self._config.memory_scope,
                candidate[:120],
            )
            return False
        logger.info(
            "voice_memory_retrieve trigger=length scope=%s query=%r",
            self._config.memory_scope,
            candidate[:120],
        )
        return len(candidate) >= 18

    def is_forced_recall_query(self, text: str | None = None) -> bool:
        candidate = str(text or self._current_user_text or "").strip()
        if not candidate:
            return False
        if not self._looks_like_question(candidate):
            return False
        return self._matches_any(candidate, self._RETRIEVE_HINT_PATTERNS)

    async def retrieve_memory_context(self) -> dict[str, Any]:
        service = self._config.get_service()
        query = self._current_user_text.strip()
        if not service or not query or not self.should_retrieve_context(query):
            return {
                "context": "",
                "memories_retrieved": 0,
                "local_pending_count": 0,
                "cloud_count": 0,
                "attempted": False,
            }
        if query == self._last_retrieved_query:
            logger.info(
                "voice_memory_retrieve cache_hit scope=%s count=%s query=%r",
                self._config.memory_scope,
                self._last_memory_count,
                query[:120],
            )
            return {
                "context": self._last_memory_context,
                "memories_retrieved": self._last_memory_count,
                "local_pending_count": self._last_local_pending_count,
                "cloud_count": self._last_cloud_count,
                "attempted": self._last_retrieve_attempted,
            }

        cache_key = self._pending_cache_key()
        local_memories = self._search_pending_entries(cache_key, query)
        scope_key = self._scope_pending_cache_key()
        if (
            scope_key
            and scope_key != cache_key
            and self.is_forced_recall_query(query)
        ):
            local_memories = self._merge_retrieved_memories(
                local_memories=local_memories,
                cloud_memories=self._search_pending_entries(scope_key, query),
            )

        try:
            timeout_seconds = (
                self._FORCED_RETRIEVE_TIMEOUT_SECONDS
                if self.is_forced_recall_query(query)
                else self._RETRIEVE_TIMEOUT_SECONDS
            )
            memories = await asyncio.wait_for(
                self._search_cloud_memories(
                    service=service,
                    query=query,
                ),
                timeout=timeout_seconds,
            )
        except Exception:
            logger.exception(
                "voice_memory_retrieve error scope=%s query=%r",
                self._config.memory_scope,
                query[:120],
            )
            memories = []

        combined = self._merge_retrieved_memories(local_memories=local_memories, cloud_memories=memories)
        lines: list[str] = []
        local_count = len(local_memories)
        cloud_count = len(memories)
        for idx, memory in enumerate(combined[:3], start=1):
            content = str(memory.get("content", "")).strip()
            if not content:
                continue
            source = str(memory.get("source", "")).strip()
            if source == "local_pending":
                lines.append(f"{idx}. [本地待同步记忆] {content[:180]}")
            else:
                lines.append(f"{idx}. [云端长期记忆] {content[:180]}")

        self._last_retrieved_query = query
        self._last_memory_context = "\n".join(lines)
        self._last_memory_count = len(lines)
        self._last_local_pending_count = local_count
        self._last_cloud_count = cloud_count
        self._last_retrieve_attempted = True
        logger.info(
            "voice_memory_retrieve result scope=%s count=%s local_pending=%s cloud=%s query=%r",
            self._config.memory_scope,
            self._last_memory_count,
            local_count,
            cloud_count,
            query[:120],
        )
        return {
            "context": self._last_memory_context,
            "memories_retrieved": self._last_memory_count,
            "local_pending_count": local_count,
            "cloud_count": cloud_count,
            "attempted": True,
        }

    async def _search_cloud_memories(
        self,
        *,
        service: EverMemService,
        query: str,
    ) -> list[dict[str, Any]]:
        base_kwargs = {
            "query": query,
            "user_id": self._config.memory_scope,
            "memory_types": ["episodic_memory", "profile"],
            "min_score": 0.35,
        }
        group_id = str(self._config.group_id or "").strip()
        if group_id:
            scoped = await service.search_memories(
                group_ids=[group_id],
                **base_kwargs,
            )
            if scoped:
                return scoped
        return await service.search_memories(**base_kwargs)

    def _extract_memory_entries(self, text: str) -> list[str]:
        entries: list[str] = []
        seen: set[str] = set()

        for sentence in self._split_sentences(text):
            candidate = self._normalize_candidate(sentence)
            if not candidate or self._looks_like_question(candidate):
                continue

            kind = self._classify_candidate(candidate)
            if not kind:
                continue

            labeled = f"{self._MEMORY_LABELS[kind]}: {candidate}"
            dedupe_key = labeled.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            entries.append(labeled)

        return entries[:2]

    def _classify_candidate(self, text: str) -> str | None:
        has_preference = self._matches_any(text, self._PREFERENCE_PATTERNS)
        has_voice = self._matches_any(text, self._VOICE_PATTERNS)
        has_constraint = self._matches_any(text, self._CONSTRAINT_PATTERNS)
        has_task = self._matches_any(text, self._TASK_PATTERNS)
        has_task_action = self._matches_any(text, self._TASK_ACTION_PATTERNS)
        has_task_context = self._matches_any(text, self._TASK_CONTEXT_PATTERNS)
        has_summary = self._matches_any(text, self._SUMMARY_PATTERNS)

        if has_voice and has_preference:
            return "voice_preference"
        if has_preference and self._matches_any(text, self._PREFERENCE_ACTION_PATTERNS):
            return "user_preference"
        if has_constraint and not self._looks_like_question(text):
            return "constraint"
        if has_task and has_task_action:
            return "action_item"
        if has_task_context or (has_task and len(text) >= 12):
            return "task_context"
        if has_summary and len(text) >= 12:
            return "session_summary"
        return None

    def _looks_like_question(self, text: str) -> bool:
        return self._matches_any(text, self._QUESTION_PATTERNS)

    @staticmethod
    def _normalize_candidate(text: str) -> str:
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        compact = re.sub(r"^[,.;:，。；：、\-\s]+", "", compact)
        compact = re.sub(
            r"^(我觉得|我想|我希望|那个|就是|嗯|呃|请帮我|帮我|麻烦你|简单说|结论是)\s*",
            "",
            compact,
            flags=re.IGNORECASE,
        )
        compact = compact.strip()
        if len(compact) < 6:
            return ""
        return compact[:160]

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        parts: list[str] = []
        for segment in re.split(r"[。！？!?\n;；]+", str(text or "")):
            if not segment.strip():
                continue
            clauses = [item.strip() for item in re.split(r"[，,]+", segment) if item.strip()]
            parts.extend(clauses or [segment.strip()])
        return parts

    @staticmethod
    def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    @classmethod
    def _prune_pending_entries(cls, scope: str) -> list[dict[str, Any]]:
        cls._load_pending_cache_from_disk()
        now = time.time()
        entries = cls._PENDING_MEMORY_CACHE.get(scope, [])
        fresh = [
            item for item in entries
            if now - float(item.get("created_at", 0.0)) <= cls._PENDING_MEMORY_TTL_SECONDS
        ]
        if fresh:
            cls._PENDING_MEMORY_CACHE[scope] = fresh[-cls._PENDING_MEMORY_MAX_PER_SCOPE :]
        else:
            cls._PENDING_MEMORY_CACHE.pop(scope, None)
        cls._save_pending_cache_to_disk()
        return cls._PENDING_MEMORY_CACHE.get(scope, [])

    @classmethod
    def _queue_pending_entries(cls, scope: str, entries: list[str]) -> int:
        if not scope or not entries:
            return 0
        existing = cls._prune_pending_entries(scope)
        seen = {cls._content_dedupe_key(str(item.get("content", ""))) for item in existing}
        now = time.time()
        appended = 0
        for entry in entries:
            key = cls._content_dedupe_key(entry)
            if not key or key in seen:
                continue
            existing.append({"content": entry, "created_at": now})
            seen.add(key)
            appended += 1
        cls._PENDING_MEMORY_CACHE[scope] = existing[-cls._PENDING_MEMORY_MAX_PER_SCOPE :]
        cls._save_pending_cache_to_disk()
        return appended

    @classmethod
    def _search_pending_entries(cls, scope: str, query: str) -> list[dict[str, Any]]:
        pending = cls._prune_pending_entries(scope)
        if not pending:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for item in pending:
            content = str(item.get("content", "")).strip()
            score = cls._score_pending_entry(query, content)
            if score < 0.18:
                continue
            scored.append((score, {"content": content, "source": "local_pending"}))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:3]]

    @classmethod
    def _merge_retrieved_memories(
        cls,
        *,
        local_memories: list[dict[str, Any]],
        cloud_memories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()

        for memory in local_memories:
            content = str(memory.get("content", "")).strip()
            key = cls._content_dedupe_key(content)
            if not key or key in seen:
                continue
            seen.add(key)
            source = str(memory.get("source", "local_pending")).strip() or "local_pending"
            merged.append({"content": content, "source": source})

        for memory in cloud_memories:
            content = str(memory.get("content", "")).strip()
            key = cls._content_dedupe_key(content)
            if not key or key in seen:
                continue
            seen.add(key)
            source = str(memory.get("source", "cloud")).strip() or "cloud"
            merged.append({"content": content, "source": source})

        return merged

    @classmethod
    def _load_pending_cache_from_disk(cls) -> None:
        path = cls._PENDING_CACHE_PATH
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError):
            logger.warning("voice_memory_pending load_failed path=%s", path)
            return

        if not isinstance(raw, dict):
            return

        loaded: dict[str, list[dict[str, Any]]] = {}
        for scope, items in raw.items():
            if not isinstance(scope, str) or not isinstance(items, list):
                continue
            normalized_items: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                try:
                    created_at = float(item.get("created_at", 0.0))
                except (TypeError, ValueError):
                    created_at = 0.0
                normalized_items.append({"content": content, "created_at": created_at})
            if normalized_items:
                loaded[scope] = normalized_items[-cls._PENDING_MEMORY_MAX_PER_SCOPE :]
        cls._PENDING_MEMORY_CACHE = loaded

    @classmethod
    def _save_pending_cache_to_disk(cls) -> None:
        path = cls._PENDING_CACHE_PATH
        serializable: dict[str, list[dict[str, Any]]] = {}
        for scope, items in cls._PENDING_MEMORY_CACHE.items():
            normalized_items = [
                {
                    "content": str(item.get("content", "")).strip(),
                    "created_at": float(item.get("created_at", 0.0)),
                }
                for item in items
                if str(item.get("content", "")).strip()
            ]
            if normalized_items:
                serializable[scope] = normalized_items
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(serializable, ensure_ascii=True), encoding="utf-8")
            temp_path.replace(path)
        except OSError:
            logger.warning("voice_memory_pending save_failed path=%s", path)

    @classmethod
    def _score_pending_entry(cls, query: str, content: str) -> float:
        normalized_query = cls._search_text(query)
        normalized_content = cls._search_text(content)
        if not normalized_query or not normalized_content:
            return 0.0
        if normalized_query in normalized_content:
            return 1.0
        if normalized_content in normalized_query:
            return 0.9

        query_grams = cls._bigrams(normalized_query)
        content_grams = cls._bigrams(normalized_content)
        overlap = len(query_grams & content_grams) / max(1, len(query_grams))
        pattern_bonus = 0.0
        if cls._matches_any(query, cls._TASK_PATTERNS) and cls._matches_any(content, cls._TASK_PATTERNS):
            pattern_bonus += 0.2
        if cls._matches_any(query, cls._PREFERENCE_PATTERNS) and cls._matches_any(content, cls._PREFERENCE_PATTERNS):
            pattern_bonus += 0.2
        if cls._matches_any(query, cls._VOICE_PATTERNS) and cls._matches_any(content, cls._VOICE_PATTERNS):
            pattern_bonus += 0.2
        return overlap + pattern_bonus

    @staticmethod
    def _search_text(text: str) -> str:
        value = str(text or "").strip().lower()
        value = re.sub(r"^\[[^\]]+\]\s*", "", value)
        value = re.sub(r"^[^:：]{1,24}[:：]\s*", "", value)
        value = re.sub(r"\s+", "", value)
        value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
        return value

    @classmethod
    def _content_dedupe_key(cls, text: str) -> str:
        return cls._search_text(text)

    @staticmethod
    def _bigrams(text: str) -> set[str]:
        if len(text) <= 2:
            return {text} if text else set()
        return {text[idx : idx + 2] for idx in range(len(text) - 1)}
