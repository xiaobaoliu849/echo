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

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None

from .config_loader import BackendConfig

logger = logging.getLogger(__name__)

GEMINI_TRANSCRIBE_LIVE_MODEL = "gemini-3.5-transcribe-live"
QWEN_AUDIO_ASR_STREAMING_MODEL = "qwen-audio-3.0-asr-flash-streaming"
FUN_ASR_REALTIME_MODEL = "fun-asr-realtime"
DEFAULT_STREAMING_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
# language_hints accepts at most 4 codes for this model family.
STREAMING_MAX_LANGUAGE_HINTS = 4
TASK_STARTED_TIMEOUT = 15.0

# Realtime streaming models selectable from the transcription UI, mapped to the
# max language_hints each accepts.
STREAMING_MODEL_LANGUAGE_HINT_CAPS = {
    GEMINI_TRANSCRIBE_LIVE_MODEL: 4,
    QWEN_AUDIO_ASR_STREAMING_MODEL: 4,
    FUN_ASR_REALTIME_MODEL: 1,
}


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


def _is_cjk_char(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch[0])
    return (
        0x3000 <= cp <= 0x303F
        or 0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF
        or 0xAC00 <= cp <= 0xD7AF
        or 0xFF00 <= cp <= 0xFFEF
    )


def _merge_streaming_delta(current: str, delta: str) -> str:
    """Merge a streaming delta into accumulated text with language-aware spacing."""
    if not delta:
        return current
    if not current:
        return delta
    if current[-1].isspace() or delta[0].isspace():
        return current + delta
    if _is_cjk_char(current[-1]) or _is_cjk_char(delta[0]):
        return current + delta
    return current + " " + delta


