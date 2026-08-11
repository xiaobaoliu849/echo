"""Tests for the GLM-4-Voice S2S server's VAD and history trimming.

These guard the turn-latency work: the standalone ``glm4voice_s2s_server.py``
decides *when* a turn fires and *how much* audio/history reaches the (slow,
int4-quantized) 9B worker.  Both directly set the wait the user feels.

The controller polls ``turn_ready()`` on every read tick, and that call is what
trims the buffer in place -- feeding audio without polling is not a real code
path, so ``_feed`` below mirrors the controller loop.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "glm4voice_s2s_server", PROJECT_ROOT / "glm4voice_s2s_server.py"
)
s2s = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(s2s)


def _pcm(seconds: float, amplitude: float, rs: np.random.RandomState) -> bytes:
    """PCM16 mono at the server's sample rate; amplitude 0 means pure silence."""
    n = int(s2s.SAMPLE_RATE * seconds)
    samples = np.zeros(n) if amplitude == 0 else rs.randn(n) * amplitude
    return samples.astype(np.int16).tobytes()


class Glm4VoiceVadTest(unittest.TestCase):
    SPEECH = 4000  # comfortably above the default 900 RMS threshold
    QUIET = 0

    def setUp(self) -> None:
        self.rs = np.random.RandomState(0)
        self.state = s2s.ConversationState("system")

    def _feed(self, seconds: float, amplitude: float, chunk: float = 0.10) -> bool:
        """Feed audio the way the reader/controller pair does, polling each tick."""
        fired = False
        for _ in range(max(1, int(round(seconds / chunk)))):
            self.state.feed_audio(_pcm(chunk, amplitude, self.rs))
            if self.state.turn_ready():
                fired = True
        return fired

    def _buffered_seconds(self) -> float:
        return len(self.state.buffer) / 2 / s2s.SAMPLE_RATE

    def test_idle_silence_does_not_grow_the_buffer(self):
        """A caller who says nothing must not accumulate audio to tokenize."""
        self.assertFalse(self._feed(60.0, self.QUIET))
        self.assertLessEqual(self._buffered_seconds(), s2s.VAD_PREROLL_S + 0.15)

    def test_leading_silence_is_trimmed_from_the_utterance(self):
        """Only speech (plus a short pre-roll) should reach the encoder."""
        self._feed(30.0, self.QUIET)
        self._feed(1.2, self.SPEECH)
        self.assertTrue(self._feed(0.6, self.QUIET))

        utterance = self.state.take_utterance()
        duration = len(utterance) / 2 / s2s.SAMPLE_RATE
        # 1.2s speech + <=0.25s pre-roll + the trailing silence that closed it,
        # nowhere near the 31.8s that was actually fed in.
        self.assertGreater(duration, 1.2)
        self.assertLess(duration, 2.4)

    def test_turn_does_not_fire_before_trailing_silence(self):
        """Firing early would cut the user off mid-sentence."""
        self._feed(30.0, self.QUIET)
        self.assertFalse(self._feed(1.2, self.SPEECH))
        self.assertFalse(self._feed(0.2, self.QUIET))

    def test_isolated_click_does_not_fire_a_turn(self):
        self.state.feed_audio(_pcm(0.06, 9000, self.rs))
        self.state.turn_ready()
        self.assertFalse(self._feed(1.5, self.QUIET))

    def test_scattered_blips_do_not_accumulate_into_a_turn(self):
        """Guards the over-sensitivity bug: speech must be *consecutive*.

        Summing total speech frames let unrelated 40ms taps (keystrokes, a
        creaking chair) add up past ``min_speech_s`` and fire a bogus turn.  The
        gaps here exceed ``trail_silence_s``, so under the old total-frame count
        the turn really did close -- consecutive counting is what prevents it.
        """
        fired = False
        for _ in range(12):
            fired = self._feed(0.04, self.SPEECH, chunk=0.04) or fired
            fired = self._feed(0.60, self.QUIET) or fired
        total_speech = 12 * 0.04
        self.assertGreater(total_speech, s2s.VAD_MIN_SPEECH_S)  # would fire if summed
        self.assertFalse(fired)

    def test_continuous_speech_is_force_closed_at_the_cap(self):
        self.assertTrue(self._feed(20.0, self.SPEECH))

    def test_utterance_is_capped_before_reaching_the_encoder(self):
        self._feed(40.0, self.SPEECH)
        sent = len(self.state.take_utterance()) / 2 / s2s.SAMPLE_RATE
        self.assertLessEqual(sent, s2s.VAD_MAX_UTTERANCE_S + 0.01)

    def test_muted_state_drops_audio_entirely(self):
        """While the assistant speaks, its own echo must not become a turn."""
        self.state.muted = True
        self.assertFalse(self._feed(3.0, 6000))
        self.assertEqual(len(self.state.buffer), 0)

    def test_clear_resets_buffer_and_turn_tracking(self):
        self._feed(1.0, self.SPEECH)
        self.state.clear()
        self.assertEqual(len(self.state.buffer), 0)
        self.assertEqual(self.state.speech_s, 0.0)
        self.assertEqual(self.state.trailing_silence_s, 0.0)

    def test_vad_config_overrides_are_honoured(self):
        """The CLI tuning flags must actually reach the VAD."""
        vad = s2s.VadConfig()
        vad.threshold = 10_000_000  # nothing counts as speech
        self.state = s2s.ConversationState("system", vad)
        self.assertFalse(self._feed(3.0, self.SPEECH))


class Glm4VoiceHistoryTrimTest(unittest.TestCase):
    """Prompt growth is the reason latency crept up across a conversation."""

    def _prompt(self, turns: int) -> str:
        return "<|system|>\nSYS" + "".join(
            f"<|user|>\nU{i}<|assistant|>A{i}\n" for i in range(turns)
        )

    def test_keeps_system_header_and_newest_turns(self):
        trimmed = s2s.Glm4VoicePipeline._trim_history(self._prompt(9), 3)
        self.assertEqual(trimmed.count("<|user|>"), 3)
        self.assertIn("SYS", trimmed)
        self.assertIn("U8", trimmed)
        self.assertNotIn("U0", trimmed)

    def test_zero_means_unbounded(self):
        prompt = self._prompt(9)
        self.assertEqual(s2s.Glm4VoicePipeline._trim_history(prompt, 0), prompt)

    def test_short_history_is_untouched(self):
        prompt = self._prompt(2)
        self.assertEqual(s2s.Glm4VoicePipeline._trim_history(prompt, 4), prompt)


if __name__ == "__main__":
    unittest.main()
