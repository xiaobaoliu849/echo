from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode

import websockets

from .background_tasks import spawn_background_task
from .realtime_constants import DEFAULT_DASHSCOPE_LIVETRANSLATE_VOICE

DEFAULT_QWEN_AUDIO_REALTIME_VOICE = "longanqian"


class DashScopeRealtimeCallback:
    def __init__(self, *, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.loop = loop
        self.queue = queue

    def _push(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        text = str(event.get("text", ""))
        stash = str(event.get("stash", ""))
        response_id = str(event.get("response_id", ""))
        if event_type == "assistant_text" and (text or stash):
            # Dedup signature uses only (response_id, text, is_final).
            # Previously including `stash` here caused the same confirmed prefix
            # to bypass deduplication whenever only the prediction changed,
            # letting _merge_streaming_text receive the same prefix twice and
            # potentially producing a duplicate delta on the second pass.
            sig = (response_id, text, bool(event.get("final")))
            if getattr(self, "_last_text_sig", None) == sig:
                return
            self._last_text_sig = sig

        if self.loop is not None and self.queue is not None:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, event)

    def on_open(self) -> None:
        return None

    def on_event(self, response: Any) -> None:
        if not isinstance(response, dict):
            return

        event_type = str(response.get("type", "")).strip()
        if event_type == "input_audio_buffer.speech_started":
            self._push(
                {
                    "type": "speech_started",
                    "provider_event_type": event_type,
                    "event_id": str(response.get("event_id", "")),
                    "item_id": str(response.get("item_id", "")),
                    "audio_start_ms": response.get("audio_start_ms"),
                }
            )
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = str(response.get("transcript", "")).strip()
            self._push(
                {
                    "type": "user_transcript",
                    "text": transcript,
                    "provider_event_type": event_type,
                    "item_id": str(response.get("item_id", "")),
                }
            )
            return
        if event_type == "conversation.item.input_audio_transcription.text":
            # LiveTranslate incremental source-language ASR: `text` is the
            # confirmed prefix, `stash` is the tentative prediction.
            confirmed = str(response.get("text", ""))
            stash = str(response.get("stash", ""))
            if confirmed or stash:
                self._push(
                    {
                        "type": "user_transcript",
                        "text": confirmed,
                        "stash": stash,
                        "cumulative": True,
                        "provider_event_type": event_type,
                        "item_id": str(response.get("item_id", "")),
                    }
                )
            return
        if event_type == "response.created":
            self._push(
                {
                    "type": "response_started",
                    "response_id": str((response.get("response") or {}).get("id", "")),
                }
            )
            return
        if event_type == "response.function_call_arguments.done":
            self._push(
                {
                    "type": "function_call",
                    "provider_call_id": str(response.get("call_id", "")),
                    "tool_name": str(response.get("name", "")),
                    "arguments": response.get("arguments", "{}"),
                    "response_id": str(response.get("response_id", "")),
                    "item_id": str(response.get("item_id", "")),
                }
            )
            return
        if event_type == "response.audio.delta":
            delta = str(response.get("delta", "")).strip()
            if delta:
                self._push(
                    {
                        "type": "assistant_audio",
                        "audio": delta,
                        "encoding": "pcm_s16le",
                        "sample_rate": 24000,
                        "response_id": str(response.get("response_id", "")),
                    }
                )
            return
        if event_type in {"response.audio_transcript.delta", "response.text.delta"}:
            delta = str(response.get("delta", ""))
            if delta:
                self._push(
                    {
                        "type": "assistant_text",
                        "text": delta,
                        "response_id": str(response.get("response_id", "")),
                    }
                )
            return
        if event_type in {"response.audio_transcript.text", "response.text.text"}:
            # LiveTranslate incremental translation: `text` is the confirmed
            # prefix, `stash` is the tentative prediction. The provider merges
            # (text + stash) into a running display string.
            confirmed = str(response.get("text", ""))
            stash = str(response.get("stash", ""))
            response_id = str(response.get("response_id", ""))
            # Monotonicity guard: the confirmed prefix is supposed to grow
            # monotonically within one response.  If a new frame delivers a
            # shorter prefix (model rollback or duplicate frame), discard it
            # to prevent _merge_streaming_text from receiving a regression that
            # could emit previously-seen text as a spurious new delta.
            if not hasattr(self, "_last_confirmed_by_response"):
                self._last_confirmed_by_response: dict[str, str] = {}
            prev_confirmed = self._last_confirmed_by_response.get(response_id, "")
            if len(confirmed) < len(prev_confirmed):
                # Silently drop regressions — do not push to the queue.
                return
            self._last_confirmed_by_response[response_id] = confirmed
            if confirmed or stash:
                self._push(
                    {
                        "type": "assistant_text",
                        "text": confirmed,
                        "stash": stash,
                        "cumulative": True,
                        "response_id": response_id,
                    }
                )
            return
        if event_type in {"response.audio_transcript.done", "response.text.done"}:
            final = response.get("transcript")
            if final is None:
                final = response.get("text")
            self._push(
                {
                    "type": "assistant_text",
                    "text": str(final or ""),
                    "final": True,
                    "response_id": str(response.get("response_id", "")),
                }
            )
            return
        if event_type == "response.done":
            response_data = response.get("response") or {}
            output_items = response_data.get("output") or []
            has_function_call = any(
                isinstance(item, dict) and item.get("type") == "function_call"
                for item in output_items
            )
            self._push(
                {
                    "type": "tool_phase_complete" if has_function_call else "turn_complete",
                    "response_id": str(response_data.get("id", "")),
                    "status": str(response_data.get("status", "completed")),
                }
            )
            return
        if event_type == "error":
            error_data = response.get("error")
            if isinstance(error_data, dict):
                message = str(error_data.get("message", "")).strip() or str(response)
            else:
                message = str(error_data or response).strip()
            self._push({"type": "error", "message": message})

    def on_close(self, close_status_code: Any, close_msg: Any) -> None:
        self._push(
            {
                "type": "closed",
                "code": int(close_status_code or 1000),
                "message": str(close_msg or "").strip(),
            }
        )


class DashScopeAudioRealtimeConversation:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        url: str,
        callback: DashScopeRealtimeCallback,
        voiceprint_audio_urls: list[str] | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.url = url
        self.callback = callback
        self.voiceprint_audio_urls = list(voiceprint_audio_urls) if voiceprint_audio_urls is not None else []
        self._ws = None
        self._receiver_task = None
        self._closed = False
        self._session_update_count = 0

    @staticmethod
    def _url_with_model(base_url: str, model: str) -> str:
        parsed = urlparse(base_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query['model'] = model
        return urlunparse(parsed._replace(query=urlencode(query)))

    async def connect(self) -> None:
        ws_url = self._url_with_model(self.url, self.model)
        self._ws = await websockets.connect(
            ws_url,
            additional_headers={
                'Authorization': f'Bearer {self.api_key}',
                'user-agent': 'VoiceSpirit/Realtime',
            },
            max_size=16777216,
            ping_interval=None,
            ping_timeout=None,
        )
        self.callback.on_open()
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        close_code = 1000
        close_message = ''
        try:
            try:
                async for message in self._ws:
                    if isinstance(message, bytes):
                        continue
                    try:
                        event = json.loads(message)
                    except Exception:
                        self.callback.on_event({
                            'type': 'error',
                            'error': {'message': 'Qwen returned invalid JSON.'}
                        })
                        continue
                    self.callback.on_event(event)
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.ConnectionClosed as exc:
                close_code = getattr(exc, 'code', 1006)
                close_message = getattr(exc, 'reason', '')
            except Exception as exc:
                close_code = 1011
                close_message = str(exc)
                self.callback.on_event({
                    'type': 'error',
                    'error': {'message': str(exc)}
                })
        finally:
            self.callback.on_close(close_code, close_message)

    def _send_event(self, event: dict[str, Any]) -> None:
        if self._closed or self._ws is None:
            raise RuntimeError('Qwen Audio realtime websocket is not connected.')
        spawn_background_task(self._ws.send(json.dumps(event, ensure_ascii=False)))

    def update_session(self, **kwargs: Any) -> None:
        if self._session_update_count == 0:
            # Long silence_duration_ms (5000ms) + low threshold (0.3)
            # gives language learners plenty of time to pause and think
            # without the model cutting in. The API allows up to 6000ms.
            turn_detection = {
                'type': 'server_vad',
                'threshold': 0.3,
                'silence_duration_ms': 5000,
            }
            if self.voiceprint_audio_urls:
                turn_detection['voiceprint_audio_urls'] = self.voiceprint_audio_urls
            
            session = {
                'modalities': ['text', 'audio'],
                'voice': str(kwargs.get('voice') or DEFAULT_QWEN_AUDIO_REALTIME_VOICE),
                'instructions': str(kwargs.get('instructions') or ''),
                'input_audio_format': 'pcm',
                'output_audio_format': 'pcm',
                'input_audio_transcription': {'model': 'fun-asr'},
                'turn_detection': turn_detection,
                'tools': kwargs.get('tools') or [],
                'max_history_turns': 50,
            }
        else:
            session = {
                'instructions': str(kwargs.get('instructions') or ''),
                'tools': kwargs.get('tools') or [],
            }
        
        self._send_event({
            'event_id': f'event_{uuid.uuid4().hex}',
            'type': 'session.update',
            'session': session,
        })
        self._session_update_count += 1

    def append_audio(self, audio_b64: str) -> None:
        self._send_event({
            'event_id': f'event_{uuid.uuid4().hex}',
            'type': 'input_audio_buffer.append',
            'audio': audio_b64,
        })

    def send_raw(self, payload: str) -> None:
        if not isinstance(payload, str):
            raise TypeError('raw DashScope event payload must be a string.')
        if self._closed or self._ws is None:
            raise RuntimeError('Qwen Audio realtime websocket is not connected.')
        spawn_background_task(self._ws.send(payload))

    def create_response(self) -> None:
        self._send_event({
            'event_id': f'event_{uuid.uuid4().hex}',
            'type': 'response.create',
        })

    def cancel_response(self) -> None:
        self._send_event({
            'event_id': f'event_{uuid.uuid4().hex}',
            'type': 'response.cancel',
        })

    def retrieve_item(self, item_id: str) -> None:
        self._send_event({
            'event_id': f'event_{uuid.uuid4().hex}',
            'type': 'conversation.item.retrieve',
            'item_id': item_id,
        })

    def delete_item(self, item_id: str) -> None:
        self._send_event({
            'event_id': f'event_{uuid.uuid4().hex}',
            'type': 'conversation.item.delete',
            'item_id': item_id,
        })

    def close(self) -> None:
        self._closed = True
        if self._receiver_task is not None:
            self._receiver_task.cancel()
        if self._ws is not None:
            spawn_background_task(self._ws.close())


DEFAULT_QWEN_LIVETRANSLATE_VOICE = DEFAULT_DASHSCOPE_LIVETRANSLATE_VOICE  # backward-compat alias


class DashScopeLiveTranslateConversation(DashScopeAudioRealtimeConversation):
    """Raw-WebSocket conversation for qwen3(.5)-livetranslate-*-realtime.

    Reuses the connect/receive/append/close machinery of the Qwen-Audio raw
    client but sends a translation-specific ``session.update`` (source/target
    language + hot-word corpus, no instructions/tools) and supports
    ``session.finish`` to flush the final translation segment.
    """

    def update_session(  # type: ignore[override]
        self,
        *,
        voice: str | None = None,
        source_language: str = "zh",
        target_language: str = "en",
        corpus_phrases: dict[str, str] | None = None,
        modalities: list[str] | None = None,
        enable_voice_clone: bool = False,
        voice_clone_frequency: str = "once",
    ) -> None:
        selected_voice = str(voice or DEFAULT_QWEN_LIVETRANSLATE_VOICE).strip()
        # Voice clone logic per official Qwen LiveTranslate API:
        # 1) Pre-cloned custom voice ID (e.g. qwen-translate-vc-xxx): frequency="never"
        # 2) Server auto-clone once or always: voice must be "default"
        if selected_voice.startswith("qwen-translate-vc-") or selected_voice.startswith("qwen-vc-"):
            enable_voice_clone = True
            voice_clone_frequency = "never"
            target_voice = selected_voice
        elif enable_voice_clone:
            freq = voice_clone_frequency.lower().strip()
            if freq not in ("once", "always", "never"):
                freq = "once"
            voice_clone_frequency = freq
            target_voice = "default" if freq in ("once", "always") else selected_voice
        else:
            target_voice = selected_voice

        session: dict[str, Any] = {
            "modalities": list(modalities or ["text", "audio"]),
            "voice": target_voice,
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            # ``input_audio_transcription.language`` tells the server what
            # source language to expect for ASR accuracy.  We keep the
            # ``model`` field so the server emits source-language ASR events
            # (conversation.item.input_audio_transcription.*), which the
            # frontend uses to display the original speech alongside the
            # translation.  Translation-text duplication is prevented by
            # the frontend's separate preview-ref pattern.
            "input_audio_transcription": {
                "model": "qwen3-asr-flash-realtime",
                "language": source_language or "zh",
            },
            "translation": {
                "language": target_language or "en",
            },
        }
        if enable_voice_clone:
            session["enable_voice_clone"] = True
            session["voice_clone_options"] = {
                "frequency": voice_clone_frequency
            }

        phrases = {str(k): str(v) for k, v in (corpus_phrases or {}).items() if str(k).strip()}
        if phrases:
            session["translation"]["corpus"] = {"phrases": phrases}

        self._send_event(
            {
                "event_id": f"event_{uuid.uuid4().hex}",
                "type": "session.update",
                "session": session,
            }
        )
        self._session_update_count += 1

    def finish_session(self) -> None:
        """Send ``session.finish`` so the server flushes the last segment."""
        self._send_event(
            {
                "event_id": f"event_{uuid.uuid4().hex}",
                "type": "session.finish",
            }
        )
