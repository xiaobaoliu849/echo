"""Recalled-memory injection for server-VAD realtime sessions.

Server-VAD providers (Qwen-Omni, Qwen-Audio) start the reply the moment the
user stops speaking, before the final transcript reaches us. Memory therefore
has to be in the session instructions *before* speech ends to shape the reply
it was recalled for. This helper:

* starts the memory search from interim ASR (``on_partial``) and pushes the
  result as soon as it lands, usually while the user is still talking;
* re-checks on the final transcript (``on_final``), reusing that search;
* runs every lookup off the provider's event loop, chained so turns apply in
  order and a slow EverOS call never delays transcripts or reply audio;
* keeps memory that arrived too late for the current reply until the end of
  the next reply instead of wiping it at turn end (``on_turn_complete``).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from .background_tasks import spawn_background_task
from .realtime_memory_session import RealtimeMemorySession

logger = logging.getLogger(__name__)

SendEvent = Callable[..., Awaitable[None]]


class RealtimeMemoryInjector:
    def __init__(
        self,
        memory_session: RealtimeMemorySession,
        *,
        build_instructions: Callable[[str], str],
        build_recall_miss: Callable[[str], str],
        push_instructions: Callable[[str], Awaitable[None]],
        send_event: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._memory = memory_session
        self._build_instructions = build_instructions
        self._build_recall_miss = build_recall_miss
        self._push = push_instructions
        self._send_event = send_event
        self._chain: asyncio.Task[Any] | None = None
        # Number of replies the server has started; memory pushed while reply
        # N is running is only visible from reply N + 1 on.
        self._response_seq = 0
        self._active_instructions = ""
        self._active_seq = -1
        # Recalled memory may serve the next reply; a "nothing found" prompt
        # must not, or an unrelated later reply apologises for a lookup.
        self._active_carry = False
        # A prefetch that injected memory, kept to announce it once the final
        # transcript (which resets the client's per-turn memory state) is out.
        self._prefetched: tuple[str, dict[str, Any]] | None = None

    # -- provider hooks -----------------------------------------------------

    def note_response_started(self) -> None:
        self._response_seq += 1

    def on_partial(self, text: str, utterance_id: str = "") -> None:
        prefetch = getattr(self._memory, "prefetch_partial", None)
        task = prefetch(text, utterance_id) if callable(prefetch) else None
        if task is None:
            return
        self._enqueue(self._apply_prefetch(task, utterance_id))

    def on_final(self, user_text: str, utterance_id: str = "", *, settle: bool = False) -> None:
        self._enqueue(self._apply_final(user_text, utterance_id, settle=settle))

    async def on_turn_complete(self) -> None:
        """Restore the base instructions unless memory still awaits its reply."""
        if self._active_instructions and self._active_carry and self._active_seq >= self._response_seq:
            # Pushed after the reply that just finished had started: it has
            # not shaped any reply yet, so keep it for the next one.
            logger.info("voice_memory_inject carried_to_next_reply")
            return
        self._active_instructions = ""
        self._active_seq = -1
        self._active_carry = False
        await self._push(self._build_instructions(""))

    # -- internals ----------------------------------------------------------

    def _enqueue(self, coro: Awaitable[None]) -> None:
        previous = self._chain

        async def run() -> None:
            if previous is not None and not previous.done():
                # asyncio.wait never raises for the awaited task's own failure
                # or cancellation, while our own cancellation still propagates.
                await asyncio.wait({previous})
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The session may have closed while the lookup was in flight.
                logger.debug("voice_memory_inject_skipped: %s", exc)

        self._chain = spawn_background_task(run(), name="voice_memory_inject")

    async def _apply_prefetch(self, task: "asyncio.Task[dict[str, Any]]", utterance_id: str) -> None:
        result = await task
        context = str(result.get("context", ""))
        if not context:
            return
        await self._apply_instructions(self._build_instructions(context), carry=True)
        # Not announced yet: the user may still be finishing their sentence
        # while the previous reply's turn is open, and the client attributes
        # memory_context to whichever turn is current.
        self._prefetched = (utterance_id, result)

    async def _apply_final(self, user_text: str, utterance_id: str, *, settle: bool) -> None:
        if settle:
            # Let a barge-in cancel land before the session is updated.
            await asyncio.sleep(0.2)
        result = await self._memory.retrieve_memory_context(utterance_id, query=user_text)
        context = str(result.get("context", ""))
        prefetched: dict[str, Any] | None = None
        if self._prefetched is not None:
            prefetch_id, prefetch_result = self._prefetched
            self._prefetched = None
            # Only this utterance's prefetch; one from an utterance that never
            # produced a final transcript must not be credited to this one.
            if not prefetch_id or not utterance_id or prefetch_id == utterance_id:
                prefetched = prefetch_result
        if result.get("attempted"):
            await self._announce(result)
        elif prefetched is not None:
            # The final wording no longer passes the recall gate, but memory
            # from this utterance's prefetch is already in the session.
            await self._announce(prefetched)
        if context and prefetched is not None and result.get("prefetched"):
            # Same memory the prefetch already put in the session before the
            # reply; pushing it again (possibly after that reply finished)
            # would make it look late and carry it into the next reply.
            return
        if context:
            logger.info(
                "voice_memory_inject scope=%s count=%s local_pending=%s cloud=%s prefetched=%s",
                self._memory._config.memory_scope,
                int(result.get("memories_retrieved", 0)),
                int(result.get("local_pending_count", 0)),
                int(result.get("cloud_count", 0)),
                bool(result.get("prefetched")),
            )
            await self._apply_instructions(self._build_instructions(context), carry=True)
        elif prefetched is None and self._memory.is_forced_recall_query(user_text):
            logger.info(
                "voice_memory_inject scope=%s count=0 forced_recall=true",
                self._memory._config.memory_scope,
            )
            await self._apply_instructions(self._build_recall_miss(user_text), carry=False)

    async def _apply_instructions(self, instructions: str, *, carry: bool) -> None:
        if instructions == self._active_instructions:
            return
        await self._push(instructions)
        self._active_instructions = instructions
        self._active_seq = self._response_seq
        self._active_carry = carry

    async def _announce(self, result: dict[str, Any]) -> None:
        await self._send_event(
            "memory_context",
            {
                "memories_retrieved": int(result.get("memories_retrieved", 0)),
                "local_pending_count": int(result.get("local_pending_count", 0)),
                "cloud_count": int(result.get("cloud_count", 0)),
                "attempted": True,
            },
        )
