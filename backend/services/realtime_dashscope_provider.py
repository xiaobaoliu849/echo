"""DashScope Qwen-Omni (SDK) realtime voice provider mixin."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

try:
    from dashscope.audio.qwen_omni import AudioFormat, MultiModality, OmniRealtimeConversation
except ImportError:  # pragma: no cover
    AudioFormat = None
    MultiModality = None
    OmniRealtimeConversation = None

from .realtime_constants import (
    DEFAULT_DASHSCOPE_REALTIME_MODEL,
    DEFAULT_DASHSCOPE_REALTIME_VOICE,
    DEFAULT_DASHSCOPE_LIVETRANSLATE_VOICE,
    DEFAULT_QWEN_OMNI_REALTIME_VOICE,
    QWEN_OMNI_REALTIME_VOICES,
    _is_dashscope_audio_realtime_model,
    _is_dashscope_live_translate_model,
    _is_dashscope_omni_realtime_model,
    _merge_streaming_text,
    _normalize_dashscope_realtime_voice,
    normalize_qwen_translate_language,
)
from .interruption_classifier import InterruptionClassifier, InterruptionDecisionCoordinator, InterruptionIntent
from .background_tasks import spawn_background_task
from .realtime_dashscope_client import (
    DashScopeAudioRealtimeConversation,
    DashScopeLiveTranslateConversation,
    DashScopeRealtimeCallback,
)
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .realtime_tool_protocol import (
    RealtimeToolCall,
    dashscope_supports_native_tools,
    dashscope_tool_declarations,
    tool_call_to_request,
    tool_error_payload,
    tool_result_payload,
)
from .voice_agent_tools import VoiceAgentToolSession

logger = logging.getLogger(__name__)


class DashScopeRealtimeMixin:
    """DashScope Qwen-Omni SDK provider methods for RealtimeVoiceService."""

    async def _send_dashscope_tool_response(
        self,
        websocket: WebSocket,
        conversation: Any,
        *,
        provider_call_id: str,
        tool_name: str,
        response_payload: dict[str, Any],
        result: dict[str, Any] | None = None,
        create_response: bool = True,
        conversation_turn_id: str = "",
        tool_call_id: str = "",
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        if not provider_call_id:
            raise ValueError("DashScope native tool response requires a provider call ID.")
        try:
            conversation.send_raw(
                json.dumps(
                    {
                        "event_id": f"event_{uuid.uuid4().hex}",
                        "type": "conversation.item.create",
                        "item": {
                            "id": f"item_{uuid.uuid4().hex}",
                            "type": "function_call_output",
                            "call_id": provider_call_id,
                            "output": json.dumps(response_payload, ensure_ascii=False),
                        },
                    },
                    ensure_ascii=False,
                )
            )
            if create_response:
                conversation.create_response()
        except Exception as exc:
            try:
                await self._send_event(
                    websocket,
                    "error",
                    provider="DashScope",
                    message=f"Qwen 工具结果回传失败，会话已关闭: {exc}",
                )
            except Exception:
                pass
            try:
                conversation.close()
            except Exception:
                logger.exception("dashscope_session_close_after_tool_delivery_failed")
            raise
        result = result or {}
        payload = {
            "provider": "DashScope",
            "provider_call_id": provider_call_id,
            "tool_name": tool_name,
            "query": str(result.get("query", "")),
            "turn_id": conversation_turn_id,
            "tool_call_id": tool_call_id,
            "route": "native",
            "source_count": int(result.get("source_count", 0) or 0),
            "sources": result.get("sources") or [],
            "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
            "status": "completed" if response_payload.get("ok") else "failed",
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_result_delivered", payload)
        await self._send_event(
            websocket,
            "tool_result_delivered",
            **payload,
        )
    @staticmethod
    def _resolve_dashscope_voiceprint_audio_urls(
        provider_settings: dict[str, Any],
        urls: list[str] | None,
    ) -> list[str]:
        raw_values = []
        if urls:
            raw_values.extend(urls)
        
        raw_config = provider_settings.get('voiceprint_audio_urls')
        if isinstance(raw_config, list):
            raw_values.extend(raw_config)
        elif isinstance(raw_config, str):
            raw_values.extend(re.split(r'[\r\n,]+', raw_config))
            
        env_config = os.environ.get('DASHSCOPE_VOICEPRINT_AUDIO_URLS', '')
        if env_config:
            raw_values.extend(re.split(r'[\r\n,]+', env_config))
            
        normalized = []
        seen = set()
        for value in raw_values:
            item = str(value or '').strip()
            if not item or item in seen:
                continue
            if not item.startswith(('http://', 'https://')):
                continue
            normalized.append(item)
            seen.add(item)
            if len(normalized) >= 5:
                return normalized
                
        return normalized
    @staticmethod
    def _configure_dashscope_conversation(conversation: Any, *, voice: str, instructions: str) -> None:
        if type(conversation) is DashScopeAudioRealtimeConversation:
            # Qwen-Audio raw client: its update_session() already sends the full
            # config on the first call and instructions+tools on later calls.
            # (Exact-type check: the DashScopeLiveTranslateConversation subclass
            # has a different update_session signature and is never configured
            # through this method.)
            conversation.update_session(
                voice=voice,
                instructions=instructions,
                tools=dashscope_tool_declarations(),
            )
            return
        if getattr(conversation, "_vs_omni_session_configured", False):
            # qwen3.5-omni-*-realtime (SDK path): voice / turn_detection /
            # input_audio_transcription are only honored on the FIRST
            # session.update. Re-sending the full config mid-session is
            # accepted (session.updated) but leaves the session deaf — the
            # server stops emitting speech_started for later audio (verified
            # against the live API). Follow-up updates carry instructions
            # only, mirroring the qwen-audio raw client's pattern.
            conversation.send_raw(
                json.dumps(
                    {
                        "event_id": f"event_{uuid.uuid4().hex}",
                        "type": "session.update",
                        "session": {"instructions": instructions},
                    },
                    ensure_ascii=False,
                )
            )
            return
        conversation.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],  # type: ignore[union-attr]
            voice=voice,
            input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,  # type: ignore[union-attr]
            output_audio_format=AudioFormat.PCM_24000HZ_MONO_16BIT,  # type: ignore[union-attr]
            enable_input_audio_transcription=True,
            enable_turn_detection=True,
            # Do NOT pass create_response=False: qwen3.5-omni-realtime honors it
            # and then never auto-responds after VAD speech_stopped, leaving the
            # UI stuck at "listening" forever (verified against the live API).
            # interrupt_response=False stays so barge-in arbitration remains
            # under the backend's interruption classifier.
            turn_detection_param={"interrupt_response": False},
            turn_detection_silence_duration_ms=2000,
            instructions=instructions,
            tools=dashscope_tool_declarations(),
        )
        conversation._vs_omni_session_configured = True

    @staticmethod
    def _configure_dashscope_live_translate(
        conversation: Any,
        *,
        voice: str,
        source_language: str,
        target_language: str,
        corpus_phrases: dict[str, str] | None = None,
        enable_voice_clone: bool = False,
        voice_clone_frequency: str = "once",
    ) -> None:
        conversation.update_session(
            voice=voice or DEFAULT_DASHSCOPE_LIVETRANSLATE_VOICE,
            source_language=normalize_qwen_translate_language(source_language, "zh"),
            target_language=normalize_qwen_translate_language(target_language, "en"),
            corpus_phrases=corpus_phrases,
            enable_voice_clone=enable_voice_clone,
            voice_clone_frequency=voice_clone_frequency,
        )
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
                result = await self._handle_common_client_command(
                    command_type, payload,
                    websocket=websocket, memory_session=memory_session,
                    tool_session=tool_session, recorder=recorder,
                    interruption=interruption, provider="DashScope",
                )
                if result == "stop":
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
        send_tool_event = self._tool_event_sender(websocket, recorder)

        interruption = interruption or InterruptionDecisionCoordinator()
        suppressed_response_ids: set[str] = set()
        tool_phase_response_ids: set[str] = set()
        cannot_create_response_retries = 0
        gated_tool_turn_id = ""
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
            if event_type == "function_call":
                function_response_id = str(event.get("response_id", "")).strip()
                if function_response_id:
                    tool_phase_response_ids.add(function_response_id)
                provider_call_id = str(event.get("provider_call_id", "")).strip()
                tool_name = str(event.get("tool_name", "")).strip()
                if not provider_call_id:
                    await self._send_event(
                        websocket,
                        "error",
                        provider="DashScope",
                        message="Qwen 返回了缺少 call ID 的工具请求，已拒绝执行。",
                    )
                    continue
                if tool_session.has_seen_provider_call(provider_call_id):
                    continue
                conversation_turn_id = recorder.current_turn_id if recorder is not None else ""
                tool_turn_id = tool_session.reserve_tool_call_id()
                try:
                    native_call = RealtimeToolCall(
                        provider="DashScope",
                        provider_call_id=provider_call_id,
                        tool_name=tool_name,
                        arguments=event.get("arguments", "{}"),
                    )
                    request = tool_call_to_request(native_call)
                except Exception as exc:
                    tool_session.mark_provider_call_seen(provider_call_id)
                    await self._send_dashscope_tool_response(
                        websocket,
                        conversation,
                        provider_call_id=provider_call_id,
                        tool_name=tool_name or "unknown_tool",
                        response_payload=tool_error_payload(str(exc)),
                        conversation_turn_id=conversation_turn_id,
                        recorder=recorder,
                    )
                    continue

                async def on_dashscope_native_result(
                    result: dict[str, Any],
                    *,
                    call_id: str = provider_call_id,
                    name: str = tool_name,
                    canonical_turn_id: str = conversation_turn_id,
                    local_tool_call_id: str = tool_turn_id,
                ) -> None:
                    nonlocal gated_tool_turn_id
                    gated_tool_turn_id = ""
                    await self._send_dashscope_tool_response(
                        websocket,
                        conversation,
                        provider_call_id=call_id,
                        tool_name=name,
                        response_payload=tool_result_payload(result),
                        result=result,
                        conversation_turn_id=canonical_turn_id,
                        tool_call_id=local_tool_call_id,
                        recorder=recorder,
                    )

                async def on_dashscope_native_error(
                    message: str,
                    *,
                    call_id: str = provider_call_id,
                    name: str = tool_name,
                    canonical_turn_id: str = conversation_turn_id,
                    local_tool_call_id: str = tool_turn_id,
                ) -> None:
                    nonlocal gated_tool_turn_id
                    gated_tool_turn_id = ""
                    await self._send_dashscope_tool_response(
                        websocket,
                        conversation,
                        provider_call_id=call_id,
                        tool_name=name,
                        response_payload=tool_error_payload(message),
                        conversation_turn_id=canonical_turn_id,
                        tool_call_id=local_tool_call_id,
                        recorder=recorder,
                    )

                async def on_dashscope_native_cancel(
                    message: str,
                    *,
                    call_id: str = provider_call_id,
                    name: str = tool_name,
                    canonical_turn_id: str = conversation_turn_id,
                    local_tool_call_id: str = tool_turn_id,
                ) -> None:
                    nonlocal gated_tool_turn_id
                    gated_tool_turn_id = ""
                    await self._send_dashscope_tool_response(
                        websocket,
                        conversation,
                        provider_call_id=call_id,
                        tool_name=name,
                        response_payload=tool_error_payload(message),
                        create_response=False,
                        conversation_turn_id=canonical_turn_id,
                        tool_call_id=local_tool_call_id,
                        recorder=recorder,
                    )

                gated_tool_turn_id = tool_turn_id
                await self._send_response_gated(
                    websocket,
                    provider="DashScope",
                    tool_name=tool_name,
                    query=request.query,
                    turn_id=tool_turn_id,
                    recorder=recorder,
                )

                await tool_session.handle_request(
                    request,
                    send_event=send_tool_event,
                    on_result=on_dashscope_native_result,
                    on_error=on_dashscope_native_error,
                    on_cancel=on_dashscope_native_cancel,
                    provider_call_id=provider_call_id,
                    conversation_turn_id=conversation_turn_id,
                    tool_call_id=tool_turn_id,
                )
                continue
            if event_type == "tool_phase_complete":
                response_id = str(event.get("response_id", "")).strip()
                tool_phase_response_ids.discard(response_id)
                if response_id == interruption.active_response_id:
                    interruption.active_response_id = ""
                continue
            if event_type == "user_transcript":
                cannot_create_response_retries = 0
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
                    cancel_provider=(cancel_dashscope_response if (interrupted_response_id and not had_deferred_terminal) else None),
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
                            gated=False,
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
                if interrupted_response_id and not had_deferred_terminal:
                    await asyncio.sleep(0.2)
                # Note: Qwen Server VAD automatically triggers response generation when speech ends,
                # so calling create_response() here is redundant and causes collision errors.
                # conversation.create_response()
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
                if response_id in tool_phase_response_ids:
                    tool_phase_response_ids.discard(response_id)
                    if response_id == interruption.active_response_id:
                        interruption.active_response_id = ""
                    continue
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
                if not gated_tool_turn_id:
                    memory_result = await memory_session.flush_turn()
                    completed_turn_id = ""
                    if recorder is not None:
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
                    await self._send_event(
                        websocket,
                        "turn_complete",
                        turn_id=completed_turn_id,
                        interrupted=False,
                    )
                continue
            if event_type == "error":
                error_msg = str(event.get("message", ""))
                if "no active response" in error_msg.lower():
                    logger.warning("DashScope returned non-fatal error: %s. Ignoring.", error_msg)
                    continue
                if "cannot create response" in error_msg.lower():
                    if cannot_create_response_retries < 2:
                        cannot_create_response_retries += 1
                        logger.warning(
                            "DashScope returned error: %s. Retrying create_response (attempt %d/2) after 300ms.",
                            error_msg,
                            cannot_create_response_retries,
                        )
                        async def delayed_retry():
                            await asyncio.sleep(0.3)
                            try:
                                conversation.create_response()
                            except Exception as exc:
                                logger.exception("dashscope_retry_create_response_failed")
                        spawn_background_task(delayed_retry())
                    else:
                        logger.warning("DashScope returned error: %s. Max retries exceeded. Ignoring.", error_msg)
                    continue
                await websocket.send_json(event)
                break
            await websocket.send_json(event)
    async def _client_to_dashscope_live_translate_loop(
        self,
        websocket: WebSocket,
        conversation: Any,
    ) -> None:
        """Forward mic audio to the LiveTranslate model; ignore chat-only commands."""
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
                if command_type == "ping":
                    await self._send_event(websocket, "pong")
                elif command_type == "stop":
                    break
                # config / text_input / interruption_* are not meaningful in
                # simultaneous-translation mode — silently ignore them.
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                conversation.append_audio(base64.b64encode(audio_bytes).decode("ascii"))

    async def _dashscope_live_translate_to_client_loop(
        self,
        websocket: WebSocket,
        queue: asyncio.Queue[dict[str, Any]],
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        """Map DashScope LiveTranslate server events to client events.

        The translation model streams cumulative text (``text`` confirmed prefix
        plus a tentative ``stash``). We merge each update into a running display
        string and emit only the novel suffix, mirroring the Google
        live-translate behaviour. An inactivity monitor finalizes a turn ~2s
        after the last content event.
        """
        interruption = InterruptionDecisionCoordinator()
        display_translation = ""
        pending_user = ""
        last_activity = time.time()
        has_content = False
        input_finished = False
        output_finished = False

        async def complete_turn(force: bool = False) -> None:
            nonlocal display_translation, pending_user, last_activity
            nonlocal has_content, input_finished, output_finished
            if not has_content:
                return
            # A turn is ready to finalize if either output_finished is True
            # (the server finished generating the translation response) or
            # force is True (inactivity timeout). Do NOT hang waiting for
            # input_finished (conversation.item.input_audio_transcription.completed)
            # which Qwen LiveTranslate often omits in continuous streaming.
            if not force and not output_finished:
                return
            # Clear the guard flags BEFORE any await so the inactivity monitor
            # and the event loop cannot both pass the guard and emit a duplicate
            # turn_complete (the awaits below yield control mid-completion).
            has_content = False
            input_finished = False
            output_finished = False
            completed_turn_id = ""
            if recorder is not None:
                completed_turn_id = await recorder.complete_turn({})
            await self._send_event(
                websocket, "turn_complete", turn_id=completed_turn_id, interrupted=False
            )
            display_translation = ""
            pending_user = ""
            last_activity = time.time()

        async def monitor_inactivity() -> None:
            try:
                while True:
                    await asyncio.sleep(0.5)
                    if has_content and time.time() - last_activity >= 2.0:
                        await complete_turn(force=True)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.exception("dashscope_live_translate_inactivity_monitor_failed: %s", exc)

        monitor_task = asyncio.create_task(monitor_inactivity())
        try:
            while True:
                event = await queue.get()
                event_type = str(event.get("type", "")).strip()
                if event_type == "closed":
                    break

                if event_type == "user_transcript":
                    last_activity = time.time()
                    has_content = True
                    if event.get("cumulative"):
                        # Only the confirmed prefix is canonical/monotonic; the
                        # tentative `stash` is sent as a separate non-accumulating
                        # field so it can never corrupt the running transcript.
                        confirmed = str(event.get("text", ""))
                        stash = str(event.get("stash", ""))
                        pending_user = confirmed
                        if confirmed or stash:
                            extra: dict[str, Any] = {"tentative": stash} if stash else {}
                            await self._send_event(
                                websocket,
                                "user_transcript",
                                text=confirmed,
                                turn_id="",
                                **extra,
                            )
                    else:
                        text = str(event.get("text", "")).strip()
                        if text:
                            pending_user = text
                            voice_turn_id = ""
                            if recorder is not None:
                                voice_turn_id = await recorder.note_user_transcript(text)
                            await self._send_event(
                                websocket, "user_transcript", text=text, final=True, turn_id=voice_turn_id
                            )
                            input_finished = True
                    await complete_turn()
                    continue

                if event_type == "assistant_text":
                    last_activity = time.time()
                    has_content = True
                    if event.get("final"):
                        # response.text.done / response.audio_transcript.done:
                        # The streaming cumulative events (response.text.text) have
                        # already built up display_translation as a running prefix.
                        # Merging the final text here causes duplication whenever the
                        # final text and the accumulated stream differ even slightly
                        # (e.g. trailing punctuation, spacing).
                        #
                        # We intentionally do NOT call _merge_streaming_text here.
                        # The final text is only used as a fallback when NO streaming
                        # events arrived before the done event (e.g. single-token
                        # ultra-fast responses where the model emits text.done
                        # before any text.text increments).
                        if not display_translation:
                            final_text = str(event.get("text", "")).strip()
                            if final_text:
                                display_translation = final_text
                                await self._emit_assistant_output(
                                    websocket,
                                    interruption,
                                    {"type": "assistant_text", "text": final_text},
                                    memory_session=memory_session,
                                    recorder=recorder,
                                    record_memory=False,
                                )
                        output_finished = True
                    else:
                        # Merge the confirmed prefix only (monotonic). The
                        # tentative `stash` is exposed as an ephemeral preview
                        # event and is deliberately kept OUT of the accumulating
                        # stream — predictions get revised and are not a growing
                        # prefix, so merging them would garble/duplicate output.
                        confirmed = str(event.get("text", ""))
                        stash = str(event.get("stash", ""))
                        display_translation, delta = _merge_streaming_text(
                            display_translation, confirmed
                        )
                        if delta:
                            await self._emit_assistant_output(
                                websocket,
                                interruption,
                                {"type": "assistant_text", "text": delta},
                                memory_session=memory_session,
                                recorder=recorder,
                                record_memory=False,
                            )
                        # Always notify the frontend of the current speculative
                        # stash — even when it is empty — so it can clear
                        # a stale preview left over from a prior event.
                        # Without this, when the confirmed text is unchanged
                        # but the stash is cleared (shrunk to nothing), the
                        # frontend would never learn that the preview should
                        # be blanked and its boundary timer could commit the
                        # stale prediction as if it were confirmed text.
                        await self._send_event(
                            websocket,
                            "translation_preview",
                            text=confirmed,
                            tentative=stash,
                        )
                    await complete_turn()
                    continue

                if event_type == "assistant_audio":
                    last_activity = time.time()
                    has_content = True
                    await self._emit_assistant_output(
                        websocket,
                        interruption,
                        event,
                        memory_session=memory_session,
                        recorder=recorder,
                        record_memory=False,
                    )
                    continue

                if event_type == "turn_complete":
                    # response.done signals the end of the server response lifecycle.
                    # Normally, response.text.done (assistant_text final=True) arrives
                    # first and already sets output_finished=True + calls complete_turn.
                    # This handler is a safety-net for modalities where no text.done
                    # is emitted (e.g. audio-only, or if the server sends response.done
                    # before text.done in a race).  Never overwrite a True flag here:
                    # that would double-trigger complete_turn on a turn already closed.
                    if not output_finished:
                        output_finished = True
                        await complete_turn()
                    continue

                if event_type == "error":
                    await websocket.send_json(event)
                    break
                # speech_started / response_started / tool events are ignored in
                # translation mode (no barge-in arbitration, no function calling).
        finally:
            monitor_task.cancel()

    async def _stream_dashscope_live_translate_session(
        self,
        websocket: WebSocket,
        *,
        settings: dict[str, str],
        voice: str,
        translation_mode: str,
        source_language_code: str,
        target_language_code: str,
        echo_target_language: bool,
        enable_voice_clone: bool = False,
        voice_clone_frequency: str = "once",
    ) -> None:
        resolved_voice = (voice or DEFAULT_DASHSCOPE_LIVETRANSLATE_VOICE).strip() or DEFAULT_DASHSCOPE_LIVETRANSLATE_VOICE
        memory_session = RealtimeMemorySession()
        recorder = await self._create_voice_session_recorder(
            provider="DashScope",
            model=settings["model"],
            voice=resolved_voice,
        )
        url = settings["realtime_base_url"]
        event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        callback = DashScopeRealtimeCallback(loop=loop, queue=event_queue)
        conversation = DashScopeLiveTranslateConversation(
            model=settings["model"],
            api_key=settings["api_key"],
            callback=callback,
            url=url,
        )
        try:
            await conversation.connect()
            await asyncio.sleep(0.5)
            # NOTE: Qwen LiveTranslate performs UNIDIRECTIONAL source→target
            # translation per its Realtime API (source language in
            # input_audio_transcription.language, target in translation.language).
            # Unlike Gemini, it has no bidirectional/echo mode, so
            # ``translation_mode`` and ``echo_target_language`` are accepted for
            # UI parity and echoed in ``session_open`` but not applied upstream.
            self._configure_dashscope_live_translate(
                conversation,
                voice=resolved_voice,
                source_language=source_language_code,
                target_language=target_language_code,
                enable_voice_clone=enable_voice_clone,
                voice_clone_frequency=voice_clone_frequency,
            )
            await asyncio.sleep(0.5)
            await self._send_event(
                websocket,
                "session_open",
                provider="DashScope",
                model=settings["model"],
                voice=resolved_voice,
                session_id=recorder.session_id if recorder is not None else "",
                mode="live_translate",
                translation_mode=translation_mode,
                source_language_code=source_language_code,
                target_language_code=target_language_code,
                echo_target_language=echo_target_language,
                enable_voice_clone=enable_voice_clone,
                voice_clone_frequency=voice_clone_frequency,
            )
            send_task = asyncio.create_task(
                self._client_to_dashscope_live_translate_loop(websocket, conversation)
            )
            receive_task = asyncio.create_task(
                self._dashscope_live_translate_to_client_loop(
                    websocket, event_queue, memory_session, recorder
                )
            )
            await self._run_duplex_tasks(send_task, receive_task)
        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.exception("DashScope live translate session failed: %s", e)
            await self._send_event(
                websocket, "error", message=f"DashScope 实时翻译会话启动失败: {str(e)}"
            )
            return
        finally:
            try:
                conversation.finish_session()
                # finish_session() schedules the send as a background task; give
                # it a moment to flush before the socket is closed so the final
                # translation segment is not dropped on stop/disconnect.
                await asyncio.sleep(0.2)
            except Exception:
                pass
            await memory_session.drain()
            if recorder is not None:
                await recorder.finish()
            try:
                conversation.close()
            except Exception:
                pass

    async def stream_dashscope_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_DASHSCOPE_REALTIME_VOICE,
        voiceprint_audio_urls: list[str] | None = None,
        translation_mode: str = "bidirectional",
        source_language_code: str = "zh-Hans",
        target_language_code: str = "en",
        echo_target_language: bool = True,
        enable_voice_clone: bool = False,
        voice_clone_frequency: str = "once",
    ) -> None:
        settings = self._resolve_dashscope_settings(model)
        if _is_dashscope_live_translate_model(settings["model"]):
            await self._stream_dashscope_live_translate_session(
                websocket,
                settings=settings,
                voice=voice,
                translation_mode=translation_mode,
                source_language_code=source_language_code,
                target_language_code=target_language_code,
                echo_target_language=echo_target_language,
                enable_voice_clone=enable_voice_clone,
                voice_clone_frequency=voice_clone_frequency,
            )
            return
        voice = _normalize_dashscope_realtime_voice(settings["model"], voice)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession(default_provider="DashScope")
        resolved_voice = (voice or DEFAULT_QWEN_OMNI_REALTIME_VOICE).strip()
        if "qwen3.5-omni" in settings["model"].lower() and resolved_voice not in QWEN_OMNI_REALTIME_VOICES:
            logger.warning(
                "qwen_omni_unsupported_voice voice=%s fallback=%s",
                resolved_voice, DEFAULT_QWEN_OMNI_REALTIME_VOICE,
            )
            resolved_voice = DEFAULT_QWEN_OMNI_REALTIME_VOICE
        recorder = await self._create_voice_session_recorder(
            provider="DashScope",
            model=settings["model"],
            voice=resolved_voice,
        )
        url = settings["realtime_base_url"]
        event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        callback = DashScopeRealtimeCallback(loop=loop, queue=event_queue)
        if _is_dashscope_audio_realtime_model(settings["model"]):
            all_settings = self.config.get_all()
            dashscope_realtime_settings = all_settings.get("dashscope_realtime")
            voiceprint_settings = dashscope_realtime_settings if isinstance(dashscope_realtime_settings, dict) else {}
            if "voiceprint_audio_urls" not in voiceprint_settings and "voiceprint_audio_urls" in all_settings:
                voiceprint_settings = {
                    **voiceprint_settings,
                    "voiceprint_audio_urls": all_settings.get("voiceprint_audio_urls"),
                }
            conversation = DashScopeAudioRealtimeConversation(
                model=settings["model"],
                api_key=settings["api_key"],
                callback=callback,
                url=url,
                voiceprint_audio_urls=self._resolve_dashscope_voiceprint_audio_urls(
                    voiceprint_settings,
                    voiceprint_audio_urls,
                ),
            )
        else:
            import dashscope

            dashscope.api_key = settings["api_key"]
            conversation = OmniRealtimeConversation(  # type: ignore[misc]
                model=settings["model"],
                callback=callback,
                url=url,
            )

        try:
            if isinstance(conversation, DashScopeAudioRealtimeConversation):
                await conversation.connect()
            else:
                conversation.connect()
            await asyncio.sleep(0.5)
            self._configure_dashscope_conversation(
                conversation,
                voice=resolved_voice,
                instructions=self._build_realtime_instructions(),
            )
            await asyncio.sleep(0.5)
            await self._send_event(
                websocket,
                "session_open",
                provider="DashScope",
                model=settings["model"],
                voice=resolved_voice,
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
            await self._run_duplex_tasks(send_task, receive_task)
        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.exception("DashScope realtime session failed: %s", e)
            await self._send_event(websocket, "error", message=f"DashScope 实时会话启动失败: {str(e)}")
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain(cancel=True)
            if recorder is not None:
                await recorder.finish()
            try:
                conversation.close()
            except Exception:
                pass
