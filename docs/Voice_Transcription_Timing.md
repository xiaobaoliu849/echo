# Voice transcription timing in Echo

Investigated 2026-09-22. The table describes tracked adapters and their configured
models, not measured latency or guaranteed access to every provider model.

## Why text arrives at different times

There are three independent stages: audio transport, speech recognition, and
deciding that an utterance is finished. A realtime voice model can receive audio
continuously while its separate recognizer returns text only after a pause.
Streaming text can also start only after an audio turn is committed; a `delta`
event name alone does not guarantee captions while the speaker is still talking.

An incremental fragment must be appended. A cumulative snapshot must replace the
previous preview, including words that were corrected or removed. The final
transcript is authoritative. Assistant speech captions are a different stream
from the user's input transcription.

## Current application behavior

| Echo connection / model family | Input text displayed | Implementation evidence |
| --- | --- | --- |
| OpenAI, default `gpt-realtime-2` | After completion; explicitly configures a separate `whisper-1` recognizer and handles completed input transcripts only | `backend/services/realtime_openai_provider.py` |
| Qwen-Omni 3.5 / 3.8 realtime | Now forwards live `text + stash` snapshots as provisional captions; previously discarded them | `realtime_dashscope_client.py`, `realtime_dashscope_provider.py` |
| Qwen-Audio 3.0 / 3.1 realtime | Live preview, then final correction; handles incremental fragments and replacement snapshots | `backend/services/realtime_qwen_audio_provider.py` |
| Google Gemini Live / native audio | Growing input transcription where the provider supplies it; some updates are delayed around interruption boundaries | `backend/services/realtime_google_provider.py` |
| Doubao duplex | Live replacement snapshots, then completed transcript | `backend/services/realtime_doubao_provider.py` |
| Gradium realtime pipeline | Growing recognized words; a 0.9-second text inactivity timer or VAD can finalize the utterance | `backend/services/realtime_gradium_provider.py` |
| Cartesia realtime / Ink-2 | User transcript forwarded on `turn.end` | `backend/services/realtime_cartesia_provider.py` |
| StepFun realtime | Completed input transcription | `backend/services/realtime_stepfun_provider.py` |
| Vercel realtime gateway | Completed input transcription in the current adapter; underlying model capability is not the same as gateway behavior | `backend/services/realtime_vercel_provider.py` |
| Local PersonaPlex / GLM-4-Voice | These adapters do not emit user transcription events; their output text accompanies the assistant's speech | Local provider mixins |
| Dedicated transcription panel | Streaming ASR routes for `gemini-3.5-transcribe-live`, `qwen-audio-3.0-asr-flash-streaming`, and `fun-asr-realtime` | `backend/services/realtime_asr_service.py` |

Live translation has separate source/translation buffering and sentence boundaries.
For example, Echo already configures Qwen 3.8 LiveTranslate with a 500 ms silence
window. This investigation leaves that behavior unchanged. A listed 3.8 model is
not a claim of account availability; Echo retains its existing 3.5 Omni default.

## Recommendation

Use live provisional captions followed by final correction for interactive voice
chat, dictation, and accessibility. They provide immediate feedback and let a user
notice recognition problems early. Mark them as provisional because names,
punctuation, and even earlier words can change. A quiet display that waits for
final text can suit users who find changing captions distracting. Neither timing
style establishes recognition accuracy or assistant reasoning quality.

For the current Echo voice experience, try the existing Qwen-Omni/Qwen-Audio,
Gemini, Doubao, or Gradium routes when live captions matter. Choose among them
using recordings in the user's actual language, accent, microphone, and noise
conditions. No comparative accuracy or latency benchmark was performed here.

## Changes made

- Qwen-Omni snapshots have a dedicated internal preview event. The adapter forwards
  them for display without running tools, retrieving memories, writing user turns,
  or classifying interruptions. An empty snapshot can withdraw earlier words.
- Frontend previews are separate from confirmed conversation text. An old answer's
  completion or interruption can no longer save a new caption as the old question.
- Captions survive the preceding turn's completion, final corrections replace them,
  and rejected backchannels/noise clear the preview. Unfinished previews are not
  silently archived as confirmed speech on hangup.
- Chat labels distinguish provisional captions (words may change) from ordinary
  voice transcripts, in Chinese and English. Providers without explicit provisional
  metadata use the neutral label.

## Provider documentation and further opportunities

Alibaba's official example explicitly treats `text + stash` as a streaming preview
and the completed event as final. This is the protocol used for the new Omni path.
[Qwen-Omni realtime documentation](https://www.alibabacloud.com/help/en/model-studio/realtime).

Google documents incremental live recognition, interim/final transcription, and
language/vocabulary hints for its dedicated transcription model. This supports
using the existing transcription panel for continuous captions; it does not prove
identical event timing across every Gemini conversation model.
[Gemini live transcription](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe).

OpenAI's current live-transcription guide recommends `gpt-live-transcribe` for
transcription-only sessions. It describes deltas during speech, final transcripts
on commit, and matching events by item ID because completion order can vary.
Echo's current OpenAI conversation adapter does not implement that separate
transcription session. Replacing its recognizer name alone would not establish
compatibility or correct ordering, so no automatic model migration was made.
[OpenAI realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription).

Future provider work should validate item-scoped preview/final ordering, failures,
and reconnects with live sessions before changing defaults. Measure time to first
caption, time from speech end to final text, correction frequency, and word/character
error rate separately. Tune silence windows with long pauses and multilingual speech;
shorter windows can split thoughts prematurely. The replay tests in this change
verify application behavior, not actual provider speed or speech accuracy.

## Verification

- Full frontend suite: 590 tests passed across 61 files.
- Frontend TypeScript check and production build: passed.
- Full backend suite in the isolated Python 3.12 packaging environment: 979 tests
  and 99 subtests passed; two dependency deprecation warnings.
- Regression coverage includes corrected/withdrawn snapshots, interruption and
  completion races, repeated utterances, identical preview/final text, rejected
  backchannels/noise, archive behavior, and hangup cleanup.
- No live provider calls or microphone latency measurements were performed.

## Adversarial review before publication

Reviewed the new provider event path and browser rendering for unwanted side
effects and unsafe text handling. Preview events do not call tool handlers,
retrieve memories, or write durable turns. Transcript text is rendered by React
as escaped text. The review found two correctness cases and added regressions:
new speech without a provider turn ID is separated from the previous question,
and rejected or empty completed speech withdraws its caption. No credential or
executable payload was added to the published changes.
