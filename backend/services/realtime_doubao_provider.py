"""Doubao / Volcengine Realtime voice provider mixin.

Single transport path: 端到端实时语音-全双工版本 (SeedPulse duplex),
``wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue``, pure JSON
event protocol authenticated with a single ``X-Api-Key`` header from the
new Volcengine speech console (API Key 管理). Docs: volcengine.com/docs/6561/2549732.

The legacy OpenSpeech binary-framing dialogue endpoint (x- Access Token +
APP ID) was removed on 2026-08-24; only the duplex protocol is supported.
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
import websockets.exceptions  # noqa: F401  # explicit: lazy loader hides it otherwise
from fastapi import WebSocket, WebSocketDisconnect

from .realtime_constants import (
    BASE_REALTIME_INSTRUCTIONS,
    DEFAULT_DOUBAO_DUPLEX_DIALOG_MODEL,
    DEFAULT_DOUBAO_DUPLEX_ENDPOINT,
    DEFAULT_DOUBAO_REALTIME_MODEL,
    DEFAULT_DOUBAO_REALTIME_VOICE,
    DOUBAO_REALTIME_VOICES,
)
from .interruption_classifier import InterruptionDecisionCoordinator
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder
from .voice_agent_tools import VoiceAgentToolSession
from .doubao_asr_provider import _get_websockets_header_kwargs

logger = logging.getLogger(__name__)

_DOUBAO_DIALOG_MODEL_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")

# websockets >= 14 renamed InvalidStatusCode → InvalidStatus.
_INVALID_STATUS_CLS = getattr(websockets.exceptions, "InvalidStatus", None)
if _INVALID_STATUS_CLS is None:  # pragma: no cover - legacy websockets
    _INVALID_STATUS_CLS = getattr(websockets.exceptions, "InvalidStatusCode", None)
_WS_INVALID_STATUS = (_INVALID_STATUS_CLS,) if isinstance(_INVALID_STATUS_CLS, type) else ()


class DoubaoRealtimeMixin:
    """Doubao Realtime provider methods for RealtimeVoiceService."""

    def _resolve_doubao_settings(
        self, model: str | None, voice: str | None = None
    ) -> dict[str, str]:
        passed_model = model.strip() if (model and model.strip()) else ""
        provider_settings = self.config.get_provider_settings("Doubao", model)
        resolved_model = passed_model or provider_settings["model"].strip() or DEFAULT_DOUBAO_REALTIME_MODEL

        custom_endpoint = provider_settings.get("realtime_base_url", "").strip()
        if "/api/v3/realtime/dialogue" in custom_endpoint:
            # 2026-08-24 起旧二进制端点已移除;清理历史遗留的自定义地址,
            # 回退默认全双工端点(否则用户保存过的旧地址会静默连不上)
            logger.warning(
                "doubao_legacy_realtime_base_url_ignored: %s", custom_endpoint
            )
            custom_endpoint = ""
        endpoint = custom_endpoint or DEFAULT_DOUBAO_DUPLEX_ENDPOINT

        requested_voice = voice.strip() if (voice and voice.strip()) else ""
        if requested_voice in DOUBAO_REALTIME_VOICES:
            resolved_voice = requested_voice
        else:
            resolved_voice = DEFAULT_DOUBAO_REALTIME_VOICE

        websearch_key = ""
        access_token = ""
        get_setting = getattr(self.config, "get_setting", None)
        if callable(get_setting):
            ws_candidate = get_setting("doubao_websearch_api_key", "")
            if isinstance(ws_candidate, str):
                websearch_key = ws_candidate.strip()
            token_candidate = get_setting("doubao_access_token", "")
            if isinstance(token_candidate, str):
                access_token = token_candidate.strip()

        # 实时语音凭证是豆包语音控制台「API Key 管理」签发的 API Key(UUID 格式,
        # X-Api-Key 鉴权,无需 APP ID)。只认独立的 doubao_access_token 字段,
        # 不再回退 doubao_api_key(那是火山方舟文字聊天的钥匙,两套体系)。
        realtime_credential = access_token
        if not realtime_credential:
            raise RuntimeError(
                "豆包实时语音凭证未配置：请在 设置 → Doubao 的「API Key / Access Token"
                "（实时语音）」栏填写新版豆包语音控制台「API Key 管理」中的 API Key。"
            )

        # 全双工 session.model 固定 1.2.6.1;允许用 x.y.z.w 形式的模型名覆盖。
        dialog_model = (
            resolved_model
            if _DOUBAO_DIALOG_MODEL_RE.match(resolved_model)
            else DEFAULT_DOUBAO_DUPLEX_DIALOG_MODEL
        )

        return {
            "api_key": realtime_credential,
            "model": resolved_model,
            "dialog_model": dialog_model,
            "voice": resolved_voice,
            "endpoint": endpoint,
            "websearch_key": websearch_key,
        }

    # ------------------------------------------------------------------
    # Duplex (全双工) JSON-protocol handshake
    # ------------------------------------------------------------------

    async def _duplex_handshake(
        self,
        doubao_ws: Any,
        *,
        voice: str,
        instructions: str | None,
        dialog_model: str,
        websearch_key: str = "",
    ) -> str:
        """session.create → session.created. Returns the server dialog id."""
        session_payload: dict[str, Any] = {
            "model": dialog_model,
            "instructions": instructions or BASE_REALTIME_INSTRUCTIONS,
            "audio": {
                "input": {"format": {"type": "pcm", "rate": 16000}},
                "output": {
                    "format": {"type": "pcm_s16le", "rate": 24000},
                    "voice": voice,
                },
            },
        }
        extension: dict[str, Any] = {
            "asr": {"extra": {}},
            "tts": {"extra": {}},
            "dialog": {"extra": {}},
        }
        if websearch_key:
            # 内置联网(融合信息搜索):不开的话模型会凭空编造天气/新闻等实时信息
            extension["dialog"]["extra"] = {
                "enable_volc_websearch": True,
                "volc_websearch_type": "web",
                "volc_websearch_api_key": websearch_key,
            }
        await doubao_ws.send(json.dumps({
            "type": "session.create",
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "session": session_payload,
            "extension": extension,
        }, ensure_ascii=False))
        while True:
            raw = await asyncio.wait_for(doubao_ws.recv(), timeout=15.0)
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            try:
                event = json.loads(text)
            except Exception:
                continue
            event_type = str(event.get("type") or "")
            if event_type == "session.created":
                return str((event.get("session") or {}).get("id") or "")
            if event_type == "error":
                err = event.get("error") or event
                raise RuntimeError(f"豆包全双工会话启动失败: {json.dumps(err, ensure_ascii=False)}")
            # session.created 之前可能先到其它下行事件,忽略继续等
        return ""

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
                        # 全双工协议没有文本触发回复的事件:文字只能进上下文,
                        # 模型在下一轮语音对话时参考。不发 response.create。
                        if memory_session is not None:
                            memory_session.note_user_transcript(content)
                        await doubao_ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                            "items": [{
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": content}],
                            }],
                        }, ensure_ascii=False))
                        # 明确告知前端该限制,避免"等待回复"静默悬挂(error 事件
                        # 会终止整个会话,故用非致命的 agent_progress 提示)
                        await self._send_event(
                            websocket, "agent_progress",
                            stage="text_context_only",
                            message="豆包全双工模式暂不支持文字直接提问，文字已记入上下文；请直接说话继续对话。",
                        )
                    continue
                if command_type == "media_input":
                    text_prompt = str(payload.get("text", "")).strip()
                    note_text = f"[Image] {text_prompt}" if text_prompt else "[Image]"
                    prompt = f"[User attached an image]\n{text_prompt}" if text_prompt else "[User attached an image]"
                    if memory_session is not None:
                        memory_session.note_user_transcript(note_text)
                    if recorder is not None:
                        await recorder.note_user_transcript(note_text)
                    # 全双工为纯语音模型:图片仅进上下文占位,不触发回复。
                    await doubao_ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                        "items": [{
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": prompt}],
                        }],
                    }, ensure_ascii=False))
                    await self._send_event(
                        websocket, "agent_progress",
                        stage="text_context_only",
                        message="豆包全双工模式暂不支持图片输入，请直接说话继续对话。",
                    )
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

    # ------------------------------------------------------------------
    # Doubao → client
    # ------------------------------------------------------------------

    @staticmethod
    def _duplex_output_suppressed(state: dict[str, Any], response_id: str) -> bool:
        """True 当该下行增量属于被打断、应丢弃的那轮回复。

        ``suppressed_response_id`` 为 None 表示当前没有抑制窗。全双工的
        Chat/TTS 事件都携带 response_id(2026-08-24 实测),按 id 精确匹配;
        barge-in 时拿不到在播 response_id(空串)或个别事件缺失 id 时,
        在窗口期内保守视为残余流一并丢弃。
        """
        suppressed = state.get("suppressed_response_id")
        if suppressed is None:
            return False
        return not suppressed or not response_id or response_id == suppressed

    @staticmethod
    def _duplex_missing_text_suffix(accumulated: str, final_text: str) -> str:
        """计算 done.text 相对已转发增量的缺失后缀;分歧(无法安全拼接)返回空串。"""
        final_text = str(final_text or "")
        if not final_text or final_text == accumulated:
            return ""
        if final_text.startswith(accumulated):
            return final_text[len(accumulated):]
        if accumulated:
            logger.warning(
                "doubao_duplex_text_done_divergent: acc=%r done=%r",
                accumulated[:120], final_text[:120],
            )
        return ""

    async def _doubao_duplex_dispatch(
        self,
        websocket: WebSocket,
        event: dict[str, Any],
        state: dict[str, Any],
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        interruption: InterruptionDecisionCoordinator,
    ) -> bool:
        """Handle one 全双工 JSON event. Returns False when the loop should end."""
        event_type = str(event.get("type") or "")

        if event_type == "session.closed":
            return False

        if event_type == "conversation.item.input_audio_transcription.started":
            # 服务端识别到用户开始说话 —— 打断客户端播报 (barge-in)。
            state["user_acc"] = ""
            state["user_final_sent"] = False
            if state.get("tts_active"):
                # 定向抑制:只丢弃被打断那轮(active_response_id)的残余增量。
                # 不能开"一刀切"抑制窗——新一轮回复的文本增量常先于它自己的
                # output_audio.started 到达(2026-08-24 实测),一刀切会把新回复
                # 开头整段文本吞掉,造成回复转写缺内容。
                state["suppressed_response_id"] = str(state.get("active_response_id") or "")
                state["turn_finalized"] = False
                state["tts_active"] = False
                state["active_response_id"] = None
                state["active_turn_id"] = None
                state["ai_acc"] = ""
                if recorder is not None:
                    try:
                        await recorder.interrupt_current_turn()
                    except Exception:
                        logger.exception("doubao_interrupt_turn_failed")
                # 不带具体 turn_id(可能与服务端 resp id 命名空间不一致):
                # 空值让前端无条件停止当前播报。
                await self._send_event(
                    websocket, "interrupted",
                    turn_id="",
                    interrupted=True,
                )
            return True

        if event_type == "conversation.item.input_audio_transcription.delta":
            # 官方协议语义(delta 是"截至目前"的完整快照而非增量,且临近结束会
            # 回退修订标点,见官方 web demo 的 setQuestion 整体替换用法):必须
            # 整体替换。此前按增量累加,interim 文本反复重复刷屏,直到
            # completed 才恢复成一遍。
            snapshot = str(event.get("delta") or "")
            if snapshot:
                state["user_acc"] = snapshot
                # 前端约定: interim=True 原位更新预览,否则视为 final 提交
                await self._send_event(
                    websocket, "user_transcript",
                    text=snapshot, interim=True,
                    turn_id=state.get("active_turn_id"),
                )
            return True

        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = str(event.get("transcript") or event.get("text") or "").strip()
            if not transcript:
                transcript = (state.get("user_acc") or "").strip()
            if transcript and not state.get("user_final_sent"):
                state["user_final_sent"] = True
                if memory_session is not None:
                    memory_session.note_user_transcript(transcript)
                    # Retrieve cloud memories and inject as context before the
                    # model auto-generates its reply. Doubao's full-duplex
                    # protocol does not support re-configuring instructions
                    # mid-session, so we inject retrieved memories as a
                    # system-side conversation item the model can reference.
                    try:
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
                            await doubao_ws.send(json.dumps({
                                "type": "conversation.item.create",
                                "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                                "items": [{
                                    "type": "message",
                                    "role": "system",
                                    "content": [{"type": "input_text", "text": f"以下是从长期记忆中检索到的相关历史信息，请参考这些内容回答用户的问题：\n{memory_context}"}],
                                }],
                            }, ensure_ascii=False))
                    except Exception:
                        logger.exception("doubao_memory_retrieve_failed")
                voice_turn_id = ""
                if recorder is not None:
                    voice_turn_id = await recorder.note_user_transcript(transcript)
                    if voice_turn_id:
                        state["active_turn_id"] = voice_turn_id
                await self._send_event(
                    websocket, "user_transcript",
                    text=transcript, turn_id=state.get("active_turn_id"),
                )
            return True

        if event_type == "conversation.item.input_audio_transcription.failed":
            logger.info("doubao_duplex_asr_failed: %s", str(event)[:300])
            return True

        if event_type == "response.output_audio.started":
            response_id = str(event.get("response_id") or "")
            # 新一轮回复开始 → 解除对上一轮被打断回复的定向抑制
            suppressed = state.get("suppressed_response_id")
            if suppressed is not None and (
                not suppressed or not response_id or response_id != suppressed
            ):
                state["suppressed_response_id"] = None
            if response_id and response_id != state.get("active_response_id"):
                # 锚定豆包命名空间的"在播回复 id"(与承载 recorder 话轮 id 的
                # active_turn_id 严格分离——后者会被迟到的 ASR completed 覆写,
                # 混用会让打断抑制错锚)。服务端可能把一条逻辑回复拆成多个
                # response_id 分段(实测):此时不清 ai_acc —— 正常轮次它已被上
                # 一轮 finalize 清空,非空即分段续流,保留它才能让 done 对账基线完整。
                state["active_response_id"] = response_id
                state["turn_finalized"] = False
                state["websearch_notified"] = False
                interruption.active_response_id = response_id
            state["tts_active"] = True
            # tts_type=network 表示本轮使用了内置联网搜索 —— 映射为前端的进度提示。
            if (
                str(event.get("tts_type") or "") == "network"
                and not state.get("websearch_notified")
            ):
                state["websearch_notified"] = True
                await self._send_event(
                    websocket, "agent_progress",
                    stage="builtin_websearch",
                    turn_id=state.get("active_turn_id"),
                    message="豆包正在使用联网搜索结果回答…",
                )
            return True

        if event_type == "response.output_audio.delta":
            if self._duplex_output_suppressed(state, str(event.get("response_id") or "")):
                return True  # 被打断那轮的残余音频:丢弃,不排期播放
            audio_b64 = str(event.get("delta") or "")
            if audio_b64:
                state["tts_active"] = True
                await self._emit_assistant_output(
                    websocket,
                    interruption,
                    {
                        "type": "assistant_audio",
                        "audio": audio_b64,
                        "encoding": "pcm_s16le",
                        "sample_rate": 24000,
                        "turn_id": state.get("active_turn_id"),
                    },
                    memory_session=memory_session,
                    recorder=recorder,
                )
            return True

        if event_type == "response.output_audio.done":
            response_id = str(event.get("response_id") or "")
            if self._duplex_output_suppressed(state, response_id):
                # 被打断那轮的合成结束信号:静默解除定向抑制,不触发收尾(否则
                # 会产生空 turn_complete 提前提交用户正在进行的下一句话)
                state["suppressed_response_id"] = None
                return True
            # 一轮音频合成结束即本轮收尾(全双工没有独立 TTSEnded 文本事件);
            # status_code=20000002 表示模型识别到用户退出意图。
            if str(event.get("status_code") or "") == "20000002":
                logger.info("doubao_duplex_exit_intent_detected")
            # 无任何回复输出时不做收尾(避免空 turn_complete 干扰前端话轮)
            if not (state.get("tts_active") or state.get("ai_acc")):
                return True
            try:
                await self._finalize_realtime_turn(
                    websocket,
                    memory_session,
                    recorder,
                    gated=False,
                )
            except Exception:
                logger.exception("doubao_finalize_turn_failed")
                if recorder:
                    try:
                        await recorder.complete_turn()
                    except Exception:
                        pass
            state["ai_acc"] = ""
            state["user_acc"] = ""
            state["active_response_id"] = None
            state["turn_finalized"] = True
            state["tts_active"] = False
            return True

        if event_type == "response.output_text.delta":
            if self._duplex_output_suppressed(state, str(event.get("response_id") or "")):
                return True  # 被打断那轮的残余文本:丢弃
            content = str(event.get("delta") or "")
            if content:
                state["ai_acc"] = (state.get("ai_acc") or "") + content
                await self._emit_assistant_output(
                    websocket,
                    interruption,
                    {"type": "assistant_text", "text": content, "turn_id": state.get("active_turn_id")},
                    memory_session=memory_session,
                    recorder=recorder,
                )
            return True

        if event_type == "response.output_text.done":
            response_id = str(event.get("response_id") or "")
            if self._duplex_output_suppressed(state, response_id):
                return True  # 被打断轮次的最终文本:整体丢弃
            if state.get("turn_finalized"):
                return True  # 本轮已收尾:迟到的 done 不再二次推送(否则全文翻倍)
            # done.text 是服务端权威全文。与已流式转发的增量对账,缺多少补多少:
            # 自愈任何路径造成的缺口且不重复推送(实测 sum(deltas) == done.text)。
            accumulated = str(state.get("ai_acc") or "")
            if final_diff := self._duplex_missing_text_suffix(accumulated, str(event.get("text") or "")):
                await self._emit_assistant_output(
                    websocket,
                    interruption,
                    {
                        "type": "assistant_text",
                        "text": final_diff,
                        "turn_id": state.get("active_turn_id"),
                    },
                    memory_session=memory_session,
                    recorder=recorder,
                )
                state["ai_acc"] = accumulated + final_diff
            return True

        if event_type == "error":
            err = event.get("error")
            if isinstance(err, dict):
                message = str(err.get("message") or err)
            else:
                message = str(err or event)
            await self._send_event(
                websocket, "error",
                message=f"豆包全双工语音服务错误: {message}",
            )
            return True

        if event_type == "response.function_call_arguments.done":
            # 全双工支持 Function Calling;当前尚未接入工具链,收到时记录日志。
            logger.info("doubao_duplex_function_call_unsupported: %s", str(event)[:300])
            return True

        # session.created/updated、input_audio_buffer.committed、
        # conversation.item.added/retrieved/deleted、response.done/canceled
        # 以及未知事件:无需处理。
        return True

    async def _doubao_to_client_loop(
        self,
        websocket: WebSocket,
        doubao_ws: Any,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None = None,
        interruption: InterruptionDecisionCoordinator | None = None,
        turn_state: dict[str, Any] | None = None,
    ) -> None:
        interruption = interruption or InterruptionDecisionCoordinator()
        # Turn lifecycle state for the downlink dispatch loop.
        turn_state = turn_state or {
            "active_turn_id": None,       # recorder 话轮 id(用户转写打标用)
            "active_response_id": None,   # 豆包在播回复 id(抑制锚点/分段判定用)
            "turn_finalized": False,      # 本轮是否已收尾(迟到 done 对账守卫)
            "ai_acc": "",
            "user_acc": "",
            "suppressed_response_id": None,
            "tts_active": False,
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

            if isinstance(raw_msg, bytes):
                raw_msg = raw_msg.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw_msg)
            except Exception:
                continue
            keep_going = await self._doubao_duplex_dispatch(
                websocket, event, turn_state,
                memory_session=memory_session,
                recorder=recorder,
                interruption=interruption,
            )
            if not keep_going:
                break

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

        headers = {
            "X-Api-Key": api_key,
        }
        url = endpoint

        ws_kwargs = {
            "max_size": 2**24,
            "ping_interval": 30,
            "ping_timeout": 30,
        }
        ws_kwargs.update(_get_websockets_header_kwargs(headers))
        ws_context = websockets.connect(url, **ws_kwargs)

        interruption = InterruptionDecisionCoordinator()
        memory_session = memory_session or RealtimeMemorySession()
        tool_session = tool_session or VoiceAgentToolSession()

        # Pre-load a compact summary of recent memories into the session
        # instructions BEFORE the duplex handshake. Doubao's full-duplex
        # protocol auto-generates a response the moment the user stops
        # speaking, so injecting context after transcription.completed is too
        # late. By folding a *concise* memory summary into the initial
        # instructions here, the model knows prior topics exist and can
        # naturally reference them when the user asks — without bloating
        # every reply with history the user didn't ask about.
        base_instructions = instructions or BASE_REALTIME_INSTRUCTIONS
        if memory_session._config.get_service() is None and not memory_session._explicitly_configured:
            memory_session.configure_from_server()
        if memory_session._config.get_service() is not None:
            try:
                from .realtime_memory_session import RealtimeMemorySession as _RMS
                service = memory_session._config.get_service()
                local_entries = _RMS._all_pending_entries_any_scope()
                cloud_entries: list[dict[str, Any]] = []
                try:
                    import asyncio as _aio
                    cloud_entries = await _aio.wait_for(
                        memory_session._search_cloud_memories(
                            service=service,
                            query=memory_session._STARTUP_QUERY,
                            force_global=True,
                        ),
                        timeout=memory_session._STARTUP_RETRIEVE_TIMEOUT_SECONDS,
                    )
                except Exception:
                    pass
                combined = memory_session._merge_retrieved_memories(
                    local_memories=local_entries,
                    cloud_memories=cloud_entries,
                )
                lines: list[str] = []
                for mem in combined[:5]:
                    content = str(mem.get("content", "")).strip()
                    if content:
                        lines.append(f"- {content[:120]}")
                if lines:
                    pre_ctx = "\n".join(lines)
                    base_instructions = (
                        f"{base_instructions}\n\n"
                        f"以下是用户之前的长期记忆摘要（仅在用户询问历史对话时引用，不要主动复述）：\n{pre_ctx}"
                    )
                    logger.info("voice_memory_handshake_inject local=%s cloud=%s", len(local_entries), len(cloud_entries))
            except Exception:
                logger.exception("doubao_memory_handshake_prefetch_failed")
        # Turn lifecycle state, owned here and consumed by the downlink loop.
        turn_state: dict[str, Any] = {
            "active_turn_id": None,       # recorder 话轮 id(用户转写打标用)
            "active_response_id": None,   # 豆包在播回复 id(抑制锚点/分段判定用)
            "turn_finalized": False,      # 本轮是否已收尾(迟到 done 对账守卫)
            "ai_acc": "",
            "user_acc": "",
            "suppressed_response_id": None,
            "tts_active": False,
            "user_final_sent": False,
            "websearch_notified": False,
        }

        try:
            async with ws_context as doubao_ws:
                try:
                    dialog_id = await self._duplex_handshake(
                        doubao_ws,
                        voice=voice_name,
                        instructions=base_instructions,
                        dialog_model=settings["dialog_model"],
                        websearch_key=settings["websearch_key"],
                    )
                except Exception as exc:
                    logger.error("doubao_duplex_handshake_failed: %s", exc)
                    await self._send_event(websocket, "error", message=str(exc))
                    return
                logger.debug("doubao_duplex_dialog_id: %s", dialog_id)

                await self._send_event(
                    websocket,
                    "session_open",
                    provider="Doubao",
                    model=model_name,
                    voice=voice_name,
                    session_id=recorder.session_id if recorder is not None else "",
                    mode="duplex_dialogue",
                )

                client_task = asyncio.create_task(
                    self._client_to_doubao_loop(
                        websocket, doubao_ws, memory_session, tool_session, recorder,
                        interruption,
                    )
                )
                doubao_task = asyncio.create_task(
                    self._doubao_to_client_loop(
                        websocket, doubao_ws, memory_session, tool_session, recorder,
                        interruption, turn_state=turn_state,
                    )
                )

                try:
                    await self._run_duplex_tasks(client_task, doubao_task)
                finally:
                    # 优雅收尾:session.close(最大努力,不再等下行)
                    try:
                        await doubao_ws.send(json.dumps({
                            "type": "session.close",
                            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                        }))
                    except Exception:
                        pass
        except WebSocketDisconnect:
            return
        except _WS_INVALID_STATUS as exc:
            status_code = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code == 401 or "401" in str(exc):
                err_msg = (
                    "火山引擎豆包实时语音鉴权失败 (HTTP 401)。请确认设置中填写的是"
                    "新版控制台（console.volcengine.com/speech/new）→「API Key 管理」"
                    "的 API Key；旧版 x- Access Token 与火山方舟(Ark) key 均不能用于"
                    "全双工实时语音。"
                )
            elif status_code == 403 or "403" in str(exc):
                err_msg = (
                    "火山引擎豆包实时语音拒绝访问 (HTTP 403)。可能原因：\n"
                    "1. 账户欠费或无可用免费/付费资源包（请检查火山引擎账户余额与订单）；\n"
                    "2. 该应用尚未在控制台开通「端到端实时语音-全双工版本」服务；\n"
                    "3. API Key 与所用项目不匹配。"
                )
            else:
                err_msg = f"豆包 WebSocket 连接被拒绝 (HTTP {status_code or exc})。"
            logger.error("doubao_ws_connect_failed: %s", exc)
            await self._send_event(websocket, "error", message=err_msg)
        except Exception as exc:
            logger.exception("doubao_session_failed")
            await self._send_event(websocket, "error", message=f"豆包实时语音连接失败: {exc}")
