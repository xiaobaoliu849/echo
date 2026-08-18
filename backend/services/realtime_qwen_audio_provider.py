"""Qwen-Audio (raw WebSocket) realtime voice provider mixin."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import struct
import time
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .realtime_constants import (
    DEFAULT_DASHSCOPE_REALTIME_MODEL,
    QWEN_AUDIO_BENIGN_ERROR_PATTERNS,
    QWEN_AUDIO_REALTIME_INSTRUCTIONS,
    QWEN_AUDIO_REALTIME_VOICES,
    DEFAULT_QWEN_AUDIO_REALTIME_VOICE,
    _audio_energy_qwen,
    _clean_transcript_text,
    _is_dashscope_audio_realtime_model,
    _merge_streaming_text,
    _normalize_dashscope_realtime_voice,
)
from .interruption_classifier import InterruptionClassifier, InterruptionDecisionCoordinator, InterruptionIntent
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .voice_agent_tools import VoiceAgentToolService, VoiceAgentToolSession, VoiceToolRequest

logger = logging.getLogger(__name__)

# Post-playback echo mute: after the AI finishes speaking, mic audio is dropped
# for this long to avoid feeding speaker echo back as a false barge-in. The
# official Qwen-Audio demo uses 0.5s in echo-suppression mode; 0.3s trims the
# dead air so users who start speaking right after the AI don't lose the first
# words of their turn (previously 1.0s, which ate utterance onsets).
POST_PLAYBACK_MUTE_SECONDS = 0.3


class QwenAudioRealtimeMixin:
    """Qwen-Audio raw-WebSocket provider methods for RealtimeVoiceService."""

    @staticmethod
    def is_qwen_audio_model(model: str | None) -> bool:
        """Return True when *model* is a Qwen-Audio realtime model (supports native function calling)."""
        return bool(model and "qwen-audio" in str(model).lower())
    @staticmethod
    def _build_qwen_audio_instructions(memory_context: str = "") -> str:
        import datetime
        current_date = datetime.date.today().isoformat()
        base = f"{QWEN_AUDIO_REALTIME_INSTRUCTIONS}\n当前日期: {current_date}。"
        if not memory_context:
            return base
        return (
            f"{base}\n\n"
            "以下是系统检索到的长期记忆，用于个性化回复。当相关时请参考这些记忆，"
            "但不要逐字引用，除非用户直接询问。\n"
            f"{memory_context}"
        )
    async def _client_to_qwen_audio_loop(
        self,
        websocket: WebSocket,
        dash_ws: Any,
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
                        await dash_ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": content}],
                            },
                        }))
                        await dash_ws.send(json.dumps({"type": "response.create"}))
                    continue
                if command_type == "media_input":
                    text_prompt = str(payload.get("text", "")).strip()
                    note_text = f"[Image] {text_prompt}" if text_prompt else "[Image]"
                    if recorder is not None:
                        await recorder.note_user_transcript(note_text)
                    if memory_session is not None:
                        memory_session.note_user_transcript(note_text)
                    prompt = f"[User attached an image]\n{text_prompt}" if text_prompt else "[User attached an image]"
                    await dash_ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": prompt}],
                        },
                    }))
                    await dash_ws.send(json.dumps({"type": "response.create"}))
                    continue
                # Qwen-specific: reset echo gate before common handling
                if command_type == "interruption_client_stopped":
                    if hasattr(interruption, "expected_playback_end_time"):
                        interruption.expected_playback_end_time = 0.0
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
                # ── Half-duplex echo suppression with energy gate ──
                # During AI playback we block ONLY low-energy audio (speaker echo)
                # and let high-energy audio through so the user can still interrupt.
                # This matches the official Qwen-Audio demo's "headphone mode".
                NOISE_GATE_THRESHOLD = 500
                ai_is_playing = bool(interruption and interruption.active_response_id)
                if ai_is_playing:
                    energy = _audio_energy_qwen(audio_bytes)
                    if energy < NOISE_GATE_THRESHOLD:
                        continue  # low energy → likely echo, suppress
                    # User is speaking loudly enough → let it through to interrupt
                elif interruption and hasattr(interruption, "expected_playback_end_time"):
                    # Brief buffer for frontend/network echo tail after AI finishes
                    if time.time() < getattr(interruption, "expected_playback_end_time") + POST_PLAYBACK_MUTE_SECONDS:
                        continue

                await dash_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_bytes).decode("ascii"),
                }))
    async def _qwen_audio_to_client_loop(
        self,
        websocket: WebSocket,
        dash_ws: Any,
        memory_session: RealtimeMemorySession,
        voice: str,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
    ) -> None:
        async def send_tool_event(event_type: str, payload: dict[str, Any]) -> None:
            if recorder is not None:
                await recorder.record_tool_event(event_type, payload)
            # Tool events are status chrome (spinner/progress), not conversation
            # content: the frontend renders them as a status line + sources panel,
            # while the user's live interim transcript already occupies the user
            # bubble. They must reach the UI the moment the tool starts — buffering
            # them behind the final ASR transcript left the desktop silent for the
            # entire search ("不知道模型在干嘛").
            await self._send_event(websocket, event_type, **payload)

        async def _flush_pending_output() -> None:
            """Send all buffered AI text/audio events now that the user transcript
            has been emitted (keeps user text above the assistant reply)."""
            nonlocal _pending_ai_output, _user_transcript_emitted
            _user_transcript_emitted = True
            if _pending_ai_output:
                for _, payload in _pending_ai_output:
                    await self._emit_assistant_output(
                        websocket, interruption, payload,
                        memory_session=memory_session, recorder=recorder,
                    )
                _pending_ai_output.clear()

        async def _emit_held_family_delta(response_id: str, state: dict[str, str] | None) -> None:
            """Force the family decision for a response still holding its first
            audio_transcript delta and emit the held text. audio_transcript wins
            by default when no text.delta ever arrived for the response."""
            if not state or state["decided"] or not state["held_audio"]:
                return
            state["decided"] = "audio_transcript"
            held = state["held_audio"]
            state["held_audio"] = ""
            payload = {
                "type": "assistant_text",
                "text": held,
                "response_id": response_id,
            }
            if not _user_transcript_emitted:
                _pending_ai_output.append(("text", payload))
            else:
                await self._emit_assistant_output(
                    websocket, interruption, payload,
                    memory_session=memory_session, recorder=recorder,
                )

        gated_tool_turn_id = ""
        # Track ALL pending native function_call ids in the current turn. A turn may
        # contain multiple parallel function_calls; the follow-up response.create must
        # only be sent after every call's function_call_output has been written back.
        pending_native_fc_call_ids: set[str] = set()
        # Tracks whether ANY native function call has occurred since the user started
        # speaking. When True, the regex-based tool extraction path is skipped to
        # prevent double-execution (native FC already handled the tool, then regex
        # fires again causing response.cancel + response_gated + duplicate tool call).
        _native_fc_occurred_this_turn = False
        # Buffer AI text/audio events until the user transcript has been emitted,
        # so the frontend always shows: user speech → AI reply. Tool events are
        # NOT buffered (see send_tool_event) so tool progress is visible instantly.
        _pending_ai_output: list[tuple[str, dict[str, Any]]] = []
        _user_transcript_emitted = True  # starts True (no pending transcript before first turn)
        # Whether the FINAL ASR transcript for the current user utterance has
        # already been forwarded to the frontend. response.created uses this to
        # decide whether the new response round must buffer its output: when the
        # transcript beat response.created (common in server_vad), re-entering
        # the buffering state would stall every tool event / reply delta until
        # the 8s deferred-done timeout, since no second transcript ever comes.
        _final_transcript_emitted_this_turn = True
        # When response.created arrives before the ASR transcript, the server has
        # started responding to the user's speech.  This flag prevents the first
        # transcript of each response cycle from being misclassified as a barge-in
        # interruption (which would silently drop it and break the UI ordering).
        _first_transcript_this_response = True
        # With modalities ["text","audio"] the model streams the same content over
        # both response.text.delta (clean LLM text) and response.audio_transcript.delta
        # (server-side ASR of its own TTS audio, which degrades badly for accented
        # non-native speech, e.g. a Chinese voice speaking English). Only ONE family
        # may be forwarded per response or the client transcript duplicates every
        # sentence. The text family is preferred: the first audio_transcript delta
        # is held back for one event so a near-simultaneous text.delta can claim
        # the response; a second audio_transcript delta (or response.done / loop
        # exit) locks the response to audio_transcript and replays the held delta.
        response_delta_family_state: dict[str, dict[str, str]] = {}
        # Marks whether the current response contains function_call(s); such a response
        # is an intermediate round and must NOT finalize the turn on response.done.
        current_response_has_function_call = False
        # ── Deferred response.done ──────────────────────────────────
        # In server_vad mode the ASR transcript often arrives AFTER response.done.
        # Instead of force-flushing the buffer on response.done (which sends AI
        # output + turn_complete before the user's text), we *defer* the
        # response.done processing until the transcript arrives (or a timeout).
        _deferred_response_done: dict[str, Any] | None = None
        TRANSCRIPT_WAIT_TIMEOUT = 8.0  # seconds to wait for ASR transcript
        # Interim (streaming) input ASR text per conversation item, used to
        # give the frontend Google-style live transcription while the user is
        # still speaking. Display-only: never touches interruption/memory logic.
        _interim_transcripts: dict[str, str] = {}
        interruption = interruption or InterruptionDecisionCoordinator()
        suppressed_response_ids: set[str] = set()

        async def _process_response_done(response_done_event: dict[str, Any]) -> None:
            """Process a response.done event (original inline logic extracted here
            so it can be reused for deferred and timeout paths)."""
            nonlocal gated_tool_turn_id, current_response_has_function_call
            nonlocal pending_native_fc_call_ids
            response_data = response_done_event.get("response") or {}
            response_id = str(response_data.get("id", ""))
            family_state = response_delta_family_state.pop(response_id, None)
            if response_id in suppressed_response_ids:
                suppressed_response_ids.discard(response_id)
                if response_id == interruption.active_response_id:
                    interruption.active_response_id = ""
                return
            if interruption.defer_terminal({"type": "turn_complete", "response_id": response_id,
                                             "status": str(response_data.get("status", "completed"))}):
                return
            if not response_id or response_id == interruption.active_response_id:
                interruption.active_response_id = ""
            # A response that carried function_call(s) is an intermediate round:
            # the turn continues after we send response.create, so do NOT finalize
            # (flush memory / emit turn_complete) here. Flush any held first
            # audio_transcript delta (e.g. the model's "让我查一下" preface) so it
            # isn't lost, then reset the flag and stop.
            if current_response_has_function_call:
                await _emit_held_family_delta(response_id, family_state)
                current_response_has_function_call = False
                pending_native_fc_call_ids.clear()
                return
            if str(response_data.get("status", "completed")) in {"cancelled", "canceled", "failed"}:
                return
            # Successful completion: emit a held first audio_transcript delta
            # (no text.delta ever arrived) before finalizing the turn.
            await _emit_held_family_delta(response_id, family_state)
            memory_result = await memory_session.flush_turn()
            completed_turn_id = ""
            if recorder is not None and not gated_tool_turn_id:
                completed_turn_id = await recorder.complete_turn(memory_result)
            await self._send_event(
                websocket, "memory_write",
                attempted_count=int(memory_result.get("attempted_count", 0)),
                saved_count=int(memory_result.get("saved_count", 0)),
                failed_count=int(memory_result.get("failed_count", 0)),
                local_pending_count=int(memory_result.get("local_pending_count", 0)),
                reason=str(memory_result.get("reason", "")),
            )
            await dash_ws.send(json.dumps({
                "type": "session.update",
                "session": {"instructions": self._build_qwen_audio_instructions()},
            }))
            if not gated_tool_turn_id:
                await self._send_event(
                    websocket, "turn_complete",
                    turn_id=completed_turn_id, interrupted=False,
                )

        async def _resolve_deferred_response_done() -> None:
            """Flush buffered output and process a deferred response.done, if any."""
            nonlocal _deferred_response_done
            if _deferred_response_done is None:
                return
            deferred = _deferred_response_done
            _deferred_response_done = None
            await _flush_pending_output()
            await _process_response_done(deferred)

        while True:
            # When a deferred response.done is waiting for the ASR transcript,
            # use a shorter recv timeout so we don't block for 5 minutes.
            recv_timeout = TRANSCRIPT_WAIT_TIMEOUT if _deferred_response_done is not None else 300
            try:
                raw = await asyncio.wait_for(dash_ws.recv(), timeout=recv_timeout)
            except asyncio.TimeoutError:
                if _deferred_response_done is not None:
                    # Transcript didn't arrive in time — give up waiting,
                    # flush buffered output and finalize the turn.
                    await _resolve_deferred_response_done()
                continue
            except Exception:
                break

            try:
                event = json.loads(raw) if isinstance(raw, str) else json.loads(str(raw))
            except Exception:
                continue

            event_type = str(event.get("type", "")).strip()
            if event_type == "closed":
                break
            if event_type in {"session.created", "session.updated"}:
                continue
            if event_type == "input_audio_buffer.speech_started":
                # If a previous response.done is still waiting for its ASR
                # transcript, the transcript will never arrive (user is speaking
                # again).  Flush and finalize it before starting the new turn.
                await _resolve_deferred_response_done()
                # New user speech starts: reset guards so the upcoming
                # transcription and function calls are handled correctly.
                _first_transcript_this_response = True
                _native_fc_occurred_this_turn = False
                _final_transcript_emitted_this_turn = False
                if interruption.active_response_id or tool_session.has_active_task or (
                    recorder is not None and bool(recorder.current_assistant_text)
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="DashScope",
                        provider_event_type=str(event.get("type", "input_audio_buffer.speech_started")),
                        recorder=recorder,
                        tool_session=tool_session,
                    )
                continue
            if event_type == "response.created":
                # If a previous response.done is still deferred (ASR transcript
                # never arrived), flush and finalize it before the new round.
                await _resolve_deferred_response_done()
                interruption.active_response_id = (
                    str((event.get("response") or {}).get("id", "")) or interruption.active_response_id or "active"
                )
                # New response round begins; reset the per-response function_call marker.
                current_response_has_function_call = False
                # Buffer this round's AI output ONLY if the user turn's final
                # transcript hasn't been forwarded yet (response.created beat the
                # ASR transcript). When the transcript already went out, another
                # one will never arrive this turn — buffering again would hide
                # the reply behind the 8s deferred-done timeout.
                _user_transcript_emitted = _final_transcript_emitted_this_turn
                _first_transcript_this_response = True
                continue
            if event_type in (
                "conversation.item.input_audio_transcription.delta",
                "conversation.item.input_audio_transcription.text",
            ):
                # Streaming interim ASR of the user's speech. Per the official
                # docs, user speech transcription has delta and completed
                # phases (like Google's input transcription); forwarding the
                # interim text lets the frontend show words as they are
                # recognized instead of waiting for the turn to finalize.
                # Two shapes are handled defensively: incremental `delta`
                # fragments and cumulative `text`(+tentative `stash`) frames.
                item_id = str(event.get("item_id", ""))
                raw_delta = event.get("delta")
                if raw_delta is not None:
                    interim_text = _interim_transcripts.get(item_id, "") + str(raw_delta)
                else:
                    interim_text = str(event.get("text", "")) + str(event.get("stash", ""))
                _interim_transcripts[item_id] = interim_text
                if len(_interim_transcripts) > 8:
                    # Bound the map: drop the oldest item's state.
                    _interim_transcripts.pop(next(iter(_interim_transcripts)), None)
                if interim_text.strip():
                    await self._send_event(
                        websocket, "user_transcript", text=interim_text, interim=True,
                    )
                continue
            if event_type.startswith("conversation.item.ambient_audio_transcription"):
                # smart_turn ambient-noise transcript (非有效轮次): not a user
                # turn, never written to context — ignore for display.
                continue
            if event_type == "conversation.item.input_audio_transcription.completed":
                _interim_transcripts.pop(str(event.get("item_id", "")), None)
                user_text = str(event.get("transcript", "")).strip()
                # ── Interruption vs. first-transcript dispatch ──
                # The server may send response.created before the ASR transcript.
                # When that happens, active_response_id is already set and the
                # transcript would be misclassified as a barge-in interruption,
                # potentially dropped entirely.  The _first_transcript_this_response
                # flag guards against this: the first transcript of each response
                # cycle always reaches the frontend so the UI order is correct.
                if not _first_transcript_this_response:
                    if interruption.pending is None and (
                        interruption.active_response_id
                        or tool_session.has_active_task
                        or (recorder is not None and bool(recorder.current_assistant_text))
                    ):
                        await self._begin_interruption(
                            websocket,
                            interruption,
                            provider="DashScope",
                            provider_event_type=str(event.get("type", "input_transcription.without_pending_vad")),
                            recorder=recorder,
                            tool_session=tool_session,
                            supersede_timed_out=True,
                        )
                    interrupted_response_id = interruption.active_response_id
                    had_deferred_terminal = interruption.has_deferred_terminal()
                    async def cancel_dashscope_response() -> None:
                        try:
                            await dash_ws.send(json.dumps({"type": "response.cancel"}))
                        except Exception:
                            logger.exception("qwen_audio_response_cancel_failed")

                    should_process_user, interruption_decision = await self._decide_interruption(
                        websocket,
                        interruption,
                        user_text,
                        memory_session=memory_session,
                        tool_session=tool_session,
                        recorder=recorder,
                        cancel_provider=cancel_dashscope_response,
                    )
                    if interruption_decision is not None and (
                        interruption_decision.get("classification") == InterruptionIntent.TRUE_BARGE_IN.value
                    ) and interrupted_response_id and not had_deferred_terminal:
                        suppressed_response_ids.add(interrupted_response_id)
                    if not should_process_user:
                        if had_deferred_terminal and interruption.take_deferred_terminal() is not None:
                            await self._finalize_realtime_turn(
                                websocket, memory_session, recorder, gated=bool(gated_tool_turn_id),
                            )
                            await dash_ws.send(json.dumps({
                                "type": "session.update",
                                "session": {"instructions": self._build_qwen_audio_instructions()},
                            }))
                        continue
                    if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
                        continue
                else:
                    _first_transcript_this_response = False
                # ── Common path: send user transcript, flush buffered AI output ──
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
                        websocket, "memory_context",
                        memories_retrieved=memory_count,
                        local_pending_count=local_pending_count,
                        cloud_count=cloud_count,
                        attempted=True,
                    )
                base_instructions = self._build_qwen_audio_instructions(memory_context)
                if not memory_context and memory_session.is_forced_recall_query(user_text):
                    base_instructions = self._build_recall_miss_instructions(user_text)
                async def on_qwen_audio_tool_result(result: dict[str, Any]) -> None:
                    nonlocal gated_tool_turn_id
                    gated_tool_turn_id = ""
                    await self._apply_qwen_audio_tool_result(websocket, dash_ws, result, recorder)

                # Native function-call gating: if the model has already called a
                # tool natively this turn, skip backend regex extraction entirely
                # to prevent double-execution (native FC runs the tool, then regex
                # fires again causing response.cancel + response_gated + duplicate).
                if _native_fc_occurred_this_turn:
                    await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
                    _final_transcript_emitted_this_turn = True
                    await _flush_pending_output()
                    # Process a deferred response.done now that ordering is correct.
                    if _deferred_response_done is not None:
                        deferred = _deferred_response_done
                        _deferred_response_done = None
                        await _process_response_done(deferred)
                    continue

                tool_request = VoiceAgentToolService.extract_tool_request(user_text)
                tool_turn_id = await tool_session.handle_user_transcript(
                    user_text,
                    send_event=send_tool_event,
                    on_result=on_qwen_audio_tool_result,
                )
                # Always emit user_transcript FIRST, before any tool events
                # (response_gated, etc.), so the frontend shows the user's
                # transcribed speech above the tool status.
                await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)
                _final_transcript_emitted_this_turn = True
                if tool_turn_id:
                    gated_tool_turn_id = tool_turn_id
                    try:
                        await dash_ws.send(json.dumps({"type": "response.cancel"}))
                    except Exception:
                        pass
                    await self._send_response_gated(
                        websocket, provider="DashScope",
                        tool_name=tool_request.tool_name if tool_request else "voice_tool",
                        query=tool_request.query if tool_request else "",
                        turn_id=tool_turn_id, recorder=recorder,
                    )
                # No manual response.create here: with server-side turn detection
                # (server_vad / smart_turn) the server creates the response on its
                # own once it finalizes the user transcript. An extra
                # response.create races the user's ongoing speech and the server
                # rejects it with "Cannot create response while user is speaking",
                # which used to tear down the whole session.
                await _flush_pending_output()
                # Process a deferred response.done now that ordering is correct.
                if _deferred_response_done is not None:
                    deferred = _deferred_response_done
                    _deferred_response_done = None
                    await _process_response_done(deferred)
                continue
            if event_type == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    call_id = str(item.get("call_id", ""))
                    if call_id:
                        pending_native_fc_call_ids.add(call_id)
                    current_response_has_function_call = True
                continue
            if event_type == "response.function_call_arguments.done":
                call_id = str(event.get("call_id", ""))
                name = str(event.get("name", ""))
                arguments_str = str(event.get("arguments", "{}"))
                # 去重：Qwen 网络抖动/重连可能重发同一个 function_call。已执行过的
                # call_id 不再重复执行工具；若 provider 同时重发了 output_item.added
                # 把它重新塞进 pending 集合，这里 discard 掉避免集合泄漏，但不再补发
                # response.create（原始那一轮已经触发过）。对齐 Google/DashScope 的
                # has_seen_provider_call / mark_provider_call_seen 逻辑。
                if tool_session.has_seen_provider_call(call_id):
                    pending_native_fc_call_ids.discard(call_id)
                    continue
                tool_session.mark_provider_call_seen(call_id)
                # Mark that native FC occurred this turn so the regex path is
                # skipped when the transcript arrives (prevents double-execution).
                _native_fc_occurred_this_turn = True
                # Execute the tool and write back its function_call_output (without
                # triggering response.create yet). Only when every pending call in this
                # turn has produced its output do we send a single response.create.
                await self._handle_qwen_audio_function_call(
                    websocket, dash_ws, call_id, name, arguments_str,
                    tool_session=tool_session,
                    recorder=recorder,
                    send_tool_event=send_tool_event,
                    trigger_response=False,
                )
                pending_native_fc_call_ids.discard(call_id)
                if not pending_native_fc_call_ids:
                    await dash_ws.send(json.dumps({
                        "type": "response.create",
                        "response": {"modalities": ["text", "audio"]}
                    }))
                continue
            if event_type == "response.audio.delta":
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    continue
                if not gated_tool_turn_id:
                    delta_b64 = str(event.get("delta", ""))
                    if delta_b64:
                        try:
                            audio_len = len(delta_b64) * 3 // 4
                            audio_duration = audio_len / 48000.0
                            if not hasattr(interruption, "expected_playback_end_time"):
                                interruption.expected_playback_end_time = time.time()
                            if interruption.expected_playback_end_time < time.time():
                                interruption.expected_playback_end_time = time.time()
                            interruption.expected_playback_end_time += audio_duration
                        except Exception:
                            pass
                    payload = {
                        "type": "assistant_audio",
                        "audio": delta_b64,
                        "response_id": response_id,
                    }
                    if not _user_transcript_emitted:
                        _pending_ai_output.append(("audio", payload))
                    else:
                        await self._emit_assistant_output(
                            websocket, interruption, payload,
                            memory_session=memory_session, recorder=recorder,
                        )
                continue
            if event_type in {"response.audio_transcript.delta", "response.text.delta"}:
                response_id = str(event.get("response_id", ""))
                if response_id in suppressed_response_ids:
                    continue
                family = (
                    "audio_transcript"
                    if event_type.startswith("response.audio_transcript")
                    else "text"
                )
                delta = str(event.get("delta", ""))
                if gated_tool_turn_id or not delta:
                    continue
                state = response_delta_family_state.setdefault(
                    response_id, {"decided": "", "held_audio": "", "accumulated_text": ""}
                )
                if family == "audio_transcript":
                    delta = _clean_transcript_text(delta)
                decided_family = state["decided"]
                deltas_to_emit: list[str] = []
                if decided_family:
                    if family == decided_family:
                        deltas_to_emit = [delta]
                    else:
                        # Cross-family continuation: if text.delta claimed the response but stopped
                        # streaming, allow audio_transcript delta if it contains novel text.
                        acc = state.get("accumulated_text", "")
                        _, novel = _merge_streaming_text(acc, delta)
                        if novel:
                            deltas_to_emit = [novel]
                        else:
                            continue
                elif family == "text":
                    # Clean LLM text claims the response immediately; any held
                    # audio_transcript delta is discarded.
                    state["decided"] = "text"
                    state["held_audio"] = ""
                    deltas_to_emit = [delta]
                elif not state["held_audio"]:
                    # First audio_transcript delta: hold it for one event so a
                    # near-simultaneous text.delta (clean text) can still win.
                    state["held_audio"] = delta
                    continue
                else:
                    # Second audio_transcript delta and no text family in sight:
                    # lock to audio_transcript, replaying the held delta first.
                    state["decided"] = "audio_transcript"
                    deltas_to_emit = [state["held_audio"], delta]
                    state["held_audio"] = ""
                for emit_delta in deltas_to_emit:
                    if not emit_delta:
                        continue
                    acc = state.get("accumulated_text", "")
                    new_acc, novel = _merge_streaming_text(acc, emit_delta)
                    if not novel:
                        continue
                    state["accumulated_text"] = new_acc
                    payload = {
                        "type": "assistant_text",
                        "text": novel,
                        "response_id": response_id,
                    }
                    if not _user_transcript_emitted:
                        _pending_ai_output.append(("text", payload))
                    else:
                        await self._emit_assistant_output(
                            websocket, interruption, payload,
                            memory_session=memory_session, recorder=recorder,
                        )
                continue
            if event_type == "response.done":
                # ★ KEY FIX: If the ASR transcript hasn't arrived yet, defer
                # response.done processing instead of force-flushing the buffer.
                # This ensures the frontend receives events in the correct order:
                #   user_transcript → tool events → assistant text/audio → turn_complete
                # The deferred response.done is processed when the transcript
                # arrives, or after TRANSCRIPT_WAIT_TIMEOUT, or when new speech /
                # a new response.created is detected.
                #
                # Exception: function_call rounds are intermediate — their
                # response.done only resets the FC flag and must NOT be deferred
                # (deferring would cause the next response.created to flush tool
                # events before the transcript, re-creating the ordering bug).
                if not _user_transcript_emitted and not current_response_has_function_call:
                    _deferred_response_done = event
                    continue
                # Transcript already emitted, or FC intermediate round — process now.
                await _process_response_done(event)
                continue
            if gated_tool_turn_id and event_type in {"assistant_audio", "assistant_text", "turn_complete"}:
                continue
            if event_type == "error":
                error_data = event.get("error")
                if isinstance(error_data, dict):
                    message = str(error_data.get("message", "")).strip() or str(event)
                else:
                    message = str(error_data or event).strip()
                # Benign race conditions (e.g. our response.create / response.cancel
                # colliding with the server's own turn management) must not kill the
                # session - log them and keep listening.
                if any(pattern in message for pattern in QWEN_AUDIO_BENIGN_ERROR_PATTERNS):
                    logger.warning("qwen_audio_benign_error message=%s", message)
                    continue
                await self._send_event(websocket, "error", message=f"DashScope: {message}")
                break

        # ── Loop exited (connection closed / error) ─────────────────
        # If a deferred response.done is still pending (transcript never
        # arrived and no timeout fired), flush and finalize it so the
        # frontend doesn't miss the turn.
        if _deferred_response_done is not None:
            await _resolve_deferred_response_done()
        # Force-decide any responses still holding their first audio_transcript
        # delta (no text.delta ever came, no response.done seen) so the held
        # text isn't lost when the connection drops mid-stream.
        for held_response_id, held_state in list(response_delta_family_state.items()):
            await _emit_held_family_delta(held_response_id, held_state)
    @staticmethod
    async def _send_qwen_audio_function_call_output(dash_ws: Any, call_id: str, output: str) -> None:
        """Write a function_call_output conversation item back to the model."""
        await dash_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id, "output": output},
        }))
    async def _handle_qwen_audio_function_call(
        self,
        websocket: WebSocket,
        dash_ws: Any,
        call_id: str,
        name: str,
        arguments_str: str,
        *,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        send_tool_event: Any = None,
        trigger_response: bool = True,
    ) -> None:
        """Handle a native function_call from Qwen-Audio: execute tool and write back its output.

        When *trigger_response* is True (single-call / standalone usage), a follow-up
        ``response.create`` is sent immediately. When False, the caller is responsible
        for sending ``response.create`` once every pending call in the turn has been
        resolved (required for turns that contain multiple parallel function_calls).
        """
        logger.info("qwen_audio_function_call call_id=%s name=%s args=%s", call_id, name, arguments_str)
        try:
            arguments = json.loads(arguments_str) if arguments_str else {}
        except json.JSONDecodeError:
            arguments = {}

        # Map function name → query text and tool_name for VoiceAgentToolService
        name_lower = name.lower().strip()
        if name_lower == "search_web":
            query = str(arguments.get("query", "")).strip()
            tool_name = "search_web"
        elif name_lower == "translate_text":
            text = str(arguments.get("text", "")).strip()
            target = str(arguments.get("target_language", "英文")).strip()
            query = f"{text}\n目标语言: {target}"
            tool_name = "translate_text"
        elif name_lower == "summarize_transcript":
            content = str(arguments.get("content", "")).strip()
            query = content
            tool_name = "summarize_transcript"
        elif name_lower == "synthesize_tts":
            content = str(arguments.get("content", "")).strip()
            query = content
            tool_name = "synthesize_tts"
        elif name_lower == "create_audio_agent_run":
            topic = str(arguments.get("topic", "")).strip()
            query = topic
            tool_name = "create_audio_agent_run"
        else:
            await self._send_qwen_audio_function_call_output(
                dash_ws, call_id, json.dumps({"error": f"未知工具: {name}"})
            )
            if trigger_response:
                await dash_ws.send(json.dumps({
                    "type": "response.create",
                    "response": {"modalities": ["text", "audio"]}
                }))
            return

        if not query:
            await self._send_qwen_audio_function_call_output(
                dash_ws, call_id, json.dumps({"error": "缺少必要的查询参数"})
            )
            if trigger_response:
                await dash_ws.send(json.dumps({
                    "type": "response.create",
                    "response": {"modalities": ["text", "audio"]}
                }))
            return

        request = VoiceToolRequest(tool_name=tool_name, query=query, display_name=tool_name, requires_confirmation=False)
        send_event_fn = send_tool_event if send_tool_event is not None else (
            lambda et, p: self._send_event(websocket, et, **p)
        )

        # Execute the tool and write back its output. The follow-up response.create is
        # deferred to the caller unless trigger_response=True.
        try:
            result = await tool_session.service.run_tool(
                request, send_event=send_event_fn, turn_id=f"native-fc-{call_id[:12]}",
            )
        except Exception as exc:
            logger.exception("qwen_audio tool execution failed call_id=%s", call_id)
            await self._send_qwen_audio_function_call_output(
                dash_ws, call_id, json.dumps({"error": str(exc)})
            )
            if trigger_response:
                await dash_ws.send(json.dumps({
                    "type": "response.create",
                    "response": {"modalities": ["text", "audio"]}
                }))
            return

        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        output = prompt if prompt.strip() else json.dumps({"status": "completed", "summary": str(result.get("answer", ""))})
        await self._send_qwen_audio_function_call_output(dash_ws, call_id, output)
        if trigger_response:
            await dash_ws.send(json.dumps({
                "type": "response.create",
                "response": {"modalities": ["text", "audio"]}
            }))
    async def _apply_qwen_audio_tool_result(
        self,
        websocket: WebSocket,
        dash_ws: Any,
        result: dict[str, Any],
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        """Inject backend regex-detected tool result as a user message (non-native fallback)."""
        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        if not prompt.strip():
            return
        payload = {
            "provider": "DashScope",
            "tool_name": str(result.get("tool_name", "search_web") or "search_web"),
            "query": str(result.get("query", "")),
            "turn_id": str(result.get("turn_id", "")),
            "source_count": int(result.get("source_count", 0) or 0),
            "sources": result.get("sources") or [],
            "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_context_injected", payload)
        await self._send_event(websocket, "tool_context_injected", **payload)
        # For raw WebSocket, send tool result as a user message then trigger response
        await dash_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        }))
        await dash_ws.send(json.dumps({
            "type": "response.create",
            "response": {"modalities": ["text", "audio"]}
        }))
    async def stream_dashscope_audio_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str | None = None,
    ) -> None:
        """Raw-WebSocket session for Qwen-Audio models with native function calling.

        This bypasses the DashScope SDK (``OmniRealtimeConversation``) and
        uses ``websockets.connect()`` directly so we can send ``tools`` in
        ``session.update`` and handle ``function_call_arguments.done`` events.
        """
        settings = self._resolve_dashscope_settings(model)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession(default_provider="DashScope")
        resolved_voice = (voice or DEFAULT_QWEN_AUDIO_REALTIME_VOICE).strip()
        if resolved_voice not in QWEN_AUDIO_REALTIME_VOICES:
            logger.warning(
                "qwen_audio_unsupported_voice voice=%s fallback=%s",
                resolved_voice, DEFAULT_QWEN_AUDIO_REALTIME_VOICE,
            )
            resolved_voice = DEFAULT_QWEN_AUDIO_REALTIME_VOICE
        recorder = await self._create_voice_session_recorder(
            provider="DashScope",
            model=settings["model"],
            voice=resolved_voice,
        )

        # Use the configured workspace Realtime URL (validated in
        # _resolve_dashscope_settings to be a cn-beijing maas URL for
        # qwen-audio models), same as stream_dashscope_session does.
        ws_url = f"{settings['realtime_base_url']}?model={settings['model']}"
        extra_headers = {
            "Authorization": f"Bearer {settings['api_key']}",
        }
        tools = VoiceAgentToolService.build_tools_schema()

        try:
            async with websockets.connect(
                ws_url,
                additional_headers=extra_headers,
                max_size=2**24,
                # Keepalive pings: without them a half-open TCP connection
                # (VPN drop, laptop sleep, NAT timeout) hangs the session
                # forever because nothing notices the peer is gone.
                ping_interval=30,
                ping_timeout=20,
            ) as dash_ws:
                # ── session.update with tools + turn detection ──
                # Default: server_vad with a moderate 2000ms silence window.
                # History: 5000ms made transcripts/replies appear ages after
                # the user finished; smart_turn (semantic endpointing) was
                # too eager — it fired on mid-sentence thinking pauses, the
                # model cut in, and the user's resumed speech then barged in
                # on that reply, looping "reply interrupted" states. 2000ms
                # is the compromise: live interim transcription (streamed
                # independently of VAD) keeps on-screen text instant, while
                # the model waits out short thinking pauses before answering.
                # config.json overrides (realtime section):
                #   "qwen_audio_turn_detection": "smart_turn"  — semantic mode
                #   "qwen_audio_silence_duration_ms": 800      — snappier VAD
                #   (API range 200-6000; official dialogue recommendation
                #    is 400-800, higher values suit language learners)
                realtime_cfg: dict[str, Any] = {}
                try:
                    cfg_section = self.config.get_all().get("realtime", {})
                    if isinstance(cfg_section, dict):
                        realtime_cfg = cfg_section
                except Exception:
                    realtime_cfg = {}
                turn_detection_mode = str(
                    realtime_cfg.get("qwen_audio_turn_detection", "")
                ).strip().lower()
                if turn_detection_mode == "smart_turn":
                    turn_detection: dict[str, Any] | None = {"type": "smart_turn"}
                else:
                    try:
                        silence_ms = int(realtime_cfg.get("qwen_audio_silence_duration_ms", 2000))
                    except (TypeError, ValueError):
                        silence_ms = 2000
                    silence_ms = max(200, min(6000, silence_ms))
                    turn_detection = {
                        "type": "server_vad",
                        "threshold": 0.3,
                        "silence_duration_ms": silence_ms,
                    }
                session_config: dict[str, Any] = {
                    "modalities": ["text", "audio"],
                    "voice": resolved_voice,
                    "input_audio_format": "pcm",
                    "output_audio_format": "pcm",
                    "instructions": self._build_qwen_audio_instructions(),
                    "tools": tools,
                    "turn_detection": turn_detection,
                    # Keep at the API default (20): larger history increases
                    # token usage and per-turn inference latency.
                    "max_history_turns": 20,
                }
                await dash_ws.send(json.dumps({
                    "type": "session.update",
                    "session": session_config,
                }))

                # Wait for the server's session.created/session.updated handshake.
                # Read events in a loop so a server-side `error` event (e.g. invalid
                # voice/param, wrong workspace URL, model not enabled for the
                # workspace) surfaces its real message instead of being swallowed,
                # and a silent server produces an explicit timeout message instead
                # of a bare empty TimeoutError.
                session_id = ""
                handshake_deadline = time.monotonic() + 15
                while not session_id:
                    remaining = handshake_deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError(
                            "已连接 DashScope，但 15 秒内未收到 session.created 确认；"
                            "请检查业务空间 Realtime URL 是否属于已开通 "
                            f"{settings['model']} 的空间，以及 API Key 是否匹配该空间。"
                        )
                    try:
                        raw = await asyncio.wait_for(dash_ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            "已连接 DashScope，但等待 session.created 超时；"
                            "请检查业务空间 Realtime URL 与 API Key 是否正确。"
                        ) from None
                    try:
                        event = json.loads(raw) if isinstance(raw, str) else {}
                    except Exception:
                        continue
                    event_type = str(event.get("type", "")).strip()
                    logger.info("qwen_audio_handshake event_type=%s", event_type or "<unknown>")
                    if event_type == "error":
                        error_data = event.get("error")
                        if isinstance(error_data, dict):
                            detail = str(error_data.get("message", "")).strip() or str(error_data)
                        else:
                            detail = str(error_data or event).strip()
                        raise RuntimeError(f"DashScope 服务端拒绝会话: {detail}")
                    if event_type in {"session.created", "session.updated"}:
                        session_id = str((event.get("session") or {}).get("id", "") or "ok")

                await self._send_event(
                    websocket,
                    "session_open",
                    provider="DashScope",
                    model=settings["model"],
                    voice=resolved_voice,
                    session_id=recorder.session_id if recorder is not None else session_id,
                )

                interruption = InterruptionDecisionCoordinator()
                send_task = asyncio.create_task(
                    self._client_to_qwen_audio_loop(
                        websocket, dash_ws, memory_session, tool_session, recorder, interruption
                    )
                )
                receive_task = asyncio.create_task(
                    self._qwen_audio_to_client_loop(
                        websocket, dash_ws, memory_session, resolved_voice,
                        tool_session, recorder, interruption,
                    )
                )
                done, pending = await asyncio.wait(
                    {send_task, receive_task},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except WebSocketDisconnect:
            return
        except Exception as e:
            detail = str(e).strip() or repr(e)
            logger.exception("Qwen-Audio realtime session failed: [%s] %s", type(e).__name__, detail)
            await self._send_event(
                websocket, "error",
                message=f"Qwen-Audio 实时会话启动失败: [{type(e).__name__}] {detail}",
            )
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            # 与 Google/DashScope/OpenAI 保持一致：会话结束时取消尚在途的工具任务，
            # 否则断连后这些任务会继续在后台跑。
            await tool_session.drain(cancel=True)
            if recorder is not None:
                await recorder.finish()
