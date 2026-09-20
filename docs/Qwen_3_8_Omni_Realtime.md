# Qwen 3.8 Omni Realtime

Status: **the 3.8 omni realtime path is wired and tested, but the shipped default
stays on `qwen3.5-omni-plus-realtime`.** A 3.8 session opened from the app is
closed by the server right after the socket opens, so it must not be the model a
fresh install starts a call with.

## What we observed

Selecting `qwen3.8-omni-flash-realtime` in a cn-beijing workspace on 2026-09-20:
the call opens, then closes on its own within a second or two, with no audio and
no assistant turn.

The failure was previously undiagnosable from the app side: the DashScope close
code and close message were dropped in `_dashscope_to_client_loop`, and an
unexpected server `error` frame was forwarded raw while nothing was logged. So
"opens then closes" had no attributable cause anywhere — neither in the UI nor in
the backend log.

## Evidence gathered

- The model id is real: the vendor's voice-cloning API reference lists
  `qwen3.8-omni-flash-realtime` among "the omni model that drives the voice".
- The vendor's model-selection page (阿里云 "选择模型") still routes **realtime**
  audio/video dialogue to `qwen3.5-omni-plus-realtime`; `qwen3.8-omni-flash` is
  offered for Chat Completions / Responses only.
- The 3.8 release coverage describes the realtime line as a second, *asynchronously
  updated* track ("还有一条异步更新的线"), i.e. a rollout rather than a switchover.
- There is still no dedicated realtime doc page for 3.8
  (`help.aliyun.com/zh/model-studio/qwen3-8-omni-flash-realtime` → 404), and the
  Realtime reference documents only the 3.5 models.

Our session payload is byte-identical for a 3.5 and a 3.8 model (verified by
capturing it from the adapter, see `tests/manual_probe_omni_session.py`), so the
payload cannot explain a 3.8-only failure — the model itself is not usable in
this workspace yet.

## Measured cause: the model is not enabled for this workspace

`tests/manual_probe_omni_session.py --minimal` on 2026-09-20 against the
configured cn-beijing workspace, same minimal session
(`modalities` + `voice`) for both models:

| model | frames received |
| --- | --- |
| `qwen3.8-omni-flash-realtime` | `session.created`, then `{"code": "AccessDenied", "message": "Access denied", "request_id": "…"}` — no `type` field — then the socket is dropped with **no close frame** |
| `qwen3.5-omni-plus-realtime` | `session.created`, `session.updated` (full echo), connection held until we sent `session.finish` |

The full adapter payload behaves identically (3.8 → AccessDenied, 3.5 →
`session.updated`), so neither the model id nor the session fields are the
problem.

The account's own catalog agrees. `GET /compatible-mode/v1/models` with the
configured key returned 256 models, including `qwen3.8-omni-flash`,
`qwen3.8-livetranslate-flash-realtime` and every 3.5 realtime alias — but **no
`qwen3.8-omni-flash-realtime`**, and no other 3.8 realtime omni entry. So this is
not a missing click on a model that exists in the account: **the 3.8 omni
realtime line has not been released to this account/region yet.** The vendor's
docs point the same way (its model-selection page still routes realtime
audio/video dialogue to 3.5, and there is no realtime page for 3.8).

That frame is why the call looked like it closed by itself. It is an error
envelope with no `type`, so `DashScopeRealtimeCallback.on_event` matched nothing
and forwarded nothing; the server then dropped the socket without a close frame,
so the backend had no code, no message and no log line either.

## What is wired

