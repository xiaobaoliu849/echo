"""Google Gemini Live realtime voice provider mixin."""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import os
import re
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None

from .realtime_constants import (
    BASE_REALTIME_INSTRUCTIONS,
    DEFAULT_GOOGLE_REALTIME_MODEL,
    DEFAULT_GOOGLE_REALTIME_VOICE,
    GOOGLE_REALTIME_VOICES,
    _is_google_live_translate_model,
    _is_google_public_rest_base_url,
    _merge_streaming_text,
)
from .interruption_classifier import InterruptionClassifier, InterruptionDecisionCoordinator, InterruptionIntent
from .realtime_memory_session import RealtimeMemorySession, _merge_memory_text
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .realtime_tool_protocol import (
    RealtimeToolCall,
    native_tool_declarations,
    tool_call_to_request,
    tool_error_payload,
    tool_result_payload,
)
from .voice_agent_tools import VoiceAgentToolSession

logger = logging.getLogger(__name__)


class GoogleRealtimeMixin:
    """Google Gemini Live provider methods for RealtimeVoiceService."""

    @staticmethod
    def _build_google_memory_prefill_turns(memory_context: str) -> list[dict[str, Any]]:
        if not memory_context.strip():
            return []
        return [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Context note for personalization only. These long-term memories may help with "
                            "the user's next turn. Use them only when relevant, and do not mention this note.\n"
                            f"{memory_context}"
                        )
                    }
                ],
            }
        ]
    async def _apply_google_memory_prefill(self, session: Any, memory_context: str) -> None:
        turns = self._build_google_memory_prefill_turns(memory_context)
        if not turns:
            return
        try:
            await session.send_client_content(turns=turns, turn_complete=False)
        except Exception:
            return
    async def _send_google_tool_response(
        self,
        websocket: WebSocket,
        session: Any,
        *,
        provider_call_id: str,
        tool_name: str,
        response_payload: dict[str, Any],
        result: dict[str, Any] | None = None,
        conversation_turn_id: str = "",
        tool_call_id: str = "",
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        await self._send_google_tool_response_batch(
            websocket,
            session,
            responses=[
                {
                    "provider_call_id": provider_call_id,
                    "tool_name": tool_name,
                    "response_payload": response_payload,
                    "result": result or {},
                    "conversation_turn_id": conversation_turn_id,
                    "tool_call_id": tool_call_id,
                }
            ],
            recorder=recorder,
        )

    async def _send_google_tool_response_batch(
        self,
        websocket: WebSocket,
        session: Any,
        *,
        responses: list[dict[str, Any]],
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        if not responses:
            return
        function_responses = []
        for item in responses:
            provider_call_id = str(item.get("provider_call_id", "")).strip()
            tool_name = str(item.get("tool_name", "")).strip()
            response_payload = item.get("response_payload") or {}
            if not provider_call_id:
                raise ValueError("Google native tool response requires a provider call ID.")
            function_responses.append(
                types.FunctionResponse(
                    id=provider_call_id,
                    name=tool_name,
                    response={"output": response_payload} if response_payload.get("ok") else {"error": response_payload},
                )
            )
        try:
            await session.send_tool_response(function_responses=function_responses)
        except Exception as exc:
            try:
                await self._send_event(
                    websocket,
                    "error",
                    provider="Google",
                    message=f"Google 工具结果回传失败，会话已关闭: {exc}",
                )
            except Exception:
                pass
            close_session = getattr(session, "close", None)
            if callable(close_session):
                try:
                    close_result = close_session()
                    if inspect.isawaitable(close_result):
                        await close_result
                except Exception:
                    logger.exception("google_session_close_after_tool_delivery_failed")
            raise
        for item in responses:
            provider_call_id = str(item.get("provider_call_id", "")).strip()
            tool_name = str(item.get("tool_name", "")).strip()
            response_payload = item.get("response_payload") or {}
            result = item.get("result") or {}
            payload = {
                "provider": "Google",
                "provider_call_id": provider_call_id,
                "tool_name": tool_name,
                "query": str(result.get("query", "")),
                "turn_id": str(item.get("conversation_turn_id", "")),
                "tool_call_id": str(item.get("tool_call_id", "")),
                "route": "native",
                "source_count": int(result.get("source_count", 0) or 0),
                "sources": result.get("sources") or [],
                "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
                "status": "completed" if response_payload.get("ok") else "failed",
            }
            if recorder is not None:
                await recorder.record_tool_event("tool_result_delivered", payload)
            await self._send_event(websocket, "tool_result_delivered", **payload)
    @staticmethod
    def _extract_transcript_text(server_content: Any, candidate_names: tuple[str, ...]) -> str:
        for attr_name in candidate_names:
            if not hasattr(server_content, attr_name):
                continue
            value = getattr(server_content, attr_name)
            if not value:
                continue
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, dict):
                text = value.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
                continue
            if hasattr(value, "text"):
                text = getattr(value, "text", None)
                if isinstance(text, str) and text.strip():
                    return text.strip()
                continue
        return ""
    @classmethod
    def _build_live_config(
        cls,
        voice: str = DEFAULT_GOOGLE_REALTIME_VOICE,
        instructions: str | None = None,
        model: str | None = None,
    ):
        is_transcribe = "transcribe" in str(model or "").lower()
        if is_transcribe:
            return types.LiveConnectConfig(
                response_modalities=["TEXT"],
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
            )

        declarations = [
            types.FunctionDeclaration(
                name=declaration["name"],
                description=declaration["description"],
                parameters_json_schema=declaration["parameters"],
            )
            for declaration in native_tool_declarations()
        ]
        system_inst = instructions or cls._build_realtime_instructions()
        tools_list = []
        if hasattr(types, "GoogleSearch"):
            tools_list.append(types.Tool(google_search=types.GoogleSearch(), function_declarations=declarations))
        else:
            tools_list.append(types.Tool(function_declarations=declarations))
        voice_lookup = {v.lower(): v for v in GOOGLE_REALTIME_VOICES}
        safe_voice = voice_lookup.get((voice or "").strip().lower(), DEFAULT_GOOGLE_REALTIME_VOICE)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system_inst,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tools_list,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=safe_voice)
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=500,
                    silence_duration_ms=1500,
                ),
                activity_handling=types.ActivityHandling.NO_INTERRUPTION,
            ),
        )
    @staticmethod
    def _build_live_translate_config(
        target_language_code: str,
        echo_target_language: bool,
    ):
        # Gemini Live Translate only accepts translation_config (target language +
        # echo toggle). system_instruction / speech_config are unsupported: input
        # language is auto-detected and output voice replicates the speaker.
        target = (target_language_code or "en").strip() or "en"

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            translation_config=types.TranslationConfig(
                target_language_code=target,
                echo_target_language=bool(echo_target_language),
            ),
        )
    async def _client_to_google_loop(
        self,
        websocket: WebSocket,
        session: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        is_live_translate: bool = False,
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
                    if is_live_translate:
                        await self._send_event(
                            websocket,
                            "error",
                            message="Gemini Live Translate 仅支持实时音频输入，不支持文本输入。",
                        )
                        continue
                    content = str(payload.get("text", "")).strip()
                    if content:
                        if recorder is not None:
                            await recorder.note_user_transcript(content)
                        if memory_session is not None:
                            memory_session.note_user_transcript(content)
                        await session.send(input=content, end_of_turn=True)
                    continue
                if command_type == "media_input":
                    if is_live_translate:
                        await self._send_event(
                            websocket,
                            "error",
                            message="Gemini Live Translate 仅支持实时音频输入，不支持多模态文件输入。",
                        )
                        continue
                    data_b64 = str(payload.get("data", "")).strip()
                    mime_type = str(payload.get("mime_type", "image/jpeg")).strip() or "image/jpeg"
                    text_prompt = str(payload.get("text", "")).strip()
                    if data_b64:
                        if "," in data_b64:
                            data_b64 = data_b64.split(",", 1)[1]
                        try:
                            raw_bytes = base64.b64decode(data_b64)
                        except Exception:
                            raw_bytes = b""
                        if raw_bytes:
                            note_text = f"[Image] {text_prompt}" if text_prompt else "[Image]"
                            if recorder is not None:
                                await recorder.note_user_transcript(note_text)
                            if memory_session is not None:
                                memory_session.note_user_transcript(note_text)
                            if types is not None:
                                if text_prompt:
                                    try:
                                        await session.send(
                                            input=[
                                                types.Part.from_bytes(data=raw_bytes, mime_type=mime_type),
                                                types.Part.from_text(text=text_prompt),
                                            ],
                                            end_of_turn=True,
                                        )
                                    except Exception:
                                        # Fallback to separate parts or send_realtime_input
                                        await session.send_realtime_input(
                                            media_chunks=[types.Blob(data=raw_bytes, mime_type=mime_type)]
                                        )
                                        await session.send(input=text_prompt, end_of_turn=True)
                                else:
                                    await session.send_realtime_input(
                                        media_chunks=[types.Blob(data=raw_bytes, mime_type=mime_type)]
                                    )
                    continue
                if command_type == "speech_activity_started":
                    if not is_live_translate and (
                        tool_session.has_active_task
                        or (recorder is not None and bool(recorder.current_turn_id))
                    ):
                        await self._begin_interruption(
                            websocket,
                            interruption,
                            provider="Google",
                            provider_event_type="client_vad.speech_started",
                            recorder=recorder,
                            tool_session=tool_session,
                        )
                    continue
                result = await self._handle_common_client_command(
                    command_type, payload,
                    websocket=websocket, memory_session=memory_session,
                    tool_session=tool_session, recorder=recorder,
                    interruption=interruption, provider="Google",
                    record_memory=not is_live_translate,
                    finalize_on_timeout=not is_live_translate,
                )
                if result == "stop":
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                if not tool_session.has_active_task:
                    await session.send_realtime_input(
                        audio=types.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")
                    )
    async def _google_to_client_loop(
        self,
        websocket: WebSocket,
        session: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        is_live_translate: bool = False,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        pending_prefill_context = ""
        gated_tool_turn_id = ""
        interruption = interruption or InterruptionDecisionCoordinator()
        pending_google_user_transcript = ""
        finalized_google_user_transcript = ""
        google_provider_interrupted_early = False
        suppress_interrupted_google_response = False
        consume_next_google_terminal = False
        last_activity_time = time.time()
        live_translate_has_content = False
        pending_google_response_text = ""
        google_output_transcription_seen = False
        google_output_transcription_text = ""
        live_translate_input_finished = False
        live_translate_output_finished = False

        async def finalize_user_transcript_if_needed(clear_transcript: bool = False) -> None:
            nonlocal pending_google_user_transcript, finalized_google_user_transcript, google_provider_interrupted_early
            nonlocal suppress_interrupted_google_response, consume_next_google_terminal
            nonlocal gated_tool_turn_id, pending_prefill_context
            nonlocal last_activity_time

            user_text = pending_google_user_transcript.strip()
            if pending_google_user_transcript == finalized_google_user_transcript:
                if clear_transcript:
                    pending_google_user_transcript = ""
                    finalized_google_user_transcript = ""
                return

            if clear_transcript:
                pending_google_user_transcript = ""
                finalized_google_user_transcript = ""
            else:
                finalized_google_user_transcript = pending_google_user_transcript

            if not user_text:
                return

            if is_live_translate:
                # In live translate mode, VAD and interruption logic are bypassed
                voice_turn_id = ""
                if recorder is not None:
                    voice_turn_id = await recorder.note_user_transcript(user_text)
                await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
                last_activity_time = time.time()
                return

            if interruption.pending is None and (
                google_provider_interrupted_early
                or tool_session.has_active_task
                or (recorder is not None and bool(recorder.current_assistant_text))
            ):
                await self._begin_interruption(
                    websocket,
                    interruption,
                    provider="Google",
                    provider_event_type="input_transcription.without_pending_vad",
                    recorder=recorder,
                    tool_session=tool_session,
                    supersede_timed_out=True,
                )
            had_deferred_terminal = interruption.has_deferred_terminal()

            should_process_user, interruption_decision = await self._decide_interruption(
                websocket,
                interruption,
                user_text,
                memory_session=memory_session,
                tool_session=tool_session,
                recorder=recorder,
                record_memory=not is_live_translate,
            )
            if not should_process_user:
                google_provider_interrupted_early = False
                if interruption.take_deferred_terminal() is not None and not is_live_translate:
                    await self._finalize_realtime_turn(
                        websocket,
                        memory_session,
                        recorder,
                        gated=bool(gated_tool_turn_id),
                    )
                return
            if interruption_decision is not None:
                is_true_barge_in = (
                    interruption_decision.get("classification")
                    == InterruptionIntent.TRUE_BARGE_IN.value
                )
                suppress_interrupted_google_response = bool(
                    is_true_barge_in
                    and not google_provider_interrupted_early
                    and not had_deferred_terminal
                )
                consume_next_google_terminal = bool(
                    not had_deferred_terminal
                    and is_true_barge_in
                    and not google_provider_interrupted_early
                )
                google_provider_interrupted_early = False
            if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
                return
            voice_turn_id = ""
            if not is_live_translate:
                memory_session.note_user_transcript(user_text)
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
                        "voice_memory_inject provider=Google scope=%s count=%s local_pending=%s cloud=%s",
                        memory_session._config.memory_scope,
                        memory_count,
                        local_pending_count,
                        cloud_count,
                    )
                    pending_prefill_context = memory_context
            await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)

        send_tool_event = self._tool_event_sender(websocket, recorder)

        google_tool_batches: dict[str, dict[str, Any]] = {}

        async def submit_google_batch_result(
            provider_call_id: str,
            tool_name: str,
            response_payload: dict[str, Any],
            result: dict[str, Any] | None = None,
            *,
            conversation_turn_id: str = "",
            tool_call_id: str = "",
            wait_for_delivery: bool = True,
        ) -> None:
            batch = google_tool_batches.get(provider_call_id)
            if batch is None:
                return
            ready: list[dict[str, Any]] | None = None
            ready_ids: list[str] = []
            acknowledgement: asyncio.Future[Any] = batch["acknowledgements"][provider_call_id]
            async with batch["lock"]:
                if batch["phase"] != "collecting" or provider_call_id not in batch["expected"]:
                    return
                batch["results"][provider_call_id] = {
                    "provider_call_id": provider_call_id,
                    "tool_name": tool_name,
                    "response_payload": response_payload,
                    "result": result or {},
                    "conversation_turn_id": conversation_turn_id,
                    "tool_call_id": tool_call_id,
                }
                if batch["expected"].issubset(batch["results"]):
                    batch["phase"] = "sending"
                    ready_ids = [call_id for call_id in batch["order"] if call_id in batch["expected"]]
                    ready = [batch["results"][call_id] for call_id in ready_ids]
            if ready is not None:
                delivery_error: BaseException | None = None
                try:
                    await self._send_google_tool_response_batch(
                        websocket,
                        session,
                        responses=ready,
                        recorder=recorder,
                    )
                except BaseException as exc:
                    delivery_error = exc
                for call_id in ready_ids:
                    pending_ack = batch["acknowledgements"][call_id]
                    if not pending_ack.done():
                        pending_ack.set_result(delivery_error)
                async with batch["lock"]:
                    batch["phase"] = "failed" if delivery_error is not None else "delivered"
                    for call_id in batch["order"]:
                        google_tool_batches.pop(call_id, None)
                if delivery_error is not None:
                    raise delivery_error
            if wait_for_delivery:
                delivery_error = await acknowledgement
                if isinstance(delivery_error, BaseException):
                    raise delivery_error

        async def drop_google_batch_call(provider_call_id: str) -> bool:
            batch = google_tool_batches.get(provider_call_id)
            if batch is None:
                return False
            ready: list[dict[str, Any]] | None = None
            ready_ids: list[str] = []
            async with batch["lock"]:
                if batch["phase"] != "collecting":
                    return False
                batch["expected"].discard(provider_call_id)
                batch["results"].pop(provider_call_id, None)
                google_tool_batches.pop(provider_call_id, None)
                dropped_ack = batch["acknowledgements"][provider_call_id]
                if not dropped_ack.done():
                    dropped_ack.set_result(asyncio.CancelledError())
                if batch["expected"].issubset(batch["results"]):
                    batch["phase"] = "sending"
                    ready_ids = [call_id for call_id in batch["order"] if call_id in batch["expected"]]
                    ready = [batch["results"][call_id] for call_id in ready_ids]
            if ready:
                delivery_error: BaseException | None = None
                try:
                    await self._send_google_tool_response_batch(
                        websocket,
                        session,
                        responses=ready,
                        recorder=recorder,
                    )
                except BaseException as exc:
                    delivery_error = exc
                for call_id in ready_ids:
                    pending_ack = batch["acknowledgements"][call_id]
                    if not pending_ack.done():
                        pending_ack.set_result(delivery_error)
                async with batch["lock"]:
                    batch["phase"] = "failed" if delivery_error is not None else "delivered"
                    for call_id in batch["order"]:
                        google_tool_batches.pop(call_id, None)
                if delivery_error is not None:
                    raise delivery_error
            elif not batch["expected"]:
                async with batch["lock"]:
                    batch["phase"] = "cancelled"
                    for call_id in batch["order"]:
                        google_tool_batches.pop(call_id, None)
            return True

        async def complete_live_translate_turn_if_needed(*, force: bool = False) -> bool:
            nonlocal pending_google_user_transcript, finalized_google_user_transcript
            nonlocal live_translate_has_content, live_translate_input_finished
            nonlocal live_translate_output_finished, last_activity_time

            if not is_live_translate or not live_translate_has_content:
                return False
            if not force and not (live_translate_input_finished and live_translate_output_finished):
                return False

            completed_turn_id = ""
            if recorder is not None:
                completed_turn_id = await recorder.complete_turn({})
            await self._send_event(
                websocket,
                "turn_complete",
                turn_id=completed_turn_id,
                interrupted=False,
            )
            pending_google_user_transcript = ""
            finalized_google_user_transcript = ""
            live_translate_has_content = False
            live_translate_input_finished = False
            live_translate_output_finished = False
            last_activity_time = time.time()
            return True

        monitor_task = None
        if is_live_translate:
            async def monitor_live_translate_inactivity():
                try:
                    while True:
                        await asyncio.sleep(0.5)
                        if live_translate_has_content:
                            now = time.time()
                            if now - last_activity_time >= 2.0:
                                await complete_live_translate_turn_if_needed(force=True)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.exception("Error in live translate inactivity monitor: %s", e)

            monitor_task = asyncio.create_task(monitor_live_translate_inactivity())

        try:
            while True:
                turn = session.receive()
                async for response in turn:
                    audio_data = getattr(response, "data", None)
                    if audio_data:
                        if is_live_translate:
                            last_activity_time = time.time()
                        if not is_live_translate:
                            await finalize_user_transcript_if_needed(clear_transcript=True)
                        if not gated_tool_turn_id and not suppress_interrupted_google_response:
                            await self._emit_assistant_output(
                                websocket,
                                interruption,
                                {
                                    "type": "assistant_audio",
                                    "audio": base64.b64encode(audio_data).decode("ascii"),
                                    "encoding": "pcm_s16le",
                                    "sample_rate": 24000,
                                },
                                memory_session=memory_session,
                                recorder=recorder,
                                record_memory=not is_live_translate,
                            )

                    response_text = getattr(response, "text", None)
                    if response_text:
                        if is_live_translate:
                            last_activity_time = time.time()
                            live_translate_has_content = True
                        if not is_live_translate:
                            await finalize_user_transcript_if_needed(clear_transcript=True)
                        # ``response.text`` is a clean LLM token delta (whitespace
                        # authoritative), not an ASR hypothesis, so it is appended
                        # verbatim rather than overlap-merged.
                        pending_google_response_text = _merge_memory_text(
                            pending_google_response_text,
                            str(response_text),
                        )

                    tool_call = getattr(response, "tool_call", None)
                    if tool_call is not None and not is_live_translate:
                        function_calls = list(getattr(tool_call, "function_calls", None) or [])
                        new_calls: list[tuple[Any, str, str]] = []
                        for function_call in function_calls:
                            provider_call_id = str(getattr(function_call, "id", "") or "").strip()
                            tool_name = str(getattr(function_call, "name", "") or "").strip()
                            logger.warning(
                                "[REALTIME-TOOL-CALL] Google Live fired tool '%s' (call_id=%s) args=%s",
                                tool_name,
                                provider_call_id,
                                dict(getattr(function_call, "args", {}) or {}),
                            )
                            if not provider_call_id:
                                await self._send_event(
                                    websocket,
                                    "error",
                                    provider="Google",
                                    message="Google 返回了缺少 call ID 的工具请求，已拒绝执行。",
                                )
                                continue
                            if tool_session.has_seen_provider_call(provider_call_id):
                                continue
                            if any(existing_id == provider_call_id for _, existing_id, _ in new_calls):
                                continue
                            new_calls.append((function_call, provider_call_id, tool_name))

                        if new_calls:
                            batch = {
                                "order": [call_id for _, call_id, _ in new_calls],
                                "expected": {call_id for _, call_id, _ in new_calls},
                                "results": {},
                                "acknowledgements": {
                                    call_id: asyncio.get_running_loop().create_future()
                                    for _, call_id, _ in new_calls
                                },
                                "lock": asyncio.Lock(),
                                "phase": "collecting",
                            }
                            for _, call_id, _ in new_calls:
                                google_tool_batches[call_id] = batch

                        for function_call, provider_call_id, tool_name in new_calls:
                            conversation_turn_id = recorder.current_turn_id if recorder is not None else ""
                            tool_turn_id = tool_session.reserve_tool_call_id()
                            raw_arguments = getattr(function_call, "args", {}) or {}
                            try:
                                native_call = RealtimeToolCall(
                                    provider="Google",
                                    provider_call_id=provider_call_id,
                                    tool_name=tool_name,
                                    arguments=raw_arguments,
                                )
                                request = tool_call_to_request(native_call)
                            except Exception as exc:
                                tool_session.mark_provider_call_seen(provider_call_id)
                                await submit_google_batch_result(
                                    provider_call_id,
                                    tool_name or "unknown_tool",
                                    tool_error_payload(str(exc)),
                                    conversation_turn_id=conversation_turn_id,
                                    tool_call_id=tool_turn_id,
                                    wait_for_delivery=False,
                                )
                                continue

                            async def on_google_native_result(
                                 result: dict[str, Any],
                                 *,
                                 call_id: str = provider_call_id,
                                 name: str = tool_name,
                                 canonical_turn_id: str = conversation_turn_id,
                                 local_tool_call_id: str = tool_turn_id,
                             ) -> None:
                                 nonlocal gated_tool_turn_id
                                 gated_tool_turn_id = ""
                                 await submit_google_batch_result(
                                     call_id,
                                     name,
                                     tool_result_payload(result),
                                     result,
                                     conversation_turn_id=canonical_turn_id,
                                     tool_call_id=local_tool_call_id,
                                 )

                            async def on_google_native_error(
                                 message: str,
                                 *,
                                 call_id: str = provider_call_id,
                                 name: str = tool_name,
                                 canonical_turn_id: str = conversation_turn_id,
                                 local_tool_call_id: str = tool_turn_id,
                             ) -> None:
                                 nonlocal gated_tool_turn_id
                                 gated_tool_turn_id = ""
                                 await submit_google_batch_result(
                                     call_id,
                                     name,
                                     tool_error_payload(message),
                                     conversation_turn_id=canonical_turn_id,
                                     tool_call_id=local_tool_call_id,
                                 )

                            async def on_google_cancel_prepare(
                                 _reason: str,
                                 *,
                                 call_id: str = provider_call_id,
                             ) -> bool:
                                 nonlocal gated_tool_turn_id
                                 gated_tool_turn_id = ""
                                 return await drop_google_batch_call(call_id)

                            gated_tool_turn_id = tool_turn_id
                            await self._send_response_gated(
                                websocket,
                                provider="Google",
                                tool_name=tool_name,
                                query=request.query,
                                turn_id=tool_turn_id,
                                recorder=recorder,
                            )

                            await tool_session.handle_request(
                                request,
                                send_event=send_tool_event,
                                on_result=on_google_native_result,
                                on_error=on_google_native_error,
                                on_cancel_prepare=on_google_cancel_prepare,
                                provider_call_id=provider_call_id,
                                conversation_turn_id=conversation_turn_id,
                                tool_call_id=tool_turn_id,
                            )

                    tool_cancellation = getattr(response, "tool_call_cancellation", None)
                    if tool_cancellation is not None and not is_live_translate:
                        for provider_call_id in list(getattr(tool_cancellation, "ids", None) or []):
                            cancelled = await tool_session.cancel_provider_call(
                                str(provider_call_id),
                                send_event=send_tool_event,
                                reason="provider_cancelled",
                                notify_provider=True,
                            )
                            if not cancelled:
                                await drop_google_batch_call(str(provider_call_id))

                    server_content = getattr(response, "server_content", None)
                    if not server_content:
                        continue

                    if getattr(server_content, "interrupted", False) and not is_live_translate:
                        await finalize_user_transcript_if_needed(clear_transcript=True)
                        google_provider_interrupted_early = True
                        pending_google_response_text = ""
                        google_output_transcription_seen = False
                        google_output_transcription_text = ""
                        await self._begin_interruption(
                            websocket,
                            interruption,
                            provider="Google",
                            provider_event_type="server_content.interrupted",
                            recorder=recorder,
                            tool_session=tool_session,
                        )

                    user_transcript_fields = ("input_transcription", "input_audio_transcription", "transcription")
                    input_transcription_value: Any = None
                    for transcript_field in user_transcript_fields:
                        if hasattr(server_content, transcript_field):
                            candidate = getattr(server_content, transcript_field)
                            if candidate is not None:
                                input_transcription_value = candidate
                                break
                    user_text_chunk = self._extract_transcript_text(server_content, user_transcript_fields)
                    if user_text_chunk:
                        if is_live_translate:
                            last_activity_time = time.time()
                            live_translate_has_content = True
                        pending_google_user_transcript = _merge_memory_text(
                            pending_google_user_transcript,
                            user_text_chunk,
                        )
                        if InterruptionClassifier.classify_interruption(pending_google_user_transcript) != InterruptionIntent.NOISE_OR_SILENCE:
                            await self._send_event(websocket, "user_transcript", text=pending_google_user_transcript, turn_id="")
                    supports_finished_marker = (
                        input_transcription_value is not None
                        and hasattr(input_transcription_value, "finished")
                    )
                    transcription_finished = bool(
                        getattr(input_transcription_value, "finished", False)
                    ) if supports_finished_marker else input_transcription_value is not None
                    if input_transcription_value is not None and transcription_finished:
                        await finalize_user_transcript_if_needed(clear_transcript=False)

                    if is_live_translate and input_transcription_value is not None and transcription_finished:
                        live_translate_input_finished = True

                    output_transcription_value: Any = None
                    for transcript_field in ("output_transcription", "output_audio_transcription"):
                        if hasattr(server_content, transcript_field):
                            candidate = getattr(server_content, transcript_field)
                            if candidate is not None:
                                output_transcription_value = candidate
                                break
                    assistant_transcript = self._extract_transcript_text(
                        server_content,
                        ("output_transcription", "output_audio_transcription"),
                    )
                    if assistant_transcript:
                        google_output_transcription_seen = True
                        (
                            google_output_transcription_text,
                            assistant_transcript_delta,
                        ) = _merge_streaming_text(
                            google_output_transcription_text, assistant_transcript
                        )
                        if is_live_translate:
                            last_activity_time = time.time()
                            live_translate_has_content = True
                        if (
                            assistant_transcript_delta
                            and not gated_tool_turn_id
                            and not suppress_interrupted_google_response
                        ):
                            await self._emit_assistant_output(
                                websocket,
                                interruption,
                                {"type": "assistant_text", "text": assistant_transcript_delta},
                                memory_session=memory_session,
                                recorder=recorder,
                                record_memory=not is_live_translate,
                            )

                    if (
                        is_live_translate
                        and output_transcription_value is not None
                        and bool(getattr(output_transcription_value, "finished", False))
                    ):
                        live_translate_output_finished = True

                    if is_live_translate:
                        await complete_live_translate_turn_if_needed()

                    if getattr(server_content, "turn_complete", False):
                        if (
                            pending_google_response_text
                            and not google_output_transcription_seen
                            and not gated_tool_turn_id
                            and not suppress_interrupted_google_response
                        ):
                            await self._emit_assistant_output(
                                websocket,
                                interruption,
                                {"type": "assistant_text", "text": pending_google_response_text},
                                memory_session=memory_session,
                                recorder=recorder,
                                record_memory=not is_live_translate,
                            )
                        pending_google_response_text = ""
                        google_output_transcription_seen = False
                        google_output_transcription_text = ""
                        await finalize_user_transcript_if_needed(clear_transcript=True)
                        if is_live_translate:
                            await complete_live_translate_turn_if_needed(force=True)
                            continue
                        if interruption.defer_terminal(
                            {"type": "turn_complete", "provider": "Google"}
                        ):
                            continue
                        if consume_next_google_terminal:
                            consume_next_google_terminal = False
                            suppress_interrupted_google_response = False
                            continue
                        memory_result: dict[str, Any] = {}
                        if not is_live_translate:
                            memory_result = await memory_session.flush_turn()
                            await self._send_event(
                                websocket,
                                "memory_write",
                                attempted_count=int(memory_result.get("attempted_count", 0)),
                                saved_count=int(memory_result.get("saved_count", 0)),
                                failed_count=int(memory_result.get("failed_count", 0)),
                                local_pending_count=int(memory_result.get("local_pending_count", 0)),
                                reason=str(memory_result.get("reason", "")),
                            )
                        if pending_prefill_context and not is_live_translate:
                            await self._apply_google_memory_prefill(session, pending_prefill_context)
                            pending_prefill_context = ""
                        if not gated_tool_turn_id:
                            completed_turn_id = ""
                            if recorder is not None:
                                completed_turn_id = await recorder.complete_turn(memory_result)
                            await self._send_event(
                                websocket,
                                "turn_complete",
                                turn_id=completed_turn_id,
                                interrupted=False,
                            )
        finally:
            if monitor_task is not None:
                monitor_task.cancel()
    async def stream_google_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_GOOGLE_REALTIME_VOICE,
        translation_mode: str = "bidirectional",
        source_language_code: str = "zh-Hans",
        target_language_code: str = "en",
        echo_target_language: bool = True,
    ) -> None:
        settings = self._resolve_google_settings(model)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession(default_provider="Google")
        recorder = await self._create_voice_session_recorder(
            provider="Google",
            model=settings["model"],
            voice=voice,
        )
        http_options: dict[str, str] = {"api_version": "v1beta"}
        if settings["base_url"]:
            http_options["base_url"] = settings["base_url"]

        api_key = settings["api_key"].strip()
        base_url = settings.get("base_url", "").strip()
        is_vertex = "aiplatform.googleapis.com" in base_url
        sa_file = "gen-lang-client-0313108616-b62670b6c2cb.json"

        if is_vertex:
            if os.path.exists(sa_file):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(sa_file)
                client = genai.Client(
                    vertexai=True,
                    project="gen-lang-client-0313108616",
                    location="us-central1",
                )
            else:
                client = genai.Client(
                    vertexai=True,
                    api_key=api_key,
                )
        else:
            client = genai.Client(api_key=api_key, http_options=http_options)
        is_live_translate = _is_google_live_translate_model(settings["model"])
        live_config = (
            self._build_live_translate_config(
                target_language_code,
                echo_target_language,
            )
            if is_live_translate
            else self._build_live_config(voice, self._build_realtime_instructions(), model=settings["model"])
        )

        try:
            async with client.aio.live.connect(model=settings["model"], config=live_config) as session:
                await self._send_event(
                    websocket,
                    "session_open",
                    provider="Google",
                    model=settings["model"],
                    voice=voice,
                    session_id=recorder.session_id if recorder is not None else "",
                    mode="live_translate" if is_live_translate else "realtime_chat",
                    translation_mode=translation_mode if is_live_translate else "",
                    source_language_code=source_language_code if is_live_translate else "",
                    target_language_code=target_language_code if is_live_translate else "",
                    echo_target_language=echo_target_language if is_live_translate else False,
                )
                interruption = InterruptionDecisionCoordinator()
                send_task = asyncio.create_task(
                    self._client_to_google_loop(
                        websocket,
                        session,
                        memory_session,
                        tool_session,
                        recorder,
                        is_live_translate,
                        interruption,
                    )
                )
                receive_task = asyncio.create_task(
                    self._google_to_client_loop(
                        websocket,
                        session,
                        memory_session,
                        tool_session,
                        recorder,
                        is_live_translate,
                        interruption,
                    )
                )
                await self._run_duplex_tasks(send_task, receive_task)
        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.exception("Google realtime session failed: %s", e)
            await self._send_event(websocket, "error", message=f"Google 实时会话启动失败: {str(e)}")
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain(cancel=True)
            if recorder is not None:
                await recorder.finish()
