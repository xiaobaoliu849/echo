# Qwen-Audio 3.1 Realtime

`qwen-audio-3.1-realtime-plus` replaces `qwen-audio-3.0-realtime-plus` /
`qwen-audio-3.0-realtime-flash` as the Qwen-Audio realtime model Echo offers. It
is the full-duplex speech model (text + audio in, text + audio out, native tool
calling, Beijing-region workspaces) and runs on Echo's own raw WebSocket client,
not the DashScope SDK.

## What changed

| where | change |
| --- | --- |
| `realtime_constants.DASHSCOPE_AUDIO_REALTIME_PATTERN` | new shared pattern `qwen-audio-3\.(0\|1)-realtime(?:-(?:plus\|flash))?` (3.2 and later are *not* accepted implicitly) |
| `realtime_constants.DASHSCOPE_AUDIO_31_REALTIME_PATTERN` | new, selects the 3.1 voice table and default |
| `realtime_constants.QWEN_AUDIO_31_REALTIME_VOICES` | new — the 13 voices 3.1 accepts |
| `realtime_constants.DEFAULT_QWEN_AUDIO_31_REALTIME_VOICE` | new — `longanqian_v3.1` |
| `_normalize_dashscope_realtime_voice` | model-aware: 3.1 → 3.1 list + `longanqian_v3.1`, 3.0 → old list + `longanqian`, everything else unchanged |
| `dashscope_supports_native_tools` | imports the shared audio pattern instead of its own 3.0-only copy |
| `realtime_qwen_audio_provider` | resolves the voice through that normalizer (per generation), logs a warning when a voice is not valid for the selected model |
| `realtime_dashscope_client` (`DashScopeAudioRealtimeConversation`) | the wire voice fallback goes through the normalizer for the session's own model |
| `voice_chat.py` | passes the user's voice through untouched instead of pre-filling the 3.0 default |
| `settings.DASHSCOPE_MODEL_LIST_SUPPLEMENTS` | ships `qwen-audio-3.1-realtime-plus` |
| `settings._RETIRED_DASHSCOPE_REALTIME_RES` | retires `qwen-audio-3.0-realtime-*` **from the picker only** |
| `settings_service` DashScope defaults | `available` + `enabled` now carry `qwen-audio-3.1-realtime-plus` |
| `realtime_voice_service` | model-support and Beijing-region error text covers 3.1 and 3.0 |
| `useVoiceChatHelpers` | `isRealtimeVoiceModel` accepts 3.0/3.1, `QWEN_AUDIO_31_VOICES` (13) is offered for a 3.1 selection, `isQwenAudio31Model` exported, DashScope picker built-ins switched to 3.1 |
| `useVoiceChat` | a 3.1 session starts on `longanqian_v3.1`; 3.0 keeps `longanqian` |

3.0 stays **runnable**: a session already configured with a 3.0 model starts on
its 3.0 voice and protocol — only the model lists (picker, supplements, settings
defaults) moved to 3.1. To offer 3.0 again in the picker, drop the
`^qwen-audio-3\.0-realtime-` retire pattern.

## Voices

Per the vendor's voice table, 3.1 keeps the five 3.0 voices and adds eight, and
its default is `longanqian_v3.1` (3.0's default is `longanqian`):

    inherited : longanqian, longanlingxin, longanlingxi, longanxiaoxin, longanlufeng
    3.1-only  : longanqian_v3.1, longanhuan_v3.1, longanlingxin_v3.1,
                longanfengyue_v3.1, xunanchuan, beth_v3.1, betty_v3.1, cally_v3.1

Only the ids are documented; the eight new ones are labelled by id in the UI
rather than with invented display names. A 3.1-only voice on a 3.0 session is
rejected by the normalizer and falls back, so a stale selection can never send a
voice the model will refuse.

## Migration claim, verified live

The vendor states that migrating from 3.0 Plus means updating the `model` query
parameter and choosing a voice that matches the model — "WebSocket 事件协议保持
不变". That was checked, not assumed, with
`tests/manual_probe_qwen_audio_session.py` on 2026-09-20 against the configured
cn-beijing workspace, replaying the exact payload the adapter sends
(`modalities`, `voice`, `instructions`, `input_audio_format`,
`input_audio_transcription: {model: fun-asr}`,
`turn_detection: {server_vad, threshold 0.3, silence_duration_ms 5000}`,
`max_history_turns: 50`, `tools`):

| model | result |
| --- | --- |
| `qwen-audio-3.1-realtime-plus` | `session.created` → `session.updated`, echoing `voice: longanqian_v3.1`, our VAD values, `fun-asr` and `max_history_turns: 50` |
| `qwen-audio-3.0-realtime-plus` | identical, echoing `voice: longanqian` |

Same payload, same protocol, only the model id and the voice differ — including
with `input_audio_transcription` stripped, which the server then fills in itself.
`input_audio_format` comes back `null` in the echo for both generations (the
server does not echo the transport format), so that is not a 3.1 regression.

## Open items

1. **Turn detection.** Echo sends `server_vad` with `threshold 0.3` and
   `silence_duration_ms 5000`, deliberately long so a learner can pause. 3.1's
   headline feature is `smart_turn` — acoustic + semantic turn boundaries, where
   backchannel ("嗯", "啊") does not interrupt the model. That is a behaviour
   change with real regression risk for the interruption pipeline and has not
   been validated with live speech, so it is not wired up yet.
2. **`tts_available`.** `_is_tts_model_id` treats any `qwen-audio*` id as a TTS
   model, so the Qwen-Audio *realtime* models are advertised under the settings'
   TTS list rather than the chat/realtime list. Pre-existing; the voice picker is
   unaffected because the frontend merges its own DashScope built-ins.
3. **New voice display names.** The eight 3.1-only voices show their raw ids
   until the vendor publishes Chinese names.
4. **Region.** Echo still requires a `.cn-beijing.maas.aliyuncs.com` workspace
   for the whole Qwen-Audio family; if 3.1 is ever offered in Singapore, that
   gate needs relaxing.

## Test coverage

- `backend/tests/test_realtime_constants.py` — 3.1/3.0 detection, no implicit
  3.2, per-generation voice defaulting, 3.1-only voice rejected on 3.0.
- `backend/tests/test_realtime_tool_protocol.py` — 3.1 and both 3.0 models
  support native tools; 3.2 does not.
- `backend/tests/test_dashscope_model_filter.py` — 3.1 is not retired, 3.0
  realtime is, and the supplement merge restores 3.1.
- `backend/tests/test_realtime_qwen_audio.py` — the raw-client session shape.
- `frontend/src/hooks/useVoiceChatHelpers.livetranslate.test.ts` /
  `useVoiceChat.test.ts` — the picker recognizes 3.1 and the DashScope built-in
  list ships it.

`docs/时时语音模型参考.txt` is a 3.0-era vendor dump and predates 3.1; it is kept
as reference only.
