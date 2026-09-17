"""Vercel AI Gateway realtime voice provider mixin.

The Gateway transports the normalized AI SDK realtime protocol (an
OpenAI-Realtime-derived wire format) over WebSocket:

* URL: ``{gateway-origin}/v4/ai/realtime-model?ai-model-id={creator/model-name}``
  (model ids ride the query, not headers, because the browser WebSocket
  cannot set headers).
* Auth: the short-lived ``vcst_`` client secret is carried through the
  ``Sec-WebSocket-Protocol`` header as the ``ai-gateway-auth.<token>``
  subprotocol, alongside the ``ai-gateway-realtime.v1`` marker subprotocol
  the Gateway echoes on its 101 response.
* Events: normalized client events (``session-update``, ``input-audio-append``,
  ``conversation-item-create``, ``response-create``, ``response-cancel``)
  and normalized server events (``session-created``, ``speech-started``,
  ``input-transcription-completed``, ``audio-delta``,
  ``audio-transcript-delta``, ``response-done``, ``error``).

This module is the only place that knows the Gateway wire format; the
interruption / memory / recorder plumbing is shared with every other
provider via ``RealtimeVoiceService``.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import httpx
import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .realtime_constants import (
    DEFAULT_GOOGLE_REALTIME_VOICE,
    DEFAULT_VERCEL_REALTIME_MODEL,
    DEFAULT_VERCEL_REALTIME_VOICE,
    GOOGLE_REALTIME_VOICES,
    VERCEL_GATEWAY_BASE_URL,
    VERCEL_REALTIME_VOICES,
    _is_google_thinking_realtime_model,
    _is_vercel_realtime_model,
)
from .interruption_classifier import InterruptionClassifier, InterruptionDecisionCoordinator, InterruptionIntent
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .voice_agent_tools import VoiceAgentToolService, VoiceAgentToolSession
from .realtime_tool_protocol import (
    RealtimeToolCall,
    tool_call_to_request,
    tool_error_payload,
    tool_result_payload,
    vercel_tool_declarations,
)

logger = logging.getLogger(__name__)

GATEWAY_REALTIME_SUBPROTOCOL = "ai-gateway-realtime.v1"
GATEWAY_AUTH_SUBPROTOCOL_PREFIX = "ai-gateway-auth."

# Shared per-session state for the two duplex loops. The client→gateway and
# gateway→client loops run as separate asyncio tasks, so any cross-loop flag
# (e.g. "a response is currently active") must live in this mutable dict,
# not in a task-local variable.

def _new_vercel_session_state() -> dict[str, Any]:
    return {"response_active": False}

# Vercel-only audio parameters. Other providers keep their own formats; this
# resampling exists solely because the Gateway enforces input rate >= 24000
# while the app's shared capture pipeline emits 16 kHz PCM16.
VERCEL_INPUT_SAMPLE_RATE = 24000
VERCEL_OUTPUT_SAMPLE_RATE = 24000
CLIENT_CAPTURE_SAMPLE_RATE = 16000
# Gateway hard limit is 256 KB per message; stay well under it after the
# 16k->24k upsample (+50%) and base64 (+33%) growth.
VERCEL_MAX_AUDIO_BYTES = 128 * 1024


def _resample_pcm16_linear(data: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Upsample little-endian PCM16 speech via linear interpolation.

    Scoped to the Vercel provider on purpose: every other provider consumes
    the client's 16 kHz stream as-is.
    """
    if src_rate == dst_rate or len(data) < 4:
        return data
    import struct

    samples = struct.unpack(f"<{len(data) // 2}h", data[: (len(data) // 2) * 2])
    if not samples:
        return b""
    src_len = len(samples)
    dst_len = round(src_len * dst_rate / src_rate)
    out = []
    step = src_len / dst_len
    for i in range(dst_len):
        pos = i * step
        idx = int(pos)
        frac = pos - idx
        a = samples[idx]
        b = samples[min(idx + 1, src_len - 1)]
        out.append(int(round(a + (b - a) * frac)))
    return struct.pack(f"<{len(out)}h", *out)



def _normalize_vercel_voice(model: str | None, voice: str | None) -> str:
    """Select a valid voice persona for Vercel AI Gateway realtime models.

    Google Gemini models (google/gemini-3.8-live*) require Google's prebuilt
    voices (defaulting to Puck). OpenAI models require OpenAI voices (defaulting
    to alloy). Cross-family selections are automatically normalized to avoid
    upstream rejection.
    """
    m = str(model or "").strip().lower()
    v = str(voice or "").strip()
    is_google = m.startswith("google/") or "gemini" in m
    if is_google:
        if v in GOOGLE_REALTIME_VOICES:
            return v
        return DEFAULT_GOOGLE_REALTIME_VOICE
    if v in VERCEL_REALTIME_VOICES:
        return v
    return DEFAULT_VERCEL_REALTIME_VOICE


class VercelRealtimeMixin:
    """Vercel AI Gateway realtime provider methods for RealtimeVoiceService."""

    def _resolve_vercel_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("Vercel", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_VERCEL_REALTIME_MODEL
        api_key = provider_settings["api_key"].strip()
        if not api_key:
            raise RuntimeError("Vercel AI Gateway API Key 未配置，无法启动实时语音会话。")
        base_url = provider_settings["base_url"].strip().rstrip("/") or VERCEL_GATEWAY_BASE_URL
        return {
            "api_key": api_key,
            "model": resolved_model,
            "base_url": base_url,
        }

    async def _mint_vercel_client_secret(
        self, settings: dict[str, str], expires_after_seconds: int = 300
    ) -> str:
        """Exchange the long-lived Gateway credential for a short-lived ``vcst_`` secret.

        Mirrors ``gateway.experimental_realtime.getToken()``: POST to the
        gateway origin's ``/v1/realtime/client-secrets`` with the Gateway
        credential in the Authorization header. The mint route is resolved
        against the *origin* (not the ``/v4/ai``-style baseURL path).
        The gateway caps ``expiresIn`` at 300 seconds.
        """
        from urllib.parse import urlsplit

        parts = urlsplit(settings["base_url"])
        mint_url = f"{parts.scheme}://{parts.netloc}/v1/realtime/client-secrets"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                mint_url,
                headers={
                    "Authorization": f"Bearer {settings['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings["model"],
                    "expiresIn": expires_after_seconds,
                },
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Vercel AI Gateway client-secret 铸造失败 (HTTP {resp.status_code}): {resp.text[:300]}"
                )
            data = resp.json()
        token = str(data.get("token", "")).strip()
        if not token:
            raise RuntimeError("Vercel AI Gateway 返回的 client secret 为空。")
        return token

    def _vercel_ws_url(self, settings: dict[str, str]) -> str:
        """Build the Gateway realtime WebSocket URL.

        Mirrors the SDK's ``toGatewayRealtimeUrl``: the WS URL is
        ``<baseURL>/realtime-model`` where baseURL includes the ``/v4/ai``
        prefix (e.g. ``wss://ai-gateway.vercel.sh/v4/ai/realtime-model``).
        Our settings store the bare origin or /v1, so the ``/v4/ai`` prefix is
        re-applied here unless the caller already supplied a custom path.
        """
        base = settings["base_url"].replace("https://", "wss://").replace("http://", "ws://")
        from urllib.parse import quote, urlsplit

        parts = urlsplit(base)
        path = parts.path.rstrip("/")
        if not path or path == "/v1":
            path = "/v4/ai"
        return f"{parts.scheme}://{parts.netloc}{path}/realtime-model?ai-model-id={quote(settings['model'], safe='')}"

    def _vercel_ws_protocols(self, client_secret: str) -> list[str]:
        return [GATEWAY_REALTIME_SUBPROTOCOL, f"{GATEWAY_AUTH_SUBPROTOCOL_PREFIX}{client_secret}"]

    async def _client_to_vercel_loop(
        self,
        websocket: WebSocket,
        vercel_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
        state: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> None:
        interruption = interruption or InterruptionDecisionCoordinator()
        state = state if state is not None else _new_vercel_session_state()
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
                if command_type == "speech_activity_started":
                    # Automatic server VAD owns turn taking for realtime models on Vercel Gateway.
                    # Local RMS energy hints must not duck/buffer output.
                    continue
                if command_type in {"text_input", "media_input"}:
                    content = str(payload.get("text", "")).strip()
                    if content:
                        if recorder is not None:
                            await recorder.note_user_transcript(content)
                        if memory_session is not None:
                            memory_session.note_user_transcript(content)
                        await vercel_ws.send(json.dumps({
                            "type": "conversation-item-create",
                            "item": {"type": "text-message", "role": "user", "text": content},
                        }))
                        if not state["response_active"]:
                            await vercel_ws.send(json.dumps({"type": "response-create"}))
                            state["response_active"] = True
                    continue
                result = await self._handle_common_client_command(
                    command_type, payload,
                    websocket=websocket, memory_session=memory_session,
                    tool_session=tool_session, recorder=recorder,
                    interruption=interruption, provider="Vercel",
                )
                if result == "stop":
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                # The shared capture pipeline sends 16 kHz PCM16, but the
                # Gateway enforces input rate >= 24000. Upsample 16k -> 24k
                # (simple linear interpolation is fine for speech).
                resampled = _resample_pcm16_linear(
                    audio_bytes, CLIENT_CAPTURE_SAMPLE_RATE, VERCEL_INPUT_SAMPLE_RATE
                )
                if len(resampled) % 2:
                    resampled = resampled[:-1]  # keep PCM16 sample alignment
                # The Gateway rejects messages over 256 KB; split oversized
                # chunks so one big frame can't kill the session.
                for off in range(0, len(resampled), VERCEL_MAX_AUDIO_BYTES):
                    await vercel_ws.send(json.dumps({
                        "type": "input-audio-append",
                        "audio": base64.b64encode(resampled[off:off + VERCEL_MAX_AUDIO_BYTES]).decode("ascii"),
                    }))

    async def _vercel_to_client_loop(
        self,
        websocket: WebSocket,
        vercel_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
        state: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> None:
        send_tool_event = self._tool_event_sender(websocket, recorder)
        state = state if state is not None else _new_vercel_session_state()

        resolved_model = model or getattr(self, "_current_vercel_model", "")
        gated_tool_turn_id = ""
        pending_prefill_context = ""
        interruption = interruption or InterruptionDecisionCoordinator()
        suppressed_response_ids: set[str] = set()
        # Id of the in-flight assistant audio message item. Truncation must
        # target an assistant 'audio' content item, never the user's
        # 'input_audio' item (the Gateway rejects that). Truncation only fires
        # while this id is set, so we reset it when each response finishes.
        assistant_audio_item_id = ""
        # NOTE: the response-active flag lives in the shared `state` dict
        # (set by stream_vercel_session), because the client loop reads it too.

        # Tracking for native server-vad interruption repair
        vercel_provider_interrupted_early = False
        consume_next_vercel_terminal = False

        async def dispatch_tool_call(
            call_id: str,
            tool_name: str,
            raw_arguments: Any,
        ) -> None:
            nonlocal gated_tool_turn_id
            call_id = str(call_id or "").strip()
            tool_name = str(tool_name or "").strip()
            if not call_id:
                logger.warning("[VERCEL-TOOL] Missing call ID for tool '%s'", tool_name)
                return
            if tool_session.has_seen_provider_call(call_id) or call_id in getattr(tool_session, "_native_tasks", {}):
                return

            logger.info(
                "[VERCEL-TOOL] Dispatched tool call '%s' (call_id=%s) args=%s",
                tool_name,
                call_id,
                raw_arguments if isinstance(raw_arguments, dict) else str(raw_arguments)[:200],
            )

            conversation_turn_id = recorder.current_turn_id if recorder is not None else ""
            tool_turn_id = tool_session.reserve_tool_call_id()

            try:
                native_call = RealtimeToolCall(
                    provider="Vercel",
                    provider_call_id=call_id,
                    tool_name=tool_name,
                    arguments=raw_arguments,
                )
                request = tool_call_to_request(native_call)
            except Exception as exc:
                logger.warning("Failed to parse Vercel tool call %s (%s): %s", tool_name, call_id, exc)
                tool_session.mark_provider_call_seen(call_id)
                await self._send_vercel_tool_response(
                    vercel_ws,
                    provider_call_id=call_id,
                    tool_name=tool_name or "unknown_tool",
                    response_payload=tool_error_payload(str(exc)),
                    conversation_turn_id=conversation_turn_id,
                    tool_call_id=tool_turn_id,
                    recorder=recorder,
                )
                return

            gated_tool_turn_id = tool_turn_id
            await self._send_response_gated(
                websocket,
                provider="Vercel",
                tool_name=tool_name,
                query=request.query,
                turn_id=tool_turn_id,
                recorder=recorder,
            )

            async def on_vercel_native_result(
                result: dict[str, Any],
                *,
                call_id: str = call_id,
                name: str = tool_name,
                canonical_turn_id: str = conversation_turn_id,
                local_tool_call_id: str = tool_turn_id,
            ) -> None:
                nonlocal gated_tool_turn_id
                gated_tool_turn_id = ""
                await self._send_vercel_tool_response(
                    vercel_ws,
                    provider_call_id=call_id,
                    tool_name=name,
                    response_payload=tool_result_payload(result),
                    result=result,
                    conversation_turn_id=canonical_turn_id,
                    tool_call_id=local_tool_call_id,
                    recorder=recorder,
                )
                state["response_active"] = True

            async def on_vercel_native_error(
                message: str,
                *,
                call_id: str = call_id,
                name: str = tool_name,
                canonical_turn_id: str = conversation_turn_id,
                local_tool_call_id: str = tool_turn_id,
            ) -> None:
                nonlocal gated_tool_turn_id
                gated_tool_turn_id = ""
                await self._send_vercel_tool_response(
                    vercel_ws,
                    provider_call_id=call_id,
                    tool_name=name,
                    response_payload=tool_error_payload(message),
                    conversation_turn_id=canonical_turn_id,
                    tool_call_id=local_tool_call_id,
                    recorder=recorder,
                )
                state["response_active"] = True

            await tool_session.handle_request(
                request,
                send_event=send_tool_event,
                on_result=on_vercel_native_result,
                on_error=on_vercel_native_error,
                provider_call_id=call_id,
                conversation_turn_id=conversation_turn_id,
                tool_call_id=tool_turn_id,
            )

        async for raw_message in vercel_ws:
            try:
                event = json.loads(raw_message) if isinstance(raw_message, str) else json.loads(str(raw_message))
            except Exception:
                continue

            event_type = str(event.get("type", "")).strip()

            if event_type == "session-created":
                await self._send_event(
                    websocket,
                    "session_open",
                    provider="Vercel",
                    model=resolved_model,
                    voice=getattr(self, "_current_vercel_voice", "") or DEFAULT_VERCEL_REALTIME_VOICE,
                    session_id=recorder.session_id if recorder is not None else str(event.get("sessionId", "")),
                )
                continue

            if event_type == "session-updated":
                continue

            if event_type == "response-created":
                interruption.active_response_id = str(event.get("responseId", ""))
                state["response_active"] = True
                continue

            # Native tool call events (AI SDK normalized or OpenAI Realtime)
            if event_type in {
                "tool-call",
                "tool_call",
                "response.function_call_arguments.done",
                "function_call_arguments_done",
            }:
                call_id = str(
                    event.get("toolCallId")
                    or event.get("callId")
                    or event.get("call_id")
                    or event.get("id")
                    or ""
                ).strip()
                tool_name = str(event.get("toolName") or event.get("name") or "").strip()
                raw_args = event.get("args") if "args" in event else event.get("arguments", {})
                await dispatch_tool_call(call_id, tool_name, raw_args)
                continue

            # Output item events (OpenAI Realtime function_call items)
            if event_type in {
                "response.output_item.done",
                "response.output_item.added",
                "response-output-item-done",
                "response-output-item-added",
            }:
                item = event.get("item") or {}
                if isinstance(item, dict) and str(item.get("type", "")).lower() in {
                    "function_call",
                    "tool_call",
                    "custom_tool_call",
                }:
                    call_id = str(
                        item.get("call_id")
                        or item.get("id")
                        or item.get("callId")
                        or ""
                    ).strip()
                    tool_name = str(item.get("name") or item.get("toolName") or "").strip()
                    raw_args = item.get("arguments") if "arguments" in item else item.get("args", {})
                    await dispatch_tool_call(call_id, tool_name, raw_args)
                    continue

            # Direct Google / provider tool_call event with function_calls list
            if event_type in {"tool_call", "function_calls"}:
                f_calls = event.get("function_calls") or []
                if isinstance(f_calls, list):
                    for fc in f_calls:
                        if isinstance(fc, dict):
                            call_id = str(fc.get("id") or fc.get("call_id") or "").strip()
                            tool_name = str(fc.get("name") or "").strip()
                            raw_args = fc.get("args") if "args" in fc else fc.get("arguments", {})
                            await dispatch_tool_call(call_id, tool_name, raw_args)
                    continue

            # Native interruption / server VAD speech onset detected
            if event_type in {"speech-started", "interrupted", "input_audio_buffer.speech_started"}:
                assistant_active = bool(
                    state.get("response_active")
                    or interruption.active_response_id
                    or tool_session.has_active_task
                    or (recorder is not None and bool(recorder.current_assistant_text))
                    or (recorder is not None and getattr(recorder, "has_assistant_output", False))
                )
                if assistant_active:
                    interrupted_response_id = interruption.active_response_id

                    async def cancel_vercel_response() -> None:
                        payload: dict[str, Any] = {"type": "response-cancel"}
                        if interrupted_response_id:
                            payload["responseId"] = interrupted_response_id
                        try:
                            await vercel_ws.send(json.dumps(payload))
                        except Exception:
                            logger.warning("Failed to send response-cancel to Vercel Gateway", exc_info=True)
                        if assistant_audio_item_id:
                            try:
                                await vercel_ws.send(
                                    json.dumps({
                                        "type": "conversation-item-truncate",
                                        "itemId": assistant_audio_item_id,
                                        "contentIndex": 0,
                                        "audioEndMs": 0,
                                    })
                                )
                            except Exception:
                                logger.warning("Failed to send conversation-item-truncate to Vercel Gateway", exc_info=True)

                    if not (vercel_provider_interrupted_early and consume_next_vercel_terminal):
                        await self._begin_interruption(
                            websocket,
                            interruption,
                            provider="Vercel",
                            provider_event_type=event_type,
                            recorder=recorder,
                            tool_session=tool_session,
                            supersede_timed_out=True,
                        )
                        await self._decide_interruption(
                            websocket,
                            interruption,
                            "",
                            memory_session=memory_session,
                            tool_session=tool_session,
                            recorder=recorder,
                            cancel_provider=cancel_vercel_response,
                            provider_interrupted=True,
                        )
                    else:
                        await cancel_vercel_response()

                    vercel_provider_interrupted_early = True
                    consume_next_vercel_terminal = True
                    if interrupted_response_id:
                        suppressed_response_ids.add(interrupted_response_id)
                    gated_tool_turn_id = ""
                    pending_prefill_context = ""
                    state["response_active"] = False
                continue

            if event_type == "audio-delta":
                audio_b64 = event.get("delta", "")
                response_id = str(event.get("responseId", ""))
                if event.get("itemId"):
                    assistant_audio_item_id = str(event.get("itemId"))
                if (
                    response_id in suppressed_response_ids
                    or consume_next_vercel_terminal
                    or vercel_provider_interrupted_early
                ):
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

            if event_type == "audio-transcript-delta":
                text_delta = event.get("delta", "")
                response_id = str(event.get("responseId", ""))
                if (
                    response_id in suppressed_response_ids
                    or consume_next_vercel_terminal
                    or vercel_provider_interrupted_early
                ):
                    continue
                if text_delta and not gated_tool_turn_id:
                    await self._emit_assistant_output(
                        websocket,
                        interruption,
                        {"type": "assistant_text", "text": str(text_delta)},
                        memory_session=memory_session,
                        recorder=recorder,
                    )
                continue

            if event_type in {"response-done", "response.done"}:
                resp_data = event.get("response") or {}
                if isinstance(resp_data, dict):
                    output_items = resp_data.get("output") or []
                    if isinstance(output_items, list):
                        for out_item in output_items:
                            if isinstance(out_item, dict) and str(out_item.get("type", "")).lower() in {"function_call", "tool_call"}:
                                c_id = str(out_item.get("call_id") or out_item.get("id") or out_item.get("callId") or "").strip()
                                t_name = str(out_item.get("name") or out_item.get("toolName") or "").strip()
                                t_args = out_item.get("arguments") if "arguments" in out_item else out_item.get("args", {})
                                if c_id and not tool_session.has_seen_provider_call(c_id):
                                    await dispatch_tool_call(c_id, t_name, t_args)

                response_id = str(event.get("responseId", "") or resp_data.get("id", ""))
                response_status = str(event.get("status", "") or resp_data.get("status", "completed")).lower()
                is_cancelled = (
                    response_status in {"cancelled", "canceled"}
                    or response_id in suppressed_response_ids
                    or consume_next_vercel_terminal
                )

                if is_cancelled:
                    consume_next_vercel_terminal = False
                    suppressed_response_ids.discard(response_id)
                    if response_id and response_id == interruption.active_response_id:
                        interruption.active_response_id = ""
                    assistant_audio_item_id = ""
                    state["response_active"] = False
                    interruption.discard_deferred_terminal()
                    continue

                if interruption.defer_terminal(dict(event)):
                    continue
                if response_id and response_id == interruption.active_response_id:
                    interruption.active_response_id = ""
                # The response's audio item is complete; never truncate a
                # stale item from a finished turn.
                assistant_audio_item_id = ""
                state["response_active"] = False
                if response_status in {"failed"}:
                    continue
                if pending_prefill_context:
                    await vercel_ws.send(json.dumps({
                        "type": "conversation-item-create",
                        "item": {
                            "type": "text-message",
                            "role": "user",
                            "text": (
                                "Context note for personalization only. These long-term memories may help with "
                                "the user's next turn. Use them only when relevant, and do not mention this note.\n"
                                f"{pending_prefill_context}"
                            ),
                        },
                    }))
                    pending_prefill_context = ""
                memory_result = await memory_session.flush_turn()
                completed_turn_id = ""
                if recorder is not None and not gated_tool_turn_id and not tool_session.has_active_task:
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
                if not gated_tool_turn_id and not tool_session.has_active_task:
                    await self._send_event(
                        websocket,
                        "turn_complete",
                        turn_id=completed_turn_id,
                        interrupted=False,
                    )
                continue

            # User speech transcription completed
            if event_type in {"input-transcription-completed", "conversation.item.input_audio_transcription.completed"}:
                user_text = str(event.get("transcript", "") or event.get("text", "")).strip()
                item_id = str(event.get("itemId", ""))
                was_interrupted_early = vercel_provider_interrupted_early
                vercel_provider_interrupted_early = False

                if was_interrupted_early:
                    # Provider already interrupted and stopped previous assistant generation.
                    # This transcript is the user's new utterance following the interruption.
                    if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
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
                                "voice_memory_inject provider=Vercel scope=%s count=%s local_pending=%s cloud=%s",
                                memory_session._config.memory_scope,
                                memory_count,
                                local_pending_count,
                                cloud_count,
                            )
                            pending_prefill_context = memory_context
                        await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)

                        async def on_vercel_tool_result(result: dict[str, Any]) -> None:
                            nonlocal gated_tool_turn_id
                            gated_tool_turn_id = ""
                            await self._apply_vercel_tool_result(vercel_ws, result, recorder)
                            state["response_active"] = True

                        tool_request = VoiceAgentToolService.extract_tool_request(user_text)
                        tool_turn_id = await tool_session.handle_user_transcript(
                            user_text,
                            send_event=send_tool_event,
                            on_result=on_vercel_tool_result,
                        )
                        if tool_turn_id:
                            gated_tool_turn_id = tool_turn_id
                            await self._send_response_gated(
                                websocket,
                                provider="Vercel",
                                tool_name=tool_request.tool_name if tool_request else "voice_tool",
                                query=tool_request.query if tool_request else "",
                                turn_id=tool_turn_id,
                                recorder=recorder,
                            )
                        else:
                            await vercel_ws.send(json.dumps({"type": "response-create"}))
                            state["response_active"] = True
                    continue

                if interruption.pending is None and (
                    state.get("response_active")
                    or interruption.active_response_id
                    or tool_session.has_active_task
                    or (recorder is not None and bool(recorder.current_assistant_text))
                ):
                    await self._begin_interruption(
                        websocket,
                        interruption,
                        provider="Vercel",
                        provider_event_type="input-transcription-completed_without_vad",
                        recorder=recorder,
                        tool_session=tool_session,
                        supersede_timed_out=True,
                    )
                interrupted_response_id = interruption.active_response_id
                had_deferred_terminal = interruption.has_deferred_terminal()

                async def cancel_vercel_response() -> None:
                    payload: dict[str, Any] = {"type": "response-cancel"}
                    if interrupted_response_id:
                        payload["responseId"] = interrupted_response_id
                    await vercel_ws.send(json.dumps(payload))

                async def discard_vercel_candidate() -> None:
                    # Truncate the assistant audio item, not the user input
                    # item (itemId here is the user transcription's item).
                    if assistant_audio_item_id:
                        await vercel_ws.send(
                            json.dumps({"type": "conversation-item-truncate", "itemId": assistant_audio_item_id, "contentIndex": 0, "audioEndMs": 0})
                        )

                should_process_user, interruption_decision = await self._decide_interruption(
                    websocket,
                    interruption,
                    user_text,
                    memory_session=memory_session,
                    tool_session=tool_session,
                    recorder=recorder,
                    cancel_provider=(cancel_vercel_response if not had_deferred_terminal else None),
                    resume_provider=discard_vercel_candidate,
                )
                if interruption_decision is not None and (
                    interruption_decision.get("classification") == InterruptionIntent.TRUE_BARGE_IN.value
                ) and interrupted_response_id and not had_deferred_terminal:
                    suppressed_response_ids.add(interrupted_response_id)
                    consume_next_vercel_terminal = True
                    state["response_active"] = False
                if not should_process_user:
                    if interruption_decision is None:
                        await discard_vercel_candidate()
                    if had_deferred_terminal and interruption.take_deferred_terminal() is not None:
                        await self._finalize_realtime_turn(
                            websocket,
                            memory_session,
                            recorder,
                            gated=bool(gated_tool_turn_id),
                        )
                    continue
                if InterruptionClassifier.classify_interruption(user_text) == InterruptionIntent.NOISE_OR_SILENCE:
                    await discard_vercel_candidate()
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
                            "voice_memory_inject provider=Vercel scope=%s count=%s local_pending=%s cloud=%s",
                            memory_session._config.memory_scope,
                            memory_count,
                            local_pending_count,
                            cloud_count,
                        )
                        pending_prefill_context = memory_context
                    await self._send_event(websocket, "user_transcript", text=user_text, turn_id=voice_turn_id)

                    async def on_vercel_tool_result(result: dict[str, Any]) -> None:
                        nonlocal gated_tool_turn_id
                        gated_tool_turn_id = ""
                        await self._apply_vercel_tool_result(vercel_ws, result, recorder)
                        state["response_active"] = True  # _apply_... ends with response-create

                    tool_request = VoiceAgentToolService.extract_tool_request(user_text)
                    tool_turn_id = await tool_session.handle_user_transcript(
                        user_text,
                        send_event=send_tool_event,
                        on_result=on_vercel_tool_result,
                    )
                    if tool_turn_id:
                        gated_tool_turn_id = tool_turn_id
                        await self._send_response_gated(
                            websocket,
                            provider="Vercel",
                            tool_name=tool_request.tool_name if tool_request else "voice_tool",
                            query=tool_request.query if tool_request else "",
                            turn_id=tool_turn_id,
                            recorder=recorder,
                        )
                    else:
                        if not state["response_active"]:
                            await vercel_ws.send(json.dumps({"type": "response-create"}))
                            state["response_active"] = True
                continue

            if event_type == "error":
                error_msg = str(event.get("message", "") or event.get("code", ""))
                await self._send_event(websocket, "error", message=f"Vercel AI Gateway: {error_msg}")
                break

        try:
            await tool_session.drain(cancel=False)
        except Exception:
            pass

    async def _apply_vercel_tool_result(
        self,
        vercel_ws: Any,
        result: dict[str, Any],
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        prompt = VoiceAgentToolService.build_model_context_prompt(result)
        if not prompt.strip():
            return
        payload = {
            "provider": "Vercel",
            "tool_name": str(result.get("tool_name", "search_web") or "search_web"),
            "query": str(result.get("query", "")),
            "turn_id": str(result.get("turn_id", "")),
            "source_count": int(result.get("source_count", 0) or 0),
            "sources": result.get("sources") or [],
            "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_context_injected", payload)
        await vercel_ws.send(json.dumps({
            "type": "conversation-item-create",
            "item": {"type": "text-message", "role": "user", "text": prompt},
        }))
        await vercel_ws.send(json.dumps({"type": "response-create"}))

    async def _send_vercel_tool_response(
        self,
        vercel_ws: Any,
        *,
        provider_call_id: str,
        tool_name: str,
        response_payload: dict[str, Any],
        result: dict[str, Any] | None = None,
        conversation_turn_id: str = "",
        tool_call_id: str = "",
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        if not provider_call_id:
            logger.warning("Vercel native tool response missing provider_call_id for %s", tool_name)
            return

        payload = {
            "provider": "Vercel",
            "tool_name": tool_name,
            "provider_call_id": provider_call_id,
            "turn_id": tool_call_id or conversation_turn_id,
            "response_payload": response_payload,
        }
        if recorder is not None:
            await recorder.record_tool_event("tool_response_sent", payload)

        output_str = (
            json.dumps(response_payload, ensure_ascii=False)
            if isinstance(response_payload, (dict, list))
            else str(response_payload)
        )

        item = {
            "type": "function_call_output",
            "call_id": provider_call_id,
            "callId": provider_call_id,
            "output": output_str,
        }

        try:
            await vercel_ws.send(json.dumps({
                "type": "conversation-item-create",
                "item": item,
            }))
            await vercel_ws.send(json.dumps({"type": "response-create"}))
        except Exception:
            logger.exception("Failed to send native tool response to Vercel Gateway for %s", tool_name)

    async def stream_vercel_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_VERCEL_REALTIME_VOICE,
    ) -> None:
        settings = self._resolve_vercel_settings(model)
        resolved_voice = _normalize_vercel_voice(settings["model"], voice)
        memory_session = RealtimeMemorySession()
        tool_session = VoiceAgentToolSession(default_provider="Vercel")
        recorder = await self._create_voice_session_recorder(
            provider="Vercel",
            model=settings["model"],
            voice=resolved_voice,
        )

        self._current_vercel_model = settings["model"]
        self._current_vercel_voice = resolved_voice

        try:
            client_secret = await self._mint_vercel_client_secret(settings)
        except Exception as e:
            logger.exception("Vercel realtime client-secret mint failed: %s", e)
            await self._send_event(websocket, "error", message=f"Vercel AI Gateway 鉴权失败: {str(e)}")
            return

        ws_url = self._vercel_ws_url(settings)
        protocols = self._vercel_ws_protocols(client_secret)

        try:
            async with websockets.connect(
                ws_url,
                subprotocols=protocols,
                max_size=2**24,
                ping_interval=30,
                ping_timeout=30,
            ) as vercel_ws:
                # Normalized session config; the Gateway maps it to the
                # upstream provider server-side.
                session_config: dict[str, Any] = {
                    "instructions": self._build_realtime_instructions(),
                    "voice": resolved_voice,
                    "tools": vercel_tool_declarations(),
                    # The Gateway only accepts ['text'] or ['audio'] —
                    # not the mixed ['text', 'audio'] the SDK type allows.
                    # Voice call => audio output; outputAudioTranscription
                    # makes the text side explicit (emits
                    # audio-transcript-delta events).
                    "outputModalities": ["audio"],
                    "inputAudioFormat": {"type": "audio/pcm", "rate": VERCEL_INPUT_SAMPLE_RATE},
                    "outputAudioFormat": {"type": "audio/pcm", "rate": VERCEL_OUTPUT_SAMPLE_RATE},
                    "inputAudioTranscription": {},
                    "outputAudioTranscription": {},
                    "turnDetection": {"type": "server-vad"},
                }

                # Google Gemini 3.8 Live Extended Thinking on Vercel AI Gateway
                # requires providerOptions.google.thinkingConfig.
                m_lower = settings["model"].lower()
                if "extended-thinking" in m_lower or (
                    m_lower.startswith("google/") and "thinking" in m_lower
                ):
                    session_config["providerOptions"] = {
                        "google": {
                            "thinkingConfig": {
                                "thinkingLevel": "LOW",
                            }
                        }
                    }

                await vercel_ws.send(json.dumps({
                    "type": "session-update",
                    "config": session_config,
                }))

                interruption = InterruptionDecisionCoordinator()
                state = _new_vercel_session_state()
                send_task = asyncio.create_task(
                    self._client_to_vercel_loop(
                        websocket, vercel_ws, memory_session, tool_session, recorder, interruption, state,
                        model=settings["model"],
                    )
                )
                receive_task = asyncio.create_task(
                    self._vercel_to_client_loop(
                        websocket, vercel_ws, memory_session, tool_session, recorder, interruption, state,
                        model=settings["model"],
                    )
                )
                await self._run_duplex_tasks(send_task, receive_task)
        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.exception("Vercel realtime session failed: %s", e)
            await self._send_event(websocket, "error", message=f"Vercel 实时会话启动失败: {str(e)}")
            return
        finally:
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            await tool_session.drain(cancel=True)
            if recorder is not None:
                await recorder.finish()
