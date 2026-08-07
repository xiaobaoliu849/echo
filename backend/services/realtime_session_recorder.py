from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .voice_agent_session_repository import VoiceAgentSessionRepository
from .realtime_memory_session import _merge_memory_text

logger = logging.getLogger(__name__)


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
