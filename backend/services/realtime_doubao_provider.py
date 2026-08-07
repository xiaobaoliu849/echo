"""Doubao / Volcengine Realtime voice provider mixin.

Primary path: Volcengine OpenSpeech end-to-end realtime dialogue API
(wss://openspeech.bytedance.com/api/v3/realtime/dialogue, resource
``volc.speech.dialog``) using the 4-byte-header binary framing protocol.
A legacy OpenAI-Realtime-compatible gateway path is kept for custom
``realtime_base_url`` overrides.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .realtime_constants import (
    BASE_REALTIME_INSTRUCTIONS,
    DEFAULT_DOUBAO_DIALOG_MODEL,
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


from .openspeech_dialogue_protocol import (
    EVENT_ASR_ENDED,
    EVENT_ASR_INFO,
    EVENT_ASR_RESPONSE,
    EVENT_CHAT_ENDED,
    EVENT_CHAT_RESPONSE,
    EVENT_CHAT_TEXT_QUERY,
    EVENT_CONNECTION_FAILED,
    EVENT_CONNECTION_FINISHED,
    EVENT_CONNECTION_STARTED,
    EVENT_DIALOG_COMMON_ERROR,
    EVENT_FINISH_CONNECTION,
    EVENT_FINISH_SESSION,
    EVENT_SESSION_FAILED,
    EVENT_SESSION_FINISHED,
    EVENT_SESSION_STARTED,
    EVENT_START_CONNECTION,
    EVENT_START_SESSION,
    EVENT_TASK_REQUEST,
    EVENT_TTS_ENDED,
    EVENT_TTS_RESPONSE,
    EVENT_TTS_SENTENCE_START,
    MSG_TYPE_AUDIO_CLIENT_REQ,
    MSG_TYPE_ERROR_INFO,
    MSG_TYPE_FULL_CLIENT_REQ,
    OpenSpeechFrame,
    decode_openspeech_frame,
    encode_openspeech_frame,
)

_DOUBAO_DIALOG_MODEL_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")

# websockets >= 14 renamed InvalidStatusCode → InvalidStatus.
_INVALID_STATUS_CLS = getattr(websockets.exceptions, "InvalidStatus", None)
if _INVALID_STATUS_CLS is None:  # pragma: no cover - legacy websockets
    _INVALID_STATUS_CLS = getattr(websockets.exceptions, "InvalidStatusCode", None)
_WS_INVALID_STATUS = (_INVALID_STATUS_CLS,) if isinstance(_INVALID_STATUS_CLS, type) else ()


def _frame_error_text(frame: OpenSpeechFrame) -> str:
    """Extract a human-readable error message from a failed/error frame."""
    try:
        data = json.loads(frame.payload.decode("utf-8"))
        if isinstance(data, dict):
            msg = data.get("error") or data.get("message") or ""
            code = data.get("status_code") or frame.code or ""
            return f"{msg} (code={code})" if code else str(msg or data)
    except Exception:
        pass
    return f"code={frame.code} event={frame.event}"


class DoubaoRealtimeMixin:
    """Doubao Realtime provider methods for RealtimeVoiceService."""

    def _resolve_doubao_settings(
        self, model: str | None, voice: str | None = None
    ) -> dict[str, str]:
        passed_model = model.strip() if (model and model.strip()) else ""
        provider_settings = self.config.get_provider_settings("Doubao", model)
        resolved_model = passed_model or provider_settings["model"].strip() or DEFAULT_DOUBAO_REALTIME_MODEL
        api_key = provider_settings["api_key"].strip()
        if not api_key:
            # Fallback to Volcengine key if configured
            volc_settings = self.config.get_provider_settings("Volcengine", model)
            api_key = volc_settings["api_key"].strip()

        custom_endpoint = provider_settings.get("realtime_base_url", "").strip()
        endpoint = custom_endpoint or DEFAULT_DOUBAO_REALTIME_ENDPOINT

        # dialog.extra.model (StartSession 必传): 1.2.1.1 = O2.0, 2.2.0.0 = SC2.0.
        dialog_model = (
            resolved_model
            if _DOUBAO_DIALOG_MODEL_RE.match(resolved_model)
            else DEFAULT_DOUBAO_DIALOG_MODEL
        )

        requested_voice = voice.strip() if (voice and voice.strip()) else ""
        if requested_voice in DOUBAO_REALTIME_VOICES:
            resolved_voice = requested_voice
        else:
            resolved_voice = DEFAULT_DOUBAO_REALTIME_VOICE

        raw_app_id = ""
        websearch_key = ""
        access_token = ""
        get_setting = getattr(self.config, "get_setting", None)
        if callable(get_setting):
            candidate = get_setting("doubao_app_id", "")
            if isinstance(candidate, str):
                raw_app_id = candidate.strip()
            ws_candidate = get_setting("doubao_websearch_api_key", "")
            if isinstance(ws_candidate, str):
                websearch_key = ws_candidate.strip()
            token_candidate = get_setting("doubao_access_token", "")
            if isinstance(token_candidate, str):
                access_token = token_candidate.strip()

        # 实时语音走豆包语音 OpenSpeech,凭证是 Access Token(+ APP ID),
        # 与文字聊天的火山方舟 API Key 是两套体系;优先读独立字段,
        # 为空时回退 doubao_api_key 以兼容旧配置。
        realtime_credential = access_token or api_key
        if not realtime_credential:
            raise RuntimeError(
                "豆包实时语音的 Access Token 未配置：请在 设置 → Doubao 的"
                "「Access Token（实时语音）」栏填写豆包语音控制台"
                "「服务接口认证信息」中的 Access Token。"
            )

        return {
            "api_key": realtime_credential,
            "model": resolved_model,
            "dialog_model": dialog_model,
            "voice": resolved_voice,
            "endpoint": endpoint,
            "app_id": raw_app_id,
            "websearch_key": websearch_key,
        }

    # ------------------------------------------------------------------
    # OpenSpeech dialogue handshake
    # ------------------------------------------------------------------

    async def _recv_openspeech_frame(self, doubao_ws: Any, timeout: float = 15.0) -> OpenSpeechFrame:
        raw = await asyncio.wait_for(doubao_ws.recv(), timeout=timeout)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return decode_openspeech_frame(raw)

    async def _openspeech_handshake(
        self,
        doubao_ws: Any,
        *,
        voice: str,
        instructions: str | None,
        dialog_model: str,
        websearch_key: str = "",
    ) -> str:
        """StartConnection → ConnectionStarted → StartSession → SessionStarted.

        Returns the session id that must be attached to every subsequent
        session-class frame.
        """
        await doubao_ws.send(
            encode_openspeech_frame(
                MSG_TYPE_FULL_CLIENT_REQ, {}, event=EVENT_START_CONNECTION,
            )
        )
        frame = await self._recv_openspeech_frame(doubao_ws)
        if frame.msg_type == MSG_TYPE_ERROR_INFO or frame.event == EVENT_CONNECTION_FAILED:
            raise RuntimeError(f"豆包实时语音连接建立失败: {_frame_error_text(frame)}")
        if frame.event != EVENT_CONNECTION_STARTED:
            raise RuntimeError(f"豆包实时语音握手异常: 未收到 ConnectionStarted (event={frame.event})。")

        session_id = str(uuid.uuid4())
        dialog_extra: dict[str, Any] = {"model": dialog_model}
        if websearch_key:
            # 内置联网(融合信息搜索):没开的话模型会凭空编造天气/新闻等实时信息
            dialog_extra["enable_volc_websearch"] = True
            dialog_extra["volc_websearch_type"] = "web"
            dialog_extra["volc_websearch_api_key"] = websearch_key
        start_payload = {
            "asr": {
                "audio_info": {"format": "pcm", "sample_rate": 16000, "channel": 1},
                # asr.extra 置空会触发 42000020,传空对象占位
                "extra": {},
            },
            "tts": {
                "speaker": voice,
                "audio_config": {"channel": 1, "format": "pcm_s16le", "sample_rate": 24000},
            },
            "dialog": {
                "bot_name": "豆包",
                "system_role": instructions or BASE_REALTIME_INSTRUCTIONS,
                "speaking_style": "",
                "extra": dialog_extra,
            },
        }
        await doubao_ws.send(
            encode_openspeech_frame(
                MSG_TYPE_FULL_CLIENT_REQ,
                start_payload,
                event=EVENT_START_SESSION,
                session_id=session_id,
            )
        )
        frame = await self._recv_openspeech_frame(doubao_ws)
        if frame.msg_type == MSG_TYPE_ERROR_INFO or frame.event == EVENT_SESSION_FAILED:
            raise RuntimeError(f"豆包实时语音会话启动失败: {_frame_error_text(frame)}")
        if frame.event != EVENT_SESSION_STARTED:
            raise RuntimeError(f"豆包实时语音握手异常: 未收到 SessionStarted (event={frame.event})。")
        return session_id

    # ------------------------------------------------------------------
    # Client → Doubao
    # ------------------------------------------------------------------

    async def _client_to_doubao_loop(
        self,
        websocket: WebSocket,
        doubao_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
        is_openspeech: bool = False,
        session_id: str = "",
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
                        if is_openspeech:
                            msg_bytes = encode_openspeech_frame(
                                msg_type=MSG_TYPE_FULL_CLIENT_REQ,
                                payload={"content": content},
                                event=EVENT_CHAT_TEXT_QUERY,
                                session_id=session_id or None,
                            )
                            await doubao_ws.send(msg_bytes)
                        else:
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
                if is_openspeech:
                    msg_bytes = encode_openspeech_frame(
                        msg_type=MSG_TYPE_AUDIO_CLIENT_REQ,
                        payload=audio_bytes,
                        event=EVENT_TASK_REQUEST,
                        session_id=session_id or None,
                    )
                    await doubao_ws.send(msg_bytes)
                else:
                    await doubao_ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(audio_bytes).decode("ascii"),
                    }))

    # ------------------------------------------------------------------
    # Doubao → client
    # ------------------------------------------------------------------

    async def _doubao_openspeech_dispatch(
        self,
        websocket: WebSocket,
        frame: OpenSpeechFrame,
        state: dict[str, Any],
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        interruption: InterruptionDecisionCoordinator,
    ) -> bool:
        """Handle one decoded server frame. Returns False when the loop should end."""
        if frame.msg_type == MSG_TYPE_ERROR_INFO:
            await self._send_event(
                websocket, "error",
                message=f"豆包实时语音服务错误: {_frame_error_text(frame)}",
            )
            return True

        event = frame.event

        def _payload_json() -> dict[str, Any]:
            try:
                data = json.loads(frame.payload.decode("utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        if event == EVENT_TTS_RESPONSE and frame.payload:
            state["tts_active"] = True
            audio_b64 = base64.b64encode(frame.payload).decode("ascii")
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
            return True

        if event == EVENT_TTS_SENTENCE_START:
            data = _payload_json()
            reply_id = str(data.get("reply_id") or data.get("question_id") or "")
            if reply_id and reply_id != state.get("active_turn_id"):
                state["active_turn_id"] = reply_id
                state["ai_acc"] = ""
                state["t0"] = time.perf_counter()
                state["text_source"] = None
                state["websearch_notified"] = False
                interruption.active_response_id = reply_id
            state["tts_active"] = True
            # tts_type=network 表示本轮回答使用了内置联网搜索 —— 这是服务端
            # 给出的唯一联网信号(不返回 query/来源列表),映射为前端的进度提示。
            if (
                str(data.get("tts_type") or "") == "network"
                and not state.get("websearch_notified")
            ):
                state["websearch_notified"] = True
                await self._send_event(
                    websocket, "agent_progress",
                    stage="builtin_websearch",
                    turn_id=state.get("active_turn_id"),
                    message="豆包正在使用联网搜索结果回答…",
                )
            # 350 的 text 可能为空(实测 ChatTextQuery 触发的轮次 text=""),
            # 所以只有真的拿到文本时才认领本轮的文本来源。
            text = str(data.get("text") or "")
            if text and state.get("text_source") in (None, "sentence"):
                state["text_source"] = "sentence"
                state["ai_acc"] = (state.get("ai_acc") or "") + text
                await self._emit_assistant_output(
                    websocket,
                    interruption,
                    {"type": "assistant_text", "text": text},
                    memory_session=memory_session,
                    recorder=recorder,
                )
            return True

        if event == EVENT_CHAT_RESPONSE:
            # 550 的 content 是增量文本块;与 350 的口播文本重叠,
            # 每轮只采用先到且非空的那个来源,避免重复。
            data = _payload_json()
            reply_id = str(data.get("reply_id") or data.get("question_id") or "")
            if reply_id and reply_id != state.get("active_turn_id"):
                state["active_turn_id"] = reply_id
                state["ai_acc"] = ""
                state["t0"] = time.perf_counter()
                state["text_source"] = None
                interruption.active_response_id = reply_id
            content = str(data.get("content") or "")
            if content and state.get("text_source") in (None, "chat"):
                state["text_source"] = "chat"
                state["ai_acc"] = (state.get("ai_acc") or "") + content
                await self._emit_assistant_output(
                    websocket,
                    interruption,
                    {"type": "assistant_text", "text": content},
                    memory_session=memory_session,
                    recorder=recorder,
                )
            return True

        if event in (EVENT_TTS_ENDED, EVENT_CHAT_ENDED):
            ai_acc = state.get("ai_acc") or ""
            active_turn_id = state.get("active_turn_id")
            if ai_acc:
                await self._send_event(
                    websocket, "ai_transcript",
                    text=ai_acc, is_final=True, turn_id=active_turn_id,
                )
            if recorder and active_turn_id:
                try:
                    await recorder.complete_turn()
                except Exception:
                    logger.exception("doubao_complete_turn_failed")
            state["ai_acc"] = ""
            state["user_acc"] = ""
            state["active_turn_id"] = None
            state["tts_active"] = False
            state["text_source"] = None
            return True

        if event == EVENT_ASR_INFO:
            # 服务端识别到用户开始说话 —— 用于打断客户端播报 (barge-in)。
            state["user_acc"] = ""
            state["user_final_sent"] = False
            if state.get("tts_active"):
                state["tts_active"] = False
                interrupted_turn_id = state.get("active_turn_id")
                state["active_turn_id"] = None
                state["ai_acc"] = ""
                state["text_source"] = None
                if recorder is not None:
                    try:
                        await recorder.interrupt_current_turn()
                    except Exception:
                        logger.exception("doubao_interrupt_turn_failed")
                await self._send_event(
                    websocket, "interrupted",
                    turn_id=interrupted_turn_id,
                    interrupted=True,
                )
            return True

        if event == EVENT_ASR_RESPONSE:
            data = _payload_json()
            results = data.get("results") or []
            if results and isinstance(results[0], dict):
                text = str(results[0].get("text") or "").strip()
                is_interim = bool(results[0].get("is_interim"))
                if text:
                    state["user_acc"] = text
                    if is_interim:
                        # 前端约定: interim=True 原位更新预览,否则视为 final 提交
                        await self._send_event(
                            websocket, "user_transcript",
                            text=text, interim=True,
                        )
                    else:
                        state["user_final_sent"] = True
                        await self._send_event(
                            websocket, "user_transcript",
                            text=text, turn_id=None,
                        )
            return True

        if event == EVENT_ASR_ENDED:
            user_acc = state.get("user_acc") or ""
            if user_acc and not state.get("user_final_sent"):
                state["user_final_sent"] = True
                await self._send_event(
                    websocket, "user_transcript",
                    text=user_acc, turn_id=None,
                )
            return True

        if event == EVENT_DIALOG_COMMON_ERROR:
            data = _payload_json()
            message = str(data.get("message") or "未知错误")
            status_code = data.get("status_code") or ""
            await self._send_event(
                websocket, "error",
                message=f"豆包实时语音错误 ({status_code}): {message}",
            )
            return True

        if event == EVENT_SESSION_FAILED:
            await self._send_event(
                websocket, "error",
                message=f"豆包实时语音会话失败: {_frame_error_text(frame)}",
            )
            return False

        if event in (EVENT_SESSION_FINISHED, EVENT_CONNECTION_FINISHED):
            return False

        # 150/154/251/350-end/553 and unknown events: nothing to do.
        return True

    async def _doubao_to_client_loop(
        self,
        websocket: WebSocket,
        doubao_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
        is_openspeech: bool = False,
        session_id: str = "",
    ) -> None:
        interruption = interruption or InterruptionDecisionCoordinator()
        active_turn_id: str | None = None
        user_transcript_acc: str = ""
        ai_transcript_acc: str = ""
        turn_start_t0: float = time.perf_counter()
        openspeech_state: dict[str, Any] = {
            "active_turn_id": None,
            "ai_acc": "",
            "user_acc": "",
            "t0": time.perf_counter(),
            "tts_active": False,
            "text_source": None,
            "user_final_sent": False,
            "websearch_notified": False,
        }

        while True:
            try:
                raw_msg = await doubao_ws.recv()
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception:
                break

            if is_openspeech:
                if isinstance(raw_msg, str):
                    raw_msg = raw_msg.encode("utf-8")
                try:
                    frame = decode_openspeech_frame(raw_msg)
                except Exception:
                    continue
                keep_going = await self._doubao_openspeech_dispatch(
                    websocket, frame, openspeech_state,
                    memory_session=memory_session,
                    recorder=recorder,
                    interruption=interruption,
                )
                if not keep_going:
                    break
                continue

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
                        user_transcript_acc, _ = _merge_streaming_text(user_transcript_acc, transcript)
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

    # ------------------------------------------------------------------
    # Session entry point
    # ------------------------------------------------------------------

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
        app_id = settings["app_id"]

        is_openspeech = "openspeech.bytedance.com" in endpoint
        if is_openspeech:
            if not app_id:
                await self._send_event(
                    websocket, "error",
                    message=(
                        "豆包实时语音需要 APP ID：请在 设置 → Doubao 中填写火山引擎"
                        "「豆包语音」控制台概览页的 APP ID（与 Access Token 配套）。"
                    ),
                )
                return
            headers = {
                "X-Api-App-ID": app_id,
                "X-Api-Access-Key": api_key,
                "X-Api-Resource-Id": "volc.speech.dialog",
                "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
                "X-Api-Connect-Id": str(uuid.uuid4()),
            }
            url = endpoint
        else:
            headers = {
                "Authorization": f"Bearer {api_key}",
            }
            url = f"{endpoint}?model={model_name}"

        ws_kwargs = {
            "max_size": 2**24,
            "ping_interval": 30,
            "ping_timeout": 30,
        }
        try:
            ws_context = websockets.connect(url, additional_headers=headers, **ws_kwargs)
        except TypeError:
            ws_context = websockets.connect(url, extra_headers=headers, **ws_kwargs)

        interruption = InterruptionDecisionCoordinator()
        memory_session = memory_session or RealtimeMemorySession()
        tool_session = tool_session or VoiceAgentToolSession()

        try:
            async with ws_context as doubao_ws:
                session_id = ""
                if is_openspeech:
                    try:
                        session_id = await self._openspeech_handshake(
                            doubao_ws,
                            voice=voice_name,
                            instructions=instructions,
                            dialog_model=settings["dialog_model"],
                            websearch_key=settings["websearch_key"],
                        )
                    except Exception as exc:
                        logger.error("doubao_openspeech_handshake_failed: %s", exc)
                        await self._send_event(websocket, "error", message=str(exc))
                        return
                else:
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

                await self._send_event(
                    websocket,
                    "session_open",
                    provider="Doubao",
                    model=model_name,
                    voice=voice_name,
                    session_id=recorder.session_id if recorder is not None else "",
                    mode="openspeech_dialogue" if is_openspeech else "realtime_gateway",
                )

                client_task = asyncio.create_task(
                    self._client_to_doubao_loop(
                        websocket, doubao_ws, memory_session, tool_session, recorder, interruption,
                        is_openspeech=is_openspeech, session_id=session_id,
                    )
                )
                doubao_task = asyncio.create_task(
                    self._doubao_to_client_loop(
                        websocket, doubao_ws, memory_session, tool_session, recorder, interruption,
                        is_openspeech=is_openspeech, session_id=session_id,
                    )
                )

                try:
                    await self._run_duplex_tasks(client_task, doubao_task)
                finally:
                    if is_openspeech and session_id:
                        # 优雅收尾:FinishSession → FinishConnection(最大努力)
                        for evt, sid in (
                            (EVENT_FINISH_SESSION, session_id),
                            (EVENT_FINISH_CONNECTION, None),
                        ):
                            try:
                                await doubao_ws.send(
                                    encode_openspeech_frame(
                                        MSG_TYPE_FULL_CLIENT_REQ, {}, event=evt, session_id=sid,
                                    )
                                )
                            except Exception:
                                break
        except WebSocketDisconnect:
            return
        except _WS_INVALID_STATUS as exc:
            status_code = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code == 401 or "401" in str(exc):
                err_msg = (
                    "火山引擎豆包实时语音鉴权失败 (HTTP 401)。请确认设置中填写的是"
                    "「豆包语音」控制台的 Access Token（X-Api-Access-Key），并且 APP ID "
                    "与该 Token 属于同一个应用；注意火山方舟(Ark)的 API Key 不能用于实时语音。"
                )
            else:
                err_msg = f"豆包 WebSocket 连接被拒绝 (HTTP {status_code or exc})。"
            logger.error("doubao_ws_connect_failed: %s", exc)
            await self._send_event(websocket, "error", message=err_msg)
        except Exception as exc:
            logger.exception("doubao_session_failed")
            await self._send_event(websocket, "error", message=f"豆包实时语音连接失败: {exc}")
