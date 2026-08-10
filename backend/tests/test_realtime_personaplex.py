"""Tests for the PersonaPlex realtime voice provider mixin.

PersonaPlex talks to a local moshi server over a WebSocket that carries Opus
frames with a one-byte kind prefix.  These tests exercise the framing, the
settings/voice resolution, and the deliberate absence of interruption
arbitration — the model is natively full duplex.
"""

import asyncio
import unittest
from unittest.mock import patch

import numpy as np

from services.realtime_constants import (
    DEFAULT_PERSONAPLEX_REALTIME_MODEL,
    DEFAULT_PERSONAPLEX_REALTIME_VOICE,
    DEFAULT_PERSONAPLEX_SERVER_URL,
    PERSONAPLEX_REALTIME_VOICES,
    PERSONAPLEX_SAMPLE_RATE,
)
from services.realtime_personaplex_provider import (
    _MSG_AUDIO,
    _MSG_TEXT,
    OPUS_FRAME_SIZE,
    _float_to_pcm16,
    _pcm16_to_float,
    _resample_linear,
)
from services.realtime_voice_service import RealtimeVoiceService


class CollectingWebSocket:
    """Collects every JSON payload sent to the client."""

    def __init__(self, inbound: list[dict] | None = None) -> None:
        self.events: list[dict] = []
        self.inbound = list(inbound or [])

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))

    async def receive(self) -> dict:
        if self.inbound:
            return self.inbound.pop(0)
        return {"type": "websocket.disconnect"}


