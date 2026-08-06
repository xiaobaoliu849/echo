"""Doubao / Volcengine Realtime voice provider mixin."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .realtime_constants import (
    DEFAULT_DOUBAO_REALTIME_ENDPOINT,
    DEFAULT_DOUBAO_REALTIME_MODEL,
    DEFAULT_DOUBAO_REALTIME_VOICE,
    DOUBAO_REALTIME_VOICES,
    _merge_streaming_text,
)
from .interruption_classifier import InterruptionDecisionCoordinator
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .voice_agent_tools import VoiceAgentToolSession

logger = logging.getLogger(__name__)


class DoubaoRealtimeMixin:
    """Doubao Realtime provider methods for RealtimeVoiceService."""

    def _resolve_doubao_settings(
        self, model: str | None, voice: str | None = None
    ) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("Doubao", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_DOUBAO_REALTIME_MODEL
        api_key = provider_settings["api_key"].strip()
        if not api_key:
            # Fallback to Volcengine key if configured
            volc_settings = self.config.get_provider_settings("Volcengine", model)
            api_key = volc_settings["api_key"].strip()

        if not api_key:
            raise RuntimeError("Doubao / Volcengine API Key 未配置，无法启动实时语音会话。")

        endpoint = (
            provider_settings.get("realtime_base_url", "").strip()
            or DEFAULT_DOUBAO_REALTIME_ENDPOINT
        )
        resolved_voice = voice.strip() if (voice and voice.strip()) else DEFAULT_DOUBAO_REALTIME_VOICE

        return {
            "api_key": api_key,
            "model": resolved_model,
            "voice": resolved_voice,
            "endpoint": endpoint,
        }

    async def _client_to_doubao_loop(
        self,
        websocket: WebSocket,
        doubao_ws: Any,
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
                if command_type == "text_input":
                    content = str(payload.get("text", "")).strip()
                    if content:
                        await doubao_ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": content}],
                            },
                        }))
                        await doubao_ws.send(json.dumps({"type": "response.create"}))
                    continue

                result = await self._handle_common_client_command(
                    command_type, payload,
                    websocket=websocket, memory_session=memory_session,
                    tool_session=tool_session, recorder=recorder,
                    interruption=interruption, provider="Doubao",
                )
                if result == "stop":
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                await doubao_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_bytes).decode("ascii"),
                }))

    async def _doubao_to_client_loop(
        self,
        websocket: WebSocket,
        doubao_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        interruption = interruption or InterruptionDecisionCoordinator()
        active_turn_id: str | None = None
        user_transcript_acc: str = ""
        ai_transcript_acc: str = ""
        turn_start_t0: float = time.perf_counter()

        while True:
            try:
                raw_msg = await doubao_ws.recv()
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception:
                break

            if isinstance(raw_msg, bytes):
                raw_msg = raw_msg.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw_msg)
            except Exception:
                continue

            event_type = event.get("type", "")

            if event_type == "conversation.item.created":
                item = event.get("item") or {}
                if item.get("role") == "user":
                    content_list = item.get("content") or []
                    for content in content_list:
                        if content.get("type") == "input_text":
                            txt = content.get("text", "")
                            if txt:
                                await self._send_event(
                                    websocket, "user_transcript",
                                    text=txt, is_final=True, turn_id=None,
                                )

            elif event_type in (
                "conversation.item.input_audio_transcription.completed",
                "response.output_item.added",
            ):
                if event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = str(event.get("transcript", "")).strip()
                    if transcript:
                        user_transcript_acc = _merge_streaming_text(user_transcript_acc, transcript)
                        await self._send_event(
                            websocket, "user_transcript",
                            text=user_transcript_acc, is_final=True, turn_id=active_turn_id,
                        )

            elif event_type == "response.created":
                resp = event.get("response") or {}
                active_turn_id = resp.get("id") or f"turn_{int(time.time()*1000)}"
                ai_transcript_acc = ""
                turn_start_t0 = time.perf_counter()
                interruption.active_response_id = active_turn_id

            elif event_type == "response.audio.delta":
                audio_b64 = event.get("delta", "")
                if audio_b64:
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

            elif event_type == "response.audio_transcript.delta":
                delta = event.get("delta", "")
                if delta:
                    ai_transcript_acc += delta
                    await self._emit_assistant_output(
                        websocket,
                        interruption,
                        {"type": "assistant_text", "text": str(delta)},
                        memory_session=memory_session,
                        recorder=recorder,
                    )

            elif event_type == "response.done":
                elapsed_ms = int((time.perf_counter() - turn_start_t0) * 1000)
                if ai_transcript_acc:
                    await self._send_event(
                        websocket, "ai_transcript",
                        text=ai_transcript_acc, is_final=True, turn_id=active_turn_id,
                    )
                if recorder and active_turn_id:
                    await recorder.complete_turn()
                user_transcript_acc = ""
                ai_transcript_acc = ""

    async def _run_doubao_session(
        self,
        websocket: WebSocket,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
        memory_session: RealtimeMemorySession | None = None,
        tool_session: VoiceAgentToolSession | None = None,
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        settings = self._resolve_doubao_settings(model, voice)
        api_key = settings["api_key"]
        endpoint = settings["endpoint"]
        model_name = settings["model"]
        voice_name = settings["voice"]

        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        url = f"{endpoint}?model={model_name}"

        async with websockets.connect(url, extra_headers=headers) as doubao_ws:
            # Configure initial session
            session_config = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "voice": voice_name,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "instructions": instructions or "You are Doubao Realtime AI voice assistant.",
                },
            }
            await doubao_ws.send(json.dumps(session_config))

            interruption = InterruptionDecisionCoordinator()
            memory_session = memory_session or RealtimeMemorySession()
            tool_session = tool_session or VoiceAgentToolSession()

            client_task = asyncio.create_task(
                self._client_to_doubao_loop(
                    websocket, doubao_ws, memory_session, tool_session, recorder, interruption
                )
            )
            doubao_task = asyncio.create_task(
                self._doubao_to_client_loop(
                    websocket, doubao_ws, memory_session, tool_session, recorder, interruption
                )
            )

            await self._run_duplex_tasks(client_task, doubao_task)
