"""Qwen 3.8 protocol regressions using official event shapes, without network calls."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.realtime_constants import _is_dashscope_live_translate_model
from services.realtime_dashscope_client import DashScopeLiveTranslateConversation, DashScopeRealtimeCallback
from services.realtime_memory_session import RealtimeMemorySession
from services.realtime_voice_service import RealtimeVoiceService

MODEL = "qwen3.8-livetranslate-flash-realtime"


@pytest.mark.parametrize("model,expected", [(MODEL, True), (MODEL.upper(), True),
    (MODEL + "-fake", False), (MODEL.replace("flash", "plus"), False)])
def test_detection(model, expected):
    assert _is_dashscope_live_translate_model(model) is expected


@pytest.mark.parametrize("clone,voice,frequency", [
    (False, "Tina", "once"), (True, "Tina", "always"),
    (False, "qwen-translate-vc-example", "once"),
])
def test_session_payload(clone, voice, frequency):
    conversation = DashScopeLiveTranslateConversation(
        model=MODEL, api_key="test", url="wss://example/api-ws/v1/realtime", callback=None)
    sent = []
    conversation._send_event = sent.append
    conversation.update_session(voice=voice, enable_voice_clone=clone,
        voice_clone_frequency=frequency, target_language="ja", modalities=["text"],
        corpus_phrases={"Echo": "Echo"})
    session = sent[0]["session"]
    assert session["output_modalities"] == ["text"]
    assert session["translation"] == {"language": "ja", "corpus": {"phrases": {"Echo": "Echo"}}}
    assert not set(session).intersection({"modalities", "voice", "input_audio_transcription",
        "input_audio_format", "output_audio_format", "turn_detection"})
    assert session["audio"]["input"]["format"]["sample_rate"] == 16000
    assert session["audio"]["output"]["format"]["sample_rate"] == 24000
    assert session["audio"]["output"]["voice"] == ("default" if clone else voice)
    # Turn detection must be sent explicitly: the server default (2500 ms of
    # silence) held an utterance open seconds after the speaker stopped.
    turn_detection = session["audio"]["input"]["turn_detection"]
    assert turn_detection["type"] == "speaker_detection"
    assert turn_detection["silence_duration_ms"] == 500
    assert 200 <= turn_detection["silence_duration_ms"] <= 6000
    if clone or voice.startswith("qwen-translate-vc-"):
        assert session["enable_voice_clone"] is True
        assert session["voice_clone_options"]["frequency"] == (frequency if clone else "never")


class _RecordingStub:
    """Minimal recorder surface used by the LiveTranslate event loop."""

    def __init__(self):
        self.calls = []

    async def note_user_transcript(self, text, *, turn_id=""):
        self.calls.append(("user", str(text)))
        return "turn-1"

    async def note_assistant_text(self, text, *, cumulative=False):
        self.calls.append(("assistant", str(text)))
        return "turn-1"

    async def note_assistant_audio(self):
        return "turn-1", None

    async def complete_turn(self, memory_payload=None):
        self.calls.append(("complete", dict(memory_payload or {})))
        return "turn-1"


@pytest.mark.parametrize("incremental_asr,expected", [(False, ["你好世界"]), (True, ["你好", "世界"])])
def test_incremental_asr_mapping_is_scoped_to_the_translation_protocol(incremental_asr, expected):
    """Qwen-Omni reuses the delta event name with a {text, stash} payload.

    Mapping those interim frames into user_transcript made the omni turn owner
    treat every ASR frame as a completed user utterance (empty transcript ->
    interruption pipeline + recorder write).
    """

    async def run():
        queue = asyncio.Queue()
        callback = DashScopeRealtimeCallback(
            loop=asyncio.get_running_loop(), queue=queue, incremental_asr=incremental_asr
        )
        for frame in (
            {"type": "conversation.item.input_audio_transcription.delta",
             "text": "你好", "stash": "世界", "item_id": "i1"},
            {"type": "conversation.item.input_audio_transcription.delta",
             "delta": "你好", "item_id": "i1"},
            {"type": "conversation.item.input_audio_transcription.delta",
             "delta": "世界", "item_id": "i1"},
        ):
            callback.on_event(frame)
        await asyncio.sleep(0)
        pushed = []
        while not queue.empty():
            pushed.append(queue.get_nowait())
        assert [event["text"] for event in pushed] == expected
        expected_type = "user_transcript" if incremental_asr else "user_transcript_preview"
        assert all(event["type"] == expected_type for event in pushed)

    asyncio.run(run())


def test_source_utterance_is_recorded_into_its_translation_turn():
    """3.8 omits per-utterance transcription `completed`, so the recorder was
    left without the user's source text (and without a turn id)."""

    async def run():
        queue = asyncio.Queue()
        recorder = _RecordingStub()
        callback = DashScopeRealtimeCallback(
            loop=asyncio.get_running_loop(), queue=queue, incremental_asr=True
        )
        output = []
        ws = SimpleNamespace(send_json=AsyncMock(side_effect=output.append))
        for event in (
            {"type": "conversation.item.input_audio_transcription.delta",
             "delta": "你好", "item_id": "i1"},
            {"type": "conversation.item.input_audio_transcription.delta",
             "delta": "，世界", "item_id": "i1"},
            {"type": "input_audio_buffer.speech_stopped", "item_id": "i1"},
            {"type": "response.text.delta", "delta": "Hello", "response_id": "r1"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
            {"type": "session.finished"},
        ):
            callback.on_event(event)
        await asyncio.sleep(0)
        await RealtimeVoiceService()._dashscope_live_translate_to_client_loop(
            ws, queue, RealtimeMemorySession(), recorder=recorder,
            callback=callback, incremental_protocol=True,
        )
        assert [c for c in recorder.calls if c[0] == "user"] == [("user", "你好，世界")]
        # The source utterance is backfilled into the turn the translation
        # opened, immediately before that turn is closed.
        assert recorder.calls[-2:] == [("user", "你好，世界"), ("complete", {})]
        text_index = [e["type"] for e in output].index("assistant_text")
        turn_index = [e["type"] for e in output].index("turn_complete")
        assert text_index < turn_index
        assert output[turn_index]["turn_id"] == "turn-1"

    asyncio.run(run())


def test_utterance_without_a_translation_is_recorded_on_close():
    async def run():
        queue = asyncio.Queue()
        recorder = _RecordingStub()
        callback = DashScopeRealtimeCallback(
            loop=asyncio.get_running_loop(), queue=queue, incremental_asr=True
        )
        ws = SimpleNamespace(send_json=AsyncMock())
        for event in (
            {"type": "conversation.item.input_audio_transcription.delta",
             "delta": "谢谢", "item_id": "i1"},
            {"type": "conversation.item.input_audio_transcription.delta",
             "delta": "，再见", "item_id": "i1"},
        ):
            callback.on_event(event)
        # An abrupt socket close (no session.finish) still has to record the
        # utterance that was captured but never translated.
        callback.on_close(1000, "")
        await asyncio.sleep(0)
        await RealtimeVoiceService()._dashscope_live_translate_to_client_loop(
            ws, queue, RealtimeMemorySession(), recorder=recorder,
            callback=callback, incremental_protocol=True,
        )
        assert recorder.calls[0] == ("user", "谢谢，再见")
        assert recorder.calls[1] == ("complete", {})

    asyncio.run(run())


def test_multi_sentence_source_items_are_recorded_in_arrival_order():
    async def run():
        queue = asyncio.Queue()
        recorder = _RecordingStub()
        callback = DashScopeRealtimeCallback(
            loop=asyncio.get_running_loop(), queue=queue, incremental_asr=True
        )
        output = []
        ws = SimpleNamespace(send_json=AsyncMock(side_effect=output.append))
        # No speech_stopped frames at all: the next item's first delta closes
        # the previous utterance.
        for event in (
            {"type": "conversation.item.input_audio_transcription.delta",
             "delta": "第一句", "item_id": "i1"},
            {"type": "conversation.item.input_audio_transcription.delta",
             "delta": "第二句", "item_id": "i2"},
            {"type": "response.text.delta", "delta": "First", "response_id": "r1"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
            {"type": "response.text.delta", "delta": "Second", "response_id": "r2"},
            {"type": "response.done", "response": {"id": "r2", "status": "completed"}},
            {"type": "session.finished"},
        ):
            callback.on_event(event)
        await asyncio.sleep(0)
        await RealtimeVoiceService()._dashscope_live_translate_to_client_loop(
            ws, queue, RealtimeMemorySession(), recorder=recorder,
            callback=callback, incremental_protocol=True,
        )
        assert [c for c in recorder.calls if c[0] == "user"] == [
            ("user", "第一句"), ("user", "第二句")
        ]

    asyncio.run(run())


@pytest.mark.parametrize("text_event", ["response.text.delta", "response.audio_transcript.delta"])
def test_delta_stream_preserves_repetition_whitespace_and_audio_order(text_event):
    async def run():
        queue = asyncio.Queue()
        callback = DashScopeRealtimeCallback(
            loop=asyncio.get_running_loop(), queue=queue, incremental_asr=True
        )
        output = []
        ws = SimpleNamespace(send_json=AsyncMock(side_effect=output.append))
        # Repetition is meaningful; neither prefix merging nor dedup may drop it.
        raw = [
            {"type": "conversation.item.input_audio_transcription.delta", "delta": "Bye", "item_id": "i1"},
            {"type": "conversation.item.input_audio_transcription.delta", "delta": " bye", "item_id": "i1"},
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Bye bye", "item_id": "i1"},
            *[{"type": text_event, "delta": text, "response_id": "r1"} for text in ["ha", "ha", " ", "世界"]],
            {"type": "response.audio_transcript.done", "transcript": "haha 世界", "response_id": "r1"},
            {"type": "response.audio.delta", "delta": "AAAA", "response_id": "r1"},
            {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
            {"type": "conversation.item.input_audio_transcription.delta", "delta": "Bye", "item_id": "i2"},
            {"type": "session.finished"},
        ]
        for event in raw:
            callback.on_event(event)
        await asyncio.sleep(0)
        # Use the real emitter and no recorder: exercises the public wire contract.
        await RealtimeVoiceService()._dashscope_live_translate_to_client_loop(
            ws, queue, RealtimeMemorySession(), incremental_protocol=True)
        assert "".join(e["text"] for e in output if e["type"] == "assistant_text") == "haha 世界"
        sources = [e for e in output if e["type"] == "user_transcript"]
        assert [e["text"] for e in sources] == ["Bye", "Bye bye", "Bye bye", "Bye"]
        assert sources[2]["item_id"] == "i1" and sources[2]["final"] is True
        assert sources[-1]["item_id"] == "i2"
        types = [e["type"] for e in output]
        assert types.index("assistant_audio") < types.index("turn_complete")
    asyncio.run(run())


@pytest.mark.parametrize("configure_error", [False, True])
def test_session_waits_for_configuration_and_drains_on_stop(configure_error):
    async def run():
        output = []
        instances = []
        class Conversation:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                self.finished = 0
                self.closed = False
                instances.append(self)
            async def connect(self):
                pass
            def update_session(self, **kwargs):
                assert not output
                self.callback.on_event({"type": "error", "error": {"message": "bad config"}}
                    if configure_error else {"type": "session.updated"})
            def finish_session(self):
                self.finished += 1
                self.callback.on_event({"type": "response.text.delta", "delta": "final segment"})
                self.callback.on_event({"type": "session.finished"})
            def close(self):
                self.closed = True
        ws = SimpleNamespace(send_json=AsyncMock(side_effect=output.append),
            receive=AsyncMock(return_value={"text": '{"type":"stop"}'}))
        svc = RealtimeVoiceService()
        svc._create_voice_session_recorder = AsyncMock(return_value=None)
        with patch("services.realtime_dashscope_provider.DashScopeLiveTranslateConversation", Conversation):
            await svc._stream_dashscope_live_translate_session(ws,
                settings={"model": MODEL, "api_key": "test", "realtime_base_url": "wss://example"},
                voice="Tina", translation_mode="unidirectional", source_language_code="zh",
                target_language_code="en", echo_target_language=False)
        assert instances[0].closed and instances[0].finished == 1
        if configure_error:
            assert not any(e["type"] == "session_open" for e in output)
            assert any("bad config" in e.get("message", "") for e in output)
        else:
            assert output[0]["type"] == "session_open"
            assert any(e.get("text") == "final segment" for e in output)
    asyncio.run(run())
