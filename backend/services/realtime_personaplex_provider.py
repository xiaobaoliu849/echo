"""PersonaPlex realtime voice provider mixin (local moshi server).

PersonaPlex is NVIDIA's full-duplex speech-to-speech model.  Unlike the cloud
providers in this package it runs locally against a ``moshi.server`` instance,
and it differs from them in three ways that shape this module:

* **Full duplex is native.**  The model listens while it speaks and handles
  barge-in internally, so this provider deliberately bypasses
  ``InterruptionDecisionCoordinator``.  Running our application-level
  arbitration on top would fight the model.
* **No function calling.**  The architecture has no tool-call channel, so
  ``search_web`` and memory injection are not available here.  The session is
  positioned as an English conversation partner, not a general assistant.
* **English only.**  The base Moshi/Helium backbone was trained on English.

Transport is the moshi server WebSocket at ``/api/chat``:

  client -> server   b"\\x01" + opus bytes     (user audio)
  server -> client   b"\\x01" + opus bytes     (agent audio)
                     b"\\x02" + utf-8 text     (agent text token)

Audio is Opus at the model sample rate (24 kHz); the browser sends PCM16 at
16 kHz, so both directions are resampled here.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from fastapi import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:  # numpy is optional at runtime — see the note below.
    import numpy as np

from .realtime_constants import (
    DEFAULT_PERSONAPLEX_REALTIME_MODEL,
    DEFAULT_PERSONAPLEX_REALTIME_VOICE,
    DEFAULT_PERSONAPLEX_SERVER_URL,
    PERSONAPLEX_REALTIME_INSTRUCTIONS,
    PERSONAPLEX_REALTIME_VOICES,
    PERSONAPLEX_SAMPLE_RATE,
)
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder

logger = logging.getLogger(__name__)

# The browser captures at 16 kHz; the model runs at 24 kHz.  Only the inbound
# direction needs resampling — ``playAssistantAudio`` builds its AudioBuffer at
# whatever ``sample_rate`` we report, so agent audio goes back out at 24 kHz
# untouched.
CLIENT_SAMPLE_RATE = 16000
# sphn accepts only exact Opus frame sizes (120/240/480/960/1920/2880 samples).
# 1920 @ 24 kHz is 80 ms — the model's own frame budget, so one Opus frame maps
# to one Mimi frame.
OPUS_FRAME_SIZE = 1920
_MSG_AUDIO = 1
_MSG_TEXT = 2
# How long the agent's text-token stream must stay quiet before we call the
# turn finished.  The model runs at 12.5 frames/s (80 ms per frame), so this is
# roughly 10 silent frames — long enough to survive natural pauses mid-sentence,
# short enough that the transcript commits promptly.
TURN_IDLE_TIMEOUT_S = 0.8


def _numpy():
    """Import numpy on first use.

    PersonaPlex is an optional local provider, but this module is imported
    unconditionally by the RealtimeVoiceService facade.  A top-level numpy
    import would therefore make an optional dependency mandatory for the whole
    backend to boot; deferring it keeps the failure scoped to this provider,
    where stream_personaplex_session reports it as a normal error event.
    """
    import numpy as np

    return np


def _resample_linear(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear resample for float32 mono audio.

    Good enough for speech at these rates and dependency-free, which matters
    because this path must not drag extra native wheels into the backend.
    """
    np = _numpy()
    if src_rate == dst_rate or pcm.size == 0:
        return pcm
    duration = pcm.shape[-1] / float(src_rate)
    dst_len = int(round(duration * dst_rate))
    if dst_len <= 0:
        return np.zeros(0, dtype=np.float32)
    src_idx = np.linspace(0.0, pcm.shape[-1] - 1, num=dst_len, dtype=np.float64)
    return np.interp(src_idx, np.arange(pcm.shape[-1]), pcm).astype(np.float32)