class FakeUpstream:
    """Fake moshi-server WebSocket yielding pre-baked binary messages."""

    def __init__(self, messages: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self._messages = list(messages or [])

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        import aiohttp

        if not self._messages:
            raise StopAsyncIteration
        payload = self._messages.pop(0)
        return type(
            "Msg", (), {"type": aiohttp.WSMsgType.BINARY, "data": payload}
        )()


class FakeOpusWriter:
    """Stands in for sphn.OpusStreamWriter — records PCM, emits fixed bytes.

    The real encoder raises on any length outside its allowed frame sizes, so
    this mock enforces the same rule; a lenient mock previously let a
    frame-misalignment bug reach production untested.
    """

    ALLOWED_FRAME_SIZES = (120, 240, 480, 960, 1920, 2880)

    def __init__(self) -> None:
        self.appended: list[np.ndarray] = []

    def append_pcm(self, pcm) -> None:
        frame = np.asarray(pcm)
        if frame.shape[-1] not in self.ALLOWED_FRAME_SIZES:
            raise ValueError(
                "pcm length has to match an allowed frame size "
                f"{list(self.ALLOWED_FRAME_SIZES)}, got {frame.shape[-1]}"
            )
        self.appended.append(frame)

    def read_bytes(self) -> bytes:
        return b"OPUS" if self.appended else b""


class FakeOpusReader:
    """Stands in for sphn.OpusStreamReader — returns one frame of PCM."""

    def __init__(self) -> None:
        self.appended: list[bytes] = []

    def append_bytes(self, payload: bytes) -> None:
        self.appended.append(payload)

    def read_pcm(self):
        if not self.appended:
            return None
        return np.full(240, 0.25, dtype=np.float32)


class FakeMemorySession:
    """Minimal RealtimeMemorySession stand-in — both methods are synchronous."""

    def __init__(self) -> None:
        self.assistant_texts: list[str] = []
        self.configured: list[dict | None] = []

    def configure(self, payload) -> None:
        self.configured.append(payload)

    def note_assistant_text(self, text: str) -> None:
        self.assistant_texts.append(text)

    async def flush_turn(self) -> dict:
        return {
            "enabled": False,
            "attempted_count": 0,
            "saved_count": 0,
            "failed_count": 0,
            "reason": "disabled_or_empty",
        }


class PersonaPlexAudioHelpersTest(unittest.TestCase):
    def test_pcm_roundtrip_preserves_amplitude(self):
        original = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
        restored = _pcm16_to_float(_float_to_pcm16(original))
        np.testing.assert_allclose(restored, original, atol=1e-4)

    def test_pcm16_clips_out_of_range_samples(self):
        raw = _float_to_pcm16(np.array([2.0, -2.0], dtype=np.float32))
        restored = _pcm16_to_float(raw)
        self.assertLessEqual(float(restored.max()), 1.0)
        self.assertGreaterEqual(float(restored.min()), -1.0)

    def test_resample_16k_to_24k_scales_length(self):
        pcm = np.zeros(1600, dtype=np.float32)  # 100 ms at 16 kHz
        out = _resample_linear(pcm, 16000, PERSONAPLEX_SAMPLE_RATE)
        self.assertEqual(out.shape[-1], 2400)  # 100 ms at 24 kHz

    def test_resample_is_a_noop_at_matching_rates(self):
        pcm = np.linspace(-1.0, 1.0, 480, dtype=np.float32)
        out = _resample_linear(pcm, PERSONAPLEX_SAMPLE_RATE, PERSONAPLEX_SAMPLE_RATE)
        self.assertIs(out, pcm)

    def test_resample_handles_empty_input(self):
        out = _resample_linear(np.zeros(0, dtype=np.float32), 16000, 24000)
        self.assertEqual(out.shape[-1], 0)


class PersonaPlexSettingsTest(unittest.TestCase):
    def setUp(self):
        self.service = RealtimeVoiceService()

    def test_defaults_resolve_to_local_moshi_server(self):
        settings = self.service._resolve_personaplex_settings(None)
        self.assertEqual(settings["model"], DEFAULT_PERSONAPLEX_REALTIME_MODEL)
        self.assertEqual(settings["server_url"], DEFAULT_PERSONAPLEX_SERVER_URL)

    def test_non_websocket_url_is_rejected(self):
        with patch.object(
            self.service.config,
            "get_provider_settings",
            return_value={"model": "m", "realtime_base_url": "http://127.0.0.1:8998"},
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self.service._resolve_personaplex_settings(None)
        self.assertIn("WebSocket", str(ctx.exception))

    def test_voice_names_get_a_pt_suffix(self):
        self.assertEqual(self.service._normalize_personaplex_voice("NATM1"), "NATM1.pt")

    def test_unknown_voice_falls_back_to_default(self):
        self.assertEqual(
            self.service._normalize_personaplex_voice("does-not-exist"),
            DEFAULT_PERSONAPLEX_REALTIME_VOICE,
        )
        self.assertEqual(
            self.service._normalize_personaplex_voice(None),
            DEFAULT_PERSONAPLEX_REALTIME_VOICE,
        )

    def test_default_voice_is_in_the_supported_list(self):
        self.assertIn(DEFAULT_PERSONAPLEX_REALTIME_VOICE, PERSONAPLEX_REALTIME_VOICES)


class PersonaPlexStreamingTest(unittest.TestCase):
    def setUp(self):
        self.service = RealtimeVoiceService()

    def test_client_audio_is_resampled_and_framed_as_opus(self):
        websocket = CollectingWebSocket(
            [{"type": "websocket.receive", "bytes": _float_to_pcm16(np.zeros(1600, dtype=np.float32))}]
        )
        upstream = FakeUpstream()
        writer = FakeOpusWriter()

        asyncio.run(
            self.service._client_to_personaplex_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_writer=writer,
            )
        )

        self.assertEqual(len(upstream.sent), 1)
        self.assertEqual(upstream.sent[0][0], _MSG_AUDIO)
        self.assertEqual(upstream.sent[0][1:], b"OPUS")
        # 100 ms at 16 kHz resamples to 2400 samples at 24 kHz, which is one
        # 1920-sample Opus frame plus a 480-sample remainder held back.
        self.assertEqual([f.shape[-1] for f in writer.appended], [OPUS_FRAME_SIZE])

    def test_partial_frames_are_carried_across_chunks(self):
        # Two 2400-sample chunks make 4800 samples: two full frames plus 960
        # carried over.  Without the carry buffer the encoder would reject both.
        chunk = {
            "type": "websocket.receive",
            "bytes": _float_to_pcm16(np.zeros(1600, dtype=np.float32)),
        }
        websocket = CollectingWebSocket([dict(chunk), dict(chunk)])
        upstream = FakeUpstream()
        writer = FakeOpusWriter()

        asyncio.run(
            self.service._client_to_personaplex_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_writer=writer,
            )
        )

        self.assertEqual(
            [f.shape[-1] for f in writer.appended],
            [OPUS_FRAME_SIZE, OPUS_FRAME_SIZE],
        )
        self.assertEqual(len(upstream.sent), 2)

    def test_a_chunk_shorter_than_one_frame_sends_nothing_yet(self):
        # 20 ms at 16 kHz is 480 samples at 24 kHz — below one frame, so it must
        # be buffered rather than truncated or padded.
        websocket = CollectingWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "bytes": _float_to_pcm16(np.zeros(320, dtype=np.float32)),
                }
            ]
        )
        upstream = FakeUpstream()
        writer = FakeOpusWriter()

        asyncio.run(
            self.service._client_to_personaplex_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_writer=writer,
            )
        )

        self.assertEqual(writer.appended, [])
        self.assertEqual(upstream.sent, [])

    def test_stop_command_ends_the_send_loop(self):
        websocket = CollectingWebSocket([{"type": "websocket.receive", "text": '{"type": "stop"}'}])
        upstream = FakeUpstream()

        asyncio.run(
            self.service._client_to_personaplex_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_writer=FakeOpusWriter(),
            )
        )
        self.assertEqual(upstream.sent, [])

    def test_ping_is_answered_with_pong(self):
        websocket = CollectingWebSocket([{"type": "websocket.receive", "text": '{"type": "ping"}'}])
        asyncio.run(
            self.service._client_to_personaplex_loop(
                websocket,
                FakeUpstream(),
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_writer=FakeOpusWriter(),
            )
        )
        self.assertEqual([e["type"] for e in websocket.events], ["pong"])

    def test_config_reports_memory_and_tools_as_unavailable(self):
        websocket = CollectingWebSocket(
            [{"type": "websocket.receive", "text": '{"type": "config", "memory": {"enabled": true}}'}]
        )
        memory_session = FakeMemorySession()

        asyncio.run(
            self.service._client_to_personaplex_loop(
                websocket,
                FakeUpstream(),
                memory_session=memory_session,
                recorder=None,
                opus_writer=FakeOpusWriter(),
            )
        )

        self.assertEqual(len(websocket.events), 1)
        event = websocket.events[0]
        self.assertEqual(event["type"], "memory_config")
        self.assertFalse(event["enabled"])

    def test_interruption_commands_are_ignored(self):
        # The model arbitrates barge-in itself, so the coordinator must stay
        # out of the loop entirely — no events, no upstream traffic.
        websocket = CollectingWebSocket(
            [
                {"type": "websocket.receive", "text": '{"type": "interruption_decision"}'},
                {"type": "websocket.receive", "text": '{"type": "interruption_pending"}'},
            ]
        )
        upstream = FakeUpstream()

        asyncio.run(
            self.service._client_to_personaplex_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_writer=FakeOpusWriter(),
            )
        )
        self.assertEqual(websocket.events, [])
        self.assertEqual(upstream.sent, [])

    def test_agent_audio_is_forwarded_at_the_model_sample_rate(self):
        websocket = CollectingWebSocket()
        upstream = FakeUpstream([bytes([_MSG_AUDIO]) + b"OPUS"])

        asyncio.run(
            self.service._personaplex_to_client_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_reader=FakeOpusReader(),
            )
        )

        audio_events = [e for e in websocket.events if e["type"] == "assistant_audio"]
        self.assertEqual(len(audio_events), 1)
        self.assertEqual(audio_events[0]["sample_rate"], PERSONAPLEX_SAMPLE_RATE)
        self.assertEqual(audio_events[0]["encoding"], "pcm_s16le")
        self.assertTrue(audio_events[0]["audio"])

    def test_text_tokens_are_batched_until_a_sentence_ends(self):
        websocket = CollectingWebSocket()
        upstream = FakeUpstream(
            [
                bytes([_MSG_TEXT]) + " Hello".encode("utf-8"),
                bytes([_MSG_TEXT]) + " there".encode("utf-8"),
                bytes([_MSG_TEXT]) + ".".encode("utf-8"),
            ]
        )

        asyncio.run(
            self.service._personaplex_to_client_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_reader=FakeOpusReader(),
            )
        )

        text_events = [e for e in websocket.events if e["type"] == "assistant_text"]
        self.assertEqual(len(text_events), 1)
        self.assertEqual(text_events[0]["text"], "Hello there.")

    def test_trailing_text_is_flushed_when_the_stream_ends(self):
        websocket = CollectingWebSocket()
        upstream = FakeUpstream([bytes([_MSG_TEXT]) + " unfinished".encode("utf-8")])

        asyncio.run(
            self.service._personaplex_to_client_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_reader=FakeOpusReader(),
            )
        )

        text_events = [e for e in websocket.events if e["type"] == "assistant_text"]
        self.assertEqual(len(text_events), 1)
        self.assertEqual(text_events[0]["text"], "unfinished")


