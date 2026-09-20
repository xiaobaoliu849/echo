# Qwen 3.8 LiveTranslate

Echo supports `qwen3.8-livetranslate-flash-realtime` in the DashScope realtime
model picker. Select it in the voice call settings and choose a target language.
It uses the existing DashScope API key and workspace Realtime WebSocket URL.

Only this generation is offered. The superseded `qwen3.5-livetranslate-*` aliases
are stripped from the DashScope model lists on every settings load, so they never
reach the picker again. An already-saved 3.5 selection still runs on its original
protocol until the user picks a model from the list.

## Protocol references

Reviewed on 2026-09-19; latency defaults re-measured live on 2026-09-20:

- [Model information](https://help.aliyun.com/zh/model-studio/qwen3-8-livetranslate-flash-realtime)
- [Integration guide](https://help.aliyun.com/en/model-studio/qwen3-5-livetranslate-flash-realtime)
- [Client events](https://help.aliyun.com/en/model-studio/live-translator-client-events)
- [Server events](https://help.aliyun.com/en/model-studio/live-translator-server-events)

The 3.8 adapter uses `output_modalities` and nested `audio.input` / `audio.output`
configuration. Input is mono PCM16 at 16 kHz; output is PCM16 at 24 kHz.
Source transcription is automatic. It sets `translation.language`, sends an
explicit turn-detection window (see Latency below), and retains terminology and
voice clone settings. It does not send the 3.5-only ASR model or flat audio
fields.

Source and translation delta events are appended in arrival order. Source text
is accumulated per provider item, then reconciled with the final transcript.
For 3.8, `response.done` completes a turn; text completion alone does not.
Startup waits for configuration acknowledgement before enabling microphone input.

The normal source-text path is the per-item
`conversation.item.input_audio_transcription.completed` event (3.8 does emit it,
0.1–2 s after the turn closes in live measurements). It only arrives when the
turn closes, so a source item is additionally treated as finished when
`input_audio_buffer.speech_stopped` arrives or when the next item's first delta
appears. Its accumulated text is attached to the recorder turn of the
translation that follows it, and any utterance still pending when the socket
closes is written as its own turn so the session export never loses the user's
words when `completed` never lands (abrupt disconnect). The incremental ASR
mapping is scoped to this model: Qwen-Omni and Qwen-Audio reuse the same
`conversation.item.input_audio_transcription.delta` event name with a
`{text, stash}` payload, which the omni turn owner must not see as a completed
user utterance.

## Latency

The adapter first shipped without `audio.input.turn_detection`, which left the
server's own defaults in place. Those defaults are `speaker_detection`,
`threshold 0.5`, **`silence_duration_ms 2500`** — the server reports the 2500 in
its `session.updated` echo, even though the published server-event reference
still documents 1000. Because this window is exactly what tells the server an
utterance has ended, every sentence paid 2.5 s of dead air after the speaker
stopped before its transcript, translation and audio were flushed.

`QWEN_LIVETRANSLATE_38_TURN_DETECTION` (realtime_constants.py) now sends
`silence_duration_ms: 500`. Measured with
`tests/manual_probe_livetranslate_latency.py` against the configured workspace on
2026-09-20, streaming a 5.9 s utterance at wall-clock pace with a realistic
microphone noise floor:

| metric (5.9 s utterance) | server default (2500 ms) | shipped (500 ms) |
| --- | --- | --- |
| first source transcript delta | 7.2–10.8 s in (only after the turn closed) | 4.5–4.9 s in (during speech) |
| turn closed after speaker stopped | +3.5 s / +9.5 s | −0.3 s / +0.04 s |
| last transcript fragment after speaker stopped | +12.5 s / +14.9 s | +1.3 s / +7.3 s |
| translation text | identical | identical |

Both columns are the two runs printed by the probe, and session-to-session
variance is large — the same default config closed one run at +3.5 s and another
at +9.5 s, and a later default run closed while the speaker was still finishing.
Read the table as "the tuned window removes the 2.5 s silence floor", not as a
fixed budget.

The remaining lag is the model itself, which the vendor rates at ~2.3 s of
simultaneous-interpretation latency; the delta stream keeps flowing while the
speaker talks, so what the user notices is the end-of-sentence flush that this
setting controls. 500 ms matches the frontend's local end-of-speech detector
(~430 ms) and is well above the 200 ms floor. It does close an input item at a
natural mid-sentence pause; the frontend already coalesces those fragments back
into one sentence, and the value can be raised (range 200–6000 ms) if a speaker
pauses for longer than that.

Stop immediately disables capture and playback, while keeping the socket open
to receive the final text. The backend sends `session.finish` and waits up to
15 seconds for the server to flush; the frontend has a 16-second cleanup timeout.
Abrupt disconnects cannot guarantee delivery of the final segment.

## Adversarial review

The pre-push review checked protocol mismatches, repeated deltas, transcript item
boundaries, text/audio ordering, startup errors, stop/cleanup, model discovery,
and compatibility with existing 3.5 sessions. Findings addressed:

1. Shared text deduplication could drop consecutive identical delta fragments.
   Incremental events now bypass cumulative-text deduplication and prefix merging.
2. Text completion and the old inactivity timer could finish a 3.8 turn before
   trailing audio arrived. The 3.8 path uses response completion instead.
3. The frontend immediately closed the socket after Stop, discarding the final
   sentence despite the backend flush. Stop now retains the socket until the
   provider acknowledges completion, with bounded cleanup on both sides.
4. A fixed startup delay could announce a usable session after configuration
   rejection. The 3.8 path waits for `session.updated` and propagates errors.
5. Review of the shipped adapter found the incremental ASR mapping applied to
   every DashScope family. Qwen-Omni / Qwen-Audio send `{text, stash}` on that
   event, so each omni ASR frame was forwarded as an empty completed user
   utterance: the turn owner ran the interruption pipeline per frame and the
   real interim transcript was dropped. The delta mapping — plus the new
   `speech_stopped` forward — is now keyed on the session type.
6. 3.8 source utterances could be missing from the session recorder: source text
   is written from the `completed` branch, which never fires for a segment that
   is cut off by an abrupt disconnect. Input-item bookkeeping now backs it up.
7. The session payload never set turn detection. The server's default requires
   `silence_duration_ms` 2500 of silence after speech before it closes an
   utterance, which is what made a finished sentence's transcript appear
   seconds after the speaker stopped. The 3.8 payload now sends an explicit
   500 ms window (see Latency).

These scenarios have mocked regression coverage. No unresolved blocker was
identified in the reviewed changes. The review was performed by the implementing
agent, not an independent reviewer.

## Live verification

Automated validation passed: 511 frontend tests across 61 files
(`npm run test:run -- --maxWorkers=2`), the frontend production build, and
965 backend tests plus 99 subtests (`python -m pytest -q`). The initial frontend
run under concurrent build/backend load hit a chat-test timeout and a cascading
failure; the affected file passed alone and the full two-worker run passed.

Using the configured workspace endpoint, the service accepted the new session
payload and returned `session.updated` and `session.finished`. A second test sent
a locally synthesized, non-private English sample with voice cloning set to
`once`, requesting Chinese translation. The server accepted the clone settings
and returned source transcript deltas, translated text deltas, 19 audio chunks,
response completion, and session completion. Credentials and generated audio
are not included in the repository.

The latency table above comes from the same live endpoint: the shipped payload
is echoed back by `session.updated` with `silence_duration_ms: 500`, and its
translation output matched the untuned session word for word.

This verifies the provider protocol and audio generation. It does not establish
translation quality across all languages, clone fidelity, long-session behavior,
how a given speaker's natural pauses interact with the 500 ms window, or
microphone/speaker operation in a packaged desktop installer.
