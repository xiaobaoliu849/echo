from __future__ import annotations

import asyncio
import functools
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .voice_agent_session_repository import VoiceAgentSessionRepository
from .realtime_memory_session import _merge_memory_text

logger = logging.getLogger(__name__)

# Assistant text arrives as many small streaming deltas per second. Instead of
# writing every delta to SQLite immediately, they are coalesced in memory and
# flushed at most this often (and always at turn finalize / barge-in / close).
ASSISTANT_TEXT_FLUSH_SECONDS = 0.5

# Dedicated single-thread executor for session persistence. SQLite only
# supports one writer anyway, and keeping these writes off asyncio's default
# pool stops them from queueing behind long TTS inference jobs (and vice
# versa) in the middle of a voice turn.
_RECORDER_DB_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="voice-session-db"
)


async def run_db_call(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking repository call on the dedicated recorder DB executor."""
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(
            _RECORDER_DB_EXECUTOR, functools.partial(func, *args, **kwargs)
        )
    return await loop.run_in_executor(_RECORDER_DB_EXECUTOR, func, *args)


class VoiceAgentSessionRecorder:
    def __init__(self, repository: VoiceAgentSessionRepository, session_id: str) -> None:
        self.repository = repository
        self.session_id = session_id
        self._turn_index = 0
        self._current_turn_id = ""
        self._pending_user_text = ""
        self._turn_user_text_persisted = False
        self._current_assistant_text = ""
        self._pending_assistant_delta = ""
        self._flush_task: asyncio.Task | None = None
        self._flush_writing = False
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
            return await run_db_call(method, *args, **kwargs)
        except Exception:
            logger.exception("voice_agent_session_record_failed method=%s session_id=%s", method_name, self.session_id)
            return None

    async def _ensure_turn(self, preferred_turn_id: str = "") -> str:
        clean_preferred = str(preferred_turn_id or "").strip()
        if clean_preferred:
            self._current_turn_id = clean_preferred
        if not self._current_turn_id:
            self._current_turn_id = self._next_turn_id()
        # The pending user text is persisted exactly once per turn; without
        # the flag every assistant delta / audio frame re-wrote it.
        if self._pending_user_text and not self._turn_user_text_persisted:
            await self._call_repository(
                "upsert_turn",
                self.session_id,
                self._current_turn_id,
                user_text=self._pending_user_text,
                fetch_turn=False,
            )
            self._turn_user_text_persisted = True
        return self._current_turn_id

    def _schedule_assistant_flush(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            return
        self._flush_task = asyncio.create_task(self._delayed_assistant_flush())

    async def _delayed_assistant_flush(self) -> None:
        await asyncio.sleep(ASSISTANT_TEXT_FLUSH_SECONDS)
        await self._flush_pending_assistant_text()

    async def _flush_pending_assistant_text(self) -> None:
        """Write any coalesced assistant deltas to the current turn row."""
        task = self._flush_task
        self._flush_task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            if self._flush_writing:
                # A flush already captured the buffer and is mid-write — let
                # it finish instead of cancelling it (cancelling would drop
                # the captured delta). The single DB executor keeps write
                # ordering intact either way.
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            else:
                # Still sleeping — nothing captured yet, safe to cancel.
                task.cancel()
        if not self._pending_assistant_delta or not self._current_turn_id:
            self._pending_assistant_delta = ""
            return
        turn_id = self._current_turn_id
        delta = self._pending_assistant_delta
        self._pending_assistant_delta = ""
        self._flush_writing = True
        try:
            await self._call_repository(
                "upsert_turn",
                self.session_id,
                turn_id,
                assistant_text=delta,
                fetch_turn=False,
            )
        finally:
            self._flush_writing = False

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
        # A barge-in can arrive while the previous turn still has coalesced
        # assistant text waiting to flush — persist it against the old turn
        # before the new one starts.
        await self._flush_pending_assistant_text()
        self._pending_user_text = clean_text
        self._turn_user_text_persisted = False
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
            fetch_turn=False,
        )
        self._turn_user_text_persisted = True
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
        # Coalesce streaming deltas and flush them in one delayed write
        # instead of hitting SQLite once per delta.
        self._pending_assistant_delta += clean_text
        self._schedule_assistant_flush()
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
        # Persist coalesced assistant text before the completion events so
        # the stored turn is complete and event ordering stays intact.
        await self._flush_pending_assistant_text()
        turn_id = await self._ensure_turn()
        status = "interrupted" if interrupted else "completed"
        await self._call_repository(
            "upsert_turn",
            self.session_id,
            turn_id,
            memory_payload=memory_payload or {},
            completed=True,
            interrupted=interrupted,
            completion_status=status,
            fetch_turn=False,
        )
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
        self._turn_user_text_persisted = False
        self._current_turn_id = ""
        self._current_assistant_text = ""
        self._pending_assistant_delta = ""
        self._first_audio_recorded = False
        return turn_id

    async def interrupt_current_turn(self) -> str:
        return await self._finalize_turn(interrupted=True)

    async def complete_turn(self, memory_payload: dict[str, Any] | None = None) -> str:
        return await self._finalize_turn(interrupted=False, memory_payload=memory_payload)

    async def finish(self, *, status: str = "closed") -> None:
        await self._flush_pending_assistant_text()
        await self._call_repository("finish_session", self.session_id, status=status)

    async def complete_session(self, *, status: str = "closed") -> None:
        await self.finish(status=status)

    async def record_turn_completed(
        self,
        turn_id: str = "",
        user_text: str = "",
        ai_text: str = "",
        elapsed_ms: int = 0,
        memory_payload: dict[str, Any] | None = None,
    ) -> str:
        return await self.complete_turn(memory_payload=memory_payload)
