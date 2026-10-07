from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from .evermem_config import EverMemConfig
from .evermem_service import EverMemService

logger = logging.getLogger(__name__)


def _resolve_pending_cache_path() -> Path:
    if os.environ.get("ECHO_DATA_DIR", "").strip() or os.environ.get("VOICESPIRIT_DATA_DIR", "").strip():
        from .config_loader import get_data_dir
        return get_data_dir() / "realtime_pending_memory.json"
    app_name = "Echo"
    if os.name == "nt":
        base_dir = Path(os.environ.get("APPDATA", str(Path.cwd())))
        preferred_dir = base_dir / app_name
    else:
        xdg_state_home = os.environ.get("XDG_STATE_HOME")
        base_dir = Path(xdg_state_home) if xdg_state_home else Path.home() / ".local" / "state"
        preferred_dir = base_dir / app_name

    fallback_dir = Path.cwd() / ".echo-state" / app_name
    for candidate in (preferred_dir, fallback_dir):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate / "realtime_pending_memory.json"
        except OSError:
            continue

    return fallback_dir / "realtime_pending_memory.json"


def _merge_memory_text(previous: str, incoming: str, *, cumulative: bool = False) -> str:
    """Accumulate streamed transcript text without corrupting word boundaries.

    ``incoming`` is a verbatim streaming delta unless ``cumulative`` is set, in
    which case it is a whole-transcript snapshot that supersedes ``previous``
    (DashScope's ``response.*.done`` canonical correction).

    Deltas are sub-word BPE tokens carrying their own whitespace (" world" for a
    new word, "ful" for a continuation), so they are concatenated exactly as
    received.  Trimming a delta or inserting a word-boundary space splits words
    ("wonder" + "ful" -> "wonder ful") and makes the persisted transcript
    disagree with both the spoken audio and the verbatim delta that the turn row
    is built from (``_pending_assistant_delta`` in
    realtime_session_recorder.py).  Deltas are likewise never deduplicated: an
    ordered transport does not re-deliver them, whereas speech genuinely repeats
    fragments ("ha" + "ha").
    """
    text = str(incoming or "")
    if not text.strip():
        return previous
    if not previous:
        return text.lstrip()
    if not cumulative:
        return f"{previous}{text}"

    # Cumulative snapshot: compare against the accumulated text ignoring the
    # trailing padding a delta may have contributed, so a clean extension is
    # still recognised as one rather than appended twice.
    base = previous.rstrip()
    snapshot = text.strip()
    if base.endswith(snapshot):
        return previous
    return snapshot


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
        "identity": "用户身份",
    }
    # Who the user is. "My name is ..." used to fall through every classifier
    # (no_candidate_memory), so the one fact users most expect remembered was
    # only ever stored inside a session summary, where search ranks it below
    # many "do you know my name?" episodes.
    _IDENTITY_NAME_PATTERNS = (
        # ASR capitalises names; requiring it keeps "my name is not important" out.
        # Matched case-sensitively; only the lead-in words are case-insensitive.
        r"\b(?i:my name(?:'s| is))\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,2})",
        r"\b(?i:call me)\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,2})",
        r"\b(?i:I(?:'m| am) called)\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,2})",
        r"我的名字(?:是|叫)\s*([一-鿿A-Za-z][一-鿿A-Za-z ·]{0,15})",
        r"(?<![你他她它])我叫(?!什么|啥|你|他|她)\s*([一-鿿A-Za-z][一-鿿A-Za-z ·]{0,15})",
        r"(?:以后)?(?:请)?叫我(?!什么|啥)\s*([一-鿿]{1,6})",
    )
    # Asking who they are: always worth a recall.
    _IDENTITY_QUESTION_PATTERNS = (
        r"\bmy name\b",
        r"\bwho am i\b",
        r"\bremember me\b",
        r"我叫什么",
        r"我叫啥",
        r"我的名字",
        r"我是谁",
        r"怎么称呼我",
    )
    # Broader: a recall-tool query like "name" or "user's name".
    _IDENTITY_TOPIC_PATTERNS = _IDENTITY_QUESTION_PATTERNS + (
        r"\bname\b",
        r"名字",
        r"称呼",
        r"\bidentity\b",
    )
    # EverOS writes episodes as declarative Chinese summaries ("用户表示希望系统
    # 记住自己的名字是 ..."). Questions about the user's name rank those below
    # episodes where the user merely asked; a statement-form query ranks the
    # one that holds the name first (measured: rank 0 vs rank 5-9).
    _IDENTITY_EXPANSION_QUERY = "记住我的名字 我叫 my name is"
    _IDENTITY_NAME_TRAILERS = re.compile(
        r"\s+(?:and|but|so|could|can|please|ok|okay|thanks|thank)\b.*$|[了的啊呢吧哦呀嘛，,。.!！?？].*$",
        re.IGNORECASE,
    )
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
        r"retrieve",
        r"recall",
        r"检索",
        r"搜索",
        r"回忆",
        r"想起",
        r"提到",
        r"刚才说",
        r"重点工作",
        r"讨论过",
        r"聊过",
        r"说过",
        r"we talked about",
        r"discussed",
    )
    _RETRIEVE_TIMEOUT_SECONDS = 3.0
    # Forced recall mid-conversation: the user asked "do you remember…?" — the
    # cloud typically responds in 2–3s, so allow a generous budget while keeping
    # it short enough for realtime voice latency.
    _FORCED_RETRIEVE_TIMEOUT_SECONDS = 5.0
    # Explicit recall via the ``recall`` command is user-initiated — the user
    # explicitly asked to search, so a generous wait is acceptable.
    _EXPLICIT_RECALL_TIMEOUT_SECONDS = 5.0
    _STARTUP_RETRIEVE_TIMEOUT_SECONDS = 3.0
    _STARTUP_WAIT_SECONDS = 1.2
    _STARTUP_QUERY = "最近的对话讨论了什么 用户偏好 当前任务 待办事项 会话摘要"
    _SESSION_MAX_USER_EXCERPTS = 30
    _SESSION_MAX_ASSISTANT_EXCERPTS = 12
    _SESSION_MAX_KEY_ENTRIES = 8
    _SESSION_SUMMARY_MAX_CHARS = 700
    # Cloud extraction is asynchronous and boundary-triggered — short voice
    # sessions may take hours (or longer) to become searchable episodes.  The
    # local pending cache is therefore the primary bridge to "next session",
    # so its TTL must cover realistic gaps between conversations, not just
    # extraction lag.
    _PENDING_MEMORY_TTL_SECONDS = 3 * 24 * 3600
    _PENDING_MEMORY_MAX_PER_SCOPE = 24
    _PENDING_MEMORY_CACHE: dict[str, list[dict[str, Any]]] = {}
    _PENDING_CACHE_PATH: Path = _resolve_pending_cache_path()

    def __init__(self) -> None:
        self._config = EverMemConfig()
        self._explicitly_configured = False
        self._current_user_text = ""
        self._current_assistant_text = ""
        # Called with (user_text, assistant_text) whenever a turn is flushed.
        # Every provider completes turns through flush_turn(), so per-turn
        # observers (the speaking coach) hook in here rather than at each
        # provider's completion path.
        self.turn_listener: Callable[[str, str], None] | None = None
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._last_retrieved_query = ""
        self._last_memory_context = ""
        self._last_memory_count = 0
        self._last_local_pending_count = 0
        self._last_cloud_count = 0
        self._last_retrieve_attempted = False
        # Explicit recall requested via the ``recall`` command is injected into
        # the next turn's context exactly once (mirrors startup injection).
        self._pending_recall_context = ""
        self._pending_recall_count = 0
        # Session-level accumulation (drives the end-of-session summary) and
        # startup memory injection state.
        self._session_user_excerpts: list[str] = []
        self._session_assistant_excerpts: list[str] = []
        self._session_key_entries: list[str] = []
        self._startup_task: asyncio.Task[None] | None = None
        self._startup_context = ""
        self._startup_count = 0
        self._startup_consumed = False
        self._session_finalized = False
        # Speculative per-utterance search started from interim ASR, so the
        # result is ready (and injectable) before server VAD starts the reply.
        self._prefetch_query = ""
        self._prefetch_utterance_id = ""
        self._prefetch_task: asyncio.Task[dict[str, Any]] | None = None
        # Kept apart from _pending_tasks: drain() cancels speculative searches
        # instead of holding session teardown on them.
        self._prefetch_tasks: set[asyncio.Task[dict[str, Any]]] = set()
        # Cloud writes run in the background so turn completion never waits
        # on EverOS; providers report the outcome with a follow-up event.
        self._last_persist_task: asyncio.Task[dict[str, Any]] | None = None

    def _pending_cache_key(self) -> str:
        return str(self._config.group_id or self._config.memory_scope).strip()

    def _scope_pending_cache_key(self) -> str:
        return str(self._config.memory_scope or "").strip()

    def configure_from_server(self) -> bool:
        """Auto-configure from server-side config.json when the client never
        sent a ``config`` command.  This lets memory work even when the
        frontend's localStorage gate (``evermem_enabled``) is stale or out of
        sync with the backend's ``memory_settings.enabled``.  No-op if the
        client already explicitly configured memory (enabled or disabled) so
        an explicit client config always wins.
        """
        if self._explicitly_configured or self._config.get_service() is not None:
            return False
        from .evermem_config import _load_server_evermem_settings, DEFAULT_EVERMEM_URL

        try:
            from .config_loader import BackendConfig

            cfg = BackendConfig()
            memory_section = cfg.get("memory_settings")
            if not isinstance(memory_section, dict) or not memory_section.get("enabled"):
                return False
        except Exception:
            return False

        server_url, server_key = _load_server_evermem_settings()
        url = server_url or DEFAULT_EVERMEM_URL
        # Resolve scope from server config; if absent, derive a stable scope
        # from the API key so writes and reads always land in the same
        # namespace (not "anonymous" which may collide across users).
        scope = ""
        group = ""
        try:
            scope = str(memory_section.get("scope_id", "") or "").strip()
        except Exception:
            pass
        if not scope and server_key:
            from .evermem_config import _hash_scope

            scope = _hash_scope("server", server_key)
        self._config.update_from_headers(
            {
                "X-EverMem-Enabled": "true",
                "X-EverMem-Url": url,
                "X-EverMem-Key": server_key,
                "X-EverMem-Scope": scope,
                "X-EverMem-Group-ID": group,
            }
        )
        logger.info(
            "voice_memory_config auto_from_server scope=%s group=%s url=%s",
            self._config.memory_scope,
            self._config.group_id,
            self._config.url,
        )
        return True

    def configure(self, payload: dict[str, Any] | None) -> None:
        self._explicitly_configured = True
        if not isinstance(payload, dict) or not payload.get("enabled"):
            self._config = EverMemConfig()
            self._current_user_text = ""
            self._current_assistant_text = ""
            # Memory was explicitly disabled — drop anything accumulated so a
            # later finalize cannot write excerpts from a disabled session.
            self._session_user_excerpts = []
            self._session_assistant_excerpts = []
            self._session_key_entries = []
            self._startup_context = ""
            self._startup_count = 0
            self._startup_consumed = True
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
        self._warm_up_service()

    def _warm_up_service(self) -> None:
        """Open the EverOS connection while the user is still getting started."""
        service = self._config.get_service()
        warm_up = getattr(service, "warm_up", None)
        if not callable(warm_up):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        task = asyncio.create_task(warm_up())
        self._prefetch_tasks.add(task)  # cancelled by drain() like a prefetch
        task.add_done_callback(self._prefetch_tasks.discard)

    def note_user_transcript(self, text: str) -> None:
        cleaned = str(text or "").strip()
        # Auto-configure from server config on first user input if the client
        # never sent a ``config`` command (e.g. frontend localStorage stale).
        if cleaned and not self._explicitly_configured and self._config.get_service() is None:
            self.configure_from_server()
        if cleaned != self._current_user_text:
            self._last_retrieved_query = ""
            self._last_memory_context = ""
            self._last_memory_count = 0
            self._last_local_pending_count = 0
            self._last_cloud_count = 0
            self._last_retrieve_attempted = False
        self._current_user_text = cleaned

    def note_assistant_text(self, text: str, *, cumulative: bool = False, replace: bool = False) -> None:
        if replace:
            self._current_assistant_text = str(text or "")
        else:
            self._current_assistant_text = _merge_memory_text(
                self._current_assistant_text, text, cumulative=cumulative
            )

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
        assistant_text = self._current_assistant_text.strip()
        self._current_user_text = ""
        self._current_assistant_text = ""
        if self.turn_listener is not None:
            try:
                self.turn_listener(user_text, assistant_text)
            except Exception:
                logger.exception("voice_memory_turn_listener_failed")
        self._record_turn_excerpts(user_text, assistant_text)

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
        self._note_key_entries(memory_entries)
        # The entries are already retrievable from the local pending cache, so
        # the cloud write (add_memory per entry + flush, often seconds) must not
        # hold turn completion. take_persist_task() hands its outcome to the
        # provider for a follow-up memory_write event; drain() awaits it.
        task = asyncio.create_task(self._persist_and_log(memory_entries, queued_count))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        self._last_persist_task = task
        return {
            "enabled": True,
            "attempted_count": len(memory_entries),
            "saved_count": 0,
            "failed_count": 0,
            "local_pending_count": queued_count,
            "reason": "saving",
        }

    async def _persist_and_log(self, entries: list[str], queued_count: int) -> dict[str, Any]:
        result = await self._persist_entries(entries=entries)
        result["enabled"] = True
        result["local_pending_count"] = queued_count
        result["reason"] = ""
        logger.info(
            "voice_memory_write scope=%s group=%s attempted=%s saved=%s failed=%s local_pending=%s entries=%s",
            self._config.memory_scope,
            self._config.group_id,
            result.get("attempted_count", 0),
            result.get("saved_count", 0),
            result.get("failed_count", 0),
            queued_count,
            entries,
        )
        return result

    def take_persist_task(self) -> "asyncio.Task[dict[str, Any]] | None":
        """Return (once) the cloud write scheduled by the last flush_turn()."""
        task = self._last_persist_task
        self._last_persist_task = None
        return task

    # -- session-level accumulation -----------------------------------------

    def _record_turn_excerpts(self, user_text: str, assistant_text: str) -> None:
        """Keep bounded per-turn excerpts for the end-of-session summary."""
        if user_text:
            excerpt = re.sub(r"\s+", " ", user_text).strip()[:160]
            if excerpt and (not self._session_user_excerpts or self._session_user_excerpts[-1] != excerpt):
                self._session_user_excerpts.append(excerpt)
                del self._session_user_excerpts[: -self._SESSION_MAX_USER_EXCERPTS]
        if assistant_text:
            excerpt = re.sub(r"\s+", " ", assistant_text).strip()[:120]
            if excerpt and (
                not self._session_assistant_excerpts or self._session_assistant_excerpts[-1] != excerpt
            ):
                self._session_assistant_excerpts.append(excerpt)
                del self._session_assistant_excerpts[: -self._SESSION_MAX_ASSISTANT_EXCERPTS]

    def _note_key_entries(self, entries: list[str]) -> None:
        seen = {self._content_dedupe_key(item) for item in self._session_key_entries}
        for entry in entries:
            key = self._content_dedupe_key(entry)
            if not key or key in seen:
                continue
            seen.add(key)
            self._session_key_entries.append(entry)
        del self._session_key_entries[: -self._SESSION_MAX_KEY_ENTRIES]

    @staticmethod
    def _pick_excerpts(excerpts: list[str], *, head: int, tail: int, max_chars: int) -> list[str]:
        """Pick the first ``head`` and last ``tail`` excerpts (deduped, trimmed)."""
        picked: list[str] = []
        seen: set[str] = set()
        for candidate in [*excerpts[:head], *excerpts[-tail:]]:
            trimmed = candidate[:max_chars].strip()
            if not trimmed or trimmed in seen:
                continue
            seen.add(trimmed)
            picked.append(trimmed)
        return picked

    def _compose_session_summary(self) -> str:
        """Build a heuristic session summary (no LLM required)."""
        date_str = datetime.date.today().isoformat()
        turn_count = len(self._session_user_excerpts)
        parts = [f"会话摘要({date_str}): 本次实时语音对话共 {turn_count} 轮。"]
        topics = self._pick_excerpts(self._session_user_excerpts, head=2, tail=2, max_chars=60)
        if topics:
            parts.append("用户谈到: " + "；".join(topics) + "。")
        if self._session_key_entries:
            parts.append("关键记忆: " + "；".join(self._session_key_entries[:6]) + "。")
        replies = self._pick_excerpts(self._session_assistant_excerpts, head=1, tail=1, max_chars=50)
        if replies:
            parts.append("助手回复要点: " + "；".join(replies) + "。")
        return "".join(parts)[: self._SESSION_SUMMARY_MAX_CHARS]

    async def finalize_session(self) -> dict[str, Any]:
        """Write a whole-session summary memory when the realtime session ends.

        Called from ``drain()`` (every provider's session teardown), so the
        conversation record persists even on abrupt disconnects. Idempotent.
        """
        if self._session_finalized:
            return {"saved": False, "reason": "already_finalized"}
        self._session_finalized = True

        service = self._config.get_service()
        if not service:
            return {"saved": False, "reason": "disabled"}
        if not self._session_user_excerpts:
            return {"saved": False, "reason": "empty_session"}

        summary = self._compose_session_summary()
        # Queue locally first so the summary is immediately retrievable next
        # session even if the cloud write fails or replication lags.
        queued = self._queue_pending_entries(self._pending_cache_key(), [summary])
        try:
            result = await service.add_memory(
                content=summary,
                user_id=self._config.memory_scope,
                sender=self._config.memory_scope,
                sender_name="User",
                group_id=self._config.group_id or None,
                flush=True,
            )
        except Exception:
            logger.exception(
                "voice_memory_session_summary_failed scope=%s", self._config.memory_scope
            )
            result = None
        saved = bool(result)
        logger.info(
            "voice_memory_session_summary scope=%s group=%s saved=%s queued=%s summary=%r",
            self._config.memory_scope,
            self._config.group_id,
            saved,
            queued,
            summary[:200],
        )
        return {
            "saved": saved,
            "queued_local": queued,
            "reason": "" if saved else "cloud_write_failed",
            "summary": summary,
        }

    # -- startup memory injection --------------------------------------------

    # Startup injection is disabled by default: opening a voice session should
    # NOT auto-search the cloud. The user asks for recall explicitly (hint words
    # or the ``recall`` command). Set this to True to re-enable the historical
    # "know what prior sessions discussed" background fetch on session open.
    _STARTUP_INJECTION_ENABLED = False

    def kickoff_startup_context(self) -> None:
        """Begin a background fetch of recent memories for session-start injection.

        Disabled by default (``_STARTUP_INJECTION_ENABLED``). When enabled, the
        result is prepended to the first turn's memory context so the assistant
        knows what prior sessions discussed — even if the first utterance is
        too trivial to trigger per-turn retrieval. When disabled, this is a
        no-op so sessions start clean and the cloud is only searched on
        explicit recall.
        """
        if not self._STARTUP_INJECTION_ENABLED:
            return
        service = self._config.get_service()
        if not service or self._startup_task is not None or self._startup_consumed:
            return
        task = asyncio.create_task(self._load_startup_context(service))
        self._startup_task = task
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _load_startup_context(self, service: EverMemService) -> None:
        local_memories: list[dict[str, Any]] = []
        cloud_memories: list[dict[str, Any]] = []
        try:
            local_memories = self._search_pending_entries(
                self._pending_cache_key(), self._STARTUP_QUERY
            )
            cloud_memories = await asyncio.wait_for(
                self._search_cloud_memories(service=service, query=self._STARTUP_QUERY),
                timeout=self._STARTUP_RETRIEVE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "voice_memory_startup timeout scope=%s", self._config.memory_scope
            )
        except Exception:
            logger.exception(
                "voice_memory_startup error scope=%s", self._config.memory_scope
            )

        combined = self._merge_retrieved_memories(
            local_memories=local_memories, cloud_memories=cloud_memories
        )
        lines: list[str] = []
        for memory in combined[:5]:
            content = str(memory.get("content", "")).strip()
            if content:
                lines.append(f"{len(lines) + 1}. {content[:180]}")
        if lines:
            self._startup_context = "【上次对话以来的记忆】\n" + "\n".join(lines)
            self._startup_count = len(lines)
        logger.info(
            "voice_memory_startup scope=%s group=%s count=%s local=%s cloud=%s",
            self._config.memory_scope,
            self._config.group_id,
            self._startup_count,
            len(local_memories),
            len(cloud_memories),
        )

    async def _consume_startup_context(self) -> str:
        """Return the startup memory block exactly once (first turn of the session)."""
        if self._startup_consumed:
            return ""
        task = self._startup_task
        if task is None:
            # No config received yet — leave the one-shot unused in case the
            # client's config command arrives before the first real turn.
            return ""
        if not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=self._STARTUP_WAIT_SECONDS)
            except asyncio.TimeoutError:
                pass
        self._startup_consumed = True
        return self._startup_context

    async def drain(self) -> None:
        prefetches = list(self._prefetch_tasks)
        for task in prefetches:
            task.cancel()
        self._clear_prefetch()
        if prefetches:
            await asyncio.gather(*prefetches, return_exceptions=True)
        try:
            await self.finalize_session()
        except Exception:
            logger.exception("voice_memory_finalize_session_failed")
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
                    # Flushed right below: a queued (202) add may not have
                    # landed yet and the flush would find nothing to extract.
                    sync=True,
                )
                if result:
                    saved_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        # Cloud extraction is async (HTTP 202): unflushed messages stay in the
        # session's raw buffer and are only reachable as pending_messages via
        # session-pinned search, never as extracted episodic_memory. A single
        # batched flush per turn forces extraction so the memory becomes
        # searchable cross-session. Fail-open: a flush error must not surface
        # as a write failure — the pending buffer is retried next turn.
        if saved_count > 0:
            try:
                await service.flush_pending_memories(
                    user_id=scope,
                    session_id=self._config.group_id or None,
                )
            except Exception:
                logger.warning(
                    "voice_memory_flush_failed scope=%s group=%s",
                    scope,
                    self._config.group_id,
                )
        return {
            "attempted_count": len(entries),
            "saved_count": saved_count,
            "failed_count": failed_count,
        }

    def should_retrieve_context(self, text: str | None = None, *, quiet: bool = False) -> bool:
        """Gate per-turn automatic recall.

        Recall is an explicit act: only fire when the user expresses a memory
        intent (hint words) or asks a question that targets memory topics. We
        deliberately do NOT recall on long-but-plain statements nor on
        classifiable-but-non-question utterances — those are worth *storing*,
        not worth interrupting the reply with a (usually empty) recall.
        """
        _log = (lambda *_args: None) if quiet else logger.info
        service = self._config.get_service()
        candidate = str(text or self._current_user_text or "").strip()
        if not service or not candidate:
            _log(
                "voice_memory_retrieve skipped reason=%s scope=%s query=%r",
                "disabled_or_empty",
                self._config.memory_scope,
                candidate[:120],
            )
            return False
        if service.should_skip_memory(candidate):
            _log(
                "voice_memory_retrieve skipped reason=%s scope=%s query=%r",
                "trivial_message",
                self._config.memory_scope,
                candidate[:120],
            )
            return False
        if self._is_identity_question(candidate):
            _log(
                "voice_memory_retrieve trigger=identity scope=%s query=%r",
                self._config.memory_scope,
                candidate[:120],
            )
            return True
        if self._matches_any(candidate, self._RETRIEVE_HINT_PATTERNS):
            _log(
                "voice_memory_retrieve trigger=hint scope=%s query=%r",
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
                _log(
                    "voice_memory_retrieve trigger=question_target scope=%s query=%r",
                    self._config.memory_scope,
                    candidate[:120],
                )
                return True
            _log(
                "voice_memory_retrieve skipped reason=%s scope=%s query=%r",
                "question_without_memory_target",
                self._config.memory_scope,
                candidate[:120],
            )
            return False
        _log(
            "voice_memory_retrieve skipped reason=%s scope=%s query=%r",
            "non_question_statement",
            self._config.memory_scope,
            candidate[:120],
        )
        return False

    def is_forced_recall_query(self, text: str | None = None) -> bool:
        candidate = str(text or self._current_user_text or "").strip()
        if not candidate:
            return False
        # A hint word alone ("earlier", "记得", "之前") signals recall intent
        # even without a question marker — treat it as forced so it gets the
        # longer cloud timeout instead of timing out at the trivial budget.
        # "Do you know my name?" is the same kind of explicit recall.
        return self._matches_any(candidate, self._RETRIEVE_HINT_PATTERNS) or self._is_identity_question(candidate)

    async def retrieve_memory_context(self, utterance_id: str = "", *, query: str | None = None) -> dict[str, Any]:
        """Per-turn memory context, with the session-start block prepended once.

        The startup block (recent summaries / preferences fetched when the
        client configured memory) rides the first turn's injection so the
        assistant opens the session knowing what earlier conversations covered,
        regardless of how trivial the first utterance is. An explicit
        ``recall`` command stages a one-shot block consumed here as well.
        """
        startup_context = await self._consume_startup_context()
        result = await self._retrieve_turn_context(utterance_id, query=query)
        recall_context, recall_count = self._consume_recall_context()
        if startup_context:
            turn_context = str(result.get("context", ""))
            result["context"] = (
                f"{startup_context}\n{turn_context}" if turn_context else startup_context
            )
            result["memories_retrieved"] = int(result.get("memories_retrieved", 0)) + self._startup_count
            result["attempted"] = True
        if recall_context:
            turn_context = str(result.get("context", ""))
            result["context"] = (
                f"【回忆】\n{recall_context}\n{turn_context}" if turn_context else f"【回忆】\n{recall_context}"
            )
            result["memories_retrieved"] = int(result.get("memories_retrieved", 0)) + recall_count
            result["attempted"] = True
            result["explicit"] = True
        return result

    async def recall_by_query(self, query: str, *, stage: bool = True) -> dict[str, Any]:
        """Explicit recall requested by the user (via the ``recall`` command).

        Bypasses ``should_retrieve_context`` — the user asked, so we search.
        Uses the longer forced-recall timeout and searches both the group and
        scope pending caches. Returns the same shape as ``retrieve_memory_context``.
        """
        service = self._config.get_service()
        cleaned = str(query or "").strip()
        if not service or not cleaned:
            return {
                "context": "",
                "memories_retrieved": 0,
                "local_pending_count": 0,
                "cloud_count": 0,
                "attempted": False,
                "explicit": True,
            }
        # Use the explicit query for retrieval (not the current turn text).
        cache_key = self._pending_cache_key()
        local_memories = self._search_pending_entries(cache_key, cleaned)
        scope_key = self._scope_pending_cache_key()
        if scope_key and scope_key != cache_key:
            local_memories = self._merge_retrieved_memories(
                local_memories=local_memories,
                cloud_memories=self._search_pending_entries(scope_key, cleaned),
            )
        try:
            memories = await asyncio.wait_for(
                self._search_cloud_memories(service=service, query=cleaned, force_global=True),
                timeout=self._EXPLICIT_RECALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "voice_memory_recall cloud_timeout scope=%s query=%r",
                self._config.memory_scope,
                cleaned[:120],
            )
            memories = []
        except Exception:
            logger.exception(
                "voice_memory_recall error scope=%s query=%r",
                self._config.memory_scope,
                cleaned[:120],
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
        logger.info(
            "voice_memory_recall result scope=%s count=%s local_pending=%s cloud=%s query=%r",
            self._config.memory_scope,
            len(lines),
            local_count,
            cloud_count,
            cleaned[:120],
        )
        context = "\n".join(lines)
        # Stage for one-shot injection into the next turn. The recall_memory
        # tool hands the result to the model directly and passes stage=False,
        # or the same memories would be injected a second time.
        if stage:
            self._pending_recall_context = context
            self._pending_recall_count = len(lines)
        return {
            "context": context,
            "memories_retrieved": len(lines),
            "local_pending_count": local_count,
            "cloud_count": cloud_count,
            "attempted": True,
            "explicit": True,
        }

    def _consume_recall_context(self) -> tuple[str, int]:
        """Return the explicit-recall context and its line count exactly once.

        Does NOT touch the ``_last_*`` per-query dedup cache: the staged block
        is a transient one-shot injection (like startup), not a cacheable
        result for the current query. Writing ``_last_*`` here would poison the
        dedup cache so a repeated query returns recall-only context and drops
        fresh per-turn search results.
        """
        if not self._pending_recall_context:
            return "", 0
        context = self._pending_recall_context
        count = self._pending_recall_count
        self._pending_recall_context = ""
        self._pending_recall_count = 0
        return context, count

    # -- speculative prefetch from interim ASR ---------------------------------

    def prefetch_partial(self, text: str, utterance_id: str = "") -> "asyncio.Task[dict[str, Any]] | None":
        """Start the memory search for an utterance the user is still speaking.

        Server-VAD providers begin the reply the moment speech ends, so a search
        started from the final transcript can only ever steer the *next* reply.
        Starting it from the first interim transcript that passes the recall
        gate gives it the rest of the utterance to finish. At most one search
        runs per utterance; the final ``retrieve_memory_context`` reuses it.
        Returns the new task, or None when nothing was started.
        """
        cleaned = str(text or "").strip()
        utterance_id = str(utterance_id or "")
        if not cleaned or self._config.get_service() is None:
            return None
        if self._prefetch_task is not None:
            if utterance_id == self._prefetch_utterance_id:
                return None
            self._clear_prefetch()
        if not self.should_retrieve_context(cleaned, quiet=True):
            return None
        task = asyncio.create_task(self._search_turn_memories(cleaned))
        self._prefetch_tasks.add(task)
        task.add_done_callback(self._prefetch_tasks.discard)
        self._prefetch_task = task
        self._prefetch_query = cleaned
        self._prefetch_utterance_id = utterance_id
        logger.info(
            "voice_memory_prefetch start scope=%s query=%r",
            self._config.memory_scope,
            cleaned[:120],
        )
        return task

    def begin_utterance(self) -> None:
        """Forget an unconsumed prefetch when a new utterance starts.

        For providers without per-utterance ids: a prefetch whose utterance
        never produced a final transcript would otherwise block the next one.
        """
        self._clear_prefetch()

    def _clear_prefetch(self) -> None:
        self._prefetch_task = None
        self._prefetch_query = ""
        self._prefetch_utterance_id = ""

    def _take_matching_prefetch(
        self, query: str, utterance_id: str = ""
    ) -> "tuple[asyncio.Task[dict[str, Any]], str] | None":
        """Hand over (once) the prefetch started for this same utterance."""
        task = self._prefetch_task
        prefetch_query = self._prefetch_query
        prefetch_id = self._prefetch_utterance_id
        self._clear_prefetch()
        if task is None or task.cancelled():
            return None
        if utterance_id and prefetch_id:
            return (task, prefetch_query) if utterance_id == prefetch_id else None
        partial = self._search_text(prefetch_query)
        final = self._search_text(query)
        if not partial or not final:
            return None
        if partial in final:
            return task, prefetch_query
        partial_grams = self._bigrams(partial)
        overlap = len(partial_grams & self._bigrams(final)) / max(1, len(partial_grams))
        return (task, prefetch_query) if overlap >= 0.6 else None

    async def _retrieve_turn_context(self, utterance_id: str = "", *, query: str | None = None) -> dict[str, Any]:
        # Callers that run off the event loop pass the utterance explicitly:
        # by the time they run, flush_turn() may have cleared the current text.
        service = self._config.get_service()
        query = (self._current_user_text if query is None else str(query)).strip()
        prefetch = self._take_matching_prefetch(query, utterance_id) if query else None
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

        result: dict[str, Any] | None = None
        if prefetch is not None:
            task, prefetch_query = prefetch
            try:
                result = dict(await task)
            except asyncio.CancelledError:
                # Only a cancelled prefetch falls back; our own cancellation
                # must propagate.
                if not task.cancelled():
                    raise
                result = None
            except Exception:
                result = None
            # A partial query that found nothing is not authoritative: the
            # rest of the sentence may carry the words that match.
            if result is not None and not result.get("memories_retrieved") and (
                self._search_text(query) != self._search_text(prefetch_query)
            ):
                result = None
            elif result is not None:
                result["prefetched"] = True
        if result is None:
            result = await self._search_turn_memories(query)

        # Only cache when the user text has not moved on while we waited.
        if self._current_user_text.strip() == query:
            self._last_retrieved_query = query
            self._last_memory_context = str(result.get("context", ""))
            self._last_memory_count = int(result.get("memories_retrieved", 0))
            self._last_local_pending_count = int(result.get("local_pending_count", 0))
            self._last_cloud_count = int(result.get("cloud_count", 0))
            self._last_retrieve_attempted = True
        return result

    async def _search_turn_memories(self, query: str) -> dict[str, Any]:
        """Search local pending + cloud memories for *query* (no caching)."""
        service = self._config.get_service()
        if not service:
            return {
                "context": "",
                "memories_retrieved": 0,
                "local_pending_count": 0,
                "cloud_count": 0,
                "attempted": False,
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
            forced = self.is_forced_recall_query(query)
            timeout_seconds = (
                self._FORCED_RETRIEVE_TIMEOUT_SECONDS
                if forced
                else self._RETRIEVE_TIMEOUT_SECONDS
            )
            memories = await asyncio.wait_for(
                self._search_cloud_memories(
                    service=service,
                    query=query,
                    force_global=forced,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "voice_memory_retrieve cloud_timeout scope=%s timeout=%s query=%r",
                self._config.memory_scope,
                timeout_seconds,
                query[:120],
            )
            memories = []
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

        logger.info(
            "voice_memory_retrieve result scope=%s count=%s local_pending=%s cloud=%s query=%r",
            self._config.memory_scope,
            len(lines),
            local_count,
            cloud_count,
            query[:120],
        )
        return {
            "context": "\n".join(lines),
            "memories_retrieved": len(lines),
            "local_pending_count": local_count,
            "cloud_count": cloud_count,
            "attempted": True,
        }

    async def _search_cloud_memories(
        self,
        *,
        service: EverMemService,
        query: str,
        force_global: bool = False,
    ) -> list[dict[str, Any]]:
        """Search EverOS, adding a statement-form query for identity questions."""
        if not self._is_identity_topic(query):
            return await self._search_cloud_core(service=service, query=query, force_global=force_global)
        original, expanded = await asyncio.gather(
            self._search_cloud_core(service=service, query=query, force_global=force_global),
            self._search_cloud_core(
                service=service, query=self._IDENTITY_EXPANSION_QUERY, force_global=force_global,
            ),
        )
        # Episodes that actually state a name first; the rest keep their order.
        stated = [
            {**mem, "source": mem.get("source") or "cloud"}
            for mem in expanded
            if "名字是" in str(mem.get("content", "")) or "name is" in str(mem.get("content", "")).lower()
        ]
        return self._merge_retrieved_memories(local_memories=stated, cloud_memories=original + expanded)

    async def _search_cloud_core(
        self,
        *,
        service: EverMemService,
        query: str,
        force_global: bool = False,
    ) -> list[dict[str, Any]]:
        """Search EverOS for memories.

        When ``force_global`` is False (default per-turn behavior), the
        group-scoped search short-circuits if it returns anything — this
        keeps latency low for normal turns where the current conversation
        context is usually what matters.

        When ``force_global`` is True (forced recall — the user is asking
        "do you remember what we said earlier"), both the scoped and the
        global user-level searches are run and merged. This prevents the
        current session's pending/raw messages from masking prior
        episodic memories that live at the user scope.
        """
        base_kwargs = {
            "query": query,
            "user_id": self._config.memory_scope,
            "memory_types": ["episodic_memory", "profile"],
            "min_score": 0.35,
        }
        group_id = str(self._config.group_id or "").strip()
        if group_id:
            if force_global:
                # Run both searches concurrently so they share the wall-clock
                # timeout budget instead of starving the global call.
                scoped, global_results = await asyncio.gather(
                    service.search_memories(group_ids=[group_id], **base_kwargs),
                    service.search_memories(**base_kwargs),
                )
                # Tag scoped cloud results so the merge labels them correctly
                # (they are cloud results from the current session group, not
                # local pending entries).
                for mem in scoped:
                    if "source" not in mem:
                        mem["source"] = "cloud_scoped"
                for mem in global_results:
                    if "source" not in mem:
                        mem["source"] = "cloud"
                return self._merge_retrieved_memories(
                    local_memories=scoped, cloud_memories=global_results
                )
            scoped = await service.search_memories(
                group_ids=[group_id],
                **base_kwargs,
            )
            if scoped:
                return scoped
        return await service.search_memories(**base_kwargs)

    @classmethod
    def _extract_identity_entries(cls, text: str) -> list[str]:
        """``用户身份`` entries for names the user states ("my name is ...")."""
        entries: list[str] = []
        for pattern in cls._IDENTITY_NAME_PATTERNS:
            for match in re.finditer(pattern, str(text or "")):
                name = cls._IDENTITY_NAME_TRAILERS.sub("", match.group(1)).strip(" ·")
                if not name or len(name) > 24:
                    continue
                entry = f"{cls._MEMORY_LABELS['identity']}: 用户的名字是 {name}（the user's name is {name}）"
                if entry not in entries:
                    entries.append(entry)
        return entries[:1]

    @classmethod
    def _is_identity_question(cls, text: str) -> bool:
        return cls._matches_any(str(text or ""), cls._IDENTITY_QUESTION_PATTERNS)

    @classmethod
    def _is_identity_topic(cls, text: str) -> bool:
        return cls._matches_any(str(text or ""), cls._IDENTITY_TOPIC_PATTERNS)

    @classmethod
    def _is_identity_entry(cls, content: str) -> bool:
        return str(content or "").startswith(f"{cls._MEMORY_LABELS['identity']}:")

    def _extract_memory_entries(self, text: str) -> list[str]:
        entries: list[str] = self._extract_identity_entries(text)
        seen: set[str] = {entry.lower() for entry in entries}

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
        # Who the user is does not go stale after three days.
        fresh = [
            item for item in entries
            if cls._is_identity_entry(str(item.get("content", "")))
            or now - float(item.get("created_at", 0.0)) <= cls._PENDING_MEMORY_TTL_SECONDS
        ]
        if fresh:
            cls._PENDING_MEMORY_CACHE[scope] = cls._cap_pending(fresh)
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
            if cls._is_identity_entry(entry):
                # A newly stated name replaces the old one.
                existing = [
                    item for item in existing
                    if not cls._is_identity_entry(str(item.get("content", "")))
                ]
            existing.append({"content": entry, "created_at": now})
            seen.add(key)
            appended += 1
        cls._PENDING_MEMORY_CACHE[scope] = cls._cap_pending(existing)
        cls._save_pending_cache_to_disk()
        return appended

    @classmethod
    def _cap_pending(cls, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep the newest entries, never evicting the identity entry."""
        limit = cls._PENDING_MEMORY_MAX_PER_SCOPE
        if len(items) <= limit:
            return items
        pinned = [item for item in items if cls._is_identity_entry(str(item.get("content", "")))]
        others = [item for item in items if item not in pinned]
        keep = others[-max(0, limit - len(pinned)):] if limit > len(pinned) else []
        return [item for item in items if item in pinned or item in keep]

    @classmethod
    def _all_pending_entries(cls, scope: str) -> list[dict[str, Any]]:
        """Return all pending cache entries for a scope without scoring."""
        pending = cls._prune_pending_entries(scope)
        return [
            {"content": str(item.get("content", "")).strip(), "source": "local_pending"}
            for item in pending
            if str(item.get("content", "")).strip()
        ]

    @classmethod
    def _all_pending_entries_any_scope(cls) -> list[dict[str, Any]]:
        """Return all pending cache entries across ALL scopes (no scoring).

        Used at handshake time when the scope may not yet match the one the
        client will configure — this ensures we see history regardless.
        """
        cls._load_pending_cache_from_disk()
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for scope, items in cls._PENDING_MEMORY_CACHE.items():
            for item in items:
                content = str(item.get("content", "")).strip()
                if content and content not in seen:
                    seen.add(content)
                    result.append({"content": content, "source": "local_pending"})
        return result

    @classmethod
    def _search_pending_entries(cls, scope: str, query: str) -> list[dict[str, Any]]:
        pending = cls._prune_pending_entries(scope)
        if not pending:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        identity_query = cls._is_identity_topic(query)
        for item in pending:
            content = str(item.get("content", "")).strip()
            # "What's my name?" shares no words with "用户的名字是 Xiao Bao".
            if identity_query and cls._is_identity_entry(content):
                scored.append((2.0, {"content": content, "source": "local_pending"}))
                continue
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
