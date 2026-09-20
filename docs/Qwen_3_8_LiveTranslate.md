# Qwen 3.8 LiveTranslate

Echo supports `qwen3.8-livetranslate-flash-realtime` in the DashScope realtime
model picker. Select it in the voice call settings and choose a target language.
It uses the existing DashScope API key and workspace Realtime WebSocket URL.

Only this generation is offered. The superseded `qwen3.5-livetranslate-*` aliases
are stripped from the DashScope model lists on every settings load, so they never
reach the picker again. An already-saved 3.5 selection still runs on its original
protocol until the user picks a model from the list.

## Protocol references

Reviewed on 2026-09-19:

- [Model information](https://help.aliyun.com/zh/model-studio/qwen3-8-livetranslate-flash-realtime)
- [Integration guide](https://help.aliyun.com/en/model-studio/qwen3-5-livetranslate-flash-realtime)
- [Client events](https://help.aliyun.com/en/model-studio/live-translator-client-events)
- [Server events](https://help.aliyun.com/en/model-studio/live-translator-server-events)

The 3.8 adapter uses `output_modalities` and nested `audio.input` / `audio.output`
configuration. Input is mono PCM16 at 16 kHz; output is PCM16 at 24 kHz.
Source transcription is automatic. The adapter leaves speaker detection at the
server default, sets `translation.language`, and retains terminology and voice
clone settings. It does not send the 3.5-only ASR model or flat audio fields.

Source and translation delta events are appended in arrival order. Source text
is accumulated per provider item, then reconciled with the final transcript.
For 3.8, `response.done` completes a turn; text completion alone does not.
Startup waits for configuration acknowledgement before enabling microphone input.

Because 3.8 streamed translations are not paired with a per-utterance
transcription `completed` event, a source item is treated as finished when
`input_audio_buffer.speech_stopped` arrives or when the next item's first delta
appears. Its accumulated text is attached to the recorder turn of the
translation that follows it, and any utterance still pending when the socket
closes is written as its own turn so the session export never loses the user's
words. The incremental ASR mapping is scoped to this model: Qwen-Omni and
Qwen-Audio reuse the same `conversation.item.input_audio_transcription.delta`
event name with a `{text, stash}` payload, which the omni turn owner must not
see as a completed user utterance.

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
6. The same review found 3.8 source utterances never reached the session
   recorder, because `note_user_transcript` was only called from the
   `completed` branch. Recorded 3.8 sessions contained assistant text only and
   carried no turn id for the user's speech.

These scenarios have mocked regression coverage. No unresolved blocker was
identified in the reviewed changes. The review was performed by the implementing
agent, not an independent reviewer.

## Live verification

Automated validation passed: 511 frontend tests across 61 files
(`npm run test:run -- --maxWorkers=2`), the frontend production build, and
957 backend tests plus 99 subtests (`python -m pytest -q`). The initial frontend
run under concurrent build/backend load hit a chat-test timeout and a cascading
failure; the affected file passed alone and the full two-worker run passed.

Using the configured workspace endpoint, the service accepted the new session
payload and returned `session.updated` and `session.finished`. A second test sent
a locally synthesized, non-private English sample with voice cloning set to
`once`, requesting Chinese translation. The server accepted the clone settings
and returned source transcript deltas, translated text deltas, 19 audio chunks,
response completion, and session completion. Credentials and generated audio
are not included in the repository.

This verifies the provider protocol and audio generation. It does not establish
translation quality across all languages, clone fidelity, long-session behavior,
or microphone/speaker operation in a packaged desktop installer.
