import unittest
from services.interruption_classifier import (
    InterruptionClassifier,
    InterruptionDecisionCoordinator,
    InterruptionIntent,
)

class TestInterruptionClassifier(unittest.TestCase):
    def test_noise_or_silence(self):
        self.assertEqual(InterruptionClassifier.classify_interruption(""), InterruptionIntent.NOISE_OR_SILENCE)
        self.assertEqual(InterruptionClassifier.classify_interruption("   "), InterruptionIntent.NOISE_OR_SILENCE)
        self.assertEqual(InterruptionClassifier.classify_interruption("。，！？"), InterruptionIntent.NOISE_OR_SILENCE)
        self.assertEqual(InterruptionClassifier.classify_interruption("我"), InterruptionIntent.NOISE_OR_SILENCE)
        self.assertEqual(InterruptionClassifier.classify_interruption("的"), InterruptionIntent.NOISE_OR_SILENCE)
        self.assertEqual(InterruptionClassifier.classify_interruption("个"), InterruptionIntent.NOISE_OR_SILENCE)

    def test_backchannel(self):
        self.assertEqual(InterruptionClassifier.classify_interruption("嗯"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("嗯嗯"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("哦哦！"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("对的。"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("是的"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("ok"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("确实"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("原来如此"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("That"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("I"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("Hello"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("Yeah sure"), InterruptionIntent.BACKCHANNEL)
        self.assertEqual(InterruptionClassifier.classify_interruption("I see"), InterruptionIntent.BACKCHANNEL)

    def test_true_barge_in(self):
        self.assertEqual(InterruptionClassifier.classify_interruption("等一下"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("停"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("别"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("等"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("不要这个"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("换一个话题"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("你刚才说什么"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("不对"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("stop"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("hold on"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("be quiet"), InterruptionIntent.TRUE_BARGE_IN)
        self.assertEqual(InterruptionClassifier.classify_interruption("Can I know what is your name"), InterruptionIntent.TRUE_BARGE_IN)

    def test_structured_rule_and_two_phase_latency(self):
        clock_values = iter((5.0, 5.125))
        coordinator = InterruptionDecisionCoordinator(clock=lambda: next(clock_values))
        pending = coordinator.begin(
            provider="OpenAI",
            interrupted_turn_id="voice-turn-1",
            provider_event_type="input_audio_buffer.speech_started",
        )
        decision = coordinator.decide("嗯嗯")

        self.assertEqual(pending["candidate_id"], "interruption-1")
        self.assertEqual(decision["classification"], "BACKCHANNEL")
        self.assertEqual(decision["decision"], "resume")
        self.assertTrue(str(decision["rule"]).startswith("backchannel_pattern:"))
        self.assertEqual(decision["decision_latency_ms"], 125)
        self.assertIsNotNone(coordinator.pending)
        self.assertIsNone(coordinator.decide("等一下"))

        coordinator.complete_decision()
        self.assertIsNone(coordinator.pending)

    def test_deferred_terminal_clears_shared_active_response(self):
        clock_values = iter((8.0, 8.25))
        coordinator = InterruptionDecisionCoordinator(clock=lambda: next(clock_values))
        coordinator.active_response_id = "response-1"
        coordinator.begin(provider="DashScope", interrupted_turn_id="voice-turn-1")
        coordinator.defer_terminal({"type": "turn_complete", "response_id": "response-1"})
        coordinator.decide("")
        coordinator.complete_decision()

        self.assertIsNotNone(coordinator.take_deferred_terminal())
        self.assertEqual(coordinator.active_response_id, "")

    def test_only_recent_same_provider_transcript_supersedes_timeout(self):
        now = [10.0]
        coordinator = InterruptionDecisionCoordinator(clock=lambda: now[0])
        first = coordinator.begin(provider="OpenAI", provider_event_type="speech_started")
        self.assertEqual(first["candidate_id"], "interruption-1")
        now[0] = 12.5
        coordinator.decide("")
        coordinator.complete_decision(timed_out=True)

        now[0] = 13.0
        late = coordinator.begin(
            provider="OpenAI",
            provider_event_type="transcript_without_vad",
            supersede_timed_out=True,
        )
        self.assertEqual(late["supersedes_candidate_id"], "interruption-1")
        coordinator.decide("等一下")
        coordinator.complete_decision()

        now[0] = 20.0
        second = coordinator.begin(provider="Google", provider_event_type="speech_started")
        coordinator.decide("")
        coordinator.complete_decision(timed_out=True)
        now[0] = 20.1
        wrong_provider = coordinator.begin(
            provider="OpenAI",
            provider_event_type="transcript_without_vad",
            supersede_timed_out=True,
        )
        self.assertNotIn("supersedes_candidate_id", wrong_provider)


class TestThreeLayerInterruptionRules(unittest.TestCase):
    """Direction-A three-layer rules: explicit command > backchannel > length fallback.

    Regression target: the assistant must NOT be cut off when the user has only said a
    short opener such as "喽" / "那个" / "我想想", while explicit interrupt commands and
    substantial utterances still interrupt immediately.
    """

    # ---- Layer 1: explicit barge-in commands always interrupt ------------------

    def test_explicit_commands_interrupt_even_when_short(self):
        for text in ["停", "停下", "别说了", "别讲了", "打住", "等等", "等一下",
                     "闭嘴", "安静", "算了", "不用说了", "stop", "wait"]:
            with self.subTest(text=text):
                self.assertEqual(
                    InterruptionClassifier.classify_interruption(text),
                    InterruptionIntent.TRUE_BARGE_IN,
                    f"{text!r} should be an explicit barge-in",
                )

    def test_short_negation_correction_interrupts(self):
        """Short negation/correction words express clear intent to redirect."""
        for text in ["不对", "错", "错了", "不是", "没有", "不要", "换个话题"]:
            with self.subTest(text=text):
                self.assertEqual(
                    InterruptionClassifier.classify_interruption(text),
                    InterruptionIntent.TRUE_BARGE_IN,
                    f"{text!r} should interrupt (negation/correction)",
                )

    # ---- Layer 2: fillers / openers / thinking-aloud never interrupt -----------

    def test_openers_and_fillers_do_not_interrupt(self):
        """The reported bug: '喽' must NOT cut off the assistant mid-sentence."""
        for text in ["喽", "呃", "额", "欸", "哎", "唉", "那个", "就是", "就是说",
                     "我想", "我想想", "让我想想", "这个", "然后呢", "喂", "在吗",
                     "听着", "说实话", "其实", "怎么说呢"]:
            with self.subTest(text=text):
                self.assertEqual(
                    InterruptionClassifier.classify_interruption(text),
                    InterruptionIntent.BACKCHANNEL,
                    f"{text!r} should NOT interrupt (opener/filler)",
                )

    def test_original_backchannels_still_do_not_interrupt(self):
        for text in ["嗯", "嗯嗯", "哦", "啊", "对", "好的", "是的", "确实",
                     "没毛病", "ok", "我知道了", "明白", "原来如此"]:
            with self.subTest(text=text):
                self.assertEqual(
                    InterruptionClassifier.classify_interruption(text),
                    InterruptionIntent.BACKCHANNEL,
                    f"{text!r} should remain a backchannel",
                )

    # ---- Layer 3: length fallback ----------------------------------------------

    def test_short_unknown_utterance_does_not_interrupt(self):
        """Unknown short utterances (< 4 effective chars) are treated as unfinished."""
        for text in ["哈喽", "嗨嗨", "耶耶", "咋了"]:
            with self.subTest(text=text):
                self.assertEqual(
                    InterruptionClassifier.classify_interruption(text),
                    InterruptionIntent.BACKCHANNEL,
                    f"{text!r} (too short) should NOT interrupt",
                )

    def test_substantial_utterance_interrupts(self):
        """Utterances with >= 4 effective chars carry a full intent and interrupt."""
        for text in ["你先别说了", "我问你个事情", "这个不太对吧", "帮我也查一下"]:
            with self.subTest(text=text):
                self.assertEqual(
                    InterruptionClassifier.classify_interruption(text),
                    InterruptionIntent.TRUE_BARGE_IN,
                    f"{text!r} (substantial) should interrupt",
                )

    def test_length_boundary_exactly_at_threshold(self):
        """4 effective chars (== threshold) is substantial; 3 chars is not."""
        self.assertEqual(
            InterruptionClassifier.classify_interruption("问问你呀"),  # 4 chars
            InterruptionIntent.TRUE_BARGE_IN,
        )
        self.assertEqual(
            InterruptionClassifier.classify_interruption("问问你"),  # 3 chars
            InterruptionIntent.BACKCHANNEL,
        )

    def test_punctuation_stripped_before_length_check(self):
        """Punctuation/whitespace must not count toward the length threshold."""
        # "嗯。。。" -> "嗯" (backchannel), not counted as 4 chars.
        self.assertEqual(
            InterruptionClassifier.classify_interruption("嗯。。。"),
            InterruptionIntent.BACKCHANNEL,
        )
        # "问 问 你 呀！！" -> "问问你呀" (4 effective chars) -> substantial.
        self.assertEqual(
            InterruptionClassifier.classify_interruption("问 问 你 呀！！"),
            InterruptionIntent.TRUE_BARGE_IN,
        )
