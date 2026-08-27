"""Tests for the Qwen-Audio-3.0-ASR-Flash-Streaming realtime ASR path.

Covers:
  - run-task / finish-task event builders (fun-asr-client-events contract)
  - result-generated parsing (interim/final, heartbeat skip, words ms->s)
  - session lifecycle against a fake upstream WebSocket
  - the /api/transcription/realtime WS handler with a fake client socket
  - realtime config message validation
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from routers.transcription import _parse_realtime_config, transcription_realtime_ws
from services.realtime_asr_service import (
    GEMINI_TRANSCRIBE_LIVE_MODEL,
    GoogleStreamingAsrSession,
    QWEN_AUDIO_ASR_STREAMING_MODEL,
    QwenAudioStreamingAsrSession,
    RealtimeAsrError,
    RealtimeAsrSentence,
    build_finish_task_event,
    build_run_task_event,
    build_streaming_asr_session,
    parse_sentence,
)


class BuildRunTaskTests(unittest.TestCase):
    def test_basic_payload_matches_protocol(self):
        event = build_run_task_event("task-1")
        self.assertEqual(event["header"]["action"], "run-task")
        self.assertEqual(event["header"]["task_id"], "task-1")
        self.assertEqual(event["header"]["streaming"], "duplex")
        payload = event["payload"]
        self.assertEqual(payload["task_group"], "audio")
        self.assertEqual(payload["task"], "asr")
        self.assertEqual(payload["function"], "recognition")
        self.assertEqual(payload["model"], QWEN_AUDIO_ASR_STREAMING_MODEL)
        self.assertEqual(payload["parameters"]["format"], "pcm")
        self.assertEqual(payload["parameters"]["sample_rate"], 16000)
        self.assertEqual(payload["input"], {})

    def test_optional_parameters_and_caps(self):
        event = build_run_task_event(
            "task-2",
            language_hints=["zh", "en", "ja", "ko", "vi"],
            vocabulary={"张三": 5},
            semantic_punctuation=True,
            max_sentence_silence=800,
        )
        parameters = event["payload"]["parameters"]
        self.assertEqual(parameters["language_hints"], ["zh", "en", "ja", "ko"])
        self.assertEqual(parameters["vocabulary"], {"张三": 5})
        self.assertTrue(parameters["semantic_punctuation_enabled"])
        self.assertEqual(parameters["max_sentence_silence"], 800)

    def test_finish_task_payload(self):
        event = build_finish_task_event("task-9")
        self.assertEqual(event["header"]["action"], "finish-task")
        self.assertEqual(event["header"]["task_id"], "task-9")
        self.assertEqual(event["header"]["streaming"], "duplex")


class ParseSentenceTests(unittest.TestCase):
    def test_final_sentence_with_words(self):
        payload = {
            "output": {
                "sentence": {
                    "begin_time": 170,
                    "end_time": 920,
                    "text": "好，我知道了",
                    "heartbeat": False,
                    "sentence_end": True,
                    "sentence_id": 1,
                    "words": [
                        {"begin_time": 170, "end_time": 295, "text": "好", "punctuation": "，"},
                        {"begin_time": 711, "end_time": 920, "text": "了", "punctuation": ""},
                    ],
                }
            },
            "usage": {"duration": 3},
        }
        sentence = parse_sentence(payload)
        self.assertIsNotNone(sentence)
        self.assertTrue(sentence.sentence_end)
        self.assertEqual(sentence.text, "好，我知道了")
        self.assertEqual(sentence.begin_ms, 170)
        self.assertEqual(sentence.end_ms, 920)
        self.assertEqual(
            sentence.words,
            [
                {"text": "好", "start": 0.17, "end": 0.295},
                {"text": "了", "start": 0.711, "end": 0.92},
            ],
        )

    def test_interim_sentence(self):
        payload = {"output": {"sentence": {"text": "你好", "sentence_end": False}}}
        sentence = parse_sentence(payload)
        self.assertIsNotNone(sentence)
        self.assertFalse(sentence.sentence_end)
        self.assertEqual(sentence.words, [])

    def test_heartbeat_returns_none(self):
        payload = {"output": {"sentence": {"heartbeat": True, "sentence_id": 0, "text": ""}}}
        self.assertIsNone(parse_sentence(payload))

    def test_malformed_payloads_return_none(self):
        self.assertIsNone(parse_sentence({}))
        self.assertIsNone(parse_sentence({"output": "nope"}))
        self.assertIsNone(parse_sentence({"output": {"sentence": "nope"}}))


class _FakeUpstreamWs:
    """Fake upstream DashScope socket driven by a script of messages."""

    def __init__(self, script: list):
        self.script = list(script)
        self.sent: list = []
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if not self.script:
            raise asyncio.TimeoutError
        return self.script.pop(0)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.script:
            raise StopAsyncIteration
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _event(name: str, payload: dict | None = None, error_message: str = "") -> str:
    header: dict = {"task_id": "t", "event": name, "attributes": {}}
    if error_message:
        header["error_message"] = error_message
    return json.dumps({"header": header, "payload": payload or {}}, ensure_ascii=False)


class SessionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_sends_run_task_and_waits_task_started(self):
        fake = _FakeUpstreamWs([_event("task-started")])
        session = QwenAudioStreamingAsrSession("sk-test", language_hints=["zh"])
        with patch(
            "services.realtime_asr_service.websockets.connect",
            new=lambda *a, **k: _awaitable(fake),
        ):
            await session.start()

        self.assertEqual(len(fake.sent), 1)
        run_task = json.loads(fake.sent[0])
        self.assertEqual(run_task["header"]["action"], "run-task")
        self.assertEqual(run_task["payload"]["model"], QWEN_AUDIO_ASR_STREAMING_MODEL)
        self.assertEqual(run_task["payload"]["parameters"]["language_hints"], ["zh"])

    async def test_start_raises_on_task_failed(self):
        fake = _FakeUpstreamWs([_event("task-failed", error_message="Invalid API key")])
        session = QwenAudioStreamingAsrSession("sk-bad")
        with patch(
            "services.realtime_asr_service.websockets.connect",
            new=lambda *a, **k: _awaitable(fake),
        ):
            with self.assertRaises(RealtimeAsrError):
                await session.start()
        self.assertTrue(fake.closed)

    async def test_send_audio_and_event_stream(self):
        script = [
            _event("task-started"),
            _event("result-generated", {"output": {"sentence": {"text": "你好", "sentence_end": False}}}),
            _event("result-generated", {"output": {"sentence": {"text": "你好世界", "sentence_end": True, "begin_time": 0, "end_time": 1000}}}),
            _event("task-finished"),
        ]
        fake = _FakeUpstreamWs(script)
        session = QwenAudioStreamingAsrSession("sk-test")
        with patch(
            "services.realtime_asr_service.websockets.connect",
            new=lambda *a, **k: _awaitable(fake),
        ):
            await session.start()
            await session.send_audio(b"\x00\x01")
            await session.finish()

            sentences = []
            async for sentence in session.events():
                sentences.append(sentence)

        self.assertEqual([s.text for s in sentences], ["你好", "你好世界"])
        self.assertFalse(sentences[0].sentence_end)
        self.assertTrue(sentences[1].sentence_end)
        # binary audio frame + finish-task JSON
        self.assertIn(b"\x00\x01", fake.sent)
        finish_events = [s for s in fake.sent if isinstance(s, str) and "finish-task" in s]
        self.assertEqual(len(finish_events), 1)

    async def test_task_failed_mid_stream_raises(self):
        script = [
            _event("task-started"),
            _event("task-failed", error_message="quota exceeded"),
        ]
        fake = _FakeUpstreamWs(script)
        session = QwenAudioStreamingAsrSession("sk-test")
        with patch(
            "services.realtime_asr_service.websockets.connect",
            new=lambda *a, **k: _awaitable(fake),
        ):
            await session.start()
            with self.assertRaises(RealtimeAsrError):
                async for _ in session.events():
                    pass


def _awaitable(value):
    future = asyncio.Future()
    future.set_result(value)
    return future


class ParseRealtimeConfigTests(unittest.TestCase):
    def test_full_config(self):
        config = _parse_realtime_config({
            "type": "config",
            "language_hints": ["zh", " en ", "", "ja", "ko", "vi"],
            "vocabulary": {"通义千问": 5, "坏值": "x"},
            "semantic_punctuation": True,
            "max_sentence_silence": 800,
        })
        self.assertEqual(config["language_hints"], ["zh", "en", "ja", "ko"])
        self.assertEqual(config["vocabulary"], {"通义千问": 5})
        self.assertTrue(config["semantic_punctuation"])
        self.assertEqual(config["max_sentence_silence"], 800)

    def test_model_selection_in_config(self):
        config = _parse_realtime_config({"model": GEMINI_TRANSCRIBE_LIVE_MODEL})
        self.assertEqual(config.get("model"), GEMINI_TRANSCRIBE_LIVE_MODEL)
        config_qwen = _parse_realtime_config({"model": QWEN_AUDIO_ASR_STREAMING_MODEL})
        self.assertEqual(config_qwen.get("model"), QWEN_AUDIO_ASR_STREAMING_MODEL)

    def test_garbage_config_returns_empty(self):
        self.assertEqual(_parse_realtime_config("junk"), {})
        self.assertEqual(_parse_realtime_config({"language_hints": "zh"}), {})
        self.assertEqual(_parse_realtime_config({"max_sentence_silence": 99999}), {})


class GoogleStreamingAsrSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_api_key_raises(self):
        session = GoogleStreamingAsrSession("")
        with self.assertRaises(ValueError) as ctx:
            await session.start()
        self.assertIn("Google API key", str(ctx.exception))

    async def test_session_lifecycle_with_mock_sdk(self):
        class MockLiveSession:
            def __init__(self):
                self.sent_realtime_inputs = []
                self.sent_turns = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def send_realtime_input(self, audio=None):
                self.sent_realtime_inputs.append(audio)

            async def send(self, **kwargs):
                self.sent_turns.append(kwargs)

            def receive(self):
                class AsyncIter:
                    def __init__(self):
                        self.yielded = False

                    def __aiter__(self):
                        return self

                    async def __anext__(self):
                        if not self.yielded:
                            self.yielded = True
                            # Return simulated server response with transcription
                            resp = type("MockResponse", (), {
                                "server_content": type("MockServerContent", (), {
                                    "turn_complete": True,
                                    "input_transcription": type("MockTranscript", (), {
                                        "text": "Hello Gemini Live",
                                        "finished": True,
                                    })(),
                                })(),
                                "text": "Hello Gemini Live",
                            })()
                            return resp
                        raise StopAsyncIteration

                return AsyncIter()

        mock_live_session = MockLiveSession()
        mock_client = type("MockClient", (), {
            "aio": type("MockAio", (), {
                "live": type("MockLive", (), {
                    "connect": lambda *a, **kw: mock_live_session,
                })(),
            })(),
        })()

        session = GoogleStreamingAsrSession(
            "fake-google-key",
            model=GEMINI_TRANSCRIBE_LIVE_MODEL,
        )

        with patch("services.realtime_asr_service.genai", type("MockGenai", (), {"Client": lambda **kw: mock_client})), \
             patch("services.realtime_asr_service.types", type("MockTypes", (), {
                 "LiveConnectConfig": lambda **kw: kw,
                 "AudioTranscriptionConfig": lambda **kw: kw,
                 "Blob": lambda data, mime_type: type("MockBlob", (), {"data": data, "mime_type": mime_type})(),
             })):
            await session.start()
            await session.send_audio(b"\x00\x01\x02")
            await session.finish()

            sentences = []
            async for sentence in session.events():
                sentences.append(sentence)
                break

            await session.close()

        self.assertEqual(len(sentences), 1)
        self.assertEqual(sentences[0].text, "Hello Gemini Live")
        self.assertTrue(sentences[0].sentence_end)
        self.assertEqual(len(mock_live_session.sent_realtime_inputs), 1)
        self.assertEqual(mock_live_session.sent_realtime_inputs[0].data, b"\x00\x01\x02")


class BuildStreamingAsrSessionTests(unittest.TestCase):
    def test_build_google_session_success(self):
        cfg = type("MockConfig", (), {
            "reload": lambda self: None,
            "get_all": lambda self: {"api_keys": {"google_api_key": "goog-key"}},
            "get_provider_settings": lambda self, name: {"base_url": "https://custom.goog.api"},
        })()
        session = build_streaming_asr_session(cfg, model=GEMINI_TRANSCRIBE_LIVE_MODEL)
        self.assertIsInstance(session, GoogleStreamingAsrSession)
        self.assertEqual(session._api_key, "goog-key")
        self.assertEqual(session._base_url, "https://custom.goog.api")
        self.assertEqual(session._model, GEMINI_TRANSCRIBE_LIVE_MODEL)

    def test_build_google_session_missing_key_raises(self):
        cfg = type("MockConfig", (), {
            "reload": lambda self: None,
            "get_all": lambda self: {"api_keys": {}},
            "get_provider_settings": lambda self, name: {},
        })()
        with self.assertRaises(ValueError) as ctx:
            build_streaming_asr_session(cfg, model=GEMINI_TRANSCRIBE_LIVE_MODEL)
        self.assertIn("Google API key not configured", str(ctx.exception))

    def test_build_dashscope_session_success(self):
        cfg = type("MockConfig", (), {
            "reload": lambda self: None,
            "get_all": lambda self: {"api_keys": {"dashscope_api_key": "dash-key"}},
            "get_provider_settings": lambda self, name: {"base_url": "https://dashscope.aliyuncs.com/api/v1"},
        })()
        session = build_streaming_asr_session(cfg, model=QWEN_AUDIO_ASR_STREAMING_MODEL)
        self.assertIsInstance(session, QwenAudioStreamingAsrSession)
        self.assertEqual(session._api_key, "dash-key")
        self.assertEqual(session._model, QWEN_AUDIO_ASR_STREAMING_MODEL)


class _FakeClientWs:
    """Fake browser-side socket for the FastAPI WS handler."""

    def __init__(self, inbox: list[dict], query_params: dict | None = None):
        self.inbox = list(inbox)
        self.sent: list[dict] = []
        self.accepted = False
        self.close_code: int | None = None
        self.query_params: dict = dict(query_params or {})

    async def accept(self):
        self.accepted = True

    async def receive(self):
        while not self.inbox:
            await asyncio.sleep(0.001)
        return self.inbox.pop(0)

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code: int = 1000):
        self.close_code = code


class _FakeSession:
    """Stand-in for QwenAudioStreamingAsrSession.

    Mirrors the real protocol: the upstream only drains its sentences *after*
    finish-task is sent (the server emits task-finished last). Blocking events()
    on finish() removes the race where the upstream would otherwise complete
    before the client's finish message is processed.
    """

    def __init__(self, sentences: list[RealtimeAsrSentence], **kwargs):
        self.kwargs = kwargs
        self.audio: list[bytes] = []
        self.finished = False
        self._sentences = sentences
        self._finish_event = asyncio.Event()

    async def start(self):
        return None

    async def send_audio(self, chunk: bytes):
        self.audio.append(chunk)

    async def finish(self):
        self.finished = True
        self._finish_event.set()

    async def events(self):
        await self._finish_event.wait()
        for sentence in self._sentences:
            # Yield control so the client loop can interleave.
            await asyncio.sleep(0)
            yield sentence

    async def close(self):
        return None


class RealtimeWsHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # These tests exercise ASR flow, not the auth gate. Force auth off so
        # the fake sockets are never rejected because of whatever tokens
        # happen to be configured on the machine running the tests.
        patcher = patch("services.api_auth_guard.is_auth_enabled", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_full_session_flow(self):
        client = _FakeClientWs([
            {"text": json.dumps({"type": "config", "language_hints": ["zh"]})},
            {"bytes": b"\x00\x01"},
            {"text": json.dumps({"type": "finish"})},
        ])
        fake_session = _FakeSession([
            RealtimeAsrSentence(text="你好", sentence_end=False),
            RealtimeAsrSentence(text="你好世界", sentence_end=True, words=[{"text": "你好", "start": 0.0, "end": 0.5}]),
        ])

        with patch(
            "routers.transcription.build_streaming_asr_session",
            return_value=fake_session,
        ) as factory:
            # The fake upstream only drains after finish(), so the handler runs
            # to completion on its own — no disconnect injection needed.
            await transcription_realtime_ws(client)

        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs.get("language_hints"), ["zh"])
        self.assertEqual(fake_session.audio, [b"\x00\x01"])
        self.assertTrue(fake_session.finished)

        types = [message["type"] for message in client.sent]
        self.assertEqual(types[0], "started")
        self.assertIn("sentence", types)
        self.assertIn("finished", types)
        self.assertEqual(client.close_code, 1000)
        sentence_msgs = [m for m in client.sent if m["type"] == "sentence"]
        self.assertEqual(sentence_msgs[-1]["text"], "你好世界")
        self.assertEqual(sentence_msgs[-1]["words"], [{"text": "你好", "start": 0.0, "end": 0.5}])

    async def test_missing_api_key_surfaces_error(self):
        client = _FakeClientWs([
            {"text": json.dumps({"type": "config"})},
        ])
        with patch(
            "routers.transcription.build_streaming_asr_session",
            side_effect=ValueError("DashScope API key not configured."),
        ):
            await transcription_realtime_ws(client)
        error_msgs = [m for m in client.sent if m["type"] == "error"]
        self.assertEqual(len(error_msgs), 1)
        self.assertIn("DashScope API key", error_msgs[0]["message"])
        self.assertEqual(client.close_code, 1003)

    async def test_invalid_config_json_rejected(self):
        client = _FakeClientWs([
            {"text": "not-json"},
        ])
        await transcription_realtime_ws(client)
        error_msgs = [m for m in client.sent if m["type"] == "error"]
        self.assertEqual(len(error_msgs), 1)
        self.assertEqual(client.close_code, 1003)

    async def test_silent_client_hits_idle_timeout_and_closes(self):
        # Client sends config then goes quiet: no finish, no disconnect, and the
        # upstream (which only drains after finish) stays silent too. The handler
        # must not block forever — it should idle-timeout and close cleanly.
        client = _FakeClientWs([
            {"text": json.dumps({"type": "config"})},
        ])
        fake_session = _FakeSession([])
        with patch("routers.transcription.REALTIME_IDLE_TIMEOUT", 0.05), patch(
            "routers.transcription.build_streaming_asr_session",
            return_value=fake_session,
        ):
            await transcription_realtime_ws(client)

        types = [message["type"] for message in client.sent]
        self.assertEqual(types[0], "started")
        self.assertIn("finished", types)
        self.assertEqual(client.close_code, 1000)

    async def test_google_gemini_streaming_ws_flow(self):
        client = _FakeClientWs([
            {"text": json.dumps({"type": "config", "model": GEMINI_TRANSCRIBE_LIVE_MODEL})},
            {"bytes": b"\x10\x20"},
            {"text": json.dumps({"type": "finish"})},
        ])
        fake_session = _FakeSession([
            RealtimeAsrSentence(text="Live Google STT", sentence_end=True),
        ])

        with patch(
            "routers.transcription.build_streaming_asr_session",
            return_value=fake_session,
        ) as factory:
            await transcription_realtime_ws(client)

        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs.get("model"), GEMINI_TRANSCRIBE_LIVE_MODEL)
        self.assertEqual(fake_session.audio, [b"\x10\x20"])
        sentence_msgs = [m for m in client.sent if m["type"] == "sentence"]
        self.assertEqual(sentence_msgs[-1]["text"], "Live Google STT")


if __name__ == "__main__":
    unittest.main()
