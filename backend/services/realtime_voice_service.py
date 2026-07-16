from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import websockets
from fastapi import WebSocket, WebSocketDisconnect

print(f"DEBUG: Realtime service using Python: {sys.executable}")
print(f"DEBUG: Python Path: {sys.path}")

logger = logging.getLogger(__name__)

from .config_loader import BackendConfig
from .evermem_config import EverMemConfig
from .evermem_service import EverMemService
from .interruption_classifier import (
    InterruptionClassifier,
    InterruptionDecisionCoordinator,
    InterruptionIntent,
)
from .voice_agent_session_repository import VoiceAgentSessionRepository
from .voice_agent_tools import VoiceAgentToolService, VoiceAgentToolSession, VoiceToolRequest

try:
    from google import genai
    from google.genai import types
except ImportError as e:  # pragma: no cover - validated at runtime in deployed env
    print(f"DEBUG: Google GenAI Import Error: {e}")
    genai = None
    types = None
except Exception as e:
    print(f"DEBUG: Google GenAI Unexpected Error: {e}")
    genai = None
    types = None

try:
    from dashscope.audio.qwen_omni import AudioFormat, MultiModality, OmniRealtimeConversation
except ImportError as e:  # pragma: no cover - validated at runtime in deployed env
    print(f"DEBUG: DashScope Realtime Import Error: {e}")
    AudioFormat = None
    MultiModality = None
    OmniRealtimeConversation = None
except Exception as e:
    print(f"DEBUG: DashScope Realtime Unexpected Error: {e}")
    AudioFormat = None
    MultiModality = None
    OmniRealtimeConversation = None


DEFAULT_GOOGLE_REALTIME_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
GOOGLE_LIVE_TRANSLATE_MODEL = "gemini-3.5-live-translate-preview"
DEFAULT_GOOGLE_REALTIME_VOICE = "Puck"
DEFAULT_DASHSCOPE_REALTIME_MODEL = "qwen3-omni-flash-realtime-2025-12-01"
DEFAULT_DASHSCOPE_REALTIME_VOICE = "Cherry"
DEFAULT_OPENAI_REALTIME_MODEL = "gpt-realtime-2"
DEFAULT_OPENAI_REALTIME_VOICE = "alloy"
OPENAI_REALTIME_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
BASE_REALTIME_INSTRUCTIONS = (
    "You are a helpful, friendly, and intelligent AI assistant. "
    "Respond naturally and conversationally in the same language the user speaks. "
    "When the user asks you to search, look up, retrieve, or verify current information, briefly acknowledge "
    "that you are checking sources and wait for external tool context before giving a factual answer."
)

QWEN_AUDIO_REALTIME_INSTRUCTIONS = (
    "你是一位智能语音助手，你的名字是小云，性别女，声音甜美，举止亲切，你能回复用户的各种问题。"
    "请你按照下面的要求聊天：\n"
    "1. 像朋友之间聊天那样，语气自然友好，避免使用正式的称谓和模板化的表达。"
    "口语化只影响你的措辞和语气，不影响内容的完整性，该说的细节、数字、具体建议一个都不能少，"
    "只是用轻松自然的方式说出来。\n"
    "2. 充分考虑对话上下文中提到的所有约束条件（如预算、偏好、禁忌、之前达成的共识等），"
    "涉及多个条件或需要综合判断时逐一回应，不要遗漏关键信息。\n"
    "3. 除非用户要求，不要输出emoji等特殊符号，不要输出Markdown格式，尽量输出纯文本。\n"
    "4. 对于简单的日常闲聊、打招呼、情感回应，保持简洁自然。"
    "对于涉及事实判断、推理计算、多条件约束、推荐列表、安全建议的问题，"
    "以回答完整正确为优先，确保关键信息完整且正确，多说的内容必须是解决问题所必需的"
    "具体信息（如价格、地点、条件），而不是铺垫、重复或修辞。\n"
    "5. 适当引入追问，遵循\"先把用户当前的问题答好、再在结尾自然地追问，"
    "推动话题向前发展\"的原则，一次只问一个问题，不要连续追问或反复确认。"
    "用户明确要求背诵某篇文章、古诗词时，须遵循指令完整背诵。\n"
    "6. 当你需要搜索、查询、翻译、总结、生成语音或创建播客时，"
    "请主动调用对应的工具函数来获取外部信息或执行操作。调用工具后，"
    "等待工具返回结果再继续回复，不要凭空编造或猜测。"
)


def _is_google_live_translate_model(model: str | None) -> bool:
    return "live-translate" in str(model or "").strip().lower()


def _is_google_public_rest_base_url(base_url: str | None) -> bool:
    normalized = str(base_url or "").strip().rstrip("/").lower()
    return normalized in {
        "https://generativelanguage.googleapis.com",
        "https://generativelanguage.googleapis.com/v1",
        "https://generativelanguage.googleapis.com/v1beta",
    }


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
    return f"{previous}{next_text}"


def _merge_streaming_text(previous: str, incoming: str) -> tuple[str, str]:
    """Return canonical stream text and only the novel suffix to publish."""
    before = str(previous or "").strip()
    next_text = str(incoming or "").strip()
    if not next_text:
        return before, ""
    if not before:
        return next_text, next_text
    if next_text.startswith(before):
        delta = next_text[len(before):]
        return next_text, delta
    if before.endswith(next_text):
        return before, ""

    overlap = 0
    for size in range(min(len(before), len(next_text)), 0, -1):
        if before[-size:] == next_text[:size]:
            overlap = size
            break
    novel = next_text[overlap:]
    if not novel:
        return before, ""

    separator = ""
    if (
        before[-1:].isalnum()
        and novel[:1].isalnum()
        and re.search(r"[A-Za-z]", before[-1:] + novel[:1])
    ):
        separator = " "
    delta = f"{separator}{novel}"
    return f"{before}{delta}", delta


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


