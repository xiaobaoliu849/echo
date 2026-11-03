"""MOSS-Live (MOSI) realtime voice provider mixin.

``wss://api.mosi.cn/v1/realtime?model=moss-live-1.0`` — a full-duplex model
with its own ``action``-keyed JSON events and raw binary PCM frames (16 kHz
up, 48 kHz down, no Base64). Bearer-key auth on the handshake.
Docs: platform.moss.cn/en/docs/reference/moss-live

Turn-taking, barge-in and backchannelling all run server-side; there is no
voice or VAD option. The one thing the server needs from the client is
playback progress: the assistant transcript is released in step with
``playback.chunk.completed`` acks, and a turn whose chunks are never acked is
cut off with ``reason: playback_timeout`` (verified 2026-11-03). Echo's
browser does not report playback, so ``_MossPlaybackClock`` acks each chunk
when it would have finished playing.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import websockets
import websockets.exceptions  # noqa: F401  # explicit: lazy loader hides it otherwise
from fastapi import WebSocket, WebSocketDisconnect

from .background_tasks import spawn_background_task
from .doubao_asr_provider import _get_websockets_header_kwargs
from .interruption_classifier import InterruptionDecisionCoordinator
from .realtime_constants import (
    BASE_REALTIME_INSTRUCTIONS,
    DEFAULT_MOSS_REALTIME_MODEL,
    DEFAULT_MOSS_REALTIME_VOICE,
    DEFAULT_MOSS_REALTIME_WS_URL,
)
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .speaking_coach import current_tutor_instructions
from .voice_agent_tools import VoiceAgentToolSession

logger = logging.getLogger(__name__)

MOSS_INPUT_SAMPLE_RATE = 16000
MOSS_OUTPUT_SAMPLE_RATE = 48000
# 20 ms of 16 kHz mono S16LE — the frame size the server expects.
MOSS_INPUT_FRAME_BYTES = 640
# Head start for the client's jitter buffer before the first chunk is heard.
MOSS_PLAYBACK_LEAD_SECONDS = 0.15

_INVALID_STATUS_CLS = getattr(websockets.exceptions, "InvalidStatus", None)
if _INVALID_STATUS_CLS is None:  # pragma: no cover - legacy websockets
    _INVALID_STATUS_CLS = getattr(websockets.exceptions, "InvalidStatusCode", None)
_WS_INVALID_STATUS = (_INVALID_STATUS_CLS,) if isinstance(_INVALID_STATUS_CLS, type) else ()


def _chunk_key(ctx: dict[str, Any]) -> dict[str, Any]:
    return {key: ctx.get(key) for key in ("chunk_id", "run_id", "turn_id")}


class _MossPlaybackClock:
    """Acks downlink audio chunks on the schedule a client would play them.

    Chunks play back to back from the moment the first one arrives (plus a
    short buffer lead); each is acked when its estimated end time passes.
    ``stop`` reports how far into the current chunk playback got.
    """

    def __init__(self, send_json: Any, *, clock: Any = time.monotonic) -> None:
        self._send_json = send_json
        self._clock = clock
        self._queue: list[dict[str, Any]] = []  # {ctx, start, end}
        self._done_runs: set[str] = set()
        self._run_turns: dict[str, str] = {}
        self._wake = asyncio.Event()

    def add_chunk(self, ctx: dict[str, Any], nbytes: int) -> None:
        duration = nbytes / (MOSS_OUTPUT_SAMPLE_RATE * 2)
        now = self._clock()
        start = max(now + MOSS_PLAYBACK_LEAD_SECONDS, self._queue[-1]["end"] if self._queue else 0.0)
        self._queue.append({"ctx": dict(ctx), "start": start, "end": start + duration})
        self._wake.set()

    def mark_audio_done(self, run_id: str) -> None:
        self._done_runs.add(run_id)
        self._wake.set()

    async def stop(self, run_id: str, turn_id: str) -> None:
        """Playback halted (barge-in): drop queued chunks, report what played."""
        played_ms = 0
        if self._queue:
            head = self._queue[0]
            played_ms = round(max(0.0, min(self._clock(), head["end"]) - head["start"]) * 1000)
        self._queue.clear()
        self._done_runs.discard(run_id)
        self._wake.set()
        await self._send_json({
            "action": "playback.stopped",
            "run_id": run_id,
            "turn_id": turn_id,
            "played_audio_ms": played_ms,
        })

    async def _complete_finished_runs(self) -> None:
        if self._queue:
            return
        while self._done_runs:
            run_id = self._done_runs.pop()
            await self._send_json({
                "action": "playback.completed",
                "run_id": run_id,
                "turn_id": self._run_turns.pop(run_id, ""),
            })

    def note_run_turn(self, run_id: str, turn_id: str) -> None:
        self._run_turns[run_id] = turn_id

    async def run(self) -> None:
        while True:
            self._wake.clear()
            if not self._queue:
                await self._complete_finished_runs()
                await self._wake.wait()
                continue
            head = self._queue[0]
            delay = head["end"] - self._clock()
            if delay > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                continue
            self._queue.pop(0)
            await self._send_json({"action": "playback.chunk.completed", **_chunk_key(head["ctx"])})


class MossRealtimeMixin:
    """MOSS-Live provider methods for RealtimeVoiceService."""

    def _resolve_moss_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("MOSS", model)
        passed_model = model.strip() if (model and model.strip()) else ""
        resolved_model = passed_model or provider_settings["model"].strip() or DEFAULT_MOSS_REALTIME_MODEL
        if not resolved_model.startswith("moss-live"):
            resolved_model = DEFAULT_MOSS_REALTIME_MODEL
        endpoint = provider_settings.get("realtime_base_url", "").strip() or DEFAULT_MOSS_REALTIME_WS_URL
        api_key = provider_settings.get("api_key", "").strip()
        if not api_key:
            raise RuntimeError("MOSS API Key 未配置：请在 设置 → MOSS 中填写 platform.moss.cn 创建的 API Key。")
        return {"api_key": api_key, "model": resolved_model, "endpoint": endpoint}

    @staticmethod
    def _moss_instructions(memory_context: str, tutor_block: str) -> str:
        import datetime

        instructions = (
            f"{BASE_REALTIME_INSTRUCTIONS}\nCurrent Date: {datetime.date.today().isoformat()}."
        )
        if memory_context:
            instructions += (
                "\n\n以下是从长期记忆中检索到的相关历史信息，仅在与用户当前问题相关时参考，不要主动复述：\n"
                f"{memory_context}"
            )
        # The coach persona goes last so it outranks the rules above it.
        return f"{instructions}{tutor_block}"

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    @staticmethod
    async def _moss_await(moss_ws: Any, action: str) -> dict[str, Any]:
        while True:
            raw = await asyncio.wait_for(moss_ws.recv(), timeout=15.0)
            if isinstance(raw, bytes):
                continue
            try:
                event = json.loads(raw)
            except Exception:
                continue
            event_action = str(event.get("action") or "")
            if event_action == action:
                return event.get("data") or {}
            if event_action == "error":
                err = (event.get("data") or {}).get("error") or event
                raise RuntimeError(f"MOSS-Live 会话启动失败: {json.dumps(err, ensure_ascii=False)}")

    async def _moss_handshake(self, moss_ws: Any, *, persona: str | None, instructions: str) -> str:
        """attach_session → session.update → mic on. Returns the server session id."""
        await moss_ws.send(json.dumps({"action": "attach_session"}))
        attached = await self._moss_await(moss_ws, "session_attached")
        session: dict[str, Any] = {"instructions": instructions}
        if persona:
            session["persona"] = {"name": "Echo", "prompt": persona[:8000]}
        await moss_ws.send(json.dumps({"action": "session.update", "session": session}, ensure_ascii=False))
        updated = await self._moss_await(moss_ws, "session.updated")
        if updated.get("error"):
            raise RuntimeError(f"MOSS-Live 会话配置失败: {updated['error']}")
        await moss_ws.send(json.dumps({"action": "mic_state", "enabled": True}))
        return str(attached.get("session_id") or "")

    # ------------------------------------------------------------------
    # Client → MOSS
    # ------------------------------------------------------------------

    async def _client_to_moss_loop(
        self,
        websocket: WebSocket,
        moss_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
        interruption: InterruptionDecisionCoordinator,
    ) -> None:
        pending = bytearray()
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            text_data = message.get("text")
            if text_data:
                try:
                    payload = json.loads(text_data)
                except Exception:
                    await self._send_event(websocket, "error", message="无效的实时语音消息。")
                    continue
                command_type = str(payload.get("type", "")).strip()
                if command_type in {"text_input", "media_input"}:
                    # 协议没有文字/图片触发回复的事件(视频帧需持续推流)。
                    await self._send_event(
                        websocket, "agent_progress",
                        stage="text_context_only",
                        message="MOSS-Live 暂不支持文字或图片输入，请直接说话继续对话。",
                    )
                    continue
                result = await self._handle_common_client_command(
                    command_type, payload,
                    websocket=websocket, memory_session=memory_session,
                    tool_session=tool_session, recorder=recorder,
                    interruption=interruption, provider="MOSS",
                )
                if result == "stop":
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                # Re-frame into the 20 ms frames the server expects.
                pending.extend(audio_bytes)
                while len(pending) >= MOSS_INPUT_FRAME_BYTES:
                    await moss_ws.send(bytes(pending[:MOSS_INPUT_FRAME_BYTES]))
                    del pending[:MOSS_INPUT_FRAME_BYTES]

    # ------------------------------------------------------------------
    # MOSS → client
    # ------------------------------------------------------------------

    async def _moss_interrupt(
        self,
        websocket: WebSocket,
        state: dict[str, Any],
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        if not state.get("speaking"):
            return
        state["speaking"] = False
        state["stopped_runs"].add(state.get("run_id") or "")
        state["ai_text"] = ""
        if recorder is not None:
            try:
                await recorder.interrupt_current_turn()
            except Exception:
                logger.exception("moss_interrupt_turn_failed")
        await self._send_event(websocket, "interrupted", turn_id="", interrupted=True)

    async def _moss_dispatch(
        self,
        websocket: WebSocket,
        moss_ws: Any,
        event: dict[str, Any],
        state: dict[str, Any],
        playback: _MossPlaybackClock,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        interruption: InterruptionDecisionCoordinator,
    ) -> None:
        action = str(event.get("action") or "")
        data = event.get("data") or {}
        run_id = str(data.get("run_id") or "")
        turn_id = str(data.get("turn_id") or "")

        async def inject_memory_context(memory_context: str) -> None:
            # No conversation-item event exists; a mid-session session.update
            # with instructions alone keeps the persona and takes effect on
            # the next reply (verified 2026-11-03).
            if not memory_context or memory_context == state.get("memory_injected"):
                return
            state["memory_injected"] = memory_context
            await moss_ws.send(json.dumps({
                "action": "session.update",
                "session": {"instructions": self._moss_instructions(memory_context, state["tutor_block"])},
            }, ensure_ascii=False))

        if action == "input.speech.started":
            state["user_final_sent"] = False
            begin_utterance = getattr(memory_session, "begin_utterance", None)
            if callable(begin_utterance):
                begin_utterance()
            # Not a barge-in by itself: the server decides semantically and
            # sends response.audio.stop when it really yields the floor.
            return

        if action == "input.transcript.updated":
            # Each update is the full text so far — replace, never append.
            snapshot = str(data.get("text") or "")
            if not snapshot:
                return
            prefetch = getattr(memory_session, "prefetch_partial", None)
            prefetch_task = prefetch(snapshot) if callable(prefetch) else None
            if prefetch_task is not None:
                async def inject_prefetched(task: Any = prefetch_task) -> None:
                    try:
                        result = await task
                        await inject_memory_context(str(result.get("context", "")))
                    except Exception as exc:
                        logger.debug("moss_memory_prefetch_skipped: %s", exc)

                spawn_background_task(inject_prefetched(), name="moss_memory_prefetch")
            await self._send_event(
                websocket, "user_transcript",
                text=snapshot, interim=True, turn_id=state.get("active_turn_id"),
            )
            return

        if action == "input.transcript.done":
            transcript = str(data.get("text") or "").strip()
            if not transcript or state.get("user_final_sent"):
                return
            state["user_final_sent"] = True
            memory_session.note_user_transcript(transcript)
            if recorder is not None:
                voice_turn_id = await recorder.note_user_transcript(transcript)
                if voice_turn_id:
                    state["active_turn_id"] = voice_turn_id
            await self._send_event(
                websocket, "user_transcript",
                text=transcript, turn_id=state.get("active_turn_id"),
            )
            self._spawn_memory_lookup(
                websocket, memory_session, transcript,
                provider="MOSS", on_context=inject_memory_context,
            )
            return

        if action == "response.audio.started":
            state["run_id"] = run_id
            state["speaking"] = True
            state["ai_text"] = ""
            playback.note_run_turn(run_id, turn_id)
            interruption.active_response_id = run_id
            return

        if action == "response.audio.context":
            # Pairs with the next binary frame.
            state["audio_contexts"].append(dict(data))
            return

        if action == "output.transcript.updated" or action == "output.transcript.done":
            if run_id in state["stopped_runs"]:
                return
            text = str(data.get("text") or "")
            if not text or text == state.get("ai_text"):
                return
            state["ai_text"] = text
            await self._emit_assistant_output(
                websocket, interruption,
                {"type": "assistant_text", "text": text, "replace": True, "cumulative": True,
                 "turn_id": state.get("active_turn_id")},
                memory_session=memory_session, recorder=recorder,
            )
            return

        if action == "response.audio.done":
            playback.mark_audio_done(run_id)
            return

        if action == "response.audio.stop":
            await playback.stop(run_id, turn_id)
            await self._moss_interrupt(websocket, state, recorder)
            return

        if action == "response.interrupted":
            await self._moss_interrupt(websocket, state, recorder)
            return

        if action == "response.ended":
            status = str(data.get("status") or "")
            if run_id in state["stopped_runs"]:
                state["stopped_runs"].discard(run_id)
                return
            if status == "aborted":
                await self._moss_interrupt(websocket, state, recorder)
                return
            if status == "failed":
                logger.warning("moss_response_failed: %s", str(event)[:300])
            state["speaking"] = False
            state["ai_text"] = ""
            try:
                await self._finalize_realtime_turn(websocket, memory_session, recorder, gated=False)
            except Exception:
                logger.exception("moss_finalize_turn_failed")
            return

        if action == "error":
            err = data.get("error") or {}
            message = str(err.get("message") or err.get("code") or data or event)
            await self._send_event(websocket, "error", message=f"MOSS-Live 服务错误: {message}")
            return

        # session.updated (memory injection ack) and unknown events: nothing to do.

    async def _moss_to_client_loop(
        self,
        websocket: WebSocket,
        moss_ws: Any,
        state: dict[str, Any],
        playback: _MossPlaybackClock,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        interruption: InterruptionDecisionCoordinator,
    ) -> None:
        while True:
            try:
                raw = await moss_ws.recv()
            except websockets.exceptions.ConnectionClosed as exc:
                if getattr(exc, "code", None) == 1008:
                    await self._send_event(websocket, "error", message=f"MOSS-Live 会话参数无效: {exc}")
                break
            except Exception:
                break

            if isinstance(raw, bytes):
                ctx = state["audio_contexts"].pop(0) if state["audio_contexts"] else {}
                if str(ctx.get("run_id") or "") in state["stopped_runs"]:
                    continue  # tail of a turn the server already cut off
                playback.add_chunk(ctx, len(raw))
                await self._emit_assistant_output(
                    websocket, interruption,
                    {
                        "type": "assistant_audio",
                        "audio": base64.b64encode(raw).decode("ascii"),
                        "encoding": "pcm_s16le",
                        "sample_rate": MOSS_OUTPUT_SAMPLE_RATE,
                        "turn_id": state.get("active_turn_id"),
                    },
                    memory_session=memory_session, recorder=recorder,
                )
                continue

            try:
                event = json.loads(raw)
            except Exception:
                continue
            await self._moss_dispatch(
                websocket, moss_ws, event, state, playback,
                memory_session=memory_session, recorder=recorder, interruption=interruption,
            )

    # ------------------------------------------------------------------
    # Session entry point
    # ------------------------------------------------------------------

    async def _run_moss_session(
        self,
        websocket: WebSocket,
        model: str | None = None,
        instructions: str | None = None,
        memory_session: RealtimeMemorySession | None = None,
        tool_session: VoiceAgentToolSession | None = None,
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        try:
            settings = self._resolve_moss_settings(model)
        except RuntimeError as exc:
            await self._send_event(websocket, "error", message=str(exc))
            return

        url = f"{settings['endpoint']}?{urlencode({'model': settings['model']})}"
        ws_kwargs: dict[str, Any] = {"max_size": 2**24, "ping_interval": 30, "ping_timeout": 30}
        ws_kwargs.update(_get_websockets_header_kwargs({"Authorization": f"Bearer {settings['api_key']}"}))

        interruption = InterruptionDecisionCoordinator()
        memory_session = memory_session or RealtimeMemorySession()
        tool_session = tool_session or VoiceAgentToolSession()
        tutor_block = "" if instructions else current_tutor_instructions()
        state: dict[str, Any] = {
            "active_turn_id": None,   # recorder 话轮 id
            "run_id": "",             # MOSS 在播回复 id
            "speaking": False,
            "ai_text": "",
            "user_final_sent": False,
            "memory_injected": "",
            "audio_contexts": [],     # response.audio.context 待配对的二进制帧
            "stopped_runs": set(),    # 已被打断、残余下行须丢弃的 run_id
            "tutor_block": tutor_block,
        }

        try:
            async with websockets.connect(url, **ws_kwargs) as moss_ws:
                try:
                    server_session_id = await self._moss_handshake(
                        moss_ws,
                        persona=instructions,
                        instructions=self._moss_instructions("", tutor_block),
                    )
                except Exception as exc:
                    logger.error("moss_handshake_failed: %s", exc)
                    await self._send_event(websocket, "error", message=str(exc))
                    return
                logger.debug("moss_session_id: %s", server_session_id)

                await self._send_event(
                    websocket,
                    "session_open",
                    provider="MOSS",
                    model=settings["model"],
                    voice=DEFAULT_MOSS_REALTIME_VOICE,
                    session_id=recorder.session_id if recorder is not None else "",
                    mode="duplex_dialogue",
                )

                async def send_json(payload: dict[str, Any]) -> None:
                    await moss_ws.send(json.dumps(payload))

                playback = _MossPlaybackClock(send_json)
                playback_task = asyncio.create_task(playback.run())
                client_task = asyncio.create_task(
                    self._client_to_moss_loop(
                        websocket, moss_ws, memory_session, tool_session, recorder, interruption,
                    )
                )
                moss_task = asyncio.create_task(
                    self._moss_to_client_loop(
                        websocket, moss_ws, state, playback,
                        memory_session, recorder, interruption,
                    )
                )
                try:
                    await self._run_duplex_tasks(client_task, moss_task)
                finally:
                    # MOSS bills until the socket closes; leaving the context
                    # manager closes it.
                    playback_task.cancel()
                    await asyncio.gather(playback_task, return_exceptions=True)
        except WebSocketDisconnect:
            return
        except _WS_INVALID_STATUS as exc:
            status_code = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code in (401, 403):
                err_msg = f"MOSS-Live 鉴权失败 (HTTP {status_code})：请检查 设置 → MOSS 中的 API Key 是否正确、是否已过期。"
            else:
                err_msg = f"MOSS-Live WebSocket 连接被拒绝 (HTTP {status_code or exc})。"
            logger.error("moss_ws_connect_failed: %s", exc)
            await self._send_event(websocket, "error", message=err_msg)
        except Exception as exc:
            logger.exception("moss_session_failed")
            await self._send_event(websocket, "error", message=f"MOSS-Live 实时语音连接失败: {exc}")

    async def stream_moss_session(
        self,
        websocket: WebSocket,
        model: str | None = None,
        instructions: str | None = None,
    ) -> None:
        recorder = await self._create_voice_session_recorder(
            provider="MOSS",
            model=model or DEFAULT_MOSS_REALTIME_MODEL,
            voice=DEFAULT_MOSS_REALTIME_VOICE,
        )
        try:
            await self._run_moss_session(
                websocket, model=model, instructions=instructions, recorder=recorder,
            )
        finally:
            if recorder is not None:
                await recorder.finish()
