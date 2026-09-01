"""Gradium realtime voice provider mixin.

Pipeline per user turn:
    mic PCM → Gradium ASR (wss://api.gradium.ai/api/speech/asr)
            → DeepSeek / LLM (streaming tokens)
            → Gradium TTS (wss://api.gradium.ai/api/speech/tts)
            → client WebSocket

Supports low-latency audio streaming, turn finalization, and barge-in interruption.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .gradium_tts_provider import (
    DEFAULT_GRADIUM_BASE_URL,
    DEFAULT_GRADIUM_MODEL,
    DEFAULT_GRADIUM_VOICE,
    gradium_headers,
    is_gradium_voice,
)
from .interruption_classifier import InterruptionDecisionCoordinator
from .llm_service import LLMService
from .realtime_constants import (
    DEFAULT_GRADIUM_REALTIME_MODEL,
    DEFAULT_GRADIUM_REALTIME_VOICE,
)
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .voice_agent_tools import VoiceAgentToolSession

logger = logging.getLogger(__name__)

_TTS_TEXT_NOISE_RE = re.compile(r"[\*#`]")
_GRADIUM_MAX_HISTORY_MESSAGES = 20
_GRADIUM_TTS_SPLIT_RE = re.compile(r"([^,.;:!?\n，。！？；：\s]+[,.;:!?\n，。！？；：\s]+)")


def _split_gradium_tts_chunks(buffer: str, is_final: bool = False) -> tuple[list[str], str]:
    """Split streamed LLM text buffer into safe TTS chunks on word/punctuation boundaries.

    Gradium TTS inserts a single space between consecutive text messages. This
    function ensures text is never split mid-word.
    """
    chunks: list[str] = []
    pos = 0
    for match in _GRADIUM_TTS_SPLIT_RE.finditer(buffer):
        chunk = match.group(1).strip()
        if chunk:
            chunks.append(chunk)
        pos = match.end()
    remaining = buffer[pos:]
    if not is_final and len(remaining) >= 20:
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", remaining):
            chunks.append(remaining[:12].strip())
            remaining = remaining[12:]
    if is_final and remaining.strip():
        chunks.append(remaining.strip())
        remaining = ""
    return chunks, remaining


def _join_transcript_pieces(pieces: list[str]) -> str:
    """Join recognized words/tokens cleanly into a natural sentence."""
    if not pieces:
        return ""
    out: list[str] = []
    for piece in pieces:
        p = piece.strip()
        if not p:
            continue
        if not out:
            out.append(p)
            continue
        prev = out[-1]
        is_prev_cjk = bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]$", prev))
        is_next_cjk = bool(re.search(r"^[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", p))
        if is_prev_cjk or is_next_cjk or p in {",", ".", "!", "?", ";", ":", "，", "。", "！", "？", "；", "："}:
            out.append(p)
        else:
            out.append(" " + p)
    return "".join(out).strip()


@dataclass
class _GradiumTurn:
    seq: int
    user_text: str
    task: "asyncio.Task[None] | None" = None


@dataclass
class _GradiumSessionState:
    tts_model: str
    voice: str
    llm_model: str
    api_key: str
    ws_base: str
    tts_ws: Any = None
    stt_ws: Any = None
    history: list[dict[str, str]] = field(default_factory=list)
    active: _GradiumTurn | None = None
    generation_done_seq: int = 0
    seq: int = 0
    tts_send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class GradiumRealtimeMixin:
    """Gradium (ASR → LLM → Gradium TTS) provider methods."""

    def _resolve_gradium_settings(self, model: str | None) -> dict[str, str]:
        gradium = self.config.get_provider_settings("Gradium", model)
        api_key = gradium["api_key"].strip()
        if not api_key:
            raise RuntimeError("Gradium API Key 未配置，无法启动实时语音会话。请在 设置 → Gradium 中填写 gradium_api_key。")
        base_url = (gradium["base_url"] or DEFAULT_GRADIUM_BASE_URL).rstrip("/")
        realtime_base = str(gradium.get("realtime_base_url", "")).strip().rstrip("/")
        if realtime_base:
            ws_base = realtime_base
        else:
            ws_base = re.sub(r"^https://", "wss://", re.sub(r"^http://", "ws://", base_url))

        cfg = self.config.get_all()
        gradium_models = cfg.get("default_models", {}).get("Gradium", {})
        tts_model = str(gradium_models.get("tts_default", "")).strip() or DEFAULT_GRADIUM_MODEL

        deepseek = self.config.get_provider_settings("DeepSeek")
        llm_api_key = deepseek["api_key"].strip()
        if not llm_api_key:
            # Fallback to OpenAI or SiliconFlow if DeepSeek is not configured
            for alt_provider in ("SiliconFlow", "OpenAI", "DashScope", "Groq"):
                alt_cfg = self.config.get_provider_settings(alt_provider)
                if alt_cfg["api_key"].strip():
                    llm_model = alt_cfg["model"].strip() or "default"
                    llm_provider = alt_provider
                    break
            else:
                raise RuntimeError(
                    "未配置对话 LLM API Key。Gradium 实时会话默认使用 DeepSeek 作为大脑模型，"
                    "请在 设置 → DeepSeek (或其他模型提供商) 中配置 API Key。"
                )
        else:
            llm_model = deepseek["model"].strip() or "deepseek-v4-flash"
            llm_provider = "DeepSeek"

        session_model = (model or "").strip() or DEFAULT_GRADIUM_REALTIME_MODEL
        return {
            "api_key": api_key,
            "ws_base": ws_base,
            "tts_model": tts_model,
            "llm_model": llm_model,
            "llm_provider": llm_provider,
            "session_model": session_model,
        }

    # -- barge-in ------------------------------------------------------------

    async def _gradium_barge_in(
        self,
        websocket: WebSocket,
        state: _GradiumSessionState,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        *,
        notify: bool = True,
    ) -> None:
        """Cancel the in-flight reply immediately on user interruption."""
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

    # -- per-turn generation (LLM stream → Gradium TTS) ----------------------

    async def _gradium_generate(
        self,
        websocket: WebSocket,
        state: _GradiumSessionState,
        turn: _GradiumTurn,
        instructions: str,
        llm: LLMService,
        llm_provider: str,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        messages = [{"role": "system", "content": instructions}] + list(state.history)
        assistant_parts: list[str] = []

        tts_url = f"{state.ws_base}/api/speech/tts"
        headers = {"x-api-key": state.api_key}

        try:
            async with websockets.connect(
                tts_url,
                additional_headers=headers,
                max_size=2**24,
                ping_interval=30,
                ping_timeout=30,
            ) as tts_ws:
                setup_msg = {
                    "type": "setup",
                    "model_name": state.tts_model or DEFAULT_GRADIUM_MODEL,
                    "voice_id": state.voice or DEFAULT_GRADIUM_VOICE,
                    "output_format": "pcm",
                }
                await tts_ws.send(json.dumps(setup_msg))

                # Wait for ready response
                ready_resp = await tts_ws.recv()
                try:
                    ready_data = json.loads(ready_resp)
                    sample_rate = int(ready_data.get("sample_rate", 48000))
                except Exception:
                    sample_rate = 48000

                async def recv_tts_audio() -> None:
                    async for raw_msg in tts_ws:
                        try:
                            msg = json.loads(raw_msg)
                        except Exception:
                            continue
                        mtype = msg.get("type")
                        if mtype == "audio":
                            audio_b64 = msg.get("audio")
                            if audio_b64:
                                await self._deliver_assistant_output(
                                    websocket,
                                    {
                                        "type": "assistant_audio",
                                        "audio": str(audio_b64),
                                        "encoding": "pcm_s16le",
                                        "sample_rate": sample_rate,
                                    },
                                    memory_session=memory_session,
                                    recorder=recorder,
                                    record_memory=False,
                                )
                        elif mtype == "end_of_stream":
                            break
                        elif mtype == "error":
                            logger.error("Gradium TTS error: %s", msg)
                            break

                recv_task = asyncio.create_task(recv_tts_audio())

                text_buffer = ""
                try:
                    async for event in llm.chat_completion_stream(
                        provider=llm_provider,
                        messages=messages,
                        model=state.llm_model,
                        temperature=0.7,
                        max_tokens=512,
                        use_memory=False,
                    ):
                        if event.get("type") != "delta":
                            continue
                        delta = str(event.get("content", ""))
                        if not delta:
                            continue
                        assistant_parts.append(delta)
                        tts_delta = _TTS_TEXT_NOISE_RE.sub("", delta)
                        if tts_delta:
                            text_buffer += tts_delta
                            chunks, text_buffer = _split_gradium_tts_chunks(text_buffer, is_final=False)
                            for chunk in chunks:
                                if chunk:
                                    await tts_ws.send(json.dumps({"type": "text", "text": chunk}))

                        await self._deliver_assistant_output(
                            websocket,
                            {"type": "assistant_text", "text": delta},
                            memory_session=memory_session,
                            recorder=recorder,
                        )

                    # Flush remaining buffered text
                    chunks, text_buffer = _split_gradium_tts_chunks(text_buffer, is_final=True)
                    for chunk in chunks:
                        if chunk:
                            await tts_ws.send(json.dumps({"type": "text", "text": chunk}))

                    # Send end of stream to signal text completion
                    await tts_ws.send(json.dumps({"type": "end_of_stream"}))
                    await recv_task
                except asyncio.CancelledError:
                    recv_task.cancel()
                    raise

            reply = "".join(assistant_parts).strip()
            if reply:
                state.history.append({"role": "assistant", "content": reply})
                del state.history[: max(0, len(state.history) - _GRADIUM_MAX_HISTORY_MESSAGES)]
            state.generation_done_seq = turn.seq
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("gradium_turn_failed seq=%s", turn.seq)
            await self._send_event(websocket, "error", message=f"Gradium 会话生成失败: {exc}")
        finally:
            if state.active is turn:
                state.active = None
                await self._finalize_realtime_turn(websocket, memory_session, recorder)

    async def _gradium_start_turn(
        self,
        websocket: WebSocket,
        state: _GradiumSessionState,
        user_text: str,
        llm: LLMService,
        llm_provider: str,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        user_text = user_text.strip()
        if not user_text:
            return
        await self._gradium_barge_in(websocket, state, memory_session, recorder, notify=True)

        memory_session.note_user_transcript(user_text)
        voice_turn_id = ""
        if recorder is not None:
            voice_turn_id = await recorder.note_user_transcript(user_text)
        await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)

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
        turn = _GradiumTurn(seq=seq, user_text=user_text)
        turn.task = asyncio.create_task(
            self._gradium_generate(
                websocket, state, turn, instructions, llm, llm_provider, memory_session, recorder
            )
        )
        state.active = turn

    # -- IO loops --------------------------------------------------------------

    async def _gradium_client_loop(
        self,
        websocket: WebSocket,
        state: _GradiumSessionState,
        llm: LLMService,
        llm_provider: str,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
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
                    await self._gradium_start_turn(
                        websocket, state, str(payload.get("text", "")),
                        llm, llm_provider, memory_session, tool_session, recorder,
                    )
                    continue
                if command_type == "media_input":
                    await self._send_event(
                        websocket, "error",
                        message="Gradium 实时会话暂不支持图片输入，请使用文字或语音。",
                    )
                    continue
                result = await self._handle_common_client_command(
                    command_type, payload,
                    websocket=websocket, memory_session=memory_session,
                    tool_session=tool_session, recorder=recorder,
                    interruption=interruption, provider="Gradium",
                )
                if result == "stop":
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes and state.stt_ws is not None:
                try:
                    chunk_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                    await state.stt_ws.send(json.dumps({"type": "audio", "audio": chunk_b64}))
                except Exception:
                    pass

    async def _gradium_stt_loop(
        self,
        websocket: WebSocket,
        state: _GradiumSessionState,
        llm: LLMService,
        llm_provider: str,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        assert state.stt_ws is not None
        accumulated_text: list[str] = []
        silence_flush_task: asyncio.Task[None] | None = None
        consecutive_silence_count: int = 0

        async def flush_turn_after_pause() -> None:
            await asyncio.sleep(0.9)
            full_text = _join_transcript_pieces(accumulated_text)
            if full_text:
                accumulated_text.clear()
                await self._gradium_start_turn(
                    websocket, state, full_text,
                    llm, llm_provider, memory_session, tool_session, recorder,
                )

        try:
            async for raw_message in state.stt_ws:
                try:
                    event = json.loads(raw_message)
                except Exception:
                    continue
                event_type = str(event.get("type", ""))
                if event_type == "text":
                    text_piece = str(event.get("text", "")).strip()
                    if text_piece:
                        if state.active is not None:
                            await self._gradium_barge_in(websocket, state, memory_session, recorder)
                        accumulated_text.append(text_piece)
                        interim_text = _join_transcript_pieces(accumulated_text)
                        await self._send_event(websocket, "user_transcript", text=interim_text, interim=True)
                        consecutive_silence_count = 0
                        if silence_flush_task is not None and not silence_flush_task.done():
                            silence_flush_task.cancel()
                        silence_flush_task = asyncio.create_task(flush_turn_after_pause())
                elif event_type == "step":
                    vad = event.get("vad")
                    if isinstance(vad, list) and len(vad) >= 4 and accumulated_text:
                        inact_2s = float(vad[2].get("inactivity_prob", 0.0))
                        inact_3s = float(vad[3].get("inactivity_prob", 0.0))
                        if inact_2s >= 0.99 and inact_3s >= 0.98:
                            consecutive_silence_count += 1
                            if consecutive_silence_count >= 5:
                                consecutive_silence_count = 0
                                if silence_flush_task is not None and not silence_flush_task.done():
                                    silence_flush_task.cancel()
                                full_text = _join_transcript_pieces(accumulated_text)
                                if full_text:
                                    accumulated_text.clear()
                                    await self._gradium_start_turn(
                                        websocket, state, full_text,
                                        llm, llm_provider, memory_session, tool_session, recorder,
                                    )
                        else:
                            consecutive_silence_count = 0
                elif event_type == "turn":
                    if event.get("turn_end"):
                        if silence_flush_task is not None and not silence_flush_task.done():
                            silence_flush_task.cancel()
                        full_text = _join_transcript_pieces(accumulated_text)
                        if full_text:
                            accumulated_text.clear()
                            await self._gradium_start_turn(
                                websocket, state, full_text,
                                llm, llm_provider, memory_session, tool_session, recorder,
                            )
                elif event_type == "error":
                    logger.error("Gradium STT error event: %s", event)
                    await self._send_event(
                        websocket, "error",
                        message=f"Gradium STT: {event.get('message', 'unknown error')}",
                    )
        finally:
            if silence_flush_task is not None and not silence_flush_task.done():
                silence_flush_task.cancel()

    # -- session entry point ---------------------------------------------------

    async def stream_gradium_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_GRADIUM_VOICE,
    ) -> None:
        if not voice or not is_gradium_voice(voice):
            voice = DEFAULT_GRADIUM_VOICE
        settings = self._resolve_gradium_settings(model)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession(default_provider=settings["llm_provider"])
        recorder = await self._create_voice_session_recorder(
            provider="Gradium",
            model=settings["session_model"],
            voice=voice,
        )
        llm = LLMService(config=self.config)

        state = _GradiumSessionState(
            tts_model=settings["tts_model"],
            voice=voice,
            llm_model=settings["llm_model"],
            api_key=settings["api_key"],
            ws_base=settings["ws_base"],
        )
        headers = {"x-api-key": settings["api_key"]}
        ws_base = settings["ws_base"]
        stt_url = f"{ws_base}/api/speech/asr"

        try:
            async with websockets.connect(
                stt_url, additional_headers=headers, max_size=2**24,
                ping_interval=30, ping_timeout=30,
            ) as stt_ws:
                setup_msg = {
                    "type": "setup",
                    "model_name": "default",
                    "input_format": "pcm_16000",
                    "json_config": {"language": "any", "delay_in_frames": 16},
                }
                await stt_ws.send(json.dumps(setup_msg))
                ready_msg = await stt_ws.recv()
                logger.debug("Gradium ASR ready: %s", ready_msg)

                state.stt_ws = stt_ws
                await self._send_event(
                    websocket,
                    "session_open",
                    provider="Gradium",
                    model=settings["session_model"],
                    voice=voice,
                    session_id=recorder.session_id if recorder is not None else "",
                )
                await self._run_duplex_tasks(
                    asyncio.create_task(
                        self._gradium_client_loop(
                            websocket, state, llm, settings["llm_provider"],
                            memory_session, tool_session, recorder
                        )
                    ),
                    asyncio.create_task(
                        self._gradium_stt_loop(
                            websocket, state, llm, settings["llm_provider"],
                            memory_session, tool_session, recorder
                        )
                    ),
                )
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.exception("Gradium realtime session failed: %s", exc)
            await self._send_event(websocket, "error", message=f"Gradium 实时会话启动失败: {exc}")
        finally:
            try:
                await self._gradium_barge_in(
                    websocket, state, memory_session, recorder, notify=False
                )
            except Exception:
                pass
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain(cancel=True)
            if recorder is not None:
                await recorder.finish()