class DashScopeRealtimeCallback:
    def __init__(self, *, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.loop = loop
        self.queue = queue

    def _push(self, event: dict[str, Any]) -> None:
        self.loop.call_soon_threadsafe(self.queue.put_nowait, event)

    def on_open(self) -> None:
        return None

    def on_event(self, response: Any) -> None:
        if not isinstance(response, dict):
            return

        event_type = str(response.get("type", "")).strip()
        if event_type == "input_audio_buffer.speech_started":
            self._push(
                {
                    "type": "speech_started",
                    "provider_event_type": event_type,
                    "event_id": str(response.get("event_id", "")),
                    "item_id": str(response.get("item_id", "")),
                    "audio_start_ms": response.get("audio_start_ms"),
                }
            )
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = str(response.get("transcript", "")).strip()
            self._push(
                {
                    "type": "user_transcript",
                    "text": transcript,
                    "provider_event_type": event_type,
                    "item_id": str(response.get("item_id", "")),
                }
            )
            return
        if event_type == "response.created":
            self._push(
                {
                    "type": "response_started",
                    "response_id": str((response.get("response") or {}).get("id", "")),
                }
            )
            return
        if event_type == "response.audio.delta":
            delta = str(response.get("delta", "")).strip()
            if delta:
                self._push(
                    {
                        "type": "assistant_audio",
                        "audio": delta,
                        "encoding": "pcm_s16le",
                        "sample_rate": 24000,
                        "response_id": str(response.get("response_id", "")),
                    }
                )
            return
        if event_type in {"response.audio_transcript.delta", "response.text.delta"}:
            delta = str(response.get("delta", ""))
            if delta:
                self._push(
                    {
                        "type": "assistant_text",
                        "text": delta,
                        "response_id": str(response.get("response_id", "")),
                    }
                )
            return
        if event_type == "response.done":
            response_data = response.get("response") or {}
            self._push(
                {
                    "type": "turn_complete",
                    "response_id": str(response_data.get("id", "")),
                    "status": str(response_data.get("status", "completed")),
                }
            )
            return
        if event_type == "error":
            error_data = response.get("error")
            if isinstance(error_data, dict):
                message = str(error_data.get("message", "")).strip() or str(response)
            else:
                message = str(error_data or response).strip()
            self._push({"type": "error", "message": message})

    def on_close(self, close_status_code: Any, close_msg: Any) -> None:
        self._push(
            {
                "type": "closed",
                "code": int(close_status_code or 1000),
                "message": str(close_msg or "").strip(),
            }
        )


class VoiceAgentSessionRecorder:
    def __init__(self, repository: VoiceAgentSessionRepository, session_id: str) -> None:
        self.repository = repository
        self.session_id = session_id
        self._turn_index = 0
        self._current_turn_id = ""
        self._pending_user_text = ""
        self._current_assistant_text = ""
        self._started_at = time.perf_counter()
        self._turn_started_at = self._started_at
        self._first_audio_recorded = False

    @property
    def current_turn_id(self) -> str:
        return self._current_turn_id

    @property
    def current_assistant_text(self) -> str:
        return self._current_assistant_text

    def _next_turn_id(self) -> str:
        self._turn_index += 1
        return f"voice-turn-{self._turn_index}"

    async def _call_repository(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            method = getattr(self.repository, method_name)
            return await asyncio.to_thread(method, *args, **kwargs)
        except Exception:
            logger.exception("voice_agent_session_record_failed method=%s session_id=%s", method_name, self.session_id)
            return None

    async def _ensure_turn(self, preferred_turn_id: str = "") -> str:
        clean_preferred = str(preferred_turn_id or "").strip()
        if clean_preferred:
            self._current_turn_id = clean_preferred
        if not self._current_turn_id:
            self._current_turn_id = self._next_turn_id()
        if self._pending_user_text:
            await self._call_repository(
                "upsert_turn",
                self.session_id,
                self._current_turn_id,
                user_text=self._pending_user_text,
            )
        return self._current_turn_id

    async def start(self, payload: dict[str, Any]) -> None:
        await self.record_session_event(
            "session_open",
            source="session",
            payload=dict(payload),
        )

    async def note_user_transcript(self, text: str) -> str:
        clean_text = str(text or "").strip()
        if not clean_text:
            return ""
        self._pending_user_text = clean_text
        self._current_turn_id = self._next_turn_id()
        self._current_assistant_text = ""
        self._turn_started_at = time.perf_counter()
        self._first_audio_recorded = False
        await self._call_repository(
            "upsert_turn",
            self.session_id,
            self._current_turn_id,
            user_text=clean_text,
            completion_status="in_progress",
        )
        await self.record_session_event(
            "user_transcript",
            source="turn",
            turn_id=self._current_turn_id,
            text=clean_text,
            payload={"completed": False, "interrupted": False},
        )
        return self._current_turn_id

    async def note_assistant_text(self, text: str) -> str:
        clean_text = str(text or "")
        if not clean_text.strip():
            return ""
        turn_id = await self._ensure_turn()
        self._current_assistant_text = _merge_memory_text(self._current_assistant_text, clean_text)
        await self._call_repository(
            "upsert_turn",
            self.session_id,
            turn_id,
            assistant_text=clean_text,
        )
        return turn_id

    async def note_assistant_audio(self) -> tuple[str, int | None]:
        turn_id = await self._ensure_turn()
        if self._first_audio_recorded:
            return turn_id, None
        self._first_audio_recorded = True
        elapsed_ms = max(0, int((time.perf_counter() - self._turn_started_at) * 1000))
        await self.record_session_event(
            "assistant_audio_started",
            source="metric",
            turn_id=turn_id,
            payload={"elapsed_ms": elapsed_ms, "first_audio_ms": elapsed_ms},
        )
        return turn_id, elapsed_ms

    async def record_session_event(
        self,
        event_type: str,
        *,
        source: str = "session_event",
        turn_id: str = "",
        text: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self._call_repository(
            "add_session_event",
            self.session_id,
            event_type,
            source=source,
            turn_id=turn_id,
            text=text,
            payload=payload or {},
        )

    async def record_tool_event(self, event_type: str, payload: dict[str, Any]) -> None:
        turn_id = str(payload.get("turn_id", "") or "")
        if (
            turn_id
            and self._current_turn_id
            and turn_id != self._current_turn_id
            and not self._current_assistant_text
        ):
            await self._call_repository(
                "rename_turn",
                self.session_id,
                self._current_turn_id,
                turn_id,
            )
            self._current_turn_id = turn_id
        linked_agent_run: dict[str, Any] | None = None
        artifact = payload.get("artifact")
        effective_turn_id = self._current_turn_id or turn_id
        if (
            event_type == "agent_result"
            and isinstance(artifact, dict)
            and artifact.get("type") == "audio_agent_run"
            and artifact.get("run_id")
            and effective_turn_id
        ):
            linked_agent_run = await self._call_repository(
                "link_agent_run_artifact",
                self.session_id,
                effective_turn_id,
                dict(artifact),
                relation_type="created_by",
                meta={"tool_name": "create_audio_agent_run"},
            )
            if isinstance(linked_agent_run, dict):
                artifact["agent_run_id"] = str(linked_agent_run.get("agent_run_id", ""))
                payload["artifact"] = artifact
        await self._call_repository("add_tool_event", self.session_id, event_type, dict(payload))
        if isinstance(linked_agent_run, dict):
            await self.record_session_event(
                "agent_run_linked",
                source="agent_run",
                turn_id=effective_turn_id,
                text=str(artifact.get("topic", "")) if isinstance(artifact, dict) else "",
                payload={
                    "agent_run_id": str(linked_agent_run.get("agent_run_id", "")),
                    "run_type": str((linked_agent_run.get("run") or {}).get("run_type", "")),
                    "source_run_id": str((linked_agent_run.get("run") or {}).get("source_run_id", "")),
                    "relation_type": str(linked_agent_run.get("relation_type", "created_by")),
                },
            )
        if turn_id and not self._current_turn_id:
            await self._ensure_turn(turn_id)

    async def _finalize_turn(
        self,
        *,
        interrupted: bool,
        memory_payload: dict[str, Any] | None = None,
    ) -> str:
        if not self._pending_user_text and not self._current_turn_id:
            return ""
        turn_id = await self._ensure_turn()
        status = "interrupted" if interrupted else "completed"
        turn = await self._call_repository(
            "upsert_turn",
            self.session_id,
            turn_id,
            memory_payload=memory_payload or {},
            completed=True,
            interrupted=interrupted,
            completion_status=status,
        )
        assistant_text = ""
        if isinstance(turn, dict):
            assistant_text = str(turn.get("assistant_text", ""))
        if not assistant_text:
            assistant_text = self._current_assistant_text
        if assistant_text.strip():
            await self.record_session_event(
                "assistant_response",
                source="turn",
                turn_id=turn_id,
                text=assistant_text,
                payload={"completed": True, "interrupted": interrupted, "status": status},
            )
        if memory_payload:
            await self.record_session_event(
                "memory_commit",
                source="memory",
                turn_id=turn_id,
                payload=dict(memory_payload),
            )
        await self.record_session_event(
            "turn_interrupted" if interrupted else "turn_completed",
            source="turn",
            turn_id=turn_id,
            payload={"interrupted": interrupted, "status": status},
        )
        self._pending_user_text = ""
        self._current_turn_id = ""
        self._current_assistant_text = ""
        self._first_audio_recorded = False
        return turn_id

    async def interrupt_current_turn(self) -> str:
        return await self._finalize_turn(interrupted=True)

    async def complete_turn(self, memory_payload: dict[str, Any] | None = None) -> str:
        return await self._finalize_turn(interrupted=False, memory_payload=memory_payload)

    async def finish(self, *, status: str = "closed") -> None:
        await self._call_repository("finish_session", self.session_id, status=status)


class RealtimeVoiceService:
    def __init__(
        self,
        config: BackendConfig | None = None,
        voice_session_repository: VoiceAgentSessionRepository | None = None,
    ):
        self.config = config or BackendConfig()
        self.voice_session_repository = voice_session_repository

    async def _create_voice_session_recorder(
        self,
        *,
        provider: str,
        model: str,
        voice: str,
    ) -> "VoiceAgentSessionRecorder | None":
        try:
            repository = self.voice_session_repository or VoiceAgentSessionRepository()
            session = await asyncio.to_thread(
                repository.create_session,
                provider=provider,
                model=model,
                voice=voice,
                meta={"transport": "websocket"},
            )
            recorder = VoiceAgentSessionRecorder(repository, str(session["id"]))
            await recorder.start(
                {
                    "provider": provider,
                    "model": model,
                    "voice": voice,
                    "status": "open",
                    "meta": {"transport": "websocket"},
                }
            )
            return recorder
        except Exception:
            logger.exception("voice_agent_session_create_failed provider=%s model=%s", provider, model)
            return None

    @staticmethod
    def _build_realtime_instructions(memory_context: str = "") -> str:
        if not memory_context:
            return BASE_REALTIME_INSTRUCTIONS
        return (
            f"{BASE_REALTIME_INSTRUCTIONS}\n\n"
            "Relevant long-term memories for personalization are provided below. Use them whenever they are relevant. "
            "If the user asks what they said earlier, what the current focus is, or asks you to recall/search memory, "
            "answer from this memory block directly. Do not claim you cannot remember, do not say each conversation is "
            "independent, and do not ignore the memory block when it is relevant. Only avoid quoting the block verbatim "
            "unless the user directly asks.\n"
            f"{memory_context}"
        )

    @staticmethod
    def _build_recall_miss_instructions(user_query: str) -> str:
        return (
            f"{BASE_REALTIME_INSTRUCTIONS}\n\n"
            "The user is explicitly asking you to recall prior conversation memory, but no matching long-term "
            "memory was retrieved for this turn. Do not pretend you remember specific prior facts. "
            "State briefly that you could not retrieve a matching saved memory, then ask the user to restate "
            "the detail if needed.\n"
            f"Current user query: {user_query}"
        )

    @staticmethod
    def _build_google_memory_prefill_turns(memory_context: str) -> list[dict[str, Any]]:
        if not memory_context.strip():
            return []
        return [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Context note for personalization only. These long-term memories may help with "
                            "the user's next turn. Use them only when relevant, and do not mention this note.\n"
                            f"{memory_context}"
                        )
                    }
                ],
            }
        ]

    async def _apply_google_memory_prefill(self, session: Any, memory_context: str) -> None:
        turns = self._build_google_memory_prefill_turns(memory_context)
        if not turns:
            return
        try:
            await session.send_client_content(turns=turns, turn_complete=False)
        except Exception:
            return

    async def _apply_google_tool_result(
        self,
        websocket: WebSocket,
        session: Any,
        result: dict[str, Any],
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        if not prompt.strip():
            return
        payload = {
            "provider": "Google",
            "tool_name": str(result.get("tool_name", "search_web") or "search_web"),
            "query": str(result.get("query", "")),
            "turn_id": str(result.get("turn_id", "")),
            "source_count": int(result.get("source_count", 0) or 0),
            "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_context_injected", payload)
        await self._send_event(
            websocket,
            "tool_context_injected",
            **payload,
        )
        await session.send(input=prompt, end_of_turn=True)

    async def _send_response_gated(
        self,
        websocket: WebSocket,
        *,
        provider: str,
        tool_name: str,
        query: str,
        turn_id: str,
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        payload = {
            "provider": provider,
            "tool_name": tool_name,
            "query": query,
            "turn_id": turn_id,
            "message": "检测到工具请求，已暂停直接回答，等待工具结果。",
        }
        if recorder is not None:
            await recorder.record_tool_event("response_gated", payload)
        await self._send_event(
            websocket,
            "response_gated",
            **payload,
        )

    async def _apply_dashscope_tool_result(
        self,
        websocket: WebSocket,
        conversation: Any,
        result: dict[str, Any],
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        if not prompt.strip():
            return
        payload = {
            "provider": "DashScope",
            "tool_name": str(result.get("tool_name", "search_web") or "search_web"),
            "query": str(result.get("query", "")),
            "turn_id": str(result.get("turn_id", "")),
            "source_count": int(result.get("source_count", 0) or 0),
            "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_context_injected", payload)
        await self._send_event(
            websocket,
            "tool_context_injected",
            **payload,
        )
        conversation.create_response(
            instructions=prompt,
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],  # type: ignore[union-attr]
        )

    def _resolve_google_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("Google", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_GOOGLE_REALTIME_MODEL
        api_key = provider_settings["api_key"].strip()
        base_url = provider_settings["base_url"].strip()
        if _is_google_public_rest_base_url(base_url):
            base_url = ""
        if not api_key:
            raise RuntimeError("Google API Key 未配置，无法启动实时语音会话。")
        if genai is None or types is None:
            raise RuntimeError("google-genai 依赖未安装，无法启动实时语音会话。")
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": resolved_model,
        }

    def _resolve_dashscope_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("DashScope", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_DASHSCOPE_REALTIME_MODEL
        api_key = provider_settings["api_key"].strip()
        base_url = provider_settings["base_url"].strip().lower()
        if not api_key:
            raise RuntimeError("DashScope API Key 未配置，无法启动实时语音会话。")
        if OmniRealtimeConversation is None or MultiModality is None or AudioFormat is None:
            raise RuntimeError("DashScope Omni Realtime 依赖未安装，无法启动实时语音会话。")
        region = "intl" if "dashscope-intl" in base_url else "cn"
        return {
            "api_key": api_key,
            "model": resolved_model,
            "region": region,
        }

    @staticmethod
    def _configure_dashscope_conversation(conversation: Any, *, voice: str, instructions: str) -> None:
        conversation.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],  # type: ignore[union-attr]
            voice=voice,
            input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,  # type: ignore[union-attr]
            output_audio_format=AudioFormat.PCM_24000HZ_MONO_16BIT,  # type: ignore[union-attr]
            enable_input_audio_transcription=True,
            enable_turn_detection=True,
            turn_detection_param={"create_response": False, "interrupt_response": False},
            instructions=instructions,
        )

    @staticmethod
    async def _send_event(websocket: WebSocket, event_type: str, **payload: Any) -> None:
        await websocket.send_json({"type": event_type, **payload})

    async def _begin_interruption(
        self,
        websocket: WebSocket,
        coordinator: InterruptionDecisionCoordinator,
        *,
        provider: str,
        provider_event_type: str,
        recorder: VoiceAgentSessionRecorder | None,
        tool_session: VoiceAgentToolSession,
        supersede_timed_out: bool = False,
    ) -> None:
        interrupted_turn_id = recorder.current_turn_id if recorder is not None else ""
        if not interrupted_turn_id:
            interrupted_turn_id = tool_session.current_turn_id
        payload = coordinator.begin(
            provider=provider,
            interrupted_turn_id=interrupted_turn_id,
            provider_event_type=provider_event_type,
            supersede_timed_out=supersede_timed_out,
        )
        if payload is None:
            return
        if recorder is not None:
            await recorder.record_session_event(
                "interruption_pending",
                source="interruption",
                turn_id=interrupted_turn_id,
                payload=dict(payload),
            )
        await self._send_event(websocket, "interruption_pending", **payload)

    async def _deliver_assistant_output(
        self,
        websocket: WebSocket,
        event: dict[str, Any],
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        record_memory: bool = True,
    ) -> None:
        event_type = str(event.get("type", ""))
        if event_type == "assistant_text":
            text = str(event.get("text", ""))
            if record_memory:
                memory_session.note_assistant_text(text)
            turn_id = await recorder.note_assistant_text(text) if recorder is not None else ""
            await self._send_event(websocket, "assistant_text", text=text, turn_id=turn_id)
            return
        if event_type == "assistant_audio":
            turn_id = ""
            first_audio_ms: int | None = None
            if recorder is not None:
                turn_id, first_audio_ms = await recorder.note_assistant_audio()
            payload = {
                "audio": str(event.get("audio", "")),
                "encoding": str(event.get("encoding", "pcm_s16le")),
                "sample_rate": int(event.get("sample_rate", 24000) or 24000),
                "turn_id": turn_id,
            }
            if first_audio_ms is not None:
                payload["first_audio_ms"] = first_audio_ms
            await self._send_event(websocket, "assistant_audio", **payload)

    async def _emit_assistant_output(
        self,
        websocket: WebSocket,
        coordinator: InterruptionDecisionCoordinator,
        event: dict[str, Any],
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        record_memory: bool = True,
    ) -> None:
        async with coordinator.output_lock:
            if coordinator.pending is not None:
                coordinator.buffer_output(event)
                return
            await self._deliver_assistant_output(
                websocket,
                event,
                memory_session=memory_session,
                recorder=recorder,
                record_memory=record_memory,
            )

    async def _flush_interruption_output(
        self,
        websocket: WebSocket,
        coordinator: InterruptionDecisionCoordinator,
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        record_memory: bool = True,
    ) -> None:
        for event in coordinator.take_buffered_output():
            await self._deliver_assistant_output(
                websocket,
                dict(event),
                memory_session=memory_session,
                recorder=recorder,
                record_memory=record_memory,
            )

    async def _decide_interruption(
        self,
        websocket: WebSocket,
        coordinator: InterruptionDecisionCoordinator,
        text: str,
        *,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
        cancel_provider: Callable[[], Awaitable[None]] | None = None,
        resume_provider: Callable[[], Awaitable[None]] | None = None,
        record_memory: bool = True,
        expected_candidate_id: str = "",
        timeout_resolution: bool = False,
    ) -> tuple[bool, dict[str, Any] | None]:
        async with coordinator.decision_lock:
            if expected_candidate_id and (
                coordinator.pending is None
                or coordinator.pending.candidate_id != expected_candidate_id
            ):
                return True, None
            decision = coordinator.decide(text)
            if decision is None:
                return True, None
            classification = str(decision.get("classification", ""))
            interrupted_turn_id = str(decision.get("interrupted_turn_id", ""))
            is_true_barge_in = classification == InterruptionIntent.TRUE_BARGE_IN.value
            decision["assistant_interrupted"] = is_true_barge_in
            decision["provider_cancel_requested"] = bool(is_true_barge_in and cancel_provider is not None)
            decision["tool_cancelled"] = bool(is_true_barge_in and tool_session.has_active_task)
            decision["stop_latency_ms"] = int(decision.get("decision_latency_ms", 0) or 0)
            decision["timeout_resolution"] = bool(timeout_resolution)
            try:
                if recorder is not None:
                    await recorder.record_session_event(
                        "interruption_decision",
                        source="interruption",
                        turn_id=interrupted_turn_id,
                        text=str(text or "").strip(),
                        payload=dict(decision),
                    )
                async with coordinator.output_lock:
                    if is_true_barge_in:
                        coordinator.discard_buffered_output()
                        coordinator.discard_deferred_terminal()
                        await self._send_event(websocket, "interruption_decision", **decision)
                        if cancel_provider is not None:
                            try:
                                await cancel_provider()
                            except Exception:
                                logger.exception(
                                    "provider_response_cancel_failed provider=%s turn_id=%s",
                                    decision.get("provider", ""),
                                    interrupted_turn_id,
                                )
                        await tool_session.cancel(
                            send_event=self._tool_event_sender(websocket, recorder),
                            reason="true_barge_in",
                        )
                        discard_memory_turn = getattr(memory_session, "discard_turn", None)
                        if callable(discard_memory_turn):
                            discard_memory_turn()
                        if recorder is not None:
                            await recorder.interrupt_current_turn()
                        await self._send_event(
                            websocket,
                            "interrupted",
                            candidate_id=str(decision.get("candidate_id", "")),
                            turn_id=interrupted_turn_id,
                            interrupted=True,
                            stop_latency_ms=decision["stop_latency_ms"],
                        )
                    else:
                        effective_resume_provider = resume_provider or coordinator.resume_provider
                        if effective_resume_provider is not None:
                            await effective_resume_provider()
                        await self._send_event(websocket, "interruption_decision", **decision)
                        await self._flush_interruption_output(
                            websocket,
                            coordinator,
                            memory_session=memory_session,
                            recorder=recorder,
                            record_memory=record_memory,
                        )
                return is_true_barge_in, decision
            finally:
                coordinator.complete_decision(timed_out=timeout_resolution)

    def _tool_event_sender(
        self,
        websocket: WebSocket,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> Callable[[str, dict[str, Any]], Awaitable[None]]:
        async def send_tool_event(event_type: str, payload: dict[str, Any]) -> None:
            if recorder is not None:
                await recorder.record_tool_event(event_type, payload)
            await self._send_event(websocket, event_type, **payload)

        return send_tool_event

    async def _record_client_interruption_stop(
        self,
        recorder: VoiceAgentSessionRecorder | None,
        payload: dict[str, Any],
        *,
        provider: str,
    ) -> None:
        if recorder is None:
            return
        candidate_id = str(payload.get("candidate_id", "") or "").strip()
        turn_id = str(payload.get("turn_id", "") or "").strip()
        raw_latency = payload.get("stop_latency_ms")
        if not candidate_id or not isinstance(raw_latency, (int, float)):
            return
        await recorder.record_session_event(
            "interruption_client_stopped",
            source="metric",
            turn_id=turn_id,
            payload={
                "candidate_id": candidate_id,
                "provider": provider,
                "stop_latency_ms": max(0, min(int(raw_latency), 120_000)),
                "stage": "client_playback_stopped",
            },
        )

    async def _finalize_realtime_turn(
        self,
        websocket: WebSocket,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        *,
        gated: bool = False,
    ) -> tuple[dict[str, Any], str]:
        memory_result = await memory_session.flush_turn()
        completed_turn_id = ""
        if recorder is not None and not gated:
            completed_turn_id = await recorder.complete_turn(memory_result)
        await self._send_event(
            websocket,
            "memory_write",
            attempted_count=int(memory_result.get("attempted_count", 0)),
            saved_count=int(memory_result.get("saved_count", 0)),
            failed_count=int(memory_result.get("failed_count", 0)),
            local_pending_count=int(memory_result.get("local_pending_count", 0)),
            reason=str(memory_result.get("reason", "")),
        )
        if not gated:
            await self._send_event(
                websocket,
                "turn_complete",
                turn_id=completed_turn_id,
                interrupted=False,
            )
        return memory_result, completed_turn_id

    @staticmethod
    def _extract_transcript_text(server_content: Any, candidate_names: tuple[str, ...]) -> str:
        for attr_name in candidate_names:
            if not hasattr(server_content, attr_name):
                continue
            value = getattr(server_content, attr_name)
            if not value:
                continue
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, dict):
                text = value.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
                continue
            if hasattr(value, "text"):
                text = getattr(value, "text", None)
                if isinstance(text, str) and text.strip():
                    return text.strip()
                continue
        return ""

    @staticmethod
    def _has_transcript_field(server_content: Any, candidate_names: tuple[str, ...]) -> bool:
        return any(
            hasattr(server_content, attr_name) and getattr(server_content, attr_name) is not None
            for attr_name in candidate_names
        )

    @staticmethod
    def _build_live_config(voice: str):
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=BASE_REALTIME_INSTRUCTIONS,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=500,
                    silence_duration_ms=1500,
                ),
                activity_handling=types.ActivityHandling.NO_INTERRUPTION,
            ),
        )

    @staticmethod
    def _build_live_translate_config(target_language_code: str, echo_target_language: bool):
        target = (target_language_code or "en").strip() or "en"
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            translation_config=types.TranslationConfig(
                target_language_code=target,
                echo_target_language=bool(echo_target_language),
            ),
        )

    async def _client_to_google_loop(
        self,
        websocket: WebSocket,
        session: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        is_live_translate: bool = False,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        interruption = interruption or InterruptionDecisionCoordinator()
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                break

            text_data = message.get("text")
            if text_data:
                try:
                    payload = json.loads(text_data)
                except Exception:
                    await self._send_event(websocket, "error", message="无效的实时语音消息。")
                    continue
                command_type = str(payload.get("type", "")).strip()
                if command_type == "config":
                    memory_session.configure(payload.get("memory"))
                    await self._send_event(
                        websocket,
                        "memory_config",
                        enabled=bool(memory_session._config.get_service()),
                        scope=memory_session._config.memory_scope,
                        group_id=memory_session._config.group_id,
                    )
                    continue
                if command_type == "text_input":
                    if is_live_translate:
                        await self._send_event(
                            websocket,
                            "error",
                            message="Gemini Live Translate 仅支持实时音频输入，不支持文本输入。",
                        )
                        continue
                    content = str(payload.get("text", "")).strip()
                    if content:
                        await session.send(input=content, end_of_turn=True)
                    continue
                if command_type == "ping":
                    await self._send_event(websocket, "pong")
                    continue
                if command_type == "interruption_client_stopped":
                    await self._record_client_interruption_stop(recorder, payload, provider="Google")
                    continue
                if command_type == "speech_activity_started":
                    if not is_live_translate and (
                        tool_session.has_active_task
                        or (recorder is not None and bool(recorder.current_turn_id))
                    ):
                        await self._begin_interruption(
                            websocket,
                            interruption,
                            provider="Google",
                            provider_event_type="client_vad.speech_started",
                            recorder=recorder,
                            tool_session=tool_session,
                        )
                    continue
                if command_type == "interruption_timeout" and interruption.pending is not None:
                    timeout_candidate_id = str(payload.get("candidate_id", ""))
                    if timeout_candidate_id and timeout_candidate_id != interruption.pending.candidate_id:
                        continue
                    should_process_user, _ = await self._decide_interruption(
                        websocket,
                        interruption,
                        "",
                        memory_session=memory_session,
                        tool_session=tool_session,
                        recorder=recorder,
                        record_memory=not is_live_translate,
                        expected_candidate_id=(timeout_candidate_id or interruption.pending.candidate_id),
                        timeout_resolution=True,
                    )
                    if (
                        not should_process_user
                        and interruption.take_deferred_terminal() is not None
                    ):
                        if not is_live_translate:
                            await self._finalize_realtime_turn(
                                websocket,
                                memory_session,
                                recorder,
                                gated=tool_session.has_active_task,
                            )
                    continue
                if command_type == "stop":
                    async def send_stop_tool_event(event_type: str, payload: dict[str, Any]) -> None:
                        if recorder is not None:
                            await recorder.record_tool_event(event_type, payload)
                        await self._send_event(websocket, event_type, **payload)

                    await tool_session.cancel(
                        send_event=send_stop_tool_event,
                        reason="session_stopped",
                    )
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                await session.send_realtime_input(
                    audio=types.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")
                )

    async def _google_to_client_loop(
        self,
        websocket: WebSocket,
        session: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        is_live_translate: bool = False,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        pending_prefill_context = ""
        gated_tool_turn_id = ""
        interruption = interruption or InterruptionDecisionCoordinator()
        pending_google_user_transcript = ""
        finalized_google_user_transcript = ""
        google_provider_interrupted_early = False
        suppress_interrupted_google_response = False
        consume_next_google_terminal = False
        last_activity_time = time.time()
        live_translate_has_content = False
        pending_google_response_text = ""
        google_output_transcription_seen = False
        google_output_transcription_text = ""
        live_translate_input_finished = False
        live_translate_output_finished = False

        async def finalize_user_transcript_if_needed(clear_transcript: bool = False) -> None:
            nonlocal pending_google_user_transcript, finalized_google_user_transcript, google_provider_interrupted_early
            nonlocal suppress_interrupted_google_response, consume_next_google_terminal
            nonlocal gated_tool_turn_id, pending_prefill_context
            nonlocal last_activity_time

            user_text = pending_google_user_transcript.strip()
            if pending_google_user_transcript == finalized_google_user_transcript:
                if clear_transcript:
                    pending_google_user_transcript = ""
                    finalized_google_user_transcript = ""
                return

            if clear_transcript:
                pending_google_user_transcript = ""
                finalized_google_user_transcript = ""
            else:
                finalized_google_user_transcript = pending_google_user_transcript

            if not user_text:
                return

            if is_live_translate:
                # In live translate mode, VAD and interruption logic are bypassed
                voice_turn_id = ""
                if recorder is not None:
                    voice_turn_id = await recorder.note_user_transcript(user_text)
                await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
                last_activity_time = time.time()
                return

            if interruption.pending is None and (
                google_provider_interrupted_early
                or tool_session.has_active_task
                or (recorder is not None and bool(recorder.current_assistant_text))
            ):
                await self._begin_interruption(
                    websocket,
                    interruption,
                    provider="Google",
                    provider_event_type="input_transcription.without_pending_vad",
                    recorder=recorder,
                    tool_session=tool_session,
                    supersede_timed_out=True,
                )
            had_deferred_terminal = interruption.has_deferred_terminal()

            should_process_user, interruption_decision = await self._decide_interruption(
                websocket,
                interruption,
                user_text,
                memory_session=memory_session,
                tool_session=tool_session,
                recorder=recorder,
                record_memory=not is_live_translate,
            )
            if not should_process_user:
                google_provider_interrupted_early = False
                if interruption.take_deferred_terminal() is not None and not is_live_translate:
                    await self._finalize_realtime_turn(
                        websocket,
                        memory_session,
                        recorder,
                        gated=bool(gated_tool_turn_id),
                    )
                return
            if interruption_decision is not None:
                is_true_barge_in = (
                    interruption_decision.get("classification")
                    == InterruptionIntent.TRUE_BARGE_IN.value
                )
                suppress_interrupted_google_response = bool(
                    is_true_barge_in
                    and not google_provider_interrupted_early
                    and not had_deferred_terminal
                )
                consume_next_google_terminal = bool(
                    not had_deferred_terminal
                    and is_true_barge_in
                    and not google_provider_interrupted_early
                )
                google_provider_interrupted_early = False
            if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
                return
            voice_turn_id = ""
            if not is_live_translate:
                memory_session.note_user_transcript(user_text)
                if recorder is not None:
                    voice_turn_id = await recorder.note_user_transcript(user_text)
                retrieval = await memory_session.retrieve_memory_context()
                memory_context = str(retrieval.get("context", ""))
                memory_count = int(retrieval.get("memories_retrieved", 0))
                local_pending_count = int(retrieval.get("local_pending_count", 0))
                cloud_count = int(retrieval.get("cloud_count", 0))
                if retrieval.get("attempted"):
                    await self._send_event(
                        websocket,
                        "memory_context",
                        memories_retrieved=memory_count,
                        local_pending_count=local_pending_count,
                        cloud_count=cloud_count,
                        attempted=True,
                    )
                if memory_context:
                    logger.info(
                        "voice_memory_inject provider=Google scope=%s count=%s local_pending=%s cloud=%s",
                        memory_session._config.memory_scope,
                        memory_count,
                        local_pending_count,
                        cloud_count,
                    )
                    pending_prefill_context = memory_context
            await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
            if not is_live_translate:
                async def on_google_tool_result(result: dict[str, Any]) -> None:
                    nonlocal gated_tool_turn_id
                    gated_tool_turn_id = ""
                    await self._apply_google_tool_result(websocket, session, result, recorder)

                tool_request = VoiceAgentToolService.extract_tool_request(user_text)
                tool_turn_id = await tool_session.handle_user_transcript(
                    user_text,
                    send_event=send_tool_event,
                    on_result=on_google_tool_result,
                )
                if tool_turn_id:
                    gated_tool_turn_id = tool_turn_id
                    await self._send_response_gated(
                        websocket,
                        provider="Google",
                        tool_name=tool_request.tool_name if tool_request else "voice_tool",
                        query=tool_request.query if tool_request else "",
                        turn_id=tool_turn_id,
                        recorder=recorder,
                    )

        async def send_tool_event(event_type: str, payload: dict[str, Any]) -> None:
            if recorder is not None:
                await recorder.record_tool_event(event_type, payload)
            await self._send_event(websocket, event_type, **payload)

        async def complete_live_translate_turn_if_needed(*, force: bool = False) -> bool:
            nonlocal pending_google_user_transcript, finalized_google_user_transcript
            nonlocal live_translate_has_content, live_translate_input_finished
            nonlocal live_translate_output_finished, last_activity_time

            if not is_live_translate or not live_translate_has_content:
                return False
            if not force and not (live_translate_input_finished and live_translate_output_finished):
                return False

            completed_turn_id = ""
            if recorder is not None:
                completed_turn_id = await recorder.complete_turn({})
            await self._send_event(
                websocket,
                "turn_complete",
                turn_id=completed_turn_id,
                interrupted=False,
            )
            pending_google_user_transcript = ""
            finalized_google_user_transcript = ""
            live_translate_has_content = False
            live_translate_input_finished = False
            live_translate_output_finished = False
            last_activity_time = time.time()
            return True

        monitor_task = None
        if is_live_translate:
            async def monitor_live_translate_inactivity():
                try:
                    while True:
                        await asyncio.sleep(0.5)
                        if live_translate_has_content:
                            now = time.time()
                            if now - last_activity_time >= 2.0:
                                await complete_live_translate_turn_if_needed(force=True)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.exception("Error in live translate inactivity monitor: %s", e)

            monitor_task = asyncio.create_task(monitor_live_translate_inactivity())

        try:
            while True:
                turn = session.receive()
                async for response in turn:
                    audio_data = getattr(response, "data", None)
                    if audio_data:
                        if is_live_translate:
                            last_activity_time = time.time()
                        if not is_live_translate:
                            await finalize_user_transcript_if_needed(clear_transcript=True)
                        if not gated_tool_turn_id and not suppress_interrupted_google_response:
                            await self._emit_assistant_output(
                                websocket,
                                interruption,
                                {
                                    "type": "assistant_audio",
                                    "audio": base64.b64encode(audio_data).decode("ascii"),
                                    "encoding": "pcm_s16le",
                                    "sample_rate": 24000,
                                },
                                memory_session=memory_session,
                                recorder=recorder,
                                record_memory=not is_live_translate,
                            )

                    response_text = getattr(response, "text", None)
                    if response_text:
                        if is_live_translate:
                            last_activity_time = time.time()
                            live_translate_has_content = True
                        if not is_live_translate:
                            await finalize_user_transcript_if_needed(clear_transcript=True)
                        pending_google_response_text, _ = _merge_streaming_text(
                            pending_google_response_text,
                            str(response_text),
                        )

                    server_content = getattr(response, "server_content", None)
                    if not server_content:
                        continue

                    if getattr(server_content, "interrupted", False) and not is_live_translate:
                        await finalize_user_transcript_if_needed(clear_transcript=True)
                        google_provider_interrupted_early = True
                        pending_google_response_text = ""
                        google_output_transcription_seen = False
                        google_output_transcription_text = ""
                        await self._begin_interruption(
                            websocket,
                            interruption,
                            provider="Google",
                            provider_event_type="server_content.interrupted",
                            recorder=recorder,
                            tool_session=tool_session,
                        )

                    user_transcript_fields = ("input_transcription", "input_audio_transcription", "transcription")
                    input_transcription_value: Any = None
                    for transcript_field in user_transcript_fields:
                        if hasattr(server_content, transcript_field):
                            candidate = getattr(server_content, transcript_field)
                            if candidate is not None:
                                input_transcription_value = candidate
                                break
                    user_text_chunk = self._extract_transcript_text(server_content, user_transcript_fields)
                    if user_text_chunk:
                        if is_live_translate:
                            last_activity_time = time.time()
                            live_translate_has_content = True
                        pending_google_user_transcript = _merge_memory_text(
                            pending_google_user_transcript,
                            user_text_chunk,
                        )
                        if InterruptionClassifier.classify_interruption(pending_google_user_transcript) != InterruptionIntent.NOISE_OR_SILENCE:
                            await self._send_event(websocket, "user_transcript", text=pending_google_user_transcript, turn_id="")
                    supports_finished_marker = (
                        input_transcription_value is not None
                        and hasattr(input_transcription_value, "finished")
                    )
                    transcription_finished = bool(
                        getattr(input_transcription_value, "finished", False)
                    ) if supports_finished_marker else input_transcription_value is not None
                    if input_transcription_value is not None and transcription_finished:
                        await finalize_user_transcript_if_needed(clear_transcript=False)

                    if is_live_translate and input_transcription_value is not None and transcription_finished:
                        live_translate_input_finished = True

                    output_transcription_value: Any = None
                    for transcript_field in ("output_transcription", "output_audio_transcription"):
                        if hasattr(server_content, transcript_field):
                            candidate = getattr(server_content, transcript_field)
                            if candidate is not None:
                                output_transcription_value = candidate
                                break
                    assistant_transcript = self._extract_transcript_text(
                        server_content,
                        ("output_transcription", "output_audio_transcription"),
                    )
                    if assistant_transcript:
                        google_output_transcription_seen = True
                        (
                            google_output_transcription_text,
                            assistant_transcript_delta,
                        ) = _merge_streaming_text(
                            google_output_transcription_text, assistant_transcript
                        )
                        if is_live_translate:
                            last_activity_time = time.time()
                            live_translate_has_content = True
                        if (
                            assistant_transcript_delta
                            and not gated_tool_turn_id
                            and not suppress_interrupted_google_response
                        ):
                            await self._emit_assistant_output(
                                websocket,
                                interruption,
                                {"type": "assistant_text", "text": assistant_transcript_delta},
                                memory_session=memory_session,
                                recorder=recorder,
                                record_memory=not is_live_translate,
                            )

                    if (
                        is_live_translate
                        and output_transcription_value is not None
                        and bool(getattr(output_transcription_value, "finished", False))
                    ):
                        live_translate_output_finished = True

                    if is_live_translate:
                        await complete_live_translate_turn_if_needed()

                    if getattr(server_content, "turn_complete", False):
                        if (
                            pending_google_response_text
                            and not google_output_transcription_seen
                            and not gated_tool_turn_id
                            and not suppress_interrupted_google_response
                        ):
                            await self._emit_assistant_output(
                                websocket,
                                interruption,
                                {"type": "assistant_text", "text": pending_google_response_text},
                                memory_session=memory_session,
                                recorder=recorder,
                                record_memory=not is_live_translate,
                            )
                        pending_google_response_text = ""
                        google_output_transcription_seen = False
                        google_output_transcription_text = ""
                        await finalize_user_transcript_if_needed(clear_transcript=True)
                        if is_live_translate:
                            await complete_live_translate_turn_if_needed(force=True)
                            continue
                        if interruption.defer_terminal(
                            {"type": "turn_complete", "provider": "Google"}
                        ):
                            continue
                        if consume_next_google_terminal:
                            consume_next_google_terminal = False
                            suppress_interrupted_google_response = False
                            continue
                        memory_result: dict[str, Any] = {}
                        if not is_live_translate:
                            memory_result = await memory_session.flush_turn()
                            await self._send_event(
                                websocket,
                                "memory_write",
                                attempted_count=int(memory_result.get("attempted_count", 0)),
                                saved_count=int(memory_result.get("saved_count", 0)),
                                failed_count=int(memory_result.get("failed_count", 0)),
                                local_pending_count=int(memory_result.get("local_pending_count", 0)),
                                reason=str(memory_result.get("reason", "")),
                            )
                        if pending_prefill_context and not is_live_translate:
                            await self._apply_google_memory_prefill(session, pending_prefill_context)
                            pending_prefill_context = ""
                        if not gated_tool_turn_id:
                            completed_turn_id = ""
                            if recorder is not None:
                                completed_turn_id = await recorder.complete_turn(memory_result)
                            await self._send_event(
                                websocket,
                                "turn_complete",
                                turn_id=completed_turn_id,
                                interrupted=False,
                            )
        finally:
            if monitor_task is not None:
                monitor_task.cancel()

    async def _client_to_dashscope_loop(
        self,
        websocket: WebSocket,
        conversation: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        interruption = interruption or InterruptionDecisionCoordinator()
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                break

            text_data = message.get("text")
            if text_data:
                try:
                    payload = json.loads(text_data)
                except Exception:
                    await self._send_event(websocket, "error", message="无效的实时语音消息。")
                    continue
                command_type = str(payload.get("type", "")).strip()
                if command_type == "config":
                    memory_session.configure(payload.get("memory"))
                    await self._send_event(
                        websocket,
                        "memory_config",
                        enabled=bool(memory_session._config.get_service()),
                        scope=memory_session._config.memory_scope,
                        group_id=memory_session._config.group_id,
                    )
                    continue
                if command_type == "ping":
                    await self._send_event(websocket, "pong")
                    continue
                if command_type == "interruption_client_stopped":
                    await self._record_client_interruption_stop(recorder, payload, provider="DashScope")
                    continue
                if command_type == "interruption_timeout" and interruption.pending is not None:
                    timeout_candidate_id = str(payload.get("candidate_id", ""))
                    if timeout_candidate_id and timeout_candidate_id != interruption.pending.candidate_id:
                        continue
                    should_process_user, _ = await self._decide_interruption(
                        websocket,
                        interruption,
                        "",
                        memory_session=memory_session,
                        tool_session=tool_session,
                        recorder=recorder,
                        expected_candidate_id=(timeout_candidate_id or interruption.pending.candidate_id),
                        timeout_resolution=True,
                    )
                    if (
                        not should_process_user
                        and interruption.take_deferred_terminal() is not None
                    ):
                        await self._finalize_realtime_turn(
                            websocket,
                            memory_session,
                            recorder,
                            gated=tool_session.has_active_task,
                        )
                    continue
                if command_type == "stop":
                    async def send_stop_tool_event(event_type: str, payload: dict[str, Any]) -> None:
                        if recorder is not None:
                            await recorder.record_tool_event(event_type, payload)
                        await self._send_event(websocket, event_type, **payload)

                    await tool_session.cancel(
                        send_event=send_stop_tool_event,
                        reason="session_stopped",
                    )
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                conversation.append_audio(base64.b64encode(audio_bytes).decode("ascii"))

    async def _dashscope_to_client_loop(
        self,
        websocket: WebSocket,
        queue: asyncio.Queue[dict[str, Any]],
        memory_session: RealtimeMemorySession,
        conversation: Any,
        voice: str,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        async def send_tool_event(event_type: str, payload: dict[str, Any]) -> None:
            if recorder is not None:
                await recorder.record_tool_event(event_type, payload)
            await self._send_event(websocket, event_type, **payload)

        gated_tool_turn_id = ""
        interruption = interruption or InterruptionDecisionCoordinator()
        suppressed_response_ids: set[str] = set()
        while True:
            event = await queue.get()
            event_type = str(event.get("type", "")).strip()
            if event_type == "closed":
                break
            if event_type == "speech_started":
                if interruption.active_response_id or tool_session.has_active_task or (
                    recorder is not None and bool(recorder.current_assistant_text)
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="DashScope",
                        provider_event_type=str(event.get("provider_event_type", "input_audio_buffer.speech_started")),
                        recorder=recorder,
                        tool_session=tool_session,
                    )
                continue
            if event_type == "response_started":
                interruption.active_response_id = (
                    str(event.get("response_id", "")) or interruption.active_response_id or "active"
                )
                continue
            if event_type == "user_transcript":
                user_text = str(event.get("text", ""))
                if interruption.pending is None and (
                    interruption.active_response_id
                    or tool_session.has_active_task
                    or (recorder is not None and bool(recorder.current_assistant_text))
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="DashScope",
                        provider_event_type=str(
                            event.get("provider_event_type", "input_transcription.without_pending_vad")
                        ),
                        recorder=recorder,
                        tool_session=tool_session,
                        supersede_timed_out=True,
                    )
                interrupted_response_id = interruption.active_response_id
                had_deferred_terminal = interruption.has_deferred_terminal()
                async def cancel_dashscope_response() -> None:
                    try:
                        conversation.cancel_response()
                    except Exception:
                        logger.exception("dashscope_response_cancel_failed")

                should_process_user, interruption_decision = await self._decide_interruption(
                    websocket,
                    interruption,
                    user_text,
                    memory_session=memory_session,
                    tool_session=tool_session,
                    recorder=recorder,
                    cancel_provider=cancel_dashscope_response,
                )
                if interruption_decision is not None and (
                    interruption_decision.get("classification") == InterruptionIntent.TRUE_BARGE_IN.value
                ) and interrupted_response_id and not had_deferred_terminal:
                    suppressed_response_ids.add(interrupted_response_id)
                if not should_process_user:
                    if had_deferred_terminal and interruption.take_deferred_terminal() is not None:
                        await self._finalize_realtime_turn(
                            websocket,
                            memory_session,
                            recorder,
                            gated=bool(gated_tool_turn_id),
                        )
                        self._configure_dashscope_conversation(
                            conversation,
                            voice=voice,
                            instructions=self._build_realtime_instructions(),
                        )
                    continue
                if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
                    continue
                memory_session.note_user_transcript(user_text)
                voice_turn_id = ""
                if recorder is not None:
                    voice_turn_id = await recorder.note_user_transcript(user_text)
                retrieval = await memory_session.retrieve_memory_context()
                memory_context = str(retrieval.get("context", ""))
                memory_count = int(retrieval.get("memories_retrieved", 0))
                local_pending_count = int(retrieval.get("local_pending_count", 0))
                cloud_count = int(retrieval.get("cloud_count", 0))
                if retrieval.get("attempted"):
                    await self._send_event(
                        websocket,
                        "memory_context",
                        memories_retrieved=memory_count,
                        local_pending_count=local_pending_count,
                        cloud_count=cloud_count,
                        attempted=True,
                    )
                if memory_context:
                    logger.info(
                        "voice_memory_inject provider=DashScope scope=%s count=%s local_pending=%s cloud=%s",
                        memory_session._config.memory_scope,
                        memory_count,
                        local_pending_count,
                        cloud_count,
                    )
                    self._configure_dashscope_conversation(
                        conversation,
                        voice=voice,
                        instructions=self._build_realtime_instructions(memory_context),
                    )
                elif memory_session.is_forced_recall_query(user_text):
                    logger.info(
                        "voice_memory_inject provider=DashScope scope=%s count=0 forced_recall=true",
                        memory_session._config.memory_scope,
                    )
                    self._configure_dashscope_conversation(
                        conversation,
                        voice=voice,
                        instructions=self._build_recall_miss_instructions(user_text),
                    )
                async def on_dashscope_tool_result(result: dict[str, Any]) -> None:
                    nonlocal gated_tool_turn_id
                    gated_tool_turn_id = ""
                    await self._apply_dashscope_tool_result(websocket, conversation, result, recorder)

                tool_request = VoiceAgentToolService.extract_tool_request(user_text)
                tool_turn_id = await tool_session.handle_user_transcript(
                    user_text,
                    send_event=send_tool_event,
                    on_result=on_dashscope_tool_result,
                )
                if tool_turn_id:
                    gated_tool_turn_id = tool_turn_id
                    try:
                        conversation.cancel_response()
                    except Exception:
                        pass
                    await self._send_response_gated(
                        websocket,
                        provider="DashScope",
                        tool_name=tool_request.tool_name if tool_request else "voice_tool",
                        query=tool_request.query if tool_request else "",
                        turn_id=tool_turn_id,
                        recorder=recorder,
                    )
                else:
                    conversation.create_response()
                await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
                continue
            elif event_type == "assistant_text":
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    continue
                if not gated_tool_turn_id:
                    await self._emit_assistant_output(
                        websocket,
                        interruption,
                        event,
                        memory_session=memory_session,
                        recorder=recorder,
                    )
                continue
            elif event_type == "assistant_audio":
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    continue
                if not gated_tool_turn_id:
                    await self._emit_assistant_output(
                        websocket,
                        interruption,
                        event,
                        memory_session=memory_session,
                        recorder=recorder,
                    )
                continue
            elif event_type == "turn_complete":
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    suppressed_response_ids.discard(response_id)
                    if response_id == interruption.active_response_id:
                        interruption.active_response_id = ""
                    continue
                if interruption.defer_terminal(dict(event)):
                    continue
                if not response_id or response_id == interruption.active_response_id:
                    interruption.active_response_id = ""
                if str(event.get("status", "completed")) in {"cancelled", "canceled", "failed"}:
                    continue
                memory_result = await memory_session.flush_turn()
                completed_turn_id = ""
                if recorder is not None and not gated_tool_turn_id:
                    completed_turn_id = await recorder.complete_turn(memory_result)
                await self._send_event(
                    websocket,
                    "memory_write",
                    attempted_count=int(memory_result.get("attempted_count", 0)),
                    saved_count=int(memory_result.get("saved_count", 0)),
                    failed_count=int(memory_result.get("failed_count", 0)),
                    local_pending_count=int(memory_result.get("local_pending_count", 0)),
                    reason=str(memory_result.get("reason", "")),
                )
                self._configure_dashscope_conversation(
                    conversation,
                    voice=voice,
                    instructions=self._build_realtime_instructions(),
                )
                if not gated_tool_turn_id:
                    await self._send_event(
                        websocket,
                        "turn_complete",
                        turn_id=completed_turn_id,
                        interrupted=False,
                    )
                continue
            if gated_tool_turn_id and event_type in {"assistant_audio", "assistant_text", "turn_complete"}:
                continue
            await websocket.send_json(event)
            if event_type == "error":
                break

    # ── OpenAI Realtime ──────────────────────────────────────────────

    def _resolve_openai_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("OpenAI", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_OPENAI_REALTIME_MODEL
        api_key = provider_settings["api_key"].strip()
        if not api_key:
            raise RuntimeError("OpenAI API Key 未配置，无法启动实时语音会话。")
        return {
            "api_key": api_key,
            "model": resolved_model,
        }

    async def _apply_openai_tool_result(
        self,
        openai_ws: Any,
        result: dict[str, Any],
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        if not prompt.strip():
            return
        payload = {
            "provider": "OpenAI",
            "tool_name": str(result.get("tool_name", "search_web") or "search_web"),
            "query": str(result.get("query", "")),
            "turn_id": str(result.get("turn_id", "")),
            "source_count": int(result.get("source_count", 0) or 0),
            "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_context_injected", payload)
        await openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        }))
        await openai_ws.send(json.dumps({"type": "response.create"}))

    async def _client_to_openai_loop(
        self,
        websocket: WebSocket,
        openai_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        interruption = interruption or InterruptionDecisionCoordinator()
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                break

            text_data = message.get("text")
            if text_data:
                try:
                    payload = json.loads(text_data)
                except Exception:
                    await self._send_event(websocket, "error", message="无效的实时语音消息。")
                    continue
                command_type = str(payload.get("type", "")).strip()
                if command_type == "config":
                    memory_session.configure(payload.get("memory"))
                    await self._send_event(
                        websocket,
                        "memory_config",
                        enabled=bool(memory_session._config.get_service()),
                        scope=memory_session._config.memory_scope,
                        group_id=memory_session._config.group_id,
                    )
                    continue
                if command_type == "text_input":
                    content = str(payload.get("text", "")).strip()
                    if content:
                        await openai_ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": content}],
                            },
                        }))
                        await openai_ws.send(json.dumps({"type": "response.create"}))
                    continue
                if command_type == "ping":
                    await self._send_event(websocket, "pong")
                    continue
                if command_type == "interruption_client_stopped":
                    await self._record_client_interruption_stop(recorder, payload, provider="OpenAI")
                    continue
                if command_type == "interruption_timeout" and interruption.pending is not None:
                    timeout_candidate_id = str(payload.get("candidate_id", ""))
                    if timeout_candidate_id and timeout_candidate_id != interruption.pending.candidate_id:
                        continue
                    should_process_user, _ = await self._decide_interruption(
                        websocket,
                        interruption,
                        "",
                        memory_session=memory_session,
                        tool_session=tool_session,
                        recorder=recorder,
                        expected_candidate_id=(timeout_candidate_id or interruption.pending.candidate_id),
                        timeout_resolution=True,
                    )
                    if (
                        not should_process_user
                        and interruption.take_deferred_terminal() is not None
                    ):
                        await self._finalize_realtime_turn(
                            websocket,
                            memory_session,
                            recorder,
                            gated=tool_session.has_active_task,
                        )
                    continue
                if command_type == "stop":
                    async def send_stop_tool_event(event_type: str, payload: dict[str, Any]) -> None:
                        if recorder is not None:
                            await recorder.record_tool_event(event_type, payload)
                        await self._send_event(websocket, event_type, **payload)

                    await tool_session.cancel(
                        send_event=send_stop_tool_event,
                        reason="session_stopped",
                    )
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                await openai_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_bytes).decode("ascii"),
                }))

    async def _openai_to_client_loop(
        self,
        websocket: WebSocket,
        openai_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        async def send_tool_event(event_type: str, payload: dict[str, Any]) -> None:
            if recorder is not None:
                await recorder.record_tool_event(event_type, payload)
            await self._send_event(websocket, event_type, **payload)

        gated_tool_turn_id = ""
        pending_prefill_context = ""
        interruption = interruption or InterruptionDecisionCoordinator()
        suppressed_response_ids: set[str] = set()

        async for raw_message in openai_ws:
            try:
                event = json.loads(raw_message) if isinstance(raw_message, str) else json.loads(str(raw_message))
            except Exception:
                continue

            event_type = str(event.get("type", "")).strip()

            # Session created
            if event_type == "session.created":
                session_info = event.get("session", {})
                await self._send_event(
                    websocket,
                    "session_open",
                    provider="OpenAI",
                    model=session_info.get("model", ""),
                    voice=session_info.get("voice", DEFAULT_OPENAI_REALTIME_VOICE),
                    session_id=recorder.session_id if recorder is not None else session_info.get("id", ""),
                )
                continue

            # Session updated confirmation
            if event_type == "session.updated":
                continue

            if event_type == "response.created":
                interruption.active_response_id = str((event.get("response") or {}).get("id", ""))
                continue

            # Input audio transcription completed (user speech)
            if event_type == "conversation.item.input_audio_transcription.completed":
                user_text = str(event.get("transcript", "")).strip()
                item_id = str(event.get("item_id", ""))
                if interruption.pending is None and (
                    interruption.active_response_id
                    or tool_session.has_active_task
                    or (recorder is not None and bool(recorder.current_assistant_text))
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="OpenAI",
                        provider_event_type="conversation.item.input_audio_transcription.completed_without_vad",
                        recorder=recorder,
                        tool_session=tool_session,
                        supersede_timed_out=True,
                    )
                interrupted_response_id = interruption.active_response_id
                had_deferred_terminal = interruption.has_deferred_terminal()

                async def cancel_openai_response() -> None:
                    payload: dict[str, Any] = {"type": "response.cancel"}
                    if interrupted_response_id:
                        payload["response_id"] = interrupted_response_id
                    await openai_ws.send(json.dumps(payload))

                async def discard_openai_candidate() -> None:
                    if item_id:
                        await openai_ws.send(
                            json.dumps({"type": "conversation.item.delete", "item_id": item_id})
                        )

                should_process_user, interruption_decision = await self._decide_interruption(
                    websocket,
                    interruption,
                    user_text,
                    memory_session=memory_session,
                    tool_session=tool_session,
                    recorder=recorder,
                    cancel_provider=cancel_openai_response,
                    resume_provider=discard_openai_candidate,
                )
                if interruption_decision is not None and (
                    interruption_decision.get("classification") == InterruptionIntent.TRUE_BARGE_IN.value
                ) and interrupted_response_id and not had_deferred_terminal:
                    suppressed_response_ids.add(interrupted_response_id)
                if not should_process_user:
                    if interruption_decision is None:
                        await discard_openai_candidate()
                    if had_deferred_terminal and interruption.take_deferred_terminal() is not None:
                        await self._finalize_realtime_turn(
                            websocket,
                            memory_session,
                            recorder,
                            gated=bool(gated_tool_turn_id),
                        )
                    continue
                if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
                    await discard_openai_candidate()
                    continue
                if user_text:
                    memory_session.note_user_transcript(user_text)
                    voice_turn_id = ""
                    if recorder is not None:
                        voice_turn_id = await recorder.note_user_transcript(user_text)
                    retrieval = await memory_session.retrieve_memory_context()
                    memory_context = str(retrieval.get("context", ""))
                    memory_count = int(retrieval.get("memories_retrieved", 0))
                    local_pending_count = int(retrieval.get("local_pending_count", 0))
                    cloud_count = int(retrieval.get("cloud_count", 0))
                    if retrieval.get("attempted"):
                        await self._send_event(
                            websocket,
                            "memory_context",
                            memories_retrieved=memory_count,
                            local_pending_count=local_pending_count,
                            cloud_count=cloud_count,
                            attempted=True,
                        )
                    if memory_context:
                        logger.info(
                            "voice_memory_inject provider=OpenAI scope=%s count=%s local_pending=%s cloud=%s",
                            memory_session._config.memory_scope,
                            memory_count,
                            local_pending_count,
                            cloud_count,
                        )
                        pending_prefill_context = memory_context
                    await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
                    # Tool detection
                    async def on_openai_tool_result(result: dict[str, Any]) -> None:
                        nonlocal gated_tool_turn_id
                        gated_tool_turn_id = ""
                        await self._apply_openai_tool_result(openai_ws, result, recorder)

                    tool_request = VoiceAgentToolService.extract_tool_request(user_text)
                    tool_turn_id = await tool_session.handle_user_transcript(
                        user_text,
                        send_event=send_tool_event,
                        on_result=on_openai_tool_result,
                    )
                    if tool_turn_id:
                        gated_tool_turn_id = tool_turn_id
                        await self._send_response_gated(
                            websocket,
                            provider="OpenAI",
                            tool_name=tool_request.tool_name if tool_request else "voice_tool",
                            query=tool_request.query if tool_request else "",
                            turn_id=tool_turn_id,
                            recorder=recorder,
                        )
                    else:
                        await openai_ws.send(json.dumps({"type": "response.create"}))
                continue

            # Speech started (VAD detected user speaking → interruption)
            if event_type == "input_audio_buffer.speech_started":
                if interruption.active_response_id or tool_session.has_active_task or (
                    recorder is not None and bool(recorder.current_assistant_text)
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="OpenAI",
                        provider_event_type=event_type,
                        recorder=recorder,
                        tool_session=tool_session,
                    )
                continue

            # Assistant audio delta
            if event_type == "response.audio.delta":
                audio_b64 = event.get("delta", "")
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    continue
                if audio_b64 and not gated_tool_turn_id:
                    await self._emit_assistant_output(
                        websocket,
                        interruption,
                        {
                            "type": "assistant_audio",
                            "audio": audio_b64,
                            "encoding": "pcm_s16le",
                            "sample_rate": 24000,
                        },
                        memory_session=memory_session,
                        recorder=recorder,
                    )
                continue

            # Assistant audio transcript delta
            if event_type == "response.audio_transcript.delta":
                text_delta = event.get("delta", "")
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    continue
                if text_delta and not gated_tool_turn_id:
                    await self._emit_assistant_output(
                        websocket,
                        interruption,
                        {"type": "assistant_text", "text": str(text_delta)},
                        memory_session=memory_session,
                        recorder=recorder,
                    )
                continue

            # Response done (turn complete)
            if event_type == "response.done":
                response_data = event.get("response") or {}
                response_status = str(response_data.get("status", "completed"))
                response_id = str(response_data.get("id", ""))
                if response_id in suppressed_response_ids:
                    suppressed_response_ids.discard(response_id)
                    if response_id == interruption.active_response_id:
                        interruption.active_response_id = ""
                    continue
                if interruption.defer_terminal(dict(event)):
                    continue
                if response_id and response_id == interruption.active_response_id:
                    interruption.active_response_id = ""
                if response_status in {"cancelled", "canceled", "failed"}:
                    continue
                if pending_prefill_context:
                    # Inject memory context as a hidden user message
                    await openai_ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{
                                "type": "input_text",
                                "text": (
                                    "Context note for personalization only. These long-term memories may help with "
                                    "the user's next turn. Use them only when relevant, and do not mention this note.\n"
                                    f"{pending_prefill_context}"
                                ),
                            }],
                        },
                    }))
                    pending_prefill_context = ""
                memory_result = await memory_session.flush_turn()
                completed_turn_id = ""
                if recorder is not None and not gated_tool_turn_id:
                    completed_turn_id = await recorder.complete_turn(memory_result)
                await self._send_event(
                    websocket,
                    "memory_write",
                    attempted_count=int(memory_result.get("attempted_count", 0)),
                    saved_count=int(memory_result.get("saved_count", 0)),
                    failed_count=int(memory_result.get("failed_count", 0)),
                    local_pending_count=int(memory_result.get("local_pending_count", 0)),
                    reason=str(memory_result.get("reason", "")),
                )
                if not gated_tool_turn_id:
                    await self._send_event(
                        websocket,
                        "turn_complete",
                        turn_id=completed_turn_id,
                        interrupted=False,
                    )
                continue

            # Error events
            if event_type == "error":
                error_msg = event.get("error", {}).get("message", "") or str(event.get("message", ""))
                await self._send_event(websocket, "error", message=f"OpenAI Realtime: {error_msg}")
                break

    async def stream_openai_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_OPENAI_REALTIME_VOICE,
    ) -> None:
        settings = self._resolve_openai_settings(model)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()
        recorder = await self._create_voice_session_recorder(
            provider="OpenAI",
            model=settings["model"],
            voice=voice,
        )

        ws_url = f"wss://api.openai.com/v1/realtime?model={settings['model']}"
        extra_headers = {
            "Authorization": f"Bearer {settings['api_key']}",
        }

        try:
            async with websockets.connect(
                ws_url,
                additional_headers=extra_headers,
                max_size=2**24,
            ) as openai_ws:
                # Configure session
                await openai_ws.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "modalities": ["text", "audio"],
                        "voice": voice,
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "input_audio_transcription": {"model": "whisper-1"},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                            "create_response": False,
                            "interrupt_response": False,
                        },
                        "instructions": self._build_realtime_instructions(),
                    },
                }))

                interruption = InterruptionDecisionCoordinator()
                send_task = asyncio.create_task(
                    self._client_to_openai_loop(
                        websocket, openai_ws, memory_session, tool_session, recorder, interruption
                    )
                )
                receive_task = asyncio.create_task(
                    self._openai_to_client_loop(
                        websocket, openai_ws, memory_session, tool_session, recorder, interruption
                    )
                )
                done, pending = await asyncio.wait(
                    {send_task, receive_task},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except WebSocketDisconnect:
            return
        except Exception as e:
            print(f"DEBUG: OpenAI Realtime Session Error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            await self._send_event(websocket, "error", message=f"OpenAI 实时会话启动失败: {str(e)}")
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain()
            if recorder is not None:
                await recorder.finish()

    async def stream_google_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_GOOGLE_REALTIME_VOICE,
        target_language_code: str = "en",
        echo_target_language: bool = True,
    ) -> None:
        settings = self._resolve_google_settings(model)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()
        recorder = await self._create_voice_session_recorder(
            provider="Google",
            model=settings["model"],
            voice=voice,
        )
        http_options: dict[str, str] = {"api_version": "v1beta"}
        if settings["base_url"]:
            http_options["base_url"] = settings["base_url"]

        client = genai.Client(api_key=settings["api_key"], http_options=http_options)
        is_live_translate = _is_google_live_translate_model(settings["model"])
        live_config = (
            self._build_live_translate_config(target_language_code, echo_target_language)
            if is_live_translate
            else self._build_live_config(voice)
        )

        try:
            async with client.aio.live.connect(model=settings["model"], config=live_config) as session:
                await self._send_event(
                    websocket,
                    "session_open",
                    provider="Google",
                    model=settings["model"],
                    voice=voice,
                    session_id=recorder.session_id if recorder is not None else "",
                    mode="live_translate" if is_live_translate else "realtime_chat",
                    target_language_code=target_language_code if is_live_translate else "",
                    echo_target_language=echo_target_language if is_live_translate else False,
                )
                interruption = InterruptionDecisionCoordinator()
                send_task = asyncio.create_task(
                    self._client_to_google_loop(
                        websocket,
                        session,
                        memory_session,
                        tool_session,
                        recorder,
                        is_live_translate,
                        interruption,
                    )
                )
                receive_task = asyncio.create_task(
                    self._google_to_client_loop(
                        websocket,
                        session,
                        memory_session,
                        tool_session,
                        recorder,
                        is_live_translate,
                        interruption,
                    )
                )
                done, pending = await asyncio.wait(
                    {send_task, receive_task},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except WebSocketDisconnect:
            return
        except Exception as e:
            print(f"DEBUG: Google Realtime Session Error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            await self._send_event(websocket, "error", message=f"Google 实时会话启动失败: {str(e)}")
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain()
            if recorder is not None:
                await recorder.finish()

    @staticmethod
    def _is_qwen_audio_model(model: str | None) -> bool:
        """Return True when *model* is a Qwen-Audio realtime model (supports native function calling)."""
        return bool(model and "qwen-audio" in str(model).lower())

    @staticmethod
    def _build_qwen_audio_instructions(memory_context: str = "") -> str:
        if not memory_context:
            return QWEN_AUDIO_REALTIME_INSTRUCTIONS
        return (
            f"{QWEN_AUDIO_REALTIME_INSTRUCTIONS}\n\n"
            "以下是系统检索到的长期记忆，用于个性化回复。当相关时请参考这些记忆，"
            "但不要逐字引用，除非用户直接询问。\n"
            f"{memory_context}"
        )

    async def _client_to_qwen_audio_loop(
        self,
        websocket: WebSocket,
        dash_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        interruption = interruption or InterruptionDecisionCoordinator()
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                break

            text_data = message.get("text")
            if text_data:
                try:
                    payload = json.loads(text_data)
                except Exception:
                    await self._send_event(websocket, "error", message="无效的实时语音消息。")
                    continue
                command_type = str(payload.get("type", "")).strip()
                if command_type == "config":
                    memory_session.configure(payload.get("memory"))
                    await self._send_event(
                        websocket,
                        "memory_config",
                        enabled=bool(memory_session._config.get_service()),
                        scope=memory_session._config.memory_scope,
                        group_id=memory_session._config.group_id,
                    )
                    continue
                if command_type == "ping":
                    await self._send_event(websocket, "pong")
                    continue
                if command_type == "interruption_client_stopped":
                    await self._record_client_interruption_stop(recorder, payload, provider="DashScope")
                    continue
                if command_type == "interruption_timeout" and interruption.pending is not None:
                    timeout_candidate_id = str(payload.get("candidate_id", ""))
                    if timeout_candidate_id and timeout_candidate_id != interruption.pending.candidate_id:
                        continue
                    should_process_user, _ = await self._decide_interruption(
                        websocket,
                        interruption,
                        "",
                        memory_session=memory_session,
                        tool_session=tool_session,
                        recorder=recorder,
                        expected_candidate_id=(timeout_candidate_id or interruption.pending.candidate_id),
                        timeout_resolution=True,
                    )
                    if (
                        not should_process_user
                        and interruption.take_deferred_terminal() is not None
                    ):
                        await self._finalize_realtime_turn(
                            websocket,
                            memory_session,
                            recorder,
                            gated=tool_session.has_active_task,
                        )
                    continue
                if command_type == "stop":
                    async def send_stop_tool_event(event_type: str, payload: dict[str, Any]) -> None:
                        if recorder is not None:
                            await recorder.record_tool_event(event_type, payload)
                        await self._send_event(websocket, event_type, **payload)

                    await tool_session.cancel(
                        send_event=send_stop_tool_event,
                        reason="session_stopped",
                    )
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                await dash_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_bytes).decode("ascii"),
                }))

    async def _qwen_audio_to_client_loop(
        self,
        websocket: WebSocket,
        dash_ws: Any,
        memory_session: RealtimeMemorySession,
        voice: str,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        async def send_tool_event(event_type: str, payload: dict[str, Any]) -> None:
            if recorder is not None:
                await recorder.record_tool_event(event_type, payload)
            await self._send_event(websocket, event_type, **payload)

        gated_tool_turn_id = ""
        # Track ALL pending native function_call ids in the current turn. A turn may
        # contain multiple parallel function_calls; the follow-up response.create must
        # only be sent after every call's function_call_output has been written back.
        pending_native_fc_call_ids: set[str] = set()
        # Marks whether the current response contains function_call(s); such a response
        # is an intermediate round and must NOT finalize the turn on response.done.
        current_response_has_function_call = False
        interruption = interruption or InterruptionDecisionCoordinator()
        suppressed_response_ids: set[str] = set()
        while True:
            try:
                raw = await asyncio.wait_for(dash_ws.recv(), timeout=300)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

            try:
                event = json.loads(raw) if isinstance(raw, str) else json.loads(str(raw))
            except Exception:
                continue

            event_type = str(event.get("type", "")).strip()
            if event_type == "closed":
                break
            if event_type in {"session.created", "session.updated"}:
                continue
            if event_type == "input_audio_buffer.speech_started":
                if interruption.active_response_id or tool_session.has_active_task or (
                    recorder is not None and bool(recorder.current_assistant_text)
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="DashScope",
                        provider_event_type=str(event.get("type", "input_audio_buffer.speech_started")),
                        recorder=recorder,
                        tool_session=tool_session,
                    )
                continue
            if event_type == "response.created":
                interruption.active_response_id = (
                    str((event.get("response") or {}).get("id", "")) or interruption.active_response_id or "active"
                )
                # New response round begins; reset the per-response function_call marker.
                current_response_has_function_call = False
                continue
            if event_type == "conversation.item.input_audio_transcription.completed":
                user_text = str(event.get("transcript", "")).strip()
                if interruption.pending is None and (
                    interruption.active_response_id
                    or tool_session.has_active_task
                    or (recorder is not None and bool(recorder.current_assistant_text))
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="DashScope",
                        provider_event_type=str(event.get("type", "input_transcription.without_pending_vad")),
                        recorder=recorder,
                        tool_session=tool_session,
                        supersede_timed_out=True,
                    )
                interrupted_response_id = interruption.active_response_id
                had_deferred_terminal = interruption.has_deferred_terminal()
                async def cancel_dashscope_response() -> None:
                    try:
                        await dash_ws.send(json.dumps({"type": "response.cancel"}))
                    except Exception:
                        logger.exception("qwen_audio_response_cancel_failed")

                should_process_user, interruption_decision = await self._decide_interruption(
                    websocket,
                    interruption,
                    user_text,
                    memory_session=memory_session,
                    tool_session=tool_session,
                    recorder=recorder,
                    cancel_provider=cancel_dashscope_response,
                )
                if interruption_decision is not None and (
                    interruption_decision.get("classification") == InterruptionIntent.TRUE_BARGE_IN.value
                ) and interrupted_response_id and not had_deferred_terminal:
                    suppressed_response_ids.add(interrupted_response_id)
                if not should_process_user:
                    if had_deferred_terminal and interruption.take_deferred_terminal() is not None:
                        await self._finalize_realtime_turn(
                            websocket, memory_session, recorder, gated=bool(gated_tool_turn_id),
                        )
                        await dash_ws.send(json.dumps({
                            "type": "session.update",
                            "session": {"instructions": self._build_qwen_audio_instructions()},
                        }))
                    continue
                if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
                    continue
                memory_session.note_user_transcript(user_text)
                voice_turn_id = ""
                if recorder is not None:
                    voice_turn_id = await recorder.note_user_transcript(user_text)
                retrieval = await memory_session.retrieve_memory_context()
                memory_context = str(retrieval.get("context", ""))
                memory_count = int(retrieval.get("memories_retrieved", 0))
                local_pending_count = int(retrieval.get("local_pending_count", 0))
                cloud_count = int(retrieval.get("cloud_count", 0))
                if retrieval.get("attempted"):
                    await self._send_event(
                        websocket, "memory_context",
                        memories_retrieved=memory_count,
                        local_pending_count=local_pending_count,
                        cloud_count=cloud_count,
                        attempted=True,
                    )
                base_instructions = self._build_qwen_audio_instructions(memory_context)
                if not memory_context and memory_session.is_forced_recall_query(user_text):
                    base_instructions = self._build_recall_miss_instructions(user_text)
                async def on_qwen_audio_tool_result(result: dict[str, Any]) -> None:
                    nonlocal gated_tool_turn_id
                    gated_tool_turn_id = ""
                    await self._apply_qwen_audio_tool_result(websocket, dash_ws, result, recorder)

                # Native function-call gating: if any function_call is still being
                # processed, skip backend regex extraction so we don't double-trigger.
                if pending_native_fc_call_ids:
                    await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
                    continue

                tool_request = VoiceAgentToolService.extract_tool_request(user_text)
                tool_turn_id = await tool_session.handle_user_transcript(
                    user_text,
                    send_event=send_tool_event,
                    on_result=on_qwen_audio_tool_result,
                )
                if tool_turn_id:
                    gated_tool_turn_id = tool_turn_id
                    try:
                        await dash_ws.send(json.dumps({"type": "response.cancel"}))
                    except Exception:
                        pass
                    await self._send_response_gated(
                        websocket, provider="DashScope",
                        tool_name=tool_request.tool_name if tool_request else "voice_tool",
                        query=tool_request.query if tool_request else "",
                        turn_id=tool_turn_id, recorder=recorder,
                    )
                else:
                    await dash_ws.send(json.dumps({"type": "response.create"}))
                await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
                continue
            if event_type == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    call_id = str(item.get("call_id", ""))
                    if call_id:
                        pending_native_fc_call_ids.add(call_id)
                    current_response_has_function_call = True
                continue
            if event_type == "response.function_call_arguments.done":
                call_id = str(event.get("call_id", ""))
                name = str(event.get("name", ""))
                arguments_str = str(event.get("arguments", "{}"))
                # Execute the tool and write back its function_call_output (without
                # triggering response.create yet). Only when every pending call in this
                # turn has produced its output do we send a single response.create.
                await self._handle_qwen_audio_function_call(
                    websocket, dash_ws, call_id, name, arguments_str,
                    tool_session=tool_session,
                    recorder=recorder,
                    send_tool_event=send_tool_event,
                    trigger_response=False,
                )
                pending_native_fc_call_ids.discard(call_id)
                if not pending_native_fc_call_ids:
                    await dash_ws.send(json.dumps({"type": "response.create"}))
                continue
            if event_type == "response.audio.delta":
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    continue
                if not gated_tool_turn_id:
                    await self._emit_assistant_output(
                        websocket, interruption, {
                            "type": "assistant_audio",
                            "audio": str(event.get("delta", "")),
                            "response_id": response_id,
                        },
                        memory_session=memory_session, recorder=recorder,
                    )
                continue
            if event_type in {"response.audio_transcript.delta", "response.text.delta"}:
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    continue
                delta = str(event.get("delta", ""))
                if not gated_tool_turn_id and delta:
                    await self._emit_assistant_output(
                        websocket, interruption, {
                            "type": "assistant_text",
                            "text": delta,
                            "response_id": response_id,
                        },
                        memory_session=memory_session, recorder=recorder,
                    )
                continue
            if event_type == "response.done":
                response_data = event.get("response") or {}
                response_id = str(response_data.get("id", ""))
                if response_id in suppressed_response_ids:
                    suppressed_response_ids.discard(response_id)
                    if response_id == interruption.active_response_id:
                        interruption.active_response_id = ""
                    continue
                if interruption.defer_terminal({"type": "turn_complete", "response_id": response_id,
                                                 "status": str(response_data.get("status", "completed"))}):
                    continue
                if not response_id or response_id == interruption.active_response_id:
                    interruption.active_response_id = ""
                # A response that carried function_call(s) is an intermediate round:
                # the turn continues after we send response.create, so do NOT finalize
                # (flush memory / emit turn_complete) here. Reset the flag and stop.
                if current_response_has_function_call:
                    current_response_has_function_call = False
                    pending_native_fc_call_ids.clear()
                    continue
                if str(response_data.get("status", "completed")) in {"cancelled", "canceled", "failed"}:
                    continue
                memory_result = await memory_session.flush_turn()
                completed_turn_id = ""
                if recorder is not None and not gated_tool_turn_id:
                    completed_turn_id = await recorder.complete_turn(memory_result)
                await self._send_event(
                    websocket, "memory_write",
                    attempted_count=int(memory_result.get("attempted_count", 0)),
                    saved_count=int(memory_result.get("saved_count", 0)),
                    failed_count=int(memory_result.get("failed_count", 0)),
                    local_pending_count=int(memory_result.get("local_pending_count", 0)),
                    reason=str(memory_result.get("reason", "")),
                )
                await dash_ws.send(json.dumps({
                    "type": "session.update",
                    "session": {"instructions": self._build_qwen_audio_instructions()},
                }))
                if not gated_tool_turn_id:
                    await self._send_event(
                        websocket, "turn_complete",
                        turn_id=completed_turn_id, interrupted=False,
                    )
                continue
            if gated_tool_turn_id and event_type in {"assistant_audio", "assistant_text", "turn_complete"}:
                continue
            if event_type == "error":
                error_data = event.get("error")
                if isinstance(error_data, dict):
                    message = str(error_data.get("message", "")).strip() or str(event)
                else:
                    message = str(error_data or event).strip()
                await self._send_event(websocket, "error", message=f"DashScope: {message}")
                break

    @staticmethod
    async def _send_qwen_audio_function_call_output(dash_ws: Any, call_id: str, output: str) -> None:
        """Write a function_call_output conversation item back to the model."""
        await dash_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id, "output": output},
        }))

    async def _handle_qwen_audio_function_call(
        self,
        websocket: WebSocket,
        dash_ws: Any,
        call_id: str,
        name: str,
        arguments_str: str,
        *,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        send_tool_event: Any = None,
        trigger_response: bool = True,
    ) -> None:
        """Handle a native function_call from Qwen-Audio: execute tool and write back its output.

        When *trigger_response* is True (single-call / standalone usage), a follow-up
        ``response.create`` is sent immediately. When False, the caller is responsible
        for sending ``response.create`` once every pending call in the turn has been
        resolved (required for turns that contain multiple parallel function_calls).
        """
        import traceback as tb_module

        logger.info("qwen_audio_function_call call_id=%s name=%s args=%s", call_id, name, arguments_str)
        try:
            arguments = json.loads(arguments_str) if arguments_str else {}
        except json.JSONDecodeError:
            arguments = {}

        # Map function name → query text and tool_name for VoiceAgentToolService
        name_lower = name.lower().strip()
        if name_lower == "search_web":
            query = str(arguments.get("query", "")).strip()
            tool_name = "search_web"
        elif name_lower == "translate_text":
            text = str(arguments.get("text", "")).strip()
            target = str(arguments.get("target_language", "英文")).strip()
            query = f"{text}\n目标语言: {target}"
            tool_name = "translate_text"
        elif name_lower == "summarize_transcript":
            content = str(arguments.get("content", "")).strip()
            query = content
            tool_name = "summarize_transcript"
        elif name_lower == "synthesize_tts":
            content = str(arguments.get("content", "")).strip()
            query = content
            tool_name = "synthesize_tts"
        elif name_lower == "create_audio_agent_run":
            topic = str(arguments.get("topic", "")).strip()
            query = topic
            tool_name = "create_audio_agent_run"
        else:
            await self._send_qwen_audio_function_call_output(
                dash_ws, call_id, json.dumps({"error": f"未知工具: {name}"})
            )
            if trigger_response:
                await dash_ws.send(json.dumps({"type": "response.create"}))
            return

        if not query:
            await self._send_qwen_audio_function_call_output(
                dash_ws, call_id, json.dumps({"error": "缺少必要的查询参数"})
            )
            if trigger_response:
                await dash_ws.send(json.dumps({"type": "response.create"}))
            return

        request = VoiceToolRequest(tool_name=tool_name, query=query, display_name=tool_name, requires_confirmation=False)
        send_event_fn = send_tool_event if send_tool_event is not None else (
            lambda et, p: self._send_event(websocket, et, **p)
        )

        # Execute the tool and write back its output. The follow-up response.create is
        # deferred to the caller unless trigger_response=True.
        try:
            result = await tool_session.service.run_tool(
                request, send_event=send_event_fn, turn_id=f"native-fc-{call_id[:12]}",
            )
        except Exception as exc:
            tb_module.print_exc()
            await self._send_qwen_audio_function_call_output(
                dash_ws, call_id, json.dumps({"error": str(exc)})
            )
            if trigger_response:
                await dash_ws.send(json.dumps({"type": "response.create"}))
            return

        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        output = prompt if prompt.strip() else json.dumps({"status": "completed", "summary": str(result.get("answer", ""))})
        await self._send_qwen_audio_function_call_output(dash_ws, call_id, output)
        if trigger_response:
            await dash_ws.send(json.dumps({"type": "response.create"}))

    async def _apply_qwen_audio_tool_result(
        self,
        websocket: WebSocket,
        dash_ws: Any,
        result: dict[str, Any],
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        """Inject backend regex-detected tool result as a user message (non-native fallback)."""
        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        if not prompt.strip():
            return
        payload = {
            "provider": "DashScope",
            "tool_name": str(result.get("tool_name", "search_web") or "search_web"),
            "query": str(result.get("query", "")),
            "turn_id": str(result.get("turn_id", "")),
            "source_count": int(result.get("source_count", 0) or 0),
            "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_context_injected", payload)
        await self._send_event(websocket, "tool_context_injected", **payload)
        # For raw WebSocket, send tool result as a user message then trigger response
        await dash_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        }))
        await dash_ws.send(json.dumps({"type": "response.create"}))

    async def stream_dashscope_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_DASHSCOPE_REALTIME_VOICE,
    ) -> None:
        settings = self._resolve_dashscope_settings(model)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()
        recorder = await self._create_voice_session_recorder(
            provider="DashScope",
            model=settings["model"],
            voice=voice,
        )
        import dashscope

        dashscope.api_key = settings["api_key"]
        base_domain = "dashscope.aliyuncs.com" if settings["region"] == "cn" else "dashscope-intl.aliyuncs.com"
        url = f"wss://{base_domain}/api-ws/v1/realtime"
        event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        callback = DashScopeRealtimeCallback(loop=loop, queue=event_queue)
        conversation = OmniRealtimeConversation(  # type: ignore[misc]
            model=settings["model"],
            callback=callback,
            url=url,
        )

        try:
            conversation.connect()
            await asyncio.sleep(0.5)
            self._configure_dashscope_conversation(
                conversation,
                voice=voice,
                instructions=self._build_realtime_instructions(),
            )
            await asyncio.sleep(0.5)
            await self._send_event(
                websocket,
                "session_open",
                provider="DashScope",
                model=settings["model"],
                voice=voice,
                session_id=recorder.session_id if recorder is not None else "",
            )

            interruption = InterruptionDecisionCoordinator()
            send_task = asyncio.create_task(
                self._client_to_dashscope_loop(
                    websocket, conversation, memory_session, tool_session, recorder, interruption
                )
            )
            receive_task = asyncio.create_task(
                self._dashscope_to_client_loop(
                    websocket,
                    event_queue,
                    memory_session,
                    conversation,
                    voice,
                    tool_session,
                    recorder,
                    interruption,
                )
            )
            done, pending = await asyncio.wait(
                {send_task, receive_task},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        except WebSocketDisconnect:
            return
        except Exception as e:
            print(f"DEBUG: DashScope Realtime Session Error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            await self._send_event(websocket, "error", message=f"DashScope 实时会话启动失败: {str(e)}")
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain()
            if recorder is not None:
                await recorder.finish()
            try:
                conversation.close()
            except Exception:
                pass

    async def stream_dashscope_audio_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str | None = None,
    ) -> None:
        """Raw-WebSocket session for Qwen-Audio models with native function calling.

        This bypasses the DashScope SDK (``OmniRealtimeConversation``) and
        uses ``websockets.connect()`` directly so we can send ``tools`` in
        ``session.update`` and handle ``function_call_arguments.done`` events.
        """
        settings = self._resolve_dashscope_settings(model)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession()
        resolved_voice = (voice or DEFAULT_DASHSCOPE_REALTIME_VOICE).strip()
        recorder = await self._create_voice_session_recorder(
            provider="DashScope",
            model=settings["model"],
            voice=resolved_voice,
        )

        base_domain = "dashscope.aliyuncs.com" if settings["region"] == "cn" else "dashscope-intl.aliyuncs.com"
        ws_url = f"wss://{base_domain}/api-ws/v1/realtime?model={settings['model']}"
        extra_headers = {
            "Authorization": f"Bearer {settings['api_key']}",
        }
        tools = VoiceAgentToolService.build_tools_schema()

        try:
            async with websockets.connect(
                ws_url,
                additional_headers=extra_headers,
                max_size=2**24,
            ) as dash_ws:
                # ── session.update with tools + smart_turn ──
                session_config: dict[str, Any] = {
                    "modalities": ["text", "audio"],
                    "voice": resolved_voice,
                    "input_audio_format": "pcm",
                    "output_audio_format": "pcm",
                    "instructions": self._build_qwen_audio_instructions(),
                    "tools": tools,
                    "turn_detection": {
                        "type": "smart_turn",
                    },
                    "max_history_turns": 50,
                }
                await dash_ws.send(json.dumps({
                    "type": "session.update",
                    "session": session_config,
                }))

                # Wait for session.created confirmation
                try:
                    raw = await asyncio.wait_for(dash_ws.recv(), timeout=10)
                    created = json.loads(raw) if isinstance(raw, str) else {}
                    session_id = (created.get("session") or {}).get("id", "")
                except Exception:
                    session_id = ""

                await self._send_event(
                    websocket,
                    "session_open",
                    provider="DashScope",
                    model=settings["model"],
                    voice=resolved_voice,
                    session_id=recorder.session_id if recorder is not None else session_id,
                )

                interruption = InterruptionDecisionCoordinator()
                send_task = asyncio.create_task(
                    self._client_to_qwen_audio_loop(
                        websocket, dash_ws, memory_session, tool_session, recorder, interruption
                    )
                )
                receive_task = asyncio.create_task(
                    self._qwen_audio_to_client_loop(
                        websocket, dash_ws, memory_session, resolved_voice,
                        tool_session, recorder, interruption,
                    )
                )
                done, pending = await asyncio.wait(
                    {send_task, receive_task},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except WebSocketDisconnect:
            return
        except Exception as e:
            print(f"DEBUG: Qwen-Audio Realtime Session Error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            await self._send_event(websocket, "error", message=f"Qwen-Audio 实时会话启动失败: {str(e)}")
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain()
            if recorder is not None:
                await recorder.finish()