class GoogleStreamingAsrSession:
    """One duplex session against Google Gemini 3.5 Transcribe Live."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "",
        model: str = GEMINI_TRANSCRIBE_LIVE_MODEL,
        sample_rate: int = 16000,
        language_hints: list[str] | None = None,
        vocabulary: dict[str, int] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._sample_rate = sample_rate
        self._language_hints = language_hints
        self._vocabulary = vocabulary
        self._client: Any = None
        self._session_ctx: Any = None
        self._session: Any = None
        self._task_queue: asyncio.Queue[RealtimeAsrSentence | None] = asyncio.Queue()
        self._receive_task: asyncio.Task | None = None
        self._closed = False
        self._finished = False
        self._accumulated_text = ""

    async def start(self) -> None:
        """Connect to Google Gemini Live API."""
        if genai is None or types is None:
            raise RealtimeAsrError("Google GenAI SDK (google-genai) is not installed.")
        if not self._api_key:
            raise ValueError("Google API key not configured. Set google_api_key in Settings.")

        http_options: dict[str, str] = {"api_version": "v1beta"}
        if self._base_url and self._base_url != "https://generativelanguage.googleapis.com/v1beta":
            http_options["base_url"] = self._base_url

        self._client = genai.Client(api_key=self._api_key, http_options=http_options)
        live_config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

        try:
            self._session_ctx = self._client.aio.live.connect(model=self._model, config=live_config)
            self._session = await self._session_ctx.__aenter__()
        except Exception as exc:
            await self.close()
            raise RealtimeAsrError(f"Google Gemini Transcribe Live session failed to start: {exc}") from exc

        self._receive_task = asyncio.create_task(self._listen_upstream())

    async def _listen_upstream(self) -> None:
        try:
            while not self._closed and self._session is not None:
                turn = self._session.receive()
                async for response in turn:
                    server_content = getattr(response, "server_content", None)
                    if server_content is not None:
                        transcript_chunk = ""
                        for field_name in ("input_transcription", "input_audio_transcription", "transcription"):
                            if hasattr(server_content, field_name):
                                val = getattr(server_content, field_name)
                                if val is not None:
                                    if isinstance(val, str):
                                        transcript_chunk = val
                                    elif hasattr(val, "text") and getattr(val, "text"):
                                        transcript_chunk = str(getattr(val, "text"))
                                    elif isinstance(val, dict) and val.get("text"):
                                        transcript_chunk = str(val.get("text"))
                                    break

                        response_text = getattr(response, "text", "") or ""
                        delta = transcript_chunk or response_text
                        if delta:
                            self._accumulated_text = _merge_streaming_delta(self._accumulated_text, delta)
                            is_end = bool(
                                getattr(server_content, "turn_complete", False)
                                or getattr(getattr(server_content, "input_transcription", None), "finished", False)
                            )
                            if is_end:
                                sentence = RealtimeAsrSentence(
                                    text=self._accumulated_text.strip(),
                                    sentence_end=True,
                                )
                                self._accumulated_text = ""
                                await self._task_queue.put(sentence)
                            else:
                                sentence = RealtimeAsrSentence(
                                    text=self._accumulated_text.strip(),
                                    sentence_end=False,
                                )
                                await self._task_queue.put(sentence)
                        elif getattr(server_content, "turn_complete", False) and self._accumulated_text.strip():
                            sentence = RealtimeAsrSentence(
                                text=self._accumulated_text.strip(),
                                sentence_end=True,
                            )
                            self._accumulated_text = ""
                            await self._task_queue.put(sentence)
                    else:
                        response_text = getattr(response, "text", "") or ""
                        if response_text:
                            self._accumulated_text = _merge_streaming_delta(self._accumulated_text, response_text)
                            await self._task_queue.put(
                                RealtimeAsrSentence(
                                    text=self._accumulated_text.strip(),
                                    sentence_end=False,
                                )
                            )
                if self._finished:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Google Gemini Live stream receive exception: %s", exc)
        finally:
            if self._accumulated_text.strip():
                try:
                    await self._task_queue.put(
                        RealtimeAsrSentence(
                            text=self._accumulated_text.strip(),
                            sentence_end=True,
                        )
                    )
                    self._accumulated_text = ""
                except Exception:
                    pass
            await self._task_queue.put(None)

    async def send_audio(self, chunk: bytes) -> None:
        """Send one binary PCM frame (mono, configured sample rate)."""
        if self._session is None or self._closed:
            raise RealtimeAsrError("Realtime ASR session not started.")
        if chunk and types is not None:
            await self._session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={self._sample_rate}")
            )

    async def finish(self) -> None:
        """Signal finish/end of audio."""
        self._finished = True
        if self._session is not None and not self._closed:
            try:
                if hasattr(self._session, "send"):
                    await self._session.send(end_of_turn=True)
            except Exception:
                pass

    async def events(self) -> AsyncIterator[RealtimeAsrSentence]:
        """Yield sentences until the session completes or errors."""
        while True:
            item = await self._task_queue.get()
            if item is None:
                break
            yield item

    async def close(self) -> None:
        self._closed = True
        if self._receive_task is not None:
            self._receive_task.cancel()
            self._receive_task = None
        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_ctx = None
            self._session = None
        if self._accumulated_text.strip():
            try:
                await self._task_queue.put(
                    RealtimeAsrSentence(
                        text=self._accumulated_text.strip(),
                        sentence_end=True,
                    )
                )
                self._accumulated_text = ""
            except Exception:
                pass
        await self._task_queue.put(None)


def _is_google_streaming_asr_model(model: str | None) -> bool:
    m = str(model or "").strip().lower()
    return m == GEMINI_TRANSCRIBE_LIVE_MODEL.lower() or m.startswith("gemini-") or m in {"google", "gemini"}


def build_streaming_asr_session(
    config: BackendConfig,
    *,
    language_hints: list[str] | None = None,
    vocabulary: dict[str, int] | None = None,
    semantic_punctuation: bool | None = None,
    max_sentence_silence: int | None = None,
    model: str | None = None,
) -> QwenAudioStreamingAsrSession | GoogleStreamingAsrSession:
    """Factory: resolve API key + WS URL from config and build a session."""
    config.reload()
    api_keys = config.get_all().get("api_keys", {})
    resolved_model = model or QWEN_AUDIO_ASR_STREAMING_MODEL

    if _is_google_streaming_asr_model(resolved_model):
        api_key = str(api_keys.get("google_api_key", "")).strip()
        if not api_key:
            raise ValueError("Google API key not configured. Set google_api_key in Settings.")
        base_url = config.get_provider_settings("Google").get("base_url", "").strip()
        hint_cap = STREAMING_MODEL_LANGUAGE_HINT_CAPS.get(resolved_model, STREAMING_MAX_LANGUAGE_HINTS)
        if language_hints:
            language_hints = language_hints[:hint_cap]
        return GoogleStreamingAsrSession(
            api_key,
            base_url=base_url,
            model=resolved_model if resolved_model not in {"google", "gemini"} else GEMINI_TRANSCRIBE_LIVE_MODEL,
            language_hints=language_hints,
            vocabulary=vocabulary,
        )

    # DashScope / Qwen path
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

    # Cap language hints per the selected streaming model's limits.
    hint_cap = STREAMING_MODEL_LANGUAGE_HINT_CAPS.get(resolved_model, STREAMING_MAX_LANGUAGE_HINTS)
    if language_hints:
        language_hints = language_hints[:hint_cap]

    return QwenAudioStreamingAsrSession(
        api_key,
        ws_url=ws_url,
        model=resolved_model,
        language_hints=language_hints,
        vocabulary=vocabulary,
        semantic_punctuation=semantic_punctuation,
        max_sentence_silence=max_sentence_silence,
    )
