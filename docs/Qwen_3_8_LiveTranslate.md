# Qwen 3.8 LiveTranslate

Echo supports `qwen3.8-livetranslate-flash-realtime` in the DashScope realtime
model picker. Select it in the voice call settings and choose a target language.
It uses the existing DashScope API key and workspace Realtime WebSocket URL.
Saved Qwen 3.5 selections remain supported with their original protocol.

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
