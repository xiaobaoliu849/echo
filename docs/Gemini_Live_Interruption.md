# Gemini Live interruption repair — 2026-09-16

When the user speaks over Gemini, Echo must stop scheduled playback when Gemini
confirms cancellation, keep sending microphone audio, and let server VAD determine
when the user has finished. This applies to `gemini-3.8-live` and
`gemini-3.8-live-extended-thinking` as well as the existing Google Live adapter.

## Root causes

- Local RMS detection started the shared transcript classifier. The browser
  reduced playback gain to 0.18 and waited up to 2.5 seconds for a decision.
- `server_content.interrupted` also started that pending state instead of resolving
  it immediately. Missing ASR and short openers could resume canceled output.
- The input loop dropped microphone frames during active tools, preventing VAD
  from hearing an interruption.
- Audio was processed before cancellation flags in the same server message.
- Independently ordered ASR and the canceled turn's terminal could change or close
  the wrong local turn, leaving playback running or losing the next utterance.

## Protocol and implementation

Google's [Live capabilities guide](https://ai.google.dev/gemini-api/docs/live-api/capabilities)
instructs clients to stop playback and clear queued audio on interruption. Its
[WebSocket reference](https://ai.google.dev/api/live) documents the canceled
generation's `interrupted` → `turnComplete` sequence and independent input
transcription ordering. The capabilities guide also documents Gemini 3.8 Live and
Extended Thinking. Standard Live omits thinking configuration; Extended Thinking
retains the existing low setting.

Echo retains automatic VAD with `START_OF_ACTIVITY_INTERRUPTS` and continuous
16 kHz PCM input, including during tool execution. Local RMS hints no longer
start Google playback ducking. A native cancellation forces a provider-confirmed
decision without ASR classification. Existing provider-neutral events stop browser
audio, discard buffered output, cancel tools, and record the interrupted turn.

Cancellation is processed before output. Output up to the canceled terminal is
discarded; that terminal does not complete the new user's turn. Early input ASR is
held until the old turn has a boundary, so the stop event still addresses the
playing response. Finished deferred ASR is published even when no reply follows.
The browser retires pending timers and ignores stale decisions after a confirmed
stop. Google Live Translate retains its separate behavior.

The existing 1,500 ms silence tolerance is preserved. This repair does not add
client `activityStart`/`activityEnd` messages: those belong to manual VAD with
automatic detection disabled. The server still determines speech onset/offset;
this change cannot guarantee a particular microphone-to-stop latency.

## GitHub investigation

The starting local and remote `main` both pointed to `54468df`, whose duplex fix
enabled provider interruption but retained the transcript-dependent playback gate.
Uncommitted StepFun integration work was excluded using an isolated worktree.

Related upstream reports were inspected:

- [python-genai #2593](https://github.com/googleapis/python-genai/issues/2593):
  questions about interrupting with automatic VAD; closed as not planned/stale.
- [python-genai #1987](https://github.com/googleapis/python-genai/issues/1987):
  a Gemini 2.5 report of VAD not responding after barge-in; closed as not
  planned/stale. This does not establish a Gemini 3.8 defect or explain Echo's
  explicit playback gain reduction.

## Adversarial review and validation

An API review using `gemini-3.8-flash` examined the patch and provider code. Review
findings were checked against deterministic replays. Fixes cover consecutive
interruptions with early ASR and finished ASR with no subsequent model reply.
Additional adversarial cases cover missing/short ASR, mixed cancellation/audio
messages, stale output, canceled terminals during Extended Thinking, duplicate
markers, tool cancellation, and continuous microphone forwarding.

The browser regression verifies all queued sources stop, old audio remains
discarded, a stale timeout/decision cannot resume playback, and the next response
plays at normal gain. Existing suspended-audio-context replay tests also pass.

Validation commands:

```text
cd frontend
npm run test:run
npm run build
cd ../backend
python -m pytest -q
```

Final results: 475 frontend tests passed; the production build passed; 896
backend tests and 95 subtests passed. `git diff --check` passed.

Build the frontend before the backend suite: desktop smoke tests require
`frontend/dist`. Automated checks use protocol replays and browser audio mocks;
a real microphone/speaker Gemini 3.8 Live conversation has not been measured.
Manual acceptance: select Google → Gemini 3.8 Live, request a long response,
interrupt mid-sentence, keep speaking, pause, and repeat during the next reply
and a tool request. Confirm the old audio stops rather than becoming quieter,
the new speech remains visible, and the next answer waits for the speech pause.
