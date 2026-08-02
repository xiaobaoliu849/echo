"""Realtime speech recognition via Qwen-Audio-3.0-ASR-Flash-Streaming / Fun-ASR-Realtime.

Implements the DashScope duplex WebSocket protocol:
  run-task -> task-started -> (binary audio frames | result-generated)*
  -> finish-task -> task-finished.

Docs: https://help.aliyun.com/zh/model-studio/fun-asr-realtime-websocket-api
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import websockets

from .config_loader import BackendConfig

logger = logging.getLogger(__name__)

QWEN_AUDIO_ASR_STREAMING_MODEL = "qwen-audio-3.0-asr-flash-streaming"
DEFAULT_STREAMING_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
# language_hints accepts at most 4 codes for this model family.
STREAMING_MAX_LANGUAGE_HINTS = 4
TASK_STARTED_TIMEOUT = 15.0


@dataclass(slots=True)
class RealtimeAsrSentence:
    """One result-generated sentence (interim or final)."""

    text: str
    sentence_end: bool
    begin_ms: int | None = None
    end_ms: int | None = None
    heartbeat: bool = False
    words: list[dict[str, Any]] = field(default_factory=list)

    def to_client_dict(self) -> dict[str, Any]:
        return {
            "type": "sentence",
            "text": self.text,
            "sentence_end": self.sentence_end,
            "begin_ms": self.begin_ms,
            "end_ms": self.end_ms,
            "words": self.words,
        }


def build_run_task_event(
    task_id: str,
    *,
    model: str = QWEN_AUDIO_ASR_STREAMING_MODEL,
    audio_format: str = "pcm",
    sample_rate: int = 16000,
    language_hints: list[str] | None = None,
    vocabulary: dict[str, int] | None = None,
    semantic_punctuation: bool | None = None,
    max_sentence_silence: int | None = None,
) -> dict[str, Any]:
    """Build the run-task client event (see fun-asr-client-events doc)."""
    parameters: dict[str, Any] = {
        "format": audio_format,
        "sample_rate": sample_rate,
    }
    if language_hints:
        parameters["language_hints"] = language_hints[:STREAMING_MAX_LANGUAGE_HINTS]
    if vocabulary:
        parameters["vocabulary"] = vocabulary
    if semantic_punctuation is not None:
        parameters["semantic_punctuation_enabled"] = bool(semantic_punctuation)
    if max_sentence_silence is not None:
        parameters["max_sentence_silence"] = int(max_sentence_silence)
    return {
        "header": {
            "action": "run-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            "model": model,
            "parameters": parameters,
            "input": {},
        },
    }


def build_finish_task_event(task_id: str) -> dict[str, Any]:
    return {
        "header": {
            "action": "finish-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {"input": {}},
    }


def parse_sentence(payload: dict[str, Any]) -> RealtimeAsrSentence | None:
    """Parse a result-generated payload into a RealtimeAsrSentence.

    Word timestamps are converted from ms to seconds, matching the sync
    transcription word model ({"text", "start", "end"}).
    Returns None for heartbeat events.
    """
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    sentence = output.get("sentence")
    if not isinstance(sentence, dict):
        return None
    if sentence.get("heartbeat"):
        return None

    words: list[dict[str, Any]] = []
    words_raw = sentence.get("words")
    if isinstance(words_raw, list):
        for item in words_raw:
            if not isinstance(item, dict):
                continue
            word_text = str(item.get("text", "")).strip()
            begin = item.get("begin_time")
            end = item.get("end_time")
            if word_text and begin is not None and end is not None:
                words.append({
                    "text": word_text,
                    "start": float(begin) / 1000.0,
                    "end": float(end) / 1000.0,
                })

    return RealtimeAsrSentence(
        text=str(sentence.get("text", "")),
        sentence_end=bool(sentence.get("sentence_end")),
        begin_ms=sentence.get("begin_time") if isinstance(sentence.get("begin_time"), int) else None,
        end_ms=sentence.get("end_time") if isinstance(sentence.get("end_time"), int) else None,
        heartbeat=bool(sentence.get("heartbeat")),
        words=words,
    )


class RealtimeAsrError(RuntimeError):
    """Raised when the upstream realtime ASR task fails."""


class QwenAudioStreamingAsrSession:
    """One duplex WebSocket session against the Fun-ASR-Realtime service."""

    def __init__(
        self,
        api_key: str,
        *,
        ws_url: str = DEFAULT_STREAMING_WS_URL,
        model: str = QWEN_AUDIO_ASR_STREAMING_MODEL,
        sample_rate: int = 16000,
        language_hints: list[str] | None = None,
        vocabulary: dict[str, int] | None = None,
        semantic_punctuation: bool | None = None,
        max_sentence_silence: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._ws_url = ws_url
        self._model = model
        self._sample_rate = sample_rate
        self._language_hints = language_hints
        self._vocabulary = vocabulary
        self._semantic_punctuation = semantic_punctuation
        self._max_sentence_silence = max_sentence_silence
        self._task_id = uuid.uuid4().hex
        self._ws: Any = None

    async def start(self) -> None:
        """Connect, send run-task and wait for task-started."""
        self._ws = await websockets.connect(
            self._ws_url,
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
            max_size=None,
        )
        run_task = build_run_task_event(
            self._task_id,
            model=self._model,
            sample_rate=self._sample_rate,
            language_hints=self._language_hints,
            vocabulary=self._vocabulary,
            semantic_punctuation=self._semantic_punctuation,
            max_sentence_silence=self._max_sentence_silence,
        )
        await self._ws.send(json.dumps(run_task, ensure_ascii=False))

        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=TASK_STARTED_TIMEOUT)
        except asyncio.TimeoutError as exc:
            await self.close()
            raise RealtimeAsrError("Realtime ASR task start timed out.") from exc

        message = json.loads(raw) if isinstance(raw, str) else {}
        event = str(message.get("header", {}).get("event", ""))
        if event == "task-started":
            return
        if event == "task-failed":
            error_message = str(message.get("header", {}).get("error_message", "task-failed"))
            await self.close()
            raise RealtimeAsrError(f"Realtime ASR task failed to start: {error_message}")
        await self.close()
        raise RealtimeAsrError(f"Unexpected realtime ASR handshake event: {event or raw!r}")

    async def send_audio(self, chunk: bytes) -> None:
        """Send one binary PCM frame (mono, configured sample rate)."""
        if self._ws is None:
            raise RealtimeAsrError("Realtime ASR session not started.")
        if chunk:
            await self._ws.send(chunk)

    async def finish(self) -> None:
        """Send finish-task; results continue until task-finished."""
        if self._ws is None:
            return
        await self._ws.send(json.dumps(build_finish_task_event(self._task_id)))

    async def events(self) -> AsyncIterator[RealtimeAsrSentence]:
        """Yield sentences until the task finishes or fails."""
        if self._ws is None:
            raise RealtimeAsrError("Realtime ASR session not started.")
        async for raw in self._ws:
            if not isinstance(raw, str):
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            header = message.get("header", {})
            if not isinstance(header, dict):
                continue
            event = str(header.get("event", ""))
            if event == "result-generated":
                payload = message.get("payload", {})
                sentence = parse_sentence(payload if isinstance(payload, dict) else {})
                if sentence is not None:
                    yield sentence
            elif event == "task-finished":
                return
            elif event == "task-failed":
                error_message = str(header.get("error_message", "unknown error"))
                raise RealtimeAsrError(f"Realtime ASR task failed: {error_message}")
        # Connection closed without task-finished.

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass


def build_streaming_asr_session(
    config: BackendConfig,
    *,
    language_hints: list[str] | None = None,
    vocabulary: dict[str, int] | None = None,
    semantic_punctuation: bool | None = None,
    max_sentence_silence: int | None = None,
) -> QwenAudioStreamingAsrSession:
    """Factory: resolve API key + WS URL from config and build a session."""
    config.reload()
    api_keys = config.get_all().get("api_keys", {})
    api_key = str(api_keys.get("dashscope_api_key", "")).strip()
    if not api_key:
        raise ValueError("DashScope API key not configured.")

    base_url = config.get_provider_settings("DashScope").get("base_url", "").strip()
    ws_url = DEFAULT_STREAMING_WS_URL
    if base_url:
        host = base_url
        for prefix in ("https://", "http://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
                break
        host = host.split("/")[0]
        if host:
            ws_url = f"wss://{host}/api-ws/v1/inference"

    return QwenAudioStreamingAsrSession(
        api_key,
        ws_url=ws_url,
        language_hints=language_hints,
        vocabulary=vocabulary,
        semantic_punctuation=semantic_punctuation,
        max_sentence_silence=max_sentence_silence,
    )
