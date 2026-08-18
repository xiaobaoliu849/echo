import asyncio
import re
import time
from dataclasses import dataclass
from enum import Enum
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

class InterruptionIntent(str, Enum):
    TRUE_BARGE_IN = "TRUE_BARGE_IN"
    BACKCHANNEL = "BACKCHANNEL"
    NOISE_OR_SILENCE = "NOISE_OR_SILENCE"


@dataclass(frozen=True)
class InterruptionClassification:
    intent: InterruptionIntent
    rule: str


@dataclass(frozen=True)
class PendingInterruption:
    candidate_id: str
    provider: str
    interrupted_turn_id: str
    provider_event_type: str
    started_at: float
    supersedes_candidate_id: str = ""


@dataclass(frozen=True)
class TimedOutInterruption:
    candidate_id: str
    provider: str
    timed_out_at: float


class InterruptionDecisionCoordinator:
    """Provider-neutral state for the detect -> transcribe -> decide flow."""

    _MAX_BUFFERED_OUTPUT_EVENTS = 256
    _TIMED_OUT_SUPERSESSION_WINDOW_SECONDS = 5.0

    def __init__(self, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._candidate_index = 0
        self._pending: PendingInterruption | None = None
        self._buffered_output: list[dict[str, object]] = []
        self._deferred_terminal: dict[str, object] | None = None
        self._active_response_id = ""
        self._resolving = False
        self._decision_at: float | None = None
        self._resume_provider: Callable[[], Awaitable[None]] | None = None
        self._last_timed_out: TimedOutInterruption | None = None
        self.decision_lock = asyncio.Lock()
        self.output_lock = asyncio.Lock()

    @property
    def pending(self) -> PendingInterruption | None:
        return self._pending

    @property
    def active_response_id(self) -> str:
        return self._active_response_id

    @active_response_id.setter
    def active_response_id(self, response_id: str) -> None:
        self._active_response_id = str(response_id or "")

    @property
    def resume_provider(self) -> Callable[[], Awaitable[None]] | None:
        return self._resume_provider

    def set_resume_provider(self, callback: Callable[[], Awaitable[None]] | None) -> None:
        self._resume_provider = callback

    def begin(
        self,
        *,
        provider: str,
        interrupted_turn_id: str = "",
        provider_event_type: str = "speech_started",
        supersede_timed_out: bool = False,
    ) -> dict[str, object] | None:
        if self._pending is not None:
            return None
        self._candidate_index += 1
        self._buffered_output = []
        self._deferred_terminal = None
        self._decision_at = None
        now = self._clock()
        last_timed_out = self._last_timed_out
        can_supersede = bool(
            supersede_timed_out
            and last_timed_out is not None
            and last_timed_out.provider == str(provider or "")
            and 0 <= now - last_timed_out.timed_out_at <= self._TIMED_OUT_SUPERSESSION_WINDOW_SECONDS
        )
        supersedes_candidate_id = last_timed_out.candidate_id if can_supersede and last_timed_out else ""
        self._last_timed_out = None
        self._pending = PendingInterruption(
            candidate_id=f"interruption-{self._candidate_index}",
            provider=str(provider or ""),
            interrupted_turn_id=str(interrupted_turn_id or ""),
            provider_event_type=str(provider_event_type or "speech_started"),
            started_at=now,
            supersedes_candidate_id=supersedes_candidate_id,
        )
        payload: dict[str, object] = {
            "candidate_id": self._pending.candidate_id,
            "provider": self._pending.provider,
            "interrupted_turn_id": self._pending.interrupted_turn_id,
            "provider_event_type": self._pending.provider_event_type,
        }
        if supersedes_candidate_id:
            payload["supersedes_candidate_id"] = supersedes_candidate_id
        return payload

    def buffer_output(self, event: dict[str, object]) -> None:
        if self._pending is not None:
            self._buffered_output.append(dict(event))
            if len(self._buffered_output) > self._MAX_BUFFERED_OUTPUT_EVENTS:
                self._buffered_output.pop(0)

    def take_buffered_output(self) -> list[dict[str, object]]:
        buffered = self._buffered_output
        self._buffered_output = []
        return buffered

    def discard_buffered_output(self) -> None:
        self._buffered_output = []

    def defer_terminal(self, event: dict[str, object]) -> bool:
        if self._pending is None:
            return False
        self._deferred_terminal = dict(event)
        return True

    def has_deferred_terminal(self) -> bool:
        return self._deferred_terminal is not None

    def take_deferred_terminal(self) -> dict[str, object] | None:
        terminal = self._deferred_terminal
        self._deferred_terminal = None
        self._clear_terminal_response(terminal)
        return terminal

    def discard_deferred_terminal(self) -> None:
        self._clear_terminal_response(self._deferred_terminal)
        self._deferred_terminal = None

    def _clear_terminal_response(self, terminal: dict[str, object] | None) -> None:
        if not terminal:
            return
        response_id = str(terminal.get("response_id", "") or "")
        if not response_id:
            response = terminal.get("response")
            if isinstance(response, dict):
                response_id = str(response.get("id", "") or "")
        if self._active_response_id and (
            not response_id
            or self._active_response_id == "active"
            or response_id == self._active_response_id
        ):
            self._active_response_id = ""

    def complete_decision(self, *, timed_out: bool = False) -> None:
        pending = self._pending
        if timed_out and pending is not None:
            self._last_timed_out = TimedOutInterruption(
                candidate_id=pending.candidate_id,
                provider=pending.provider,
                timed_out_at=self._decision_at if self._decision_at is not None else pending.started_at,
            )
        elif pending is not None and pending.supersedes_candidate_id:
            self._last_timed_out = None
        self._pending = None
        self._resolving = False
        self._decision_at = None
        self._resume_provider = None

    def decide(self, text: str) -> dict[str, object] | None:
        pending = self._pending
        if pending is None or self._resolving:
            return None
        self._resolving = True
        classification = InterruptionClassifier.classify_with_rule(text)
        self._decision_at = self._clock()
        elapsed_ms = max(0, int((self._decision_at - pending.started_at) * 1000))
        action = {
            InterruptionIntent.TRUE_BARGE_IN: "cancel",
            InterruptionIntent.BACKCHANNEL: "resume",
            InterruptionIntent.NOISE_OR_SILENCE: "ignore",
        }[classification.intent]
        decision: dict[str, object] = {
            "candidate_id": pending.candidate_id,
            "classification": classification.intent.value,
            "rule": classification.rule,
            "decision": action,
            "transcript": str(text or "").strip(),
            "provider": pending.provider,
            "interrupted_turn_id": pending.interrupted_turn_id,
            "provider_event_type": pending.provider_event_type,
            "elapsed_ms": elapsed_ms,
            "decision_latency_ms": elapsed_ms,
        }
        if pending.supersedes_candidate_id:
            decision["supersedes_candidate_id"] = pending.supersedes_candidate_id
        return decision

class InterruptionClassifier:
    """
    Classifies user speech transcript into three categories using a three-layer rule:

      Layer 1 — explicit barge-in commands (highest priority): always interrupt.
      Layer 2 — backchannels / fillers / unfinished openers: never interrupt.
      Layer 3 — length fallback: short utterances (< _MIN_BARGE_IN_CHARS effective
                chars) are treated as unfinished/backchannel; longer ones as true barge-in.

    The goal is to avoid cutting off the assistant when the user has only said a short
    opener (e.g. "喽", "那个", "我想想") while still honoring clear interrupt commands.
    """

    # Minimum effective characters for a CJK utterance to be considered a true barge-in.
    _MIN_BARGE_IN_CHARS = 4
    # Minimum words for an English/Latin utterance to be considered a true barge-in.
    _MIN_BARGE_IN_WORDS = 3

    # Layer 1: explicit interrupt commands — always a true barge-in regardless of length.
    _EXPLICIT_BARGE_IN_PATTERNS = [
        r"^停(下|一下|止)?$",
        r"^别(说|讲|说?了|说话|出声)?.*$",
        r"^打住$",
        r"^等(等|一下|一等|会儿)?$",
        r"^闭嘴$",
        r"^安静(点|一下)?$",
        r"^算了$",
        r"^不用(说|讲|再?说)了?$",
        r"^别烦我$",
        # --- short negation / correction: clear intent to redirect the assistant ---
        r"^不对$",
        r"^错了?$",
        r"^not$",
        r"^不是$",
        r"^不不$",
        r"^没有$",
        r"^不要(这个|那个|这样)?$",
        r"^换(一个|个)?(话题|说法|方向)?$",
        r"^(stop|wait|hold\s*on|shut\s*up|quiet|be\s*quiet|cancel|never\s*mind|wrong|no\s*no|pause|stop\s*talking)$",
    ]

    # Layer 2: backchannels, fillers, thinking-out-loud and unfinished openers — never interrupt.
    _BACKCHANNEL_PATTERNS = [
        # --- original short affirmations ---
        r"^嗯(嗯|啊)?$",
        r"^哦(哦)?$",
        r"^啊$",
        r"^对(的|啊|呀)?$",
        r"^好(的|啊|呀|嘞)?$",
        r"^是(的|啊)?$",
        r"^确实$",
        r"^没毛病$",
        r"^(OK|ok|okay)$",
        r"^我知道了$",
        r"^明白(了)?$",
        r"^原来如此$",
        # --- hesitation / thinking / opening fillers (do not interrupt) ---
        r"^喽$",
        r"^呃+$",
        r"^额+$",
        r"^欸$",
        r"^哎(呀|哟)?$",
        r"^唉$",
        r"^那个(那个)?$",
        r"^就是(说)?$",
        r"^我想(想|一下)?$",
        r"^让(我|咱)(想想|想一下|想想?看)$",
        r"^这个(这个)?$",
        r"^这样的话$",
        r"^然后呢$",
        r"^喂$",
        r"^你好$",
        r"^在吗$",
        r"^听着$",
        r"^说实话$",
        r"^其实$",
        r"^(咋|怎么)说(呢|吧)?$",
        # --- English conversational backchannels, fillers and short starters ---
        r"^(yeah|yes|yep|yup|uh|um|umm|uh-huh|uh\s*huh|mm|mmm|mm-hmm|mm\s*hmm|mhm)$",
        r"^(well|right|sure|got\s*it|cool|ah|oh|like|so|hey|hi|hello|that|this|i|you|and|alright|fine|thanks|thank\s*you)$",
        r"^(i\s*see|i\s*mean|you\s*know|go\s*on|i\s*hear\s*you|makes\s*sense)$",
    ]

    @classmethod
    def classify_with_rule(cls, text: str) -> InterruptionClassification:
        cleaned_text = str(text or "").strip()

        # Remove common punctuation for evaluation
        eval_text = re.sub(r"[,.;:，。；：！？!?\s]+", "", cleaned_text)

        # Noise or silence
        if not eval_text:
            logger.info("interruption_classification result=NOISE_OR_SILENCE text=%r", cleaned_text)
            return InterruptionClassification(
                intent=InterruptionIntent.NOISE_OR_SILENCE,
                rule="empty_or_punctuation",
            )

        # Layer 1: explicit barge-in commands always interrupt, even when short.
        for pattern in cls._EXPLICIT_BARGE_IN_PATTERNS:
            if re.match(pattern, eval_text, re.IGNORECASE) or re.match(pattern, cleaned_text, re.IGNORECASE):
                logger.info(
                    "interruption_classification result=TRUE_BARGE_IN text=%r rule=explicit pattern=%r",
                    cleaned_text, pattern,
                )
                return InterruptionClassification(
                    intent=InterruptionIntent.TRUE_BARGE_IN,
                    rule=f"explicit_barge_in:{pattern}",
                )

        # Layer 2: backchannels / fillers / openers never interrupt.
        for pattern in cls._BACKCHANNEL_PATTERNS:
            if re.match(pattern, eval_text, re.IGNORECASE) or re.match(pattern, cleaned_text, re.IGNORECASE):
                logger.info("interruption_classification result=BACKCHANNEL text=%r pattern=%r", cleaned_text, pattern)
                return InterruptionClassification(
                    intent=InterruptionIntent.BACKCHANNEL,
                    rule=f"backchannel_pattern:{pattern}",
                )

        # Single-character noise/echo filtering:
        # If the transcript is a single character and not a known barge-in command or backchannel,
        # treat it as noise/silence to prevent false interruptions from echoes or ASR errors.
        if len(eval_text) == 1:
            logger.info("interruption_classification result=NOISE_OR_SILENCE text=%r reason=single_char_noise", cleaned_text)
            return InterruptionClassification(
                intent=InterruptionIntent.NOISE_OR_SILENCE,
                rule="single_char_noise",
            )

        # Layer 3: length & language fallback.
        # For English/Latin utterances, check word count: 1-2 words are usually fillers or incomplete openers.
        has_latin = bool(re.search(r"[a-zA-Z]", eval_text))
        if has_latin:
            words = re.findall(r"[a-zA-Z0-9']+", cleaned_text)
            if len(words) < cls._MIN_BARGE_IN_WORDS:
                logger.info(
                    "interruption_classification result=BACKCHANNEL text=%r rule=too_few_words words=%d",
                    cleaned_text, len(words),
                )
                return InterruptionClassification(
                    intent=InterruptionIntent.BACKCHANNEL,
                    rule=f"too_few_words:{len(words)}",
                )
        else:
            # For CJK utterances, check character count.
            if len(eval_text) < cls._MIN_BARGE_IN_CHARS:
                logger.info(
                    "interruption_classification result=BACKCHANNEL text=%r rule=too_short len=%d",
                    cleaned_text, len(eval_text),
                )
                return InterruptionClassification(
                    intent=InterruptionIntent.BACKCHANNEL,
                    rule=f"too_short:{len(eval_text)}",
                )

        logger.info("interruption_classification result=TRUE_BARGE_IN text=%r rule=length", cleaned_text)
        return InterruptionClassification(
            intent=InterruptionIntent.TRUE_BARGE_IN,
            rule="substantial_speech",
        )

    @classmethod
    def classify_interruption(cls, text: str) -> InterruptionIntent:
        """Backward-compatible enum-only classifier used by existing callers."""
        return cls.classify_with_rule(text).intent