def _pcm16_to_float(raw: bytes) -> np.ndarray:
    np = _numpy()
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _float_to_pcm16(pcm: np.ndarray) -> bytes:
    np = _numpy()
    clipped = np.clip(pcm, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


class PersonaPlexRealtimeMixin:
    """PersonaPlex (local moshi server) provider methods for RealtimeVoiceService."""

    def _resolve_personaplex_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("PersonaPlex", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_PERSONAPLEX_REALTIME_MODEL
        server_url = (
            str(provider_settings.get("realtime_base_url", "")).strip()
            or str(provider_settings.get("base_url", "")).strip()
            or DEFAULT_PERSONAPLEX_SERVER_URL
        ).rstrip("/")
        if not server_url.startswith(("ws://", "wss://")):
            raise RuntimeError(
                "PersonaPlex 服务地址需为 WebSocket 地址，例如 ws://127.0.0.1:8998。"
                "请先在本地启动 moshi.server，再在设置中填写该地址。"
            )
        return {"model": resolved_model, "server_url": server_url}

    @staticmethod
    def _normalize_personaplex_voice(voice: str | None) -> str:
        candidate = str(voice or "").strip()
        if not candidate:
            return DEFAULT_PERSONAPLEX_REALTIME_VOICE
        if not candidate.endswith(".pt"):
            candidate = f"{candidate}.pt"
        if candidate not in PERSONAPLEX_REALTIME_VOICES:
            return DEFAULT_PERSONAPLEX_REALTIME_VOICE
        return candidate

    async def _client_to_personaplex_loop(
        self,
        websocket: WebSocket,
        upstream: Any,
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        opus_writer: Any,
    ) -> None:
        """Forward browser PCM16@16k to the moshi server as Opus@24k."""
        np = _numpy()
        # sphn only accepts exact Opus frame sizes, but browser chunks resample
        # to arbitrary lengths, so carry the remainder across iterations.
        carry = np.zeros(0, dtype=np.float32)

        async def encode_and_send(pcm: np.ndarray) -> None:
            nonlocal carry
            carry = np.concatenate((carry, pcm)) if carry.size else pcm
            while carry.shape[0] >= OPUS_FRAME_SIZE:
                opus_writer.append_pcm(carry[:OPUS_FRAME_SIZE])
                carry = carry[OPUS_FRAME_SIZE:]
                chunk = opus_writer.read_bytes()
                if chunk:
                    await upstream.send_bytes(bytes([_MSG_AUDIO]) + chunk)

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

                # PersonaPlex has no tool channel and no interruption arbitration,
                # so only the transport-level commands apply here.
                if command_type == "config":
                    memory_session.configure(payload.get("memory"))
                    await self._send_event(
                        websocket,
                        "memory_config",
                        enabled=False,
                        scope="",
                        group_id="",
                        message="PersonaPlex 为本地全双工模型，暂不支持长期记忆与工具调用。",
                    )
                    continue
                if command_type == "ping":
                    await self._send_event(websocket, "pong")
                    continue
                if command_type == "stop":
                    break
                # interruption_* commands are intentionally ignored: the model
                # arbitrates barge-in itself.
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                pcm = _pcm16_to_float(audio_bytes)
                await encode_and_send(
                    _resample_linear(pcm, CLIENT_SAMPLE_RATE, PERSONAPLEX_SAMPLE_RATE)
                )

    async def _personaplex_to_client_loop(
        self,
        websocket: WebSocket,
        upstream: Any,
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
        opus_reader: Any,
    ) -> None:
        """Forward moshi Opus@24k + text tokens back to the browser."""
        import aiohttp

        np = _numpy()

        pending_text: list[str] = []
        # Full-duplex models emit no explicit end-of-turn marker, but they only
        # produce text tokens while the agent is actually speaking.  A gap in
        # that stream is therefore the turn boundary, and the frontend needs a
        # turn_complete to commit the transcript.
        turn_open = False
        idle_task: asyncio.Task[None] | None = None

        async def flush_text() -> None:
            if not pending_text:
                return
            text = "".join(pending_text).strip()
            pending_text.clear()
            if not text:
                return
            # Delivered directly rather than through _emit_assistant_output:
            # there is no InterruptionDecisionCoordinator in this mode.
            await self._deliver_assistant_output(
                websocket,
                {"type": "assistant_text", "text": text},
                memory_session=memory_session,
                recorder=recorder,
            )

        async def close_turn() -> None:
            nonlocal turn_open
            if not turn_open:
                return
            turn_open = False
            await flush_text()
            await self._finalize_realtime_turn(websocket, memory_session, recorder)

        async def close_turn_when_idle() -> None:
            try:
                await asyncio.sleep(TURN_IDLE_TIMEOUT_S)
            except asyncio.CancelledError:
                return
            await close_turn()

        def restart_idle_timer() -> None:
            nonlocal idle_task
            if idle_task is not None:
                idle_task.cancel()
            idle_task = asyncio.create_task(close_turn_when_idle())

        async for message in upstream:
            if message.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.ERROR,
            ):
                break
            if message.type != aiohttp.WSMsgType.BINARY:
                continue
            data = message.data
            if not isinstance(data, bytes) or not data:
                continue

            kind = data[0]
            if kind == _MSG_AUDIO:
                opus_reader.append_bytes(data[1:])
                pcm = opus_reader.read_pcm()
                if pcm is None or len(pcm) == 0:
                    continue
                await self._deliver_assistant_output(
                    websocket,
                    {
                        "type": "assistant_audio",
                        "audio": base64.b64encode(
                            _float_to_pcm16(np.asarray(pcm, dtype=np.float32))
                        ).decode("ascii"),
                        "encoding": "pcm_s16le",
                        "sample_rate": PERSONAPLEX_SAMPLE_RATE,
                    },
                    memory_session=memory_session,
                    recorder=recorder,
                )
            elif kind == _MSG_TEXT:
                piece = data[1:].decode("utf-8", errors="replace")
                pending_text.append(piece)
                turn_open = True
                restart_idle_timer()
                # Flush on sentence boundaries so the transcript stays readable
                # without emitting one event per token.
                if piece.strip().endswith((".", "!", "?", "…")):
                    await flush_text()

        if idle_task is not None:
            idle_task.cancel()
        await close_turn()

    async def stream_personaplex_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_PERSONAPLEX_REALTIME_VOICE,
        instructions: str | None = None,
    ) -> None:
        try:
            import aiohttp
            import numpy  # noqa: F401 - presence check; used lazily via _numpy()
            import sphn
        except ImportError as exc:  # pragma: no cover - depends on local install
            # Name the running interpreter explicitly.  A machine can easily have
            # several (conda, a project venv, the desktop launcher's pick), and
            # "install it in the backend environment" sends people to the wrong
            # one -- the install succeeds and the error stays.
            import sys

            await self._send_event(
                websocket,
                "error",
                message=(
                    f"PersonaPlex 依赖未安装：{exc}。"
                    f'请对当前后端解释器执行：\n"{sys.executable}" '
                    "-m pip install -r backend/requirements-personaplex.txt"
                ),
            )
            return

        try:
            settings = self._resolve_personaplex_settings(model)
        except RuntimeError as exc:
            await self._send_event(websocket, "error", message=str(exc))
            return

        resolved_voice = self._normalize_personaplex_voice(voice)
        text_prompt = (instructions or "").strip() or PERSONAPLEX_REALTIME_INSTRUCTIONS

        memory_session = RealtimeMemorySession()
        recorder = await self._create_voice_session_recorder(
            provider="PersonaPlex",
            model=settings["model"],
            voice=resolved_voice,
        )

        query = urlencode({"text_prompt": text_prompt, "voice_prompt": resolved_voice})
        ws_url = f"{settings['server_url']}/api/chat?{query}"

        opus_writer = sphn.OpusStreamWriter(PERSONAPLEX_SAMPLE_RATE)
        opus_reader = sphn.OpusStreamReader(PERSONAPLEX_SAMPLE_RATE)

        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(ws_url, max_msg_size=2**24) as upstream:
                    # Wait for moshi.server's b"\x00" handshake confirming system prompt stepping is done
                    handshake_msg = await upstream.receive()
                    if handshake_msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        raise RuntimeError("moshi.server 在初始化握手前关闭了连接。")

                    await self._send_event(
                        websocket,
                        "session_open",
                        provider="PersonaPlex",
                        model=settings["model"],
                        voice=resolved_voice,
                        session_id=recorder.session_id if recorder is not None else "",
                    )
                    send_task = asyncio.create_task(
                        self._client_to_personaplex_loop(
                            websocket,
                            upstream,
                            memory_session=memory_session,
                            recorder=recorder,
                            opus_writer=opus_writer,
                        )
                    )
                    receive_task = asyncio.create_task(
                        self._personaplex_to_client_loop(
                            websocket,
                            upstream,
                            memory_session=memory_session,
                            recorder=recorder,
                            opus_reader=opus_reader,
                        )
                    )
                    await self._run_duplex_tasks(send_task, receive_task)
        except WebSocketDisconnect:
            return
        except aiohttp.ClientError as exc:
            logger.warning("personaplex_connect_failed url=%s err=%s", ws_url, exc)
            await self._send_event(
                websocket,
                "error",
                message=(
                    f"无法连接本地 PersonaPlex 服务（{settings['server_url']}）：{exc}。"
                    "请确认 moshi.server 已启动。"
                ),
            )
            return
        except Exception as exc:
            logger.exception("PersonaPlex realtime session failed: %s", exc)
            await self._send_event(websocket, "error", message=f"PersonaPlex 实时会话失败: {exc}")
            return
        finally:
            # The receive loop already finalizes each turn; this only catches a
            # turn that was still open when the session dropped.  flush_turn()
            # is a no-op when there is nothing pending.
            memory_result = await memory_session.flush_turn()
            if recorder is not None:
                await recorder.complete_turn(memory_result)
            await memory_session.drain()
            if recorder is not None:
                await recorder.finish()
