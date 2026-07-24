"""Tests for the DashScope Qwen LiveTranslate realtime path.

Covers:
  - ``_is_dashscope_live_translate_model`` model detection
  - ``normalize_qwen_translate_language`` BCP-47 → Qwen language mapping
  - ``DashScopeRealtimeCallback`` translation-event mapping
  - ``DashScopeLiveTranslateConversation.update_session`` payload shape
  - ``_resolve_dashscope_settings`` exempting livetranslate from native-tools check
  - ``_dashscope_live_translate_to_client_loop`` end-to-end event flow
  - ``stream_dashscope_session`` routing livetranslate models to the translate path

No live API is contacted — everything is mocked, matching the existing
realtime test conventions.
"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.realtime_constants import (
    _is_dashscope_live_translate_model,
    normalize_qwen_translate_language,
)
from services.realtime_dashscope_client import (
    DashScopeLiveTranslateConversation,
    DashScopeRealtimeCallback,
)
from services.realtime_memory_session import RealtimeMemorySession
from services.realtime_voice_service import RealtimeVoiceService


class CollectingWebSocket:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))

    def of_type(self, event_type: str) -> list[dict]:
        return [e for e in self.events if e.get("type") == event_type]


class ModelDetectionTests(unittest.TestCase):
    def test_matches_current_and_legacy_names(self):
        self.assertTrue(_is_dashscope_live_translate_model("qwen3.5-livetranslate-flash-realtime"))
        self.assertTrue(_is_dashscope_live_translate_model("qwen3-livetranslate-flash-realtime"))
        self.assertTrue(_is_dashscope_live_translate_model("qwen3.5-livetranslate-plus-realtime"))
        self.assertTrue(
            _is_dashscope_live_translate_model("qwen3.5-livetranslate-flash-realtime-2026-05-19")
        )
        # Case-insensitive
        self.assertTrue(_is_dashscope_live_translate_model("QWEN3.5-LiveTranslate-Flash-Realtime"))

    def test_rejects_other_models(self):
        self.assertFalse(_is_dashscope_live_translate_model("qwen3.5-omni-plus-realtime"))
        self.assertFalse(_is_dashscope_live_translate_model("qwen-audio-3.0-realtime-plus"))
        self.assertFalse(_is_dashscope_live_translate_model("gemini-3.5-live-translate-preview"))
        self.assertFalse(_is_dashscope_live_translate_model("qwen-mt-plus"))
        self.assertFalse(_is_dashscope_live_translate_model(None))
        self.assertFalse(_is_dashscope_live_translate_model(""))


class LanguageNormalizationTests(unittest.TestCase):
    def test_maps_bcp47_and_aliases(self):
        self.assertEqual(normalize_qwen_translate_language("zh-Hans"), "zh")
        self.assertEqual(normalize_qwen_translate_language("zh-CN"), "zh")
        self.assertEqual(normalize_qwen_translate_language("zh-Hant"), "zh")
        self.assertEqual(normalize_qwen_translate_language("en-US"), "en")
        self.assertEqual(normalize_qwen_translate_language("pt-BR"), "pt")
        self.assertEqual(normalize_qwen_translate_language("Japanese"), "ja")

    def test_passthrough_and_fallback(self):
        self.assertEqual(normalize_qwen_translate_language("fr"), "fr")
        # Unknown compound falls back to primary subtag
        self.assertEqual(normalize_qwen_translate_language("xx-YY"), "xx")
        # Empty → default
        self.assertEqual(normalize_qwen_translate_language(""), "en")
        self.assertEqual(normalize_qwen_translate_language(None, "zh"), "zh")


class CallbackTranslationEventTests(unittest.TestCase):
    def _map(self, raw_events: list[dict]) -> list[dict]:
        """Feed raw server events through the callback on a live loop and drain."""

        async def run() -> list[dict]:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            callback = DashScopeRealtimeCallback(loop=loop, queue=queue)
            for raw in raw_events:
                callback.on_event(raw)
            # Let call_soon_threadsafe callbacks execute on the running loop.
            await asyncio.sleep(0)
            out: list[dict] = []
            while not queue.empty():
                out.append(queue.get_nowait())
            return out

        return asyncio.run(run())

    def test_incremental_translation_text(self):
        events = self._map(
            [{"type": "response.audio_transcript.text", "text": "Hello", "stash": " world", "response_id": "r1"}]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "assistant_text")
        self.assertEqual(events[0]["text"], "Hello")
        self.assertEqual(events[0]["stash"], " world")
        self.assertTrue(events[0]["cumulative"])

    def test_final_translation_done_uses_transcript(self):
        events = self._map(
            [{"type": "response.audio_transcript.done", "transcript": "Hello world", "response_id": "r1"}]
        )
        self.assertEqual(events[0]["type"], "assistant_text")
        self.assertEqual(events[0]["text"], "Hello world")
        self.assertTrue(events[0]["final"])

    def test_text_only_done_uses_text_field(self):
        events = self._map([{"type": "response.text.done", "text": "Bonjour", "response_id": "r1"}])
        self.assertEqual(events[0]["text"], "Bonjour")
        self.assertTrue(events[0]["final"])

    def test_incremental_source_transcription(self):
        events = self._map(
            [{"type": "conversation.item.input_audio_transcription.text", "text": "你好", "stash": "世界"}]
        )
        self.assertEqual(events[0]["type"], "user_transcript")
        self.assertEqual(events[0]["text"], "你好")
        self.assertEqual(events[0]["stash"], "世界")
        self.assertTrue(events[0]["cumulative"])

    def test_audio_delta_still_mapped(self):
        events = self._map([{"type": "response.audio.delta", "delta": "AAAA", "response_id": "r1"}])
        self.assertEqual(events[0]["type"], "assistant_audio")
        self.assertEqual(events[0]["sample_rate"], 24000)


class LiveTranslateSessionConfigTests(unittest.TestCase):
    def test_update_session_builds_translation_payload(self):
        captured: list[dict] = []
        conversation = DashScopeLiveTranslateConversation(
            model="qwen3.5-livetranslate-flash-realtime",
            api_key="k",
            callback=SimpleNamespace(on_open=lambda: None),  # type: ignore[arg-type]
            url="wss://example/api-ws/v1/realtime",
        )
        conversation._send_event = captured.append  # type: ignore[method-assign]
        conversation.update_session(
            voice="Tina",
            source_language="zh",
            target_language="en",
            corpus_phrases={"人工智能": "Artificial Intelligence"},
        )
        self.assertEqual(len(captured), 1)
        payload = captured[0]
        self.assertEqual(payload["type"], "session.update")
        session = payload["session"]
        self.assertEqual(session["translation"]["language"], "en")
        self.assertEqual(session["input_audio_transcription"]["language"], "zh")
        self.assertEqual(
            session["input_audio_transcription"]["model"], "qwen3-asr-flash-realtime"
        )
        self.assertEqual(
            session["translation"]["corpus"]["phrases"], {"人工智能": "Artificial Intelligence"}
        )
        self.assertEqual(session["input_audio_format"], "pcm")
        self.assertEqual(session["output_audio_format"], "pcm")
        # No chat-only fields leak into the translation session
        self.assertNotIn("instructions", session)
        self.assertNotIn("tools", session)
        # Regression: the translation model runs its own server-side VAD and derives
        # the rate from input_audio_format. Sending the chat-style turn_detection /
        # sample_rate fields makes DashScope reject session.update (parameter error),
        # which looks like "connected but no response". They must never be sent.
        self.assertNotIn("turn_detection", session)
        self.assertNotIn("sample_rate", session)

    def test_update_session_omits_empty_corpus(self):
        captured: list[dict] = []
        conversation = DashScopeLiveTranslateConversation(
            model="qwen3.5-livetranslate-flash-realtime",
            api_key="k",
            callback=SimpleNamespace(on_open=lambda: None),  # type: ignore[arg-type]
            url="wss://example/api-ws/v1/realtime",
        )
        conversation._send_event = captured.append  # type: ignore[method-assign]
        conversation.update_session(voice="Tina", corpus_phrases={})
        self.assertNotIn("corpus", captured[0]["session"]["translation"])

    def test_update_session_voice_clone_once_forces_default_voice(self):
        captured: list[dict] = []
        conversation = DashScopeLiveTranslateConversation(
            model="qwen3.5-livetranslate-flash-realtime",
            api_key="k",
            callback=SimpleNamespace(on_open=lambda: None),  # type: ignore[arg-type]
            url="wss://example/api-ws/v1/realtime",
        )
        conversation._send_event = captured.append  # type: ignore[method-assign]
        conversation.update_session(
            voice="Tina",
            enable_voice_clone=True,
            voice_clone_frequency="once",
        )
        session = captured[0]["session"]
        self.assertTrue(session["enable_voice_clone"])
        self.assertEqual(session["voice_clone_options"]["frequency"], "once")
        self.assertEqual(session["voice"], "default")

    def test_update_session_voice_clone_precloned_custom_voice(self):
        captured: list[dict] = []
        conversation = DashScopeLiveTranslateConversation(
            model="qwen3.5-livetranslate-flash-realtime",
            api_key="k",
            callback=SimpleNamespace(on_open=lambda: None),  # type: ignore[arg-type]
            url="wss://example/api-ws/v1/realtime",
        )
        conversation._send_event = captured.append  # type: ignore[method-assign]
        conversation.update_session(
            voice="qwen-translate-vc-myvoice123",
        )
        session = captured[0]["session"]
        self.assertTrue(session["enable_voice_clone"])
        self.assertEqual(session["voice_clone_options"]["frequency"], "never")
        self.assertEqual(session["voice"], "qwen-translate-vc-myvoice123")

    def test_finish_session_sends_session_finish(self):
        captured: list[dict] = []
        conversation = DashScopeLiveTranslateConversation(
            model="m", api_key="k",
            callback=SimpleNamespace(on_open=lambda: None),  # type: ignore[arg-type]
            url="wss://example/api-ws/v1/realtime",
        )
        conversation._send_event = captured.append  # type: ignore[method-assign]
        conversation.finish_session()
        self.assertEqual(captured[0]["type"], "session.finish")


class ResolveSettingsTests(unittest.TestCase):
    def _service(self, model: str) -> RealtimeVoiceService:
        fake_config = SimpleNamespace(
            get_provider_settings=lambda provider, m: {
                "provider": provider,
                "api_key": "test-key",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "realtime_base_url": "wss://ws-123.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
                "model": model,
            }
        )
        return RealtimeVoiceService(config=fake_config)  # type: ignore[arg-type]

    def test_livetranslate_exempt_from_native_tools(self):
        svc = self._service("qwen3.5-livetranslate-flash-realtime")
        settings = svc._resolve_dashscope_settings(None)
        self.assertEqual(settings["model"], "qwen3.5-livetranslate-flash-realtime")
        self.assertTrue(settings["realtime_base_url"].endswith("/api-ws/v1/realtime"))

    def test_unsupported_model_still_rejected(self):
        svc = self._service("qwen-mt-plus")
        with self.assertRaises(RuntimeError):
            svc._resolve_dashscope_settings(None)


class LiveTranslateLoopTests(unittest.TestCase):
    def _run_loop(self, events: list[dict]) -> CollectingWebSocket:
        svc = RealtimeVoiceService()
        ws = CollectingWebSocket()

        async def run() -> CollectingWebSocket:
            queue: asyncio.Queue = asyncio.Queue()
            for event in events:
                queue.put_nowait(event)
            queue.put_nowait({"type": "closed"})
            await svc._dashscope_live_translate_to_client_loop(
                ws, queue, RealtimeMemorySession(), None
            )
            return ws

        return asyncio.run(run())

    def test_final_translation_and_turn_complete(self):
        ws = self._run_loop(
            [
                {"type": "user_transcript", "text": "你好世界"},
                {"type": "assistant_text", "text": "Hello world", "final": True},
            ]
        )
        user_events = ws.of_type("user_transcript")
        self.assertTrue(any(e["text"] == "你好世界" for e in user_events))
        assistant_text = "".join(e["text"] for e in ws.of_type("assistant_text"))
        self.assertIn("Hello world", assistant_text)
        self.assertEqual(len(ws.of_type("turn_complete")), 1)

    def test_cumulative_translation_emits_novel_delta_only(self):
        ws = self._run_loop(
            [
                {"type": "assistant_text", "text": "Hello", "stash": "", "cumulative": True},
                {"type": "assistant_text", "text": "Hello world", "stash": "", "cumulative": True},
                {"type": "assistant_text", "text": "Hello world", "final": True},
            ]
        )
        deltas = [e["text"] for e in ws.of_type("assistant_text")]
        joined = "".join(deltas)
        # The merged output should contain the full phrase exactly once overall,
        # not duplicate the "Hello" prefix on the second update.
        self.assertEqual(joined.count("Hello"), 1)
        self.assertIn("world", joined)

    def test_revised_stash_does_not_duplicate_or_garble(self):
        # A tentative prediction ("world") is later revised away ("everyone").
        # Because only the confirmed prefix is merged, the revised stash must not
        # leak into the canonical stream.
        ws = self._run_loop(
            [
                {"type": "assistant_text", "text": "Hello", "stash": "world", "cumulative": True},
                {"type": "assistant_text", "text": "Hello everyone", "stash": "", "cumulative": True},
                {"type": "assistant_text", "text": "Hello everyone", "final": True},
            ]
        )
        joined = "".join(e["text"] for e in ws.of_type("assistant_text"))
        self.assertEqual(joined, "Hello everyone")
        self.assertNotIn("world", joined)
        self.assertEqual(joined.count("Hello"), 1)

    def test_final_event_with_punctuation_does_not_duplicate(self):
        # Streaming cumulative text delivered "Hello world"
        # The done event (final=True) delivers "Hello world."
        # Because streaming already delivered the text, final=True must NOT
        # re-emit a duplicate chunk.
        ws = self._run_loop(
            [
                {"type": "assistant_text", "text": "Hello world", "cumulative": True},
                {"type": "assistant_text", "text": "Hello world.", "final": True},
            ]
        )
        texts = [e["text"] for e in ws.of_type("assistant_text")]
        self.assertEqual(texts, ["Hello world"])

    def test_final_event_fallback_when_no_streaming_text(self):
        # Ultra-fast single-token response where no streaming text.text arrived
        # before the final=True event. It must emit the text once as fallback.
        ws = self._run_loop(
            [
                {"type": "assistant_text", "text": "Hello world", "final": True},
            ]
        )
        texts = [e["text"] for e in ws.of_type("assistant_text")]
        self.assertEqual(texts, ["Hello world"])

    def test_cjk_confirmed_merge_has_no_stray_space_or_duplication(self):
        ws = self._run_loop(
            [
                {"type": "assistant_text", "text": "你好", "stash": "世界", "cumulative": True},
                {"type": "assistant_text", "text": "你好世界", "stash": "", "cumulative": True},
            ]
        )
        joined = "".join(e["text"] for e in ws.of_type("assistant_text"))
        self.assertEqual(joined, "你好世界")
        self.assertNotIn(" ", joined)
        self.assertEqual(joined.count("你好"), 1)

    def test_stash_is_exposed_as_separate_preview_not_canonical(self):
        ws = self._run_loop(
            [{"type": "assistant_text", "text": "Hello", "stash": "world", "cumulative": True}]
        )
        previews = ws.of_type("translation_preview")
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0]["tentative"], "world")
        # The accumulating assistant_text stream carries only the confirmed text.
        assistant = "".join(e["text"] for e in ws.of_type("assistant_text"))
        self.assertEqual(assistant, "Hello")
        self.assertNotIn("world", assistant)

    def test_source_transcript_cumulative_uses_confirmed_only(self):
        ws = self._run_loop(
            [
                {"type": "user_transcript", "text": "你好", "stash": "世界", "cumulative": True},
                {"type": "user_transcript", "text": "你好世界"},
            ]
        )
        user_texts = [e["text"] for e in ws.of_type("user_transcript")]
        # Confirmed-only cumulative text, then the final transcript.
        self.assertIn("你好", user_texts)
        self.assertIn("你好世界", user_texts)
        # No garbled "confirmed + stash" concatenation leaked into the text field.
        self.assertNotIn("你好 世界", user_texts)

    def test_assistant_audio_forwarded(self):
        ws = self._run_loop(
            [{"type": "assistant_audio", "audio": "AAAA", "encoding": "pcm_s16le", "sample_rate": 24000}]
        )
        audio_events = ws.of_type("assistant_audio")
        self.assertEqual(len(audio_events), 1)
        self.assertEqual(audio_events[0]["audio"], "AAAA")


class StreamRoutingTests(unittest.TestCase):
    def test_livetranslate_routes_to_translate_session(self):
        svc = RealtimeVoiceService()
        settings = {
            "api_key": "k",
            "model": "qwen3.5-livetranslate-flash-realtime",
            "realtime_base_url": "wss://ws/api-ws/v1/realtime",
        }
        with patch.object(svc, "_resolve_dashscope_settings", return_value=settings), patch.object(
            svc, "_stream_dashscope_live_translate_session", new=AsyncMock()
        ) as translate_mock:
            asyncio.run(
                svc.stream_dashscope_session(
                    CollectingWebSocket(),
                    model="qwen3.5-livetranslate-flash-realtime",
                    translation_mode="bidirectional",
                    source_language_code="zh-Hans",
                    target_language_code="en",
                    echo_target_language=True,
                )
            )
            translate_mock.assert_awaited_once()
            kwargs = translate_mock.call_args.kwargs
            self.assertEqual(kwargs["source_language_code"], "zh-Hans")
            self.assertEqual(kwargs["target_language_code"], "en")
            self.assertEqual(kwargs["translation_mode"], "bidirectional")
            self.assertEqual(kwargs["settings"]["model"], "qwen3.5-livetranslate-flash-realtime")


if __name__ == "__main__":
    unittest.main()
