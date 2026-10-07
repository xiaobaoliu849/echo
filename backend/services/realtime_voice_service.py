"""Realtime voice service — facade composing per-provider mixins.

This module is the single public entry-point for realtime voice sessions.
Provider-specific logic lives in the mixin modules:

- ``realtime_google_provider``    — Google Gemini Live
- ``realtime_dashscope_provider`` — DashScope Qwen-Omni (SDK)
- ``realtime_openai_provider``    — OpenAI Realtime
- ``realtime_qwen_audio_provider``— Qwen-Audio (raw WebSocket)
- ``realtime_doubao_provider``    — Doubao OpenSpeech dialogue
- ``realtime_personaplex_provider``— PersonaPlex (local moshi server)

Shared infrastructure (interruption arbitration, output delivery, turn
finalization, event emission) stays here.  All names that external code
(routers, tests) historically imported from this module are re-exported
at the bottom for backward compatibility.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from fastapi import WebSocket

from .config_loader import BackendConfig, normalize_provider_name
from .interruption_classifier import (
    InterruptionClassifier,
    InterruptionDecisionCoordinator,
    InterruptionIntent,
)
from .voice_agent_session_repository import VoiceAgentSessionRepository
from .voice_agent_tools import VoiceAgentToolSession
from .realtime_tool_protocol import (
    RealtimeToolCall,
    dashscope_supports_native_tools,
    dashscope_tool_declarations,
    native_tool_declarations,
    tool_call_to_request,
    tool_error_payload,
    tool_result_payload,
)
from .background_tasks import spawn_background_task
from .realtime_memory_session import RealtimeMemorySession
from .realtime_dashscope_client import DashScopeRealtimeCallback, DashScopeAudioRealtimeConversation
from .realtime_session_recorder import VoiceAgentSessionRecorder, run_db_call
from .speaking_coach import SpeakingCoach, current_tutor_instructions, normalize_coach_config, should_review

# Conditional SDK imports — kept here so that test_api_smoke can patch
# ``realtime_voice_service.genai`` / ``realtime_voice_service.types``.
try:
    from google import genai
    from google.genai import types
except ImportError as e:  # pragma: no cover
    genai = None
    types = None
except Exception as e:
    genai = None
    types = None

try:
    from dashscope.audio.qwen_omni import AudioFormat, MultiModality, OmniRealtimeConversation
except ImportError as e:  # pragma: no cover
    AudioFormat = None
    MultiModality = None
    OmniRealtimeConversation = None
except Exception as e:
    AudioFormat = None
    MultiModality = None
    OmniRealtimeConversation = None

# Constants & helpers — imported so they remain accessible as module attributes
# for backward-compatible ``from services.realtime_voice_service import X``.
from .realtime_constants import (  # noqa: F401 — re-exports
    BASE_REALTIME_INSTRUCTIONS,
    DEFAULT_DASHSCOPE_REALTIME_MODEL,
    DEFAULT_DASHSCOPE_REALTIME_VOICE,
    DEFAULT_GOOGLE_REALTIME_MODEL,
    DEFAULT_AGENT_PLATFORM_REALTIME_MODEL,
    DEFAULT_VERTEXAI_REALTIME_MODEL,
    DEFAULT_GOOGLE_REALTIME_VOICE,
    DEFAULT_OPENAI_REALTIME_MODEL,
    DEFAULT_OPENAI_REALTIME_VOICE,
    DEFAULT_CARTESIA_REALTIME_MODEL,
    DEFAULT_CARTESIA_REALTIME_VOICE,
    DEFAULT_GRADIUM_REALTIME_MODEL,
    DEFAULT_GRADIUM_REALTIME_VOICE,
    DEFAULT_VERCEL_REALTIME_MODEL,
    DEFAULT_VERCEL_REALTIME_VOICE,
    DEFAULT_STEPFUN_REALTIME_MODEL,
    DEFAULT_STEPFUN_REALTIME_VOICE,
    STEPFUN_REALTIME_VOICES,
    DEFAULT_DOUBAO_REALTIME_MODEL,
    DEFAULT_DOUBAO_REALTIME_VOICE,
    DEFAULT_PERSONAPLEX_REALTIME_MODEL,
    DEFAULT_PERSONAPLEX_REALTIME_VOICE,
    DEFAULT_PERSONAPLEX_SERVER_URL,
    DEFAULT_GLM4VOICE_REALTIME_MODEL,
    DEFAULT_GLM4VOICE_REALTIME_VOICE,
    PERSONAPLEX_REALTIME_INSTRUCTIONS,
    PERSONAPLEX_REALTIME_VOICES,
    PERSONAPLEX_SAMPLE_RATE,
    DEFAULT_QWEN_AUDIO_REALTIME_VOICE,
    DEFAULT_QWEN_OMNI_REALTIME_VOICE,
    DEFAULT_DASHSCOPE_LIVETRANSLATE_VOICE,
    QWEN_AUDIO_BENIGN_ERROR_PATTERNS,
    QWEN_AUDIO_REALTIME_INSTRUCTIONS,
    QWEN_AUDIO_REALTIME_VOICES,
    QWEN_OMNI_REALTIME_VOICES,
    _audio_energy_qwen,
    _is_dashscope_audio_realtime_model,
    _is_dashscope_live_translate_model,
    _is_dashscope_omni_realtime_model,
    _is_google_live_translate_model,
    _is_google_public_rest_base_url,
    _is_google_realtime_model,
    _normalize_dashscope_realtime_voice,
    normalize_qwen_translate_language,
)

# Provider mixins
from .realtime_google_provider import GoogleRealtimeMixin
from .realtime_dashscope_provider import DashScopeRealtimeMixin
from .realtime_openai_provider import OpenAIRealtimeMixin
from .realtime_qwen_audio_provider import QwenAudioRealtimeMixin
from .realtime_doubao_provider import DoubaoRealtimeMixin
from .realtime_personaplex_provider import PersonaPlexRealtimeMixin
from .realtime_glm4voice_provider import RealtimeGlm4VoiceMixin
from .realtime_cartesia_provider import CartesiaRealtimeMixin
from .realtime_gradium_provider import GradiumRealtimeMixin
from .realtime_vercel_provider import VercelRealtimeMixin
from .realtime_stepfun_provider import StepFunRealtimeMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared session infrastructure
# ---------------------------------------------------------------------------

class RealtimeVoiceService(
    GoogleRealtimeMixin,
    DashScopeRealtimeMixin,
    OpenAIRealtimeMixin,
    QwenAudioRealtimeMixin,
    DoubaoRealtimeMixin,
    PersonaPlexRealtimeMixin,
    RealtimeGlm4VoiceMixin,
    CartesiaRealtimeMixin,
    GradiumRealtimeMixin,
    VercelRealtimeMixin,
    StepFunRealtimeMixin,
):
    """Orchestrates realtime voice sessions across multiple providers.

    Provider-specific streaming logic is inherited from the mixins.
    This class provides the shared infrastructure: interruption arbitration,
    output delivery, turn/memory finalization, settings resolution, and the
    WebSocket event emitter.
    """

    def __init__(
        self,
        config: BackendConfig | None = None,
        voice_session_repository: VoiceAgentSessionRepository | None = None,
    ):
        self.config = config or BackendConfig()
        self.voice_session_repository = voice_session_repository
        self.speaking_coach = SpeakingCoach()
        # Strong refs so in-flight background coach reviews are not GC'd.
        self._coach_tasks: set[asyncio.Task[Any]] = set()

    @staticmethod
    async def _run_duplex_tasks(*tasks: asyncio.Task[Any]) -> None:
        """Stop the peer loop on normal disconnect as well as on exceptions."""
        done, pending = await asyncio.wait(set(tasks), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    async def _create_voice_session_recorder(
        self,
        *,
        provider: str,
        model: str,
        voice: str,
    ) -> "VoiceAgentSessionRecorder | None":
        try:
            repository = self.voice_session_repository or VoiceAgentSessionRepository()
            session = await run_db_call(
                repository.create_session,
                provider=provider,
                model=model,
                voice=voice,
                meta={"transport": "websocket"},
            )
            recorder = VoiceAgentSessionRecorder(repository, str(session["id"]))
            await recorder.start(
                {
                    "provider": provider,
                    "model": model,
                    "voice": voice,
                    "status": "open",
                    "meta": {"transport": "websocket"},
                }
            )
            return recorder
        except Exception:
            logger.exception("voice_agent_session_create_failed provider=%s model=%s", provider, model)
            return None

    @staticmethod
    def _get_base_instructions() -> str:
        import datetime
        current_date = datetime.date.today().isoformat()
        return f"{BASE_REALTIME_INSTRUCTIONS}\nCurrent Date: {current_date}.{current_tutor_instructions()}"

    @staticmethod
    def _build_realtime_instructions(
        memory_context: str = "",
        initial_memory_context: str = "",
        **kwargs: Any,
    ) -> str:
        ctx = (memory_context or initial_memory_context or "").strip()
        base_inst = RealtimeVoiceService._get_base_instructions()
        memory_rules = (
            "\n\n[Memory & Tool Calling Rules]\n"
            "You have access to long-term memory via the `recall_memory` tool, external search via `search_web`, and canvas visualization via `render_canvas`.\n"
            "- When the user asks to recall or remember previous conversations, what you discussed days ago, "
            "what the user said earlier, or personal preferences/profile, you MUST use the `recall_memory` tool "
            "or the long-term memories provided below. NEVER use `search_web` to search the internet for user private memories or prior conversations.\n"
            "- Only call `search_web` for real-time external public information (news, weather, sports scores, public facts) when explicitly needed.\n"
            "- Only call `render_canvas` when the user explicitly asks you to make something visual (draw, design, sketch, "
            "build, create, generate, or show a UI, component, webpage, or diagram), or to change what is already on the "
            "canvas; in those cases call it right away without asking. If the user is describing, discussing, explaining, or giving feedback about something "
            "(for example this app's own interface, waveform, colors, or status light, or a change they want made), that is "
            "conversation, not a drawing request: first restate what you understood, and if a mockup might help, ask "
            "\"Want me to sketch that on the canvas?\" before calling the tool. When unsure, ask instead of drawing.\n"
            "- Once you do decide to draw, actually execute `render_canvas` with the complete code, mode ('react' or 'html'), "
            "and title; never just say you are drawing. Keep the code self-contained: import only from react and real "
            "lucide-react icon names, and build everything else with plain elements or inline SVG."
        )
        if not ctx:
            return f"{base_inst}{memory_rules}"
        return (
            f"{base_inst}{memory_rules}\n\n"
            "Relevant long-term memories for personalization are provided below. Use them whenever they are relevant. "
            "If the user asks what they said earlier, what the current focus is, or asks you to recall/search memory, "
            "answer from this memory block directly. Do not claim you cannot remember, do not say each conversation is "
            "independent, and do not ignore the memory block when it is relevant. Only avoid quoting the block verbatim "
            "unless the user directly asks.\n"
            f"{ctx}"
        )

    @staticmethod
    def _build_recall_miss_instructions(user_query: str) -> str:
        base_inst = RealtimeVoiceService._get_base_instructions()
        return f"{base_inst}\n\n{RealtimeVoiceService._recall_miss_note(user_query)}"

    @staticmethod
    def _recall_miss_note(user_query: str) -> str:
        return (
            "The user is explicitly asking you to recall prior conversation memory, but the memory search "
            "returned no matching results. This may mean the earlier conversation has not yet been indexed "
            "into long-term memory, or no relevant memory was stored. Do not pretend you remember specific "
            "prior facts. Tell the user briefly that you searched but could not find a matching saved memory, "
            "and that recent conversations may take time to become searchable. Then ask the user to restate "
            "the detail if needed.\n"
            f"Current user query: {user_query}"
        )

    # -- provider-agnostic tool / response gating --------------------------

    async def _send_response_gated(
        self,
        websocket: WebSocket,
        *,
        provider: str,
        tool_name: str,
        query: str,
        turn_id: str,
        recorder: VoiceAgentSessionRecorder | None = None,
    ) -> None:
        payload = {
            "provider": provider,
            "tool_name": tool_name,
            "query": query,
            "turn_id": turn_id,
            "message": "检测到工具请求，已暂停直接回答，等待工具结果。",
        }
        if recorder is not None:
            await recorder.record_tool_event("response_gated", payload)
        await self._send_event(
            websocket,
            "response_gated",
            **payload,
        )

    # -- settings resolution (checks module-level SDK availability) --------

    def _resolve_google_settings(self, model: str | None, provider: str = "Google") -> dict[str, str]:
        provider = normalize_provider_name(provider)
        provider_settings = self.config.get_provider_settings(provider, model)
        default_realtime_model = DEFAULT_AGENT_PLATFORM_REALTIME_MODEL if provider == "AgentPlatform" else DEFAULT_GOOGLE_REALTIME_MODEL
        requested_model = (model or "").strip()
        if requested_model and _is_google_realtime_model(requested_model):
            resolved_model = requested_model
        else:
            configured_model = provider_settings["model"].strip()
            if configured_model and _is_google_realtime_model(configured_model):
                resolved_model = configured_model
            else:
                resolved_model = default_realtime_model
        api_key = provider_settings["api_key"].strip()
        base_url = provider_settings["base_url"].strip()
        if provider == "Google" and "aiplatform.googleapis.com" in base_url:
            base_url = ""
        if _is_google_public_rest_base_url(base_url):
            base_url = ""
        if not api_key and provider != "AgentPlatform":
            raise RuntimeError(f"{provider} API Key 未配置，无法启动实时语音会话。")
        if genai is None or types is None:
            raise RuntimeError("google-genai 依赖未安装，无法启动实时语音会话。")
        res = {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "model": resolved_model,
        }
        if provider == "AgentPlatform":
            res["sa_file"] = provider_settings.get("sa_file", "")
            res["project_id"] = provider_settings.get("project_id", "")
            res["location"] = provider_settings.get("location", "us-central1")
        return res

    def _resolve_dashscope_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("DashScope", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_DASHSCOPE_REALTIME_MODEL
        api_key = provider_settings["api_key"].strip()
        if not api_key:
            raise RuntimeError("DashScope API Key 未配置，无法启动实时语音会话。")
        if _is_dashscope_omni_realtime_model(resolved_model):
            if OmniRealtimeConversation is None or MultiModality is None or AudioFormat is None:
                raise RuntimeError("DashScope Omni Realtime 依赖未安装，无法启动实时语音会话。")
        # LiveTranslate models do not support native tools; skip the tool check for them.
        if not _is_dashscope_live_translate_model(resolved_model) and not dashscope_supports_native_tools(resolved_model):
            raise RuntimeError(
                "Echo 实时语音仅支持具备原生 Function Calling 的 "
                "qwen3.8-omni-flash-realtime、qwen3.5-omni-plus-realtime、"
                "qwen3.5-omni-flash-realtime，或 qwen-audio-3.1/3.0-realtime-plus、"
                "qwen-audio-3.0-realtime-flash；请在设置中升级模型。"
            )
        realtime_base_url = (
            str(provider_settings.get("realtime_base_url", "")).strip()
            or os.environ.get("DASHSCOPE_REALTIME_BASE_URL", "").strip()
        ).rstrip("/")
        if not realtime_base_url.startswith("wss://") or not realtime_base_url.endswith("/api-ws/v1/realtime"):
            raise RuntimeError(
                "请在设置中配置 Qwen 的业务空间 Realtime WebSocket URL，"
                "格式如 wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime。"
            )
        parsed_url = urlparse(realtime_base_url)
        endpoint_host = (parsed_url.hostname or "").lower()
        if _is_dashscope_audio_realtime_model(resolved_model) and not endpoint_host.endswith((
            ".cn-beijing.maas.aliyuncs.com",
            ".ap-southeast-1.maas.aliyuncs.com",
        )):
            raise RuntimeError(
                "qwen-audio 实时语音模型（3.1 / 3.0）需要北京或新加坡地域的业务空间 Realtime WebSocket URL，"
                "并使用同地域 API Key。"
            )
        return {
            "api_key": api_key,
            "model": resolved_model,
            "realtime_base_url": realtime_base_url,
        }

    # -- WebSocket event emission ------------------------------------------

    @staticmethod
    async def _send_event(websocket: WebSocket, event_type: str, **payload: Any) -> None:
        await websocket.send_json({"type": event_type, **payload})

    # -- interruption arbitration ------------------------------------------

    async def _begin_interruption(
        self,
        websocket: WebSocket,
        coordinator: InterruptionDecisionCoordinator,
        *,
        provider: str,
        provider_event_type: str,
        recorder: VoiceAgentSessionRecorder | None,
        tool_session: VoiceAgentToolSession,
        supersede_timed_out: bool = False,
    ) -> None:
        interrupted_turn_id = recorder.current_turn_id if recorder is not None else ""
        if not interrupted_turn_id:
            interrupted_turn_id = tool_session.current_turn_id
        payload = coordinator.begin(
            provider=provider,
            interrupted_turn_id=interrupted_turn_id,
            provider_event_type=provider_event_type,
            supersede_timed_out=supersede_timed_out,
        )
        if payload is None:
            return
        if recorder is not None:
            await recorder.record_session_event(
                "interruption_pending",
                source="interruption",
                turn_id=interrupted_turn_id,
                payload=dict(payload),
            )
        await self._send_event(websocket, "interruption_pending", **payload)

    # -- assistant output delivery -----------------------------------------

    async def _deliver_assistant_output(
        self,
        websocket: WebSocket,
        event: dict[str, Any],
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        record_memory: bool = True,
    ) -> None:
        event_type = str(event.get("type", ""))
        if event_type == "assistant_text":
            text = str(event.get("text", ""))
            # Strip Markdown symbols to prevent TTS from reading them aloud.
            # Only drop a '#' that heads a Markdown ATX heading (followed by
            # whitespace or another '#') so language names like "C#"/"F#"
            # survive intact.
            text = re.sub(r"[\*`]", "", text)
            text = re.sub(r"#(?=\s|#)", "", text)
            # A cumulative event carries the whole transcript so far (or a final
            # canonical correction) and supersedes what was streamed; anything
            # else is a verbatim delta that must be appended exactly as sent.
            cumulative = bool(event.get("cumulative") or event.get("final"))
            replace = bool(event.get("replace"))
            if record_memory:
                if replace:
                    memory_session.note_assistant_text(text, cumulative=cumulative, replace=True)
                else:
                    memory_session.note_assistant_text(text, cumulative=cumulative)
            turn_id = ""
            if recorder is not None:
                if replace:
                    turn_id = await recorder.note_assistant_text(text, cumulative=cumulative, replace=True)
                else:
                    turn_id = await recorder.note_assistant_text(text, cumulative=cumulative)
            payload: dict[str, Any] = {"text": text, "turn_id": turn_id}
            if cumulative:
                payload["cumulative"] = True
            if replace:
                payload["replace"] = True
            await self._send_event(websocket, "assistant_text", **payload)
            return
        if event_type == "assistant_audio":
            turn_id = ""
            first_audio_ms: int | None = None
            if recorder is not None:
                turn_id, first_audio_ms = await recorder.note_assistant_audio()
            payload = {
                "audio": str(event.get("audio", "")),
                "encoding": str(event.get("encoding", "pcm_s16le")),
                "sample_rate": int(event.get("sample_rate", 24000) or 24000),
                "turn_id": turn_id,
            }
            if first_audio_ms is not None:
                payload["first_audio_ms"] = first_audio_ms
            await self._send_event(websocket, "assistant_audio", **payload)
            return
        if event_type == "assistant_video_frame":
            await self._send_event(websocket, "assistant_video_frame",
                                   mime_type=event["mime_type"], data=event["data"])

    async def _emit_assistant_output(
        self,
        websocket: WebSocket,
        coordinator: InterruptionDecisionCoordinator,
        event: dict[str, Any],
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        record_memory: bool = True,
    ) -> None:
        async with coordinator.output_lock:
            if coordinator.pending is not None:
                coordinator.buffer_output(event)
                return
            await self._deliver_assistant_output(
                websocket,
                event,
                memory_session=memory_session,
                recorder=recorder,
                record_memory=record_memory,
            )

    async def _flush_interruption_output(
        self,
        websocket: WebSocket,
        coordinator: InterruptionDecisionCoordinator,
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        record_memory: bool = True,
    ) -> None:
        for event in coordinator.take_buffered_output():
            await self._deliver_assistant_output(
                websocket,
                dict(event),
                memory_session=memory_session,
                recorder=recorder,
                record_memory=record_memory,
            )

    async def _decide_interruption(
        self,
        websocket: WebSocket,
        coordinator: InterruptionDecisionCoordinator,
        text: str,
        *,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
        cancel_provider: Callable[[], Awaitable[None]] | None = None,
        resume_provider: Callable[[], Awaitable[None]] | None = None,
        record_memory: bool = True,
        expected_candidate_id: str = "",
        timeout_resolution: bool = False,
        provider_interrupted: bool = False,
    ) -> tuple[bool, dict[str, Any] | None]:
        async with coordinator.decision_lock:
            if expected_candidate_id and (
                coordinator.pending is None
                or coordinator.pending.candidate_id != expected_candidate_id
            ):
                return True, None
            decision = coordinator.decide(text, provider_interrupted=provider_interrupted)
            if decision is None:
                return True, None
            classification = str(decision.get("classification", ""))
            interrupted_turn_id = str(decision.get("interrupted_turn_id", ""))
            is_true_barge_in = classification == InterruptionIntent.TRUE_BARGE_IN.value
            decision["assistant_interrupted"] = is_true_barge_in
            decision["provider_cancel_requested"] = bool(is_true_barge_in and cancel_provider is not None)
            decision["tool_cancelled"] = bool(is_true_barge_in and tool_session.has_active_task)
            decision["stop_latency_ms"] = int(decision.get("decision_latency_ms", 0) or 0)
            decision["timeout_resolution"] = bool(timeout_resolution)
            try:
                if recorder is not None:
                    await recorder.record_session_event(
                        "interruption_decision",
                        source="interruption",
                        turn_id=interrupted_turn_id,
                        text=str(text or "").strip(),
                        payload=dict(decision),
                    )
                async with coordinator.output_lock:
                    if is_true_barge_in:
                        coordinator.discard_buffered_output()
                        coordinator.discard_deferred_terminal()
                        await self._send_event(websocket, "interruption_decision", **decision)
                        if cancel_provider is not None:
                            try:
                                await cancel_provider()
                            except Exception:
                                logger.exception(
                                    "provider_response_cancel_failed provider=%s turn_id=%s",
                                    decision.get("provider", ""),
                                    interrupted_turn_id,
                                )
                        await tool_session.cancel(
                            send_event=self._tool_event_sender(websocket, recorder),
                            reason="true_barge_in",
                        )
                        discard_memory_turn = getattr(memory_session, "discard_turn", None)
                        if callable(discard_memory_turn):
                            discard_memory_turn()
                        if recorder is not None:
                            await recorder.interrupt_current_turn()
                        await self._send_event(
                            websocket,
                            "interrupted",
                            candidate_id=str(decision.get("candidate_id", "")),
                            turn_id=interrupted_turn_id,
                            interrupted=True,
                            stop_latency_ms=decision["stop_latency_ms"],
                        )
                    else:
                        effective_resume_provider = resume_provider or coordinator.resume_provider
                        if effective_resume_provider is not None:
                            await effective_resume_provider()
                        await self._send_event(websocket, "interruption_decision", **decision)
                        await self._flush_interruption_output(
                            websocket,
                            coordinator,
                            memory_session=memory_session,
                            recorder=recorder,
                            record_memory=record_memory,
                        )
                return is_true_barge_in, decision
            finally:
                coordinator.complete_decision(timed_out=timeout_resolution)

    # -- shared client command handling ------------------------------------

    async def _handle_common_client_command(
        self,
        command_type: str,
        payload: dict[str, Any],
        *,
        websocket: WebSocket,
        memory_session: RealtimeMemorySession,
        tool_session: VoiceAgentToolSession,
        recorder: VoiceAgentSessionRecorder | None,
        interruption: InterruptionDecisionCoordinator,
        provider: str,
        record_memory: bool = True,
        finalize_on_timeout: bool = True,
    ) -> str | None:
        """Handle client→server commands shared across all providers.

        Returns ``"handled"`` if the command was processed (caller should
        ``continue``), ``"stop"`` if the session should end (caller should
        ``break``), or ``None`` if *command_type* is not a common command
        and the provider should handle it itself.
        """
        if command_type == "config":
            memory_session.configure(payload.get("memory"))
            # Fetch recent memories in the background so the first turn can
            # inject what earlier sessions discussed (see kickoff docstring).
            memory_session.kickoff_startup_context()
            await self._send_event(
                websocket,
                "memory_config",
                enabled=bool(memory_session._config.get_service()),
                scope=memory_session._config.memory_scope,
                group_id=memory_session._config.group_id,
            )
            return "handled"

        if command_type == "recall":
            query = str(payload.get("query", "") or "").strip()
            retrieval = await memory_session.recall_by_query(query)
            await self._send_event(
                websocket,
                "memory_context",
                memories_retrieved=int(retrieval.get("memories_retrieved", 0)),
                local_pending_count=int(retrieval.get("local_pending_count", 0)),
                cloud_count=int(retrieval.get("cloud_count", 0)),
                attempted=bool(retrieval.get("attempted", False)),
                explicit=True,
                query=query,
            )
            return "handled"

        if command_type == "coach_config":
            await self._apply_coach_config(websocket, payload, memory_session=memory_session, recorder=recorder)
            return "handled"

        if command_type == "ping":
            await self._send_event(websocket, "pong")
            return "handled"

        if command_type == "interruption_client_stopped":
            await self._record_client_interruption_stop(recorder, payload, provider=provider)
            return "handled"

        if command_type == "interruption_timeout" and interruption.pending is not None:
            timeout_candidate_id = str(payload.get("candidate_id", ""))
            if timeout_candidate_id and timeout_candidate_id != interruption.pending.candidate_id:
                return "handled"
            should_process_user, _ = await self._decide_interruption(
                websocket,
                interruption,
                "",
                memory_session=memory_session,
                tool_session=tool_session,
                recorder=recorder,
                record_memory=record_memory,
                expected_candidate_id=(timeout_candidate_id or interruption.pending.candidate_id),
                timeout_resolution=True,
            )
            if (
                not should_process_user
                and interruption.take_deferred_terminal() is not None
                and finalize_on_timeout
            ):
                await self._finalize_realtime_turn(
                    websocket,
                    memory_session,
                    recorder,
                    gated=tool_session.has_active_task,
                )
            return "handled"

        if command_type == "stop":
            await tool_session.cancel(
                send_event=self._tool_event_sender(websocket, recorder),
                reason="session_stopped",
            )
            return "stop"

        return None

    # -- tool event plumbing -----------------------------------------------

    def _tool_event_sender(
        self,
        websocket: WebSocket,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> Callable[[str, dict[str, Any]], Awaitable[None]]:
        async def send_tool_event(event_type: str, payload: dict[str, Any]) -> None:
            if recorder is not None:
                await recorder.record_tool_event(event_type, payload)
            await self._send_event(websocket, event_type, **payload)

        return send_tool_event

    async def _record_client_interruption_stop(
        self,
        recorder: VoiceAgentSessionRecorder | None,
        payload: dict[str, Any],
        *,
        provider: str,
    ) -> None:
        if recorder is None:
            return
        candidate_id = str(payload.get("candidate_id", "") or "").strip()
        turn_id = str(payload.get("turn_id", "") or "").strip()
        raw_latency = payload.get("stop_latency_ms")
        if not candidate_id or not isinstance(raw_latency, (int, float)):
            return
        await recorder.record_session_event(
            "interruption_client_stopped",
            source="metric",
            turn_id=turn_id,
            payload={
                "candidate_id": candidate_id,
                "provider": provider,
                "stop_latency_ms": max(0, min(int(raw_latency), 120_000)),
                "stage": "client_playback_stopped",
            },
        )

    # -- turn / memory finalization ----------------------------------------

    @staticmethod
    def _memory_note_event(memory_context: str) -> str:
        """OpenAI-style hidden user item carrying recalled memory."""
        return json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "Context note for personalization only. These long-term memories may help with "
                        "the user's next turn. Use them only when relevant, and do not mention this note.\n"
                        f"{memory_context}"
                    ),
                }],
            },
        })

    def _spawn_memory_lookup(
        self,
        websocket: WebSocket,
        memory_session: RealtimeMemorySession,
        user_text: str,
        *,
        provider: str,
        on_context: Callable[[str], Awaitable[None] | None],
        utterance_id: str = "",
    ) -> None:
        """Retrieve memory for a finished user turn without blocking the caller.

        Awaiting EverOS inline held the transcript and every provider event
        queued behind it for seconds. The caller emits the user transcript
        first; ``memory_context`` follows once the lookup lands, and
        ``on_context`` receives the context for the provider to inject.
        """

        async def run() -> None:
            try:
                retrieval = await memory_session.retrieve_memory_context(utterance_id, query=user_text)
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
                        "voice_memory_inject provider=%s scope=%s count=%s local_pending=%s cloud=%s",
                        provider,
                        memory_session._config.memory_scope,
                        memory_count,
                        local_pending_count,
                        cloud_count,
                    )
                    outcome = on_context(memory_context)
                    if asyncio.iscoroutine(outcome):
                        await outcome
            except Exception as exc:
                # The session may have closed while the lookup was in flight.
                logger.debug("voice_memory_lookup_skipped provider=%s: %s", provider, exc)

        spawn_background_task(run(), name=f"voice_memory_lookup_{provider}")

    async def _send_memory_write(
        self,
        websocket: WebSocket,
        memory_session: RealtimeMemorySession,
        memory_result: dict[str, Any],
    ) -> None:
        """Report a flushed turn's memory write, then its cloud outcome.

        flush_turn() only queues the cloud write, so the first event says
        "saving"; the real counts follow once EverOS answers, without holding
        turn completion (or the next turn's events) on the network.
        """

        async def send(result: dict[str, Any], **extra: Any) -> None:
            await self._send_event(
                websocket,
                "memory_write",
                **extra,
                attempted_count=int(result.get("attempted_count", 0)),
                saved_count=int(result.get("saved_count", 0)),
                failed_count=int(result.get("failed_count", 0)),
                local_pending_count=int(result.get("local_pending_count", 0)),
                reason=str(result.get("reason", "")),
            )

        await send(memory_result)
        take_persist_task = getattr(memory_session, "take_persist_task", None)
        task = take_persist_task() if callable(take_persist_task) else None
        if not isinstance(task, asyncio.Future):
            return

        async def report_outcome() -> None:
            try:
                outcome = await task
                await send(outcome, followup=True)
            except Exception as exc:
                # The client may have hung up while the write was in flight.
                logger.debug("voice_memory_write_followup_skipped: %s", exc)

        spawn_background_task(report_outcome(), name="voice_memory_write_followup")

    async def _finalize_realtime_turn(
        self,
        websocket: WebSocket,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        *,
        gated: bool = False,
    ) -> tuple[dict[str, Any], str]:
        memory_result = await memory_session.flush_turn()
        completed_turn_id = ""
        if recorder is not None and not gated:
            completed_turn_id = await recorder.complete_turn(memory_result)
        await self._send_memory_write(websocket, memory_session, memory_result)
        if not gated:
            await self._send_event(
                websocket,
                "turn_complete",
                turn_id=completed_turn_id,
                interrupted=False,
            )
        return memory_result, completed_turn_id

    # -- speaking coach ------------------------------------------------------

    MAX_COACH_REVIEWS_IN_FLIGHT = 2

    async def _apply_coach_config(
        self,
        websocket: WebSocket,
        payload: dict[str, Any],
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        """Handle the ``coach_config`` client command (shared by every provider).

        Reviews are triggered from ``memory_session.flush_turn()``, the one
        step every provider's turn-completion path goes through.
        """
        coach_config = normalize_coach_config(payload.get("coach"))
        coach_state = self._coach_state(websocket, create=True)
        if coach_state is not None:
            coach_state["config"] = coach_config

        def on_turn_flushed(user_text: str, assistant_text: str) -> None:
            self._schedule_coach_review(
                websocket, recorder, user_text=user_text, assistant_text=assistant_text, turn_id=""
            )

        memory_session.turn_listener = on_turn_flushed if coach_config else None
        await self._send_event(websocket, "coach_config", enabled=coach_config is not None, coach=coach_config)

    @staticmethod
    def _coach_state(websocket: WebSocket, *, create: bool = False) -> dict[str, Any] | None:
        """Per-connection coach state, kept on ``websocket.state``."""
        state = getattr(websocket, "state", None)
        if state is None:
            return None
        coach_state = getattr(state, "speaking_coach", None)
        if isinstance(coach_state, dict):
            return coach_state
        if not create:
            return None
        coach_state = {"config": None, "in_flight": 0, "previous_assistant_text": ""}
        try:
            state.speaking_coach = coach_state
        except Exception:
            return None
        return coach_state

    def _schedule_coach_review(
        self,
        websocket: WebSocket,
        recorder: VoiceAgentSessionRecorder | None,
        *,
        user_text: str,
        assistant_text: str,
        turn_id: str,
    ) -> None:
        coach_state = self._coach_state(websocket)
        if coach_state is None or not isinstance(coach_state.get("config"), dict):
            return
        # The tutor reply that *prompted* this utterance is the useful context.
        context = coach_state.get("previous_assistant_text", "")
        if assistant_text:
            coach_state["previous_assistant_text"] = assistant_text
        if not should_review(user_text):
            return
        if coach_state["in_flight"] >= self.MAX_COACH_REVIEWS_IN_FLIGHT:
            logger.info("speaking_coach review dropped: %d already in flight", coach_state["in_flight"])
            return
        coach_state["in_flight"] += 1
        task = asyncio.create_task(
            self._run_coach_review(
                websocket,
                coach_state,
                dict(coach_state["config"]),
                user_text=user_text,
                context=context,
                turn_id=turn_id,
                session_id=getattr(recorder, "session_id", "") or "",
            )
        )
        self._coach_tasks.add(task)
        task.add_done_callback(self._coach_tasks.discard)

    async def _run_coach_review(
        self,
        websocket: WebSocket,
        coach_state: dict[str, Any],
        config: dict[str, Any],
        *,
        user_text: str,
        context: str,
        turn_id: str,
        session_id: str,
    ) -> None:
        try:
            review = await self.speaking_coach.review(config, user_text, context)
            if review is None or review["verdict"] == "skip":
                return
            feedback_id = 0
            try:
                feedback_id = await run_db_call(
                    self.speaking_coach.repository.add,
                    review=review,
                    user_text=user_text,
                    config=config,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            except Exception:
                logger.exception("speaking_coach persist failed")
            await self._send_event(
                websocket,
                "coach_feedback",
                id=feedback_id,
                turn_id=turn_id,
                user_text=user_text,
                # Saved phrases keep the language they were practised in, even
                # if the learner switches practice language before saving.
                target_language=config["target_language"],
                **review,
            )
        except Exception as exc:
            # Socket closed or LLM failure: coaching is best-effort by design.
            logger.info("speaking_coach review failed: %s", exc)
        finally:
            coach_state["in_flight"] = max(0, coach_state["in_flight"] - 1)

    async def stream_doubao_session(
        self,
        websocket: WebSocket,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> None:
        recorder = await self._create_voice_session_recorder(
            provider="Doubao",
            model=model or DEFAULT_DOUBAO_REALTIME_MODEL,
            voice=voice or DEFAULT_DOUBAO_REALTIME_VOICE,
        )
        try:
            await self._run_doubao_session(
                websocket,
                model=model,
                voice=voice,
                instructions=instructions,
                recorder=recorder,
            )
        finally:
            if recorder is not None:
                await recorder.finish()


# ---------------------------------------------------------------------------
# Backward-compatible re-exports
# ---------------------------------------------------------------------------
# Tests and routers historically imported these names from this module.
# They are re-exported so that existing import paths keep working.

__all__ = [
    "RealtimeVoiceService",
    # constants
    "DEFAULT_DASHSCOPE_REALTIME_VOICE",
    "DEFAULT_GOOGLE_REALTIME_VOICE",
    "DEFAULT_OPENAI_REALTIME_VOICE",
    "DEFAULT_QWEN_AUDIO_REALTIME_VOICE",
    "DEFAULT_DOUBAO_REALTIME_VOICE",
    "DEFAULT_CARTESIA_REALTIME_VOICE",
    "DEFAULT_GRADIUM_REALTIME_VOICE",
    "DEFAULT_VERCEL_REALTIME_VOICE",
    "DEFAULT_STEPFUN_REALTIME_VOICE",
    "STEPFUN_REALTIME_VOICES",
    # re-exported from sibling modules (used by tests)
    "RealtimeMemorySession",
    "VoiceAgentSessionRecorder",
    "DashScopeRealtimeCallback",
    "DashScopeAudioRealtimeConversation",
    "_is_google_live_translate_model",
]
