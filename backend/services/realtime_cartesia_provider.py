"""Cartesia realtime voice provider mixin.

Unlike the speech-to-speech providers (Gemini Live, Qwen-Omni, ...), Cartesia
ships best-in-class STT and TTS but no LLM — the conversation brain is plugged
in by us. The pipeline per user turn is:

    mic PCM 16kHz → Cartesia Ink-2 STT (built-in *semantic* turn detection)
                  → DeepSeek chat model (streaming, low-latency flash tier)
                  → Cartesia Sonic TTS (WebSocket contexts, PCM s16le 24kHz)
                  → client

Turn-taking is driven entirely by Ink-2 turn events (``turn.start`` /
``turn.end``), which deliberately replaces both a VAD and the rule-based
``InterruptionClassifier`` used by the other providers: when the user starts
speaking while a reply is generating or playing, the LLM stream and the Sonic
context are cancelled immediately (true barge-in, no classification step).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .cartesia_tts_provider import (
    CARTESIA_VERSION,
    DEFAULT_CARTESIA_BASE_URL,
    DEFAULT_CARTESIA_MODEL,
    DEFAULT_CARTESIA_VOICE,
    infer_cartesia_language,
)
from .interruption_classifier import InterruptionDecisionCoordinator
from .llm_service import LLMService
from .realtime_constants import (
    DEFAULT_CARTESIA_REALTIME_MODEL,
    DEFAULT_CARTESIA_STT_MODEL,
)
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .voice_agent_tools import VoiceAgentToolSession

logger = logging.getLogger(__name__)

# Markdown symbols are stripped before text is pushed to Sonic (same rule as
# the shared _deliver_assistant_output display path).
_TTS_TEXT_NOISE_RE = re.compile(r"[\*#`]")

# Keep the LLM prompt bounded on long sessions.
_CARTESIA_MAX_HISTORY_MESSAGES = 20


@dataclass
class _CartesiaTurn:
    seq: int
    context_id: str
    user_text: str
    task: "asyncio.Task[None] | None" = None


@dataclass
class _CartesiaSessionState:
    tts_model: str
    voice: str
    llm_model: str
    tts_ws: Any = None
    stt_ws: Any = None
    history: list[dict[str, str]] = field(default_factory=list)
    active: _CartesiaTurn | None = None
    # Seq of the turn whose LLM stream has finished; the TTS `done` event for
    # that context finalizes the turn.
    generation_done_seq: int = 0
    seq: int = 0
    tts_send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class CartesiaRealtimeMixin:
    """Cartesia (Ink-2 STT → DeepSeek → Sonic TTS) provider methods."""

    def _resolve_cartesia_settings(self, model: str | None) -> dict[str, str]:
        cartesia = self.config.get_provider_settings("Cartesia", model)
        api_key = cartesia["api_key"].strip()
        if not api_key:
            raise RuntimeError("Cartesia API Key 未配置，无法启动实时语音会话。请在 设置 → Cartesia 中填写 cartesia_api_key。")
        base_url = (cartesia["base_url"] or DEFAULT_CARTESIA_BASE_URL).rstrip("/")
        realtime_base = str(cartesia.get("realtime_base_url", "")).strip().rstrip("/")
        if realtime_base:
            ws_base = realtime_base
        else:
            ws_base = re.sub(r"^https://", "wss://", re.sub(r"^http://", "ws://", base_url))

        cfg = self.config.get_all()
        cartesia_models = cfg.get("default_models", {}).get("Cartesia", {})
        tts_model = str(cartesia_models.get("tts_default", "")).strip() or DEFAULT_CARTESIA_MODEL

        deepseek = self.config.get_provider_settings("DeepSeek")
        llm_api_key = deepseek["api_key"].strip()
        if not llm_api_key:
            raise RuntimeError(
                "DeepSeek API Key 未配置。Cartesia 实时会话使用 DeepSeek 作为对话模型，"
                "请在 设置 → DeepSeek 中填写 deepseek_api_key。"
            )
        llm_model = deepseek["model"].strip() or "deepseek-v4-flash"

        session_model = (model or "").strip() or DEFAULT_CARTESIA_REALTIME_MODEL
        return {
            "api_key": api_key,
            "ws_base": ws_base,
            "tts_model": tts_model,
            "llm_model": llm_model,
            "session_model": session_model,
        }

    # -- barge-in ------------------------------------------------------------

    async def _cartesia_barge_in(
        self,
        websocket: WebSocket,
        state: _CartesiaSessionState,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        *,
        notify: bool = True,
    ) -> None:
        """Cancel the in-flight reply immediately (no classifier: Ink-2's
        semantic turn.start *is* the interruption decision)."""
        turn = state.active
        if turn is None:
            return
        state.active = None
        if turn.task is not None and not turn.task.done():
            turn.task.cancel()
            try:
                await turn.task
            except (asyncio.CancelledError, Exception):
                pass
        if state.tts_ws is not None:
            try:
                async with state.tts_send_lock:
                    await state.tts_ws.send(json.dumps({"context_id": turn.context_id, "cancel": True}))
            except Exception:
                pass
        # Roll back the unanswered user turn so the next reply is not
        # conditioned on a question the assistant never answered.
        if state.history and state.history[-1] == {"role": "user", "content": turn.user_text}:
            state.history.pop()
        discard_memory_turn = getattr(memory_session, "discard_turn", None)
        if callable(discard_memory_turn):
            discard_memory_turn()
        interrupted_turn_id = ""
        if recorder is not None:
            interrupted_turn_id = recorder.current_turn_id
            await recorder.interrupt_current_turn()
        if notify:
            await self._send_event(
                websocket,
                "interrupted",
                candidate_id="",
                turn_id=interrupted_turn_id,
                interrupted=True,
                stop_latency_ms=0,
            )

    # -- per-turn generation (DeepSeek stream → Sonic context) ---------------

    async def _cartesia_generate(
        self,
        websocket: WebSocket,
        state: _CartesiaSessionState,
        turn: _CartesiaTurn,
        instructions: str,
        llm: LLMService,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        base_msg: dict[str, Any] = {
            "model_id": state.tts_model,
            "voice": {"id": state.voice},
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000},
            "language": infer_cartesia_language(turn.user_text),
            "context_id": turn.context_id,
            "max_buffer_delay_ms": 500,
        }
        messages = [{"role": "system", "content": instructions}] + list(state.history)
        assistant_parts: list[str] = []

        async def close_context() -> None:
            if state.tts_ws is None:
                return
            async with state.tts_send_lock:
                await state.tts_ws.send(
                    json.dumps({**base_msg, "transcript": "", "continue": False})
                )

        try:
            async for event in llm.chat_completion_stream(
                provider="DeepSeek",
                messages=messages,
                model=state.llm_model,
                temperature=0.7,
                max_tokens=512,
                use_memory=False,  # realtime memory is handled by RealtimeMemorySession
            ):
                if event.get("type") != "delta":
                    continue
                delta = str(event.get("content", ""))
                if not delta:
                    continue
                assistant_parts.append(delta)
                tts_delta = _TTS_TEXT_NOISE_RE.sub("", delta)
                if tts_delta and state.tts_ws is not None:
                    async with state.tts_send_lock:
                        await state.tts_ws.send(
                            json.dumps({**base_msg, "transcript": tts_delta, "continue": True})
                        )
                await self._deliver_assistant_output(
                    websocket,
                    {"type": "assistant_text", "text": delta},
                    memory_session=memory_session,
                    recorder=recorder,
                )
            await close_context()
            reply = "".join(assistant_parts).strip()
            if reply:
                state.history.append({"role": "assistant", "content": reply})
                del state.history[: max(0, len(state.history) - _CARTESIA_MAX_HISTORY_MESSAGES)]
            state.generation_done_seq = turn.seq
        except asyncio.CancelledError:
            # Barge-in: halt any not-yet-started Sonic generation for this context.
            if state.tts_ws is not None:
                try:
                    async with state.tts_send_lock:
                        await state.tts_ws.send(
                            json.dumps({"context_id": turn.context_id, "cancel": True})
                        )
                except Exception:
                    pass
            raise
        except Exception as exc:
            logger.exception("cartesia_turn_failed seq=%s", turn.seq)
            await self._send_event(websocket, "error", message=f"Cartesia 会话生成失败: {exc}")
            try:
                await close_context()
            except Exception:
                pass
            if state.active is turn:
                state.active = None
                await self._finalize_realtime_turn(websocket, memory_session, recorder)

    async def _cartesia_start_turn(
        self,
        websocket: WebSocket,
        state: _CartesiaSessionState,
        user_text: str,
        llm: LLMService,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        user_text = user_text.strip()
        if not user_text:
            return
        await self._cartesia_barge_in(
            websocket, state, memory_session, recorder, notify=True
        )

        memory_session.note_user_transcript(user_text)
        voice_turn_id = ""
        if recorder is not None:
            voice_turn_id = await recorder.note_user_transcript(user_text)
        await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id, final=True)

        retrieval = await memory_session.retrieve_memory_context()
        if retrieval.get("attempted"):
            await self._send_event(
                websocket,
                "memory_context",
                memories_retrieved=int(retrieval.get("memories_retrieved", 0)),
                local_pending_count=int(retrieval.get("local_pending_count", 0)),
                cloud_count=int(retrieval.get("cloud_count", 0)),
                attempted=True,
            )
        instructions = self._build_realtime_instructions(str(retrieval.get("context", "")))

        state.history.append({"role": "user", "content": user_text})
        seq = state.next_seq()
        turn = _CartesiaTurn(
            seq=seq,
            context_id=f"vs-{seq}-{uuid.uuid4().hex[:12]}",
            user_text=user_text,
        )
        turn.task = asyncio.create_task(
            self._cartesia_generate(
                websocket, state, turn, instructions, llm, memory_session, recorder
            )
        )
        state.active = turn

    # -- IO loops --------------------------------------------------------------

    async def _cartesia_client_loop(
        self,
        websocket: WebSocket,
        state: _CartesiaSessionState,
        llm: LLMService,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        # Unused by this provider (no interruption classification) but required
        # by the shared common-command handler.
        interruption = InterruptionDecisionCoordinator()
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
                if command_type == "text_input":
                    await self._cartesia_start_turn(
                        websocket, state, str(payload.get("text", "")),
                        llm, memory_session, tool_session, recorder,
                    )
                    continue
                if command_type == "media_input":
                    await self._send_event(
                        websocket, "error",
                        message="Cartesia 实时会话暂不支持图片输入，请使用文字或语音。",
                    )
                    continue
                result = await self._handle_common_client_command(
                    command_type, payload,
                    websocket=websocket, memory_session=memory_session,
                    tool_session=tool_session, recorder=recorder,
                    interruption=interruption, provider="Cartesia",
                )
                if result == "stop":
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes and state.stt_ws is not None:
                await state.stt_ws.send(audio_bytes)

    async def _cartesia_stt_loop(
        self,
        websocket: WebSocket,
        state: _CartesiaSessionState,
        llm: LLMService,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        assert state.stt_ws is not None
        async for raw_message in state.stt_ws:
            try:
                event = json.loads(raw_message)
            except Exception:
                continue
            event_type = str(event.get("type", ""))
            if event_type == "turn.start":
                # Semantic barge-in: the user started speaking — stop any
                # in-flight reply immediately.
                await self._cartesia_barge_in(websocket, state, memory_session, recorder)
            elif event_type == "turn.end":
                transcript = str(event.get("transcript", "")).strip()
                if transcript:
                    await self._cartesia_start_turn(
                        websocket, state, transcript,
                        llm, memory_session, tool_session, recorder,
                    )
            elif event_type == "error":
                await self._send_event(
                    websocket, "error",
                    message=f"Cartesia STT: {event.get('message', 'unknown error')}",
                )

    async def _cartesia_tts_loop(
        self,
        websocket: WebSocket,
        state: _CartesiaSessionState,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        assert state.tts_ws is not None
        async for raw_message in state.tts_ws:
            try:
                event = json.loads(raw_message)
            except Exception:
                continue
            event_type = str(event.get("type", ""))
            context_id = str(event.get("context_id", ""))
            active = state.active

            if event_type == "chunk":
                audio = event.get("audio")
                if not audio:
                    continue
                # Drop audio from superseded (barged-in) contexts.
                if active is None or context_id != active.context_id:
                    continue
                await self._deliver_assistant_output(
                    websocket,
                    {
                        "type": "assistant_audio",
                        "audio": str(audio),
                        "encoding": "pcm_s16le",
                        "sample_rate": 24000,
                    },
                    memory_session=memory_session,
                    recorder=recorder,
                    record_memory=False,
                )
            elif event_type == "done":
                if active is None or context_id != active.context_id:
                    continue
                if state.generation_done_seq != active.seq:
                    # LLM still streaming; `done` here can only belong to a
                    # cancelled context — ignore defensively.
                    continue
                state.active = None
                await self._finalize_realtime_turn(websocket, memory_session, recorder)
            elif event_type == "error":
                await self._send_event(
                    websocket, "error",
                    message=f"Cartesia TTS: {event.get('message', event.get('error', 'unknown error'))}",
                )

    # -- session entry point ---------------------------------------------------

    async def stream_cartesia_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_CARTESIA_VOICE,
    ) -> None:
        settings = self._resolve_cartesia_settings(model)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession(default_provider="DeepSeek")
        recorder = await self._create_voice_session_recorder(
            provider="Cartesia",
            model=settings["session_model"],
            voice=voice,
        )
        llm = LLMService(config=self.config)

        state = _CartesiaSessionState(
            tts_model=settings["tts_model"],
            voice=voice,
            llm_model=settings["llm_model"],
        )
        headers = {"Authorization": f"Bearer {settings['api_key']}"}
        ws_base = settings["ws_base"]
        stt_url = (
            f"{ws_base}/stt/turns/websocket"
            f"?model={DEFAULT_CARTESIA_STT_MODEL}&encoding=pcm_s16le&sample_rate=16000"
            f"&cartesia_version={CARTESIA_VERSION}"
        )
        tts_url = f"{ws_base}/tts/websocket?cartesia_version={CARTESIA_VERSION}"

        try:
            async with websockets.connect(
                stt_url, additional_headers=headers, max_size=2**24,
                ping_interval=30, ping_timeout=30,
            ) as stt_ws:
                async with websockets.connect(
                    tts_url, additional_headers=headers, max_size=2**24,
                    ping_interval=30, ping_timeout=30,
                ) as tts_ws:
                    state.stt_ws = stt_ws
                    state.tts_ws = tts_ws
                    await self._send_event(
                        websocket,
                        "session_open",
                        provider="Cartesia",
                        model=settings["session_model"],
                        voice=voice,
                        session_id=recorder.session_id if recorder is not None else "",
                    )
                    await self._run_duplex_tasks(
                        asyncio.create_task(
                            self._cartesia_client_loop(
                                websocket, state, llm, memory_session, tool_session, recorder
                            )
                        ),
                        asyncio.create_task(
                            self._cartesia_stt_loop(
                                websocket, state, llm, memory_session, tool_session, recorder
                            )
                        ),
                        asyncio.create_task(
                            self._cartesia_tts_loop(websocket, state, memory_session, recorder)
                        ),
                    )
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.exception("Cartesia realtime session failed: %s", exc)
            await self._send_event(websocket, "error", message=f"Cartesia 实时会话启动失败: {exc}")
        finally:
            try:
                await self._cartesia_barge_in(
                    websocket, state, memory_session, recorder, notify=False
                )
            except Exception:
                pass
            if state.stt_ws is not None:
                try:
                    await state.stt_ws.send(json.dumps({"type": "close"}))
                except Exception:
                    pass
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain(cancel=True)
            if recorder is not None:
                await recorder.finish()
