# Qwen-Audio realtime interruption

Echo uses the Qwen-Audio 3.1 realtime WebSocket protocol through FastAPI. In
`server_vad` and `smart_turn` modes, the browser keeps streaming 16 kHz mono
PCM input while the assistant speaks. Qwen detects a new utterance and cancels
the in-progress response with `response.done` status `cancelled` and reason
`turn_detected`.

On `input_audio_buffer.speech_started`, the backend immediately sends
`assistant_playback_stop` to clear the browser's queued 24 kHz PCM audio. If
an assistant response or tool task is active in `server_vad` mode, it also
resolves the canonical interruption as a native barge-in, stops the tool, and
suppresses late audio from the interrupted response. It does not wait for the
final ASR transcript or send a redundant `response.cancel` for an automatic
VAD interruption.

For `smart_turn`, an acoustic speech-start can later become an ambient-audio
event rather than a user turn. Echo still clears local playback immediately,
then keeps the assistant response if Qwen reports ambient audio. It records a
barge-in when Qwen reports a normal user transcription or confirms cancellation
with `reason=turn_detected`.

The browser requests microphone echo cancellation. Echo's WebSocket path
relies on that browser processing; Alibaba recommends AOQ for its built-in
noise suppression and acoustic echo cancellation. Speakers in a noisy room can
still cause false VAD triggers. Headphones are the most reliable way to assess
barge-in behavior on this transport.

Verification:

- Backend event-replay tests cover continuous input during playback, immediate
  interruption, late provider audio, cancelled responses, deferred output, and
  `smart_turn` ambient audio.
- Frontend hook tests cover clearing queued audio even when the provider has
  already completed its response.
- A live Qwen-Audio 3.1 probe using synthesized, non-private English speech
  confirmed a `session.updated` handshake, first response audio, then
  `response.done` with `status=cancelled` and `reason=turn_detected` after a
  second utterance. The provider completed the subsequent response without an
  error. This probe checks the provider protocol; the replay tests check Echo's
  forwarding and playback behavior.

Official references: [Qwen-Audio realtime guide](https://www.alibabacloud.com/help/en/model-studio/qwen-audio-realtime-user-guides),
[server events](https://www.alibabacloud.com/help/en/model-studio/qwen-audio-realtime-server-events),
and [client events](https://www.alibabacloud.com/help/en/model-studio/fun-audiochat-client-events).