| where | change |
| --- | --- |
| `realtime_constants.DASHSCOPE_OMNI_REALTIME_PATTERN` | new shared pattern `qwen3\.(?:5\|8)-omni-(?:plus\|flash)-realtime(?:-date)?` |
| `realtime_tool_protocol.dashscope_supports_native_tools` | imports that pattern instead of keeping its own 3.5-only copy |
| `realtime_dashscope_provider` | the omni session profile (semantic_vad / 0.5 / 900 ms silence / `qwen3-asr-flash-realtime` / 500 ms prefix) and the omni voice validation are keyed on `_is_dashscope_omni_realtime_model`, not on the literal `"qwen3.5-omni"` substring |
| `settings.DASHSCOPE_MODEL_LIST_SUPPLEMENTS` | does **not** force-add `qwen3.8-omni-flash-realtime` — advertising a model the account cannot use only produces an AccessDenied call. `_filter_dashscope_models` keeps the id, so discovery surfaces it the moment the vendor lists it |
| `settings_service` DashScope defaults | 3.8 omni is in `available`, **not** in `enabled` (the picker's default set) |
| `realtime_constants.DEFAULT_DASHSCOPE_REALTIME_MODEL`, `useVoiceChatHelpers.DEFAULT_DASHSCOPE_MODEL` | both stay `qwen3.5-omni-plus-realtime` |
| `realtime_voice_service` model-support error | names the 3.8 model first, keeps the 3.5 and qwen-audio entries |
| `useVoiceChatHelpers.isRealtimeVoiceModel` | accepts the 3.8 omni family; still rejects the non-realtime `qwen3.8-omni-flash` |

The literal-substring bug mattered on its own: before it, a 3.8 omni session fell
through to the generic profile (server_vad, no ASR model, 1200 ms silence), which
would have degraded turn-taking even once the model is available.

## Diagnostics added

- `dashscope_realtime_connecting model=… voice=…` on every DashScope call.
- `dashscope_omni_session_update model=… voice=… omni_profile=… asr_model=…`, so
  the profile a given model id resolves to is visible.
- `dashscope_realtime_server_error model=… code=… message=…` for every server
  error frame.
- `dashscope_realtime_socket_closed model=… code=… message=…` for every socket
  close, and a client-facing `error` event when the close is **not** a clean
  user-initiated 1000 — previously silent.
- `dashscope_untyped_error code=… message=… request_id=…` for error envelopes
  that carry no `type` — i.e. exactly the AccessDenied above — pushed to the
  client as a normal `error` event instead of being dropped.

## Verifying on a real workspace

    cd backend
    python tests/manual_probe_omni_session.py                     # 3.8 and 3.5
    python tests/manual_probe_omni_session.py qwen3.8-omni-plus-realtime

The probe captures the payload the adapter actually sends (by configuring a real
SDK conversation with its send stubbed out), then drives raw `websockets`
sessions and prints every frame, the `session.updated` echo, any `error` payload
and the handshake failure text. It runs three variants per model: the adapter
payload, the payload without `input_audio_transcription` (the 3.5-era ASR model is
the field our 3.8 LiveTranslate adapter had to stop sending), and the 3.5 model
as a control.

## Flipping the default to 3.8

0. Wait for the rollout (`GET /compatible-mode/v1/models` must list
   `qwen3.8-omni-flash-realtime`), then confirm a live session with
   `python tests/manual_probe_omni_session.py --minimal`: it must answer
   `session.updated` instead of AccessDenied. 阿里云 ticket/支持 can confirm
   whether the account can be allow-listed early.
1. `DEFAULT_DASHSCOPE_REALTIME_MODEL` → `qwen3.8-omni-flash-realtime`
   (or `qwen3.8-omni-plus-realtime`, the pattern accepts both).
2. Add the same id to the `enabled` list in
   `settings_service.DEFAULT_MODELS`'s DashScope entry (no supplement needed once
   the model list returns it).
3. `DEFAULT_DASHSCOPE_MODEL` in `frontend/src/hooks/useVoiceChatHelpers.ts` to match.
4. Update this doc with the measured behavior, and the `Closing note` in
   `docs/Realtime_Native_Tool_Calling_Design.md` if the id changes.

Users who want to try it before then can add `qwen3.8-omni-flash-realtime` to the
DashScope model list in Settings; the backend already runs it on the omni profile.

## Not covered

The 3.8-only capabilities — spatial-audio "听声辨位" session parameters and Skill
injection for identity / business knowledge — are untouched. Echo drives the
audio-in / audio-out conversational path only, which is identical across both
generations. The omni voice list is still the 3.5 set (`QWEN_OMNI_REALTIME_VOICES`);
the backend falls back to `Tina` for voices a model rejects, so a 3.8-only voice
degrades instead of breaking a call.

## Test coverage

- `backend/tests/test_realtime_tool_protocol.py` — the shared pattern accepts 3.8
  and rejects `qwen3.8-omni-flash`; the shipped default passes both runtime gates.
- `backend/tests/test_realtime_dashscope.py` — a 3.8 conversation gets the omni
  session profile; a server-side close is reported to the client with its code and
  message; a clean 1000 close stays silent; the vendor error code survives the
  callback; an untyped AccessDenied frame becomes a client `error` event.
- `backend/tests/test_dashscope_model_filter.py` — 3.8 omni is not retired and
  survives the supplement merge.
- `frontend/src/hooks/useVoiceChatHelpers.livetranslate.test.ts` and
  `useVoiceChat.test.ts` — the picker recognizes the 3.8 family while the
  DashScope fallback stays on 3.5 omni.
