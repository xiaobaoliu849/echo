"""GLM-4-Voice local realtime provider mixin for VoiceSpirit.

Integrates Zhipu GLM-4-Voice (9B) local realtime speech-to-speech engine.
Applies the provider-neutral WebSocket contract used by the frontend.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    import numpy as np

from .realtime_constants import (
    DEFAULT_GLM4VOICE_REALTIME_MODEL,
    DEFAULT_GLM4VOICE_REALTIME_VOICE,
    DEFAULT_GLM4VOICE_SERVER_URL,
    GLM4VOICE_REALTIME_INSTRUCTIONS,
)
from .realtime_memory_session import RealtimeMemorySession
from .realtime_session_recorder import VoiceAgentSessionRecorder

logger = logging.getLogger(__name__)

CLIENT_SAMPLE_RATE = 16000
GLM4VOICE_SAMPLE_RATE = 22050
_MSG_AUDIO = 1
_MSG_TEXT = 2
TURN_IDLE_TIMEOUT_S = 0.8


def _numpy():
    import numpy as np
    return np


def _pcm16_to_float(data: bytes) -> np.ndarray:
    np = _numpy()
    if not data:
        return np.zeros(0, dtype=np.float32)
    s16 = np.frombuffer(data, dtype=np.int16)
    return s16.astype(np.float32) / 32768.0


def _float_to_pcm16(data: np.ndarray) -> bytes:
    np = _numpy()
    if data.size == 0:
        return b""
    clipped = np.clip(data, -1.0, 1.0)
    s16 = (clipped * 32767.0).astype(np.int16)
    return s16.tobytes()


def _resample_linear(
    audio: np.ndarray, orig_sr: int, target_sr: int
) -> np.ndarray:
    np = _numpy()
    if audio.size == 0 or orig_sr == target_sr:
        return audio
    duration = audio.shape[0] / float(orig_sr)
    target_num_samples = int(round(duration * target_sr))
    if target_num_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=audio.shape[0], endpoint=True)
    x_new = np.linspace(0.0, 1.0, num=target_num_samples, endpoint=True)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class RealtimeGlm4VoiceMixin:
    """FastAPI mixin for proxying browser audio to local GLM-4-Voice server."""

    def _resolve_glm4voice_url(self, settings: dict[str, Any]) -> str:
        base = settings.get("realtime_base_url") or DEFAULT_GLM4VOICE_SERVER_URL
        if not base.startswith("ws://") and not base.startswith("wss://"):
            base = f"ws://{base}"
        return base.rstrip("/")

    def _resolve_glm4voice_settings(self, model: str | None) -> dict[str, str]:
        provider_settings = self.config.get_provider_settings("GLM4Voice", model)
        resolved_model = provider_settings["model"].strip() or DEFAULT_GLM4VOICE_REALTIME_MODEL
        server_url = (
            str(provider_settings.get("realtime_base_url", "")).strip()
            or str(provider_settings.get("base_url", "")).strip()
            or DEFAULT_GLM4VOICE_SERVER_URL
        )
        return {
            "model": resolved_model,
            "realtime_base_url": self._resolve_glm4voice_url({"realtime_base_url": server_url}),
        }

    async def _client_to_glm4voice_loop(
        self,
        websocket: WebSocket,
        upstream: Any,
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        np = _numpy()

        async def encode_and_send(pcm: np.ndarray) -> None:
            # Raw PCM16 at the local server's native sample rate (22050 Hz).
            await upstream.send_bytes(bytes([_MSG_AUDIO]) + _float_to_pcm16(pcm))

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

                if command_type == "config":
                    memory_session.configure(payload.get("memory"))
                    await self._send_event(
                        websocket,
                        "memory_config",
                        enabled=False,
                        scope="",
                        group_id="",
                        message="GLM-4-Voice 为本地端到端模型，暂不支持工具调用。",
                    )
                    continue
                if command_type == "ping":
                    await self._send_event(websocket, "pong")
                    continue
                if command_type == "stop":
                    break
                continue

            audio_bytes = message.get("bytes")
            if audio_bytes:
                pcm = _pcm16_to_float(audio_bytes)
                await encode_and_send(
                    _resample_linear(pcm, CLIENT_SAMPLE_RATE, GLM4VOICE_SAMPLE_RATE)
                )

    async def _glm4voice_to_client_loop(
        self,
        websocket: WebSocket,
        upstream: Any,
        *,
        memory_session: RealtimeMemorySession,
        recorder: VoiceAgentSessionRecorder | None,
    ) -> None:
        import aiohttp

        np = _numpy()
        pending_text: list[str] = []
        turn_open = False
        idle_task: asyncio.Task[None] | None = None

        async def flush_text() -> None:
            if not pending_text:
                return
            text = "".join(pending_text).strip()
            pending_text.clear()
            if not text:
                return
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
                pcm_bytes = data[1:]
                if not pcm_bytes:
                    continue
                await self._deliver_assistant_output(
                    websocket,
                    {
                        "type": "assistant_audio",
                        "audio": base64.b64encode(pcm_bytes).decode("ascii"),
                        "encoding": "pcm_s16le",
                        "sample_rate": GLM4VOICE_SAMPLE_RATE,
                    },
                    memory_session=memory_session,
                    recorder=recorder,
                )
            elif kind == _MSG_TEXT:
                piece = data[1:].decode("utf-8", errors="replace")
                pending_text.append(piece)
                turn_open = True
                restart_idle_timer()
                if piece.strip().endswith((".", "!", "?", "…", "。", "！", "？")):
                    await flush_text()

        if idle_task is not None:
            idle_task.cancel()
        await close_turn()

    async def stream_glm4voice_session(
        self,
        websocket: WebSocket,
        *,
        model: str | None = None,
        voice: str = DEFAULT_GLM4VOICE_REALTIME_VOICE,
        instructions: str | None = None,
    ) -> None:
        import aiohttp

        try:
            settings = self._resolve_glm4voice_settings(model)
        except RuntimeError as exc:
            await self._send_event(websocket, "error", message=str(exc))
            return

        base_url = settings["realtime_base_url"]
        text_prompt = (instructions or "").strip() or GLM4VOICE_REALTIME_INSTRUCTIONS
        ws_url = (
            f"{base_url}"
            f"?text_prompt={aiohttp.helpers.quote(text_prompt)}"
            f"&voice_prompt={aiohttp.helpers.quote(voice)}"
        )

        memory_session = RealtimeMemorySession()
        recorder = await self._create_voice_session_recorder(
            provider="GLM4Voice",
            model=settings["model"],
            voice=voice,
        )

        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(ws_url, max_msg_size=2**24) as upstream:
                    # Wait for handshake indicating system prompt setup completion
                    handshake_msg = await upstream.receive()
                    if handshake_msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        raise RuntimeError("GLM-4-Voice 服务在初始化握手前关闭了连接。")

                    await self._send_event(
                        websocket,
                        "session_open",
                        provider="GLM4Voice",
                        model=settings["model"],
                        voice=voice,
                        session_id=recorder.session_id if recorder is not None else "",
                    )
                    send_task = asyncio.create_task(
                        self._client_to_glm4voice_loop(
                            websocket,
                            upstream,
                            memory_session=memory_session,
                            recorder=recorder,
                        )
                    )
                    receive_task = asyncio.create_task(
                        self._glm4voice_to_client_loop(
                            websocket,
                            upstream,
                            memory_session=memory_session,
                            recorder=recorder,
                        )
                    )
                    await self._run_duplex_tasks(send_task, receive_task)

        except WebSocketDisconnect:
            return
        except (aiohttp.ClientError, OSError) as exc:
            logger.warning("glm4voice_connect_failed url=%s err=%s", ws_url, exc)
            await self._send_event(
                websocket,
                "error",
                message=(
                    f"无法连接本地 GLM-4-Voice 服务（{base_url}）：{exc}。"
                    "请确认已双击运行 run_glm4voice_server.bat，且该服务支持 WebSocket 语音对语音协议。"
                ),
            )
            return
        except Exception as exc:
            logger.exception("GLM-4-Voice realtime session failed: %s", exc)
            await self._send_event(websocket, "error", message=f"GLM-4-Voice 实时会话失败: {exc}")
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