class PersonaPlexTurnBoundaryTest(unittest.TestCase):
    """The model emits no end-of-turn marker, so it is derived from text idleness."""

    def setUp(self):
        self.service = RealtimeVoiceService()

    def test_turn_completes_when_the_text_stream_ends(self):
        websocket = CollectingWebSocket()
        upstream = FakeUpstream([bytes([_MSG_TEXT]) + " Hi.".encode("utf-8")])

        asyncio.run(
            self.service._personaplex_to_client_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_reader=FakeOpusReader(),
            )
        )

        types = [e["type"] for e in websocket.events]
        self.assertIn("turn_complete", types)
        # The transcript must be delivered before the turn is committed,
        # otherwise the frontend commits an empty bubble.
        self.assertLess(types.index("assistant_text"), types.index("turn_complete"))

    def test_audio_only_output_does_not_open_a_turn(self):
        # Without text tokens there is nothing to commit, so no turn_complete.
        websocket = CollectingWebSocket()
        upstream = FakeUpstream([bytes([_MSG_AUDIO]) + b"OPUS"])

        asyncio.run(
            self.service._personaplex_to_client_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_reader=FakeOpusReader(),
            )
        )

        types = [e["type"] for e in websocket.events]
        self.assertIn("assistant_audio", types)
        self.assertNotIn("turn_complete", types)

    def test_only_one_turn_completes_per_utterance(self):
        websocket = CollectingWebSocket()
        upstream = FakeUpstream(
            [
                bytes([_MSG_TEXT]) + " One.".encode("utf-8"),
                bytes([_MSG_TEXT]) + " Two.".encode("utf-8"),
            ]
        )

        asyncio.run(
            self.service._personaplex_to_client_loop(
                websocket,
                upstream,
                memory_session=FakeMemorySession(),
                recorder=None,
                opus_reader=FakeOpusReader(),
            )
        )

        types = [e["type"] for e in websocket.events]
        self.assertEqual(types.count("turn_complete"), 1)


if __name__ == "__main__":
    unittest.main()
