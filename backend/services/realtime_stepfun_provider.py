"""StepFun (StepAudio 3 Realtime) voice provider mixin."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .realtime_constants import (
    DEFAULT_STEPFUN_REALTIME_MODEL,
    DEFAULT_STEPFUN_REALTIME_VOICE,
    DEFAULT_STEPFUN_REALTIME_WS_URL,
)
from .interruption_classifier import InterruptionClassifier, InterruptionDecisionCoordinator, InterruptionIntent
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .voice_agent_tools import VoiceAgentToolService, VoiceAgentToolSession

logger = logging.getLogger(__name__)


class StepFunRealtimeMixin:
    """StepFun (StepAudio 3 Realtime) provider methods for RealtimeVoiceService."""

    def _resolve_stepfun_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("StepFun", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_STEPFUN_REALTIME_MODEL
        api_key = provider_settings["api_key"].strip()
        if not api_key:
            raise RuntimeError("StepFun API Key 未配置，无法启动实时语音会话。")

        realtime_base_url = (
            provider_settings.get("realtime_base_url", "").strip()
            or DEFAULT_STEPFUN_REALTIME_WS_URL
        )
        return {
            "api_key": api_key,
            "model": resolved_model,
            "ws_url": realtime_base_url,
        }

    async def _apply_stepfun_tool_result(
        self,
        stepfun_ws: Any,
        result: dict[str, Any],
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        if not prompt.strip():
            return
        payload = {
            "provider": "StepFun",
            "tool_name": str(result.get("tool_name", "search_web") or "search_web"),
            "query": str(result.get("query", "")),
            "turn_id": str(result.get("turn_id", "")),
            "source_count": int(result.get("source_count", 0) or 0),
            "sources": result.get("sources") or [],
            "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_context_injected", payload)
        await stepfun_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        }))
        await stepfun_ws.send(json.dumps({"type": "response.create"}))

    async def _client_to_stepfun_loop(
        self,
        websocket: WebSocket,
        stepfun_ws: Any,
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
                        if recorder is not None:
                            await recorder.note_user_transcript(content)
                        if memory_session is not None:
                            memory_session.note_user_transcript(content)
                        await stepfun_ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": content}],
                            },
                        }))
                        await stepfun_ws.send(json.dumps({"type": "response.create"}))
                    continue
                if command_type == "media_input":
                    text_prompt = str(payload.get("text", "")).strip()
                    note_text = f"[Image] {text_prompt}" if text_prompt else "[Image]"
                    if recorder is not None:
                        await recorder.note_user_transcript(note_text)
                    if memory_session is not None:
                        memory_session.note_user_transcript(note_text)
                    prompt = f"[User attached an image]\n{text_prompt}" if text_prompt else "[User attached an image]"
                    await stepfun_ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": prompt}],
                        },
                    }))
                    await stepfun_ws.send(json.dumps({"type": "response.create"}))
                    continue
                result = await self._handle_common_client_command(
                    command_type, payload,
                    websocket=websocket, memory_session=memory_session,
                    tool_session=tool_session, recorder=recorder,
                    interruption=interruption, provider="StepFun",
                )
                if result == "stop":
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                await stepfun_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_bytes).decode("ascii"),
                }))

    async def _stepfun_to_client_loop(
        self,
        websocket: WebSocket,
        stepfun_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        send_tool_event = self._tool_event_sender(websocket, recorder)

        gated_tool_turn_id = ""
        pending_prefill_context = ""
        interruption = interruption or InterruptionDecisionCoordinator()
        suppressed_response_ids: set[str] = set()

        async for raw_message in stepfun_ws:
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
                    provider="StepFun",
                    model=session_info.get("model", ""),
                    voice=session_info.get("voice", DEFAULT_STEPFUN_REALTIME_VOICE),
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
            if event_type in ("conversation.item.input_audio_transcription.completed", "input_audio_transcription.completed"):
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
                        provider="StepFun",
                        provider_event_type="conversation.item.input_audio_transcription.completed_without_vad",
                        recorder=recorder,
                        tool_session=tool_session,
                        supersede_timed_out=True,
                    )
                interrupted_response_id = interruption.active_response_id
                had_deferred_terminal = interruption.has_deferred_terminal()

                async def cancel_stepfun_response() -> None:
                    payload: dict[str, Any] = {"type": "response.cancel"}
                    if interrupted_response_id:
                        payload["response_id"] = interrupted_response_id
                    await stepfun_ws.send(json.dumps(payload))

                async def discard_stepfun_candidate() -> None:
                    if item_id:
                        await stepfun_ws.send(
                            json.dumps({"type": "conversation.item.delete", "item_id": item_id})
                        )

                should_process_user, interruption_decision = await self._decide_interruption(
                    websocket,
                    interruption,
                    user_text,
                    memory_session=memory_session,
                    tool_session=tool_session,
                    recorder=recorder,
                    cancel_provider=(cancel_stepfun_response if not had_deferred_terminal else None),
                    resume_provider=discard_stepfun_candidate,
                )
                if interruption_decision is not None and (
                    interruption_decision.get("classification") == InterruptionIntent.TRUE_BARGE_IN.value
                ) and interrupted_response_id and not had_deferred_terminal:
                    suppressed_response_ids.add(interrupted_response_id)
                if not should_process_user:
                    if interruption_decision is None:
                        await discard_stepfun_candidate()
                    if had_deferred_terminal and interruption.take_deferred_terminal() is not None:
                        await self._finalize_realtime_turn(
                            websocket,
                            memory_session,
                            recorder,
                            gated=bool(gated_tool_turn_id),
                        )
                    continue
                if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
                    await discard_stepfun_candidate()
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
                            "voice_memory_inject provider=StepFun scope=%s count=%s local_pending=%s cloud=%s",
                            memory_session._config.memory_scope,
                            memory_count,
                            local_pending_count,
                            cloud_count,
                        )
                        pending_prefill_context = memory_context
                    await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)

                    # Tool detection
                    async def on_stepfun_tool_result(result: dict[str, Any]) -> None:
                        nonlocal gated_tool_turn_id
                        gated_tool_turn_id = ""
                        await self._apply_stepfun_tool_result(stepfun_ws, result, recorder)

                    tool_request = VoiceAgentToolService.extract_tool_request(user_text)
                    tool_turn_id = await tool_session.handle_user_transcript(
                        user_text,
                        send_event=send_tool_event,
                        on_result=on_stepfun_tool_result,
                    )
                    if tool_turn_id:
                        gated_tool_turn_id = tool_turn_id
                        await self._send_response_gated(
                            websocket,
                            provider="StepFun",
                            tool_name=tool_request.tool_name if tool_request else "voice_tool",
                            query=tool_request.query if tool_request else "",
                            turn_id=tool_turn_id,
                            recorder=recorder,
                        )
                    else:
                        await stepfun_ws.send(json.dumps({"type": "response.create"}))
                continue

            # Speech started (VAD detected user speaking → interruption)
            if event_type == "input_audio_buffer.speech_started":
                if interruption.active_response_id or tool_session.has_active_task or (
                    recorder is not None and bool(recorder.current_assistant_text)
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="StepFun",
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
                        {
                            "type": "assistant_text",
                            "text": text_delta,
                        },
                        memory_session=memory_session,
                        recorder=recorder,
                    )
                continue

            # Assistant output done (single item finished)
            if event_type == "response.output_item.done":
                continue

            # Response completed
            if event_type == "response.done":
                response_obj = event.get("response") or {}
                response_id = str(response_obj.get("id", ""))
                if response_id in suppressed_response_ids:
                    suppressed_response_ids.discard(response_id)
                    continue
                interruption.active_response_id = ""
                if not gated_tool_turn_id:
                    if interruption.pending is not None:
                        interruption.defer_terminal_event(event)
                    else:
                        await self._finalize_realtime_turn(
                            websocket,
                            memory_session,
                            recorder,
                            gated=False,
                        )
                continue

            # Explicit cancellation acknowledged
            if event_type == "response.cancelled":
                interruption.active_response_id = ""
                continue

            # Error event
            if event_type == "error":
                error_obj = event.get("error", {})
                error_msg = error_obj.get("message", "StepFun 实时服务发生错误")
                logger.error("StepFun realtime error: %s", error_msg)
                await self._send_event(websocket, "error", message=error_msg)
                continue

    async def _run_stepfun_session(
        self,
        websocket: WebSocket,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        settings = self._resolve_stepfun_settings(model)
        voice = (voice or DEFAULT_STEPFUN_REALTIME_VOICE).strip()

        memory_session = RealtimeMemorySession(self.config)
        tool_session = VoiceAgentToolSession(self.config)

        await self._send_event(
            websocket,
            "session_init",
            provider="StepFun",
            model=settings["model"],
            voice=voice,
        )

        ws_url = f"{settings['ws_url']}?model={settings['model']}"
        extra_headers = {
            "Authorization": f"Bearer {settings['api_key']}",
        }

        try:
            async with websockets.connect(
                ws_url,
                additional_headers=extra_headers,
                max_size=2**24,
                ping_interval=30,
                ping_timeout=30,
            ) as stepfun_ws:
                # Configure session
                await stepfun_ws.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "modalities": ["text", "audio"],
                        "voice": voice,
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                            "create_response": False,
                            "interrupt_response": False,
                        },
                        "instructions": instructions or self._build_realtime_instructions(),
                    },
                }))

                interruption = InterruptionDecisionCoordinator()
                send_task = asyncio.create_task(
                    self._client_to_stepfun_loop(
                        websocket, stepfun_ws, memory_session, tool_session, recorder, interruption
                    )
                )
                receive_task = asyncio.create_task(
                    self._stepfun_to_client_loop(
                        websocket, stepfun_ws, memory_session, tool_session, recorder, interruption
                    )
                )
                await self._run_duplex_tasks(send_task, receive_task)
        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.exception("StepFun realtime session failed: %s", e)
            await self._send_event(websocket, "error", message=f"StepFun 实时会话启动失败: {str(e)}")
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain(cancel=True)
            if recorder is not None:
                await recorder.finish()

    async def stream_stepfun_session(
        self,
        websocket: WebSocket,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> None:
        recorder = await self._create_voice_session_recorder(
            provider="StepFun",
            model=model or DEFAULT_STEPFUN_REALTIME_MODEL,
            voice=voice or DEFAULT_STEPFUN_REALTIME_VOICE,
        )
        try:
            await self._run_stepfun_session(
                websocket,
                model=model,
                voice=voice,
                instructions=instructions,
                recorder=recorder,
            )
        finally:
            if recorder is not None:
                await recorder.finish()
