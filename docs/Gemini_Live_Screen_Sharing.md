# Live screen sharing in Echo

Researched and verified on 2026-10-03.

Screen sharing gives the voice model visual input. An avatar is the model's
video output. These are independent: a Google Cloud avatar can see the selected
screen while speaking, and an ordinary audio call can also see it.

## Provider capabilities

| Echo provider | Model | Voice | Screen input in Echo | Avatar output |
| --- | --- | --- | --- | --- |
| Google Gemini API | `gemini-3.8-live` | Yes | Yes | Use Google Agent Platform |
| Google Agent Platform | `gemini-3.8-live` | Yes | Yes, including avatar calls | Yes, with Cloud access |
| Vercel AI Gateway | `google/gemini-3.8-live` | Yes | Gateway realtime currently rejects image input | Not enabled by Echo |
| Vercel AI Gateway | `google/gemini-3.8-live-extended-thinking` | Yes | Gateway realtime currently rejects image input | Not enabled by Echo |

Vercel's Gemini announcement mentions visual grounding, but its realtime
documentation explicitly excludes image input. Echo follows that transport
limitation and shows the direct Google providers as the screen-sharing options.
Private-preview Extended Thinking, translation models, and other providers do
not receive this control. There is no silent provider or credential switch.

Sources:

- [Gemini API input modalities](https://ai.google.dev/gemini-api/docs/live-api/capabilities)
- [Cloud audio/video streaming](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/send-audio-video-streams)
- [Cloud avatar configuration](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/configure-live-avatars)
- [Vercel Gemini 3.8 Live announcement](https://vercel.com/changelog/gemini-3-8-live-models-now-available-on-ai-gateway)
- [Vercel realtime limitations](https://vercel.com/docs/ai-gateway/modalities/realtime#limitations)

## Use it

1. Select Google Gemini API or Google Agent Platform and `gemini-3.8-live`.
   Configure that provider's credentials in Settings. For an avatar, use the
   existing Cloud face/voice/accent settings described in
   [Gemini Live avatars](Gemini_Live_Avatars.md).
2. Start the call. Click **Share screen / 共享屏幕** after it connects, then
   explicitly choose a browser tab, window, or screen. Windows Electron uses
   Echo's thumbnail picker for windows and screens; browser choices depend on
   the browser's own picker.
3. Discuss the selected content aloud or type a question. A small preview and
   sharing indicator remain visible in both audio and avatar calls.
4. Click **Stop sharing / 停止共享**, the browser's Stop sharing control, or
   hang up. History replacement, connection failure, and component unmount
   release capture too. Muting the microphone does not stop screen sharing.

Google accepts at most one video frame per second. Echo preserves aspect ratio,
limits the longest side to 768 pixels, JPEG-compresses each frame, and limits
each JPEG to 96 KiB. Share the specific lesson/application window for readable
content; fast animations and tiny full-desktop text can be harder to understand.
This shares visual context and does not provide remote control of the computer.
Screen/system audio is excluded; the existing microphone handles conversation.

Chrome, Edge, and the Electron desktop shell are the intended capture surfaces.
PyWebView/WebView2 support depends on its installed runtime; when capture is
unavailable Echo explains which supported surface to use.

## Transport and lifecycle

- `screen_frame` is a provider-neutral client command with base64 JPEG data.
  The Google adapter validates the format, decoded dimensions, size, and frame
  rate, then calls `send_realtime_input(video=Blob(...))` on the existing session.
- Frames do not end turns, invoke tools, enter PCM playback, or create timeline
  and memory entries. Echo retains at most the latest frame in session memory
  for typed visual questions; it does not save screen recordings or frame files.
- Realtime frames are processed asynchronously by Google. An immediate typed
  question carries the latest frame and its text together through
  `send_client_content`, preventing the question from outrunning visual input.
  `screen_share_stopped` clears that retained frame. Previously processed visual
  context can remain in the provider's ongoing conversation.
- The capture hook binds a permission request, track, timer, and frames to one
  WebSocket. Late picker results are stopped, socket replacement cannot receive
  old frames, and backpressure drops frames instead of growing a screen queue.
- Invalid or unsupported visual input emits `input_rejected`, which stops only
  screen sharing (or reports a rejected attachment) and preserves the audio call.
- Electron's sandboxed modal grants only an explicitly selected enumerated
  source. Main-frame identity, origin, user gesture, and post-picker navigation
  are checked; IPC accepts only the picker renderer. Cancellation and shutdown
  remove listeners. Picker files are included in the installer manifest.

## Review and verification

Implementation review covered provider capability boundaries, immediate typed
questions, avatar/audio separation, malformed and oversized JPEGs, frame rate,
backpressure, stale picker results, hangup/history/disconnection cleanup, and
Electron source selection/IPC restrictions. Regression cases were added for
findings before the final verification run. This is an implementation review,
not an independent audit.

Actual provider probes used a synthetic 768×432 lesson image containing
`MATH LESSON` and `7 + 5 = ?`. Gemini API audio, Cloud audio, and Cloud Ben/Puck
avatar sessions all identified the title and answered 12. Cloud avatar output
contained MP4 fragments while screen input remained JPEG. The final probes sent
the typed question immediately after the frame, without a processing delay.
A real Vercel Gemini 3.8 Live connection also returned audio and transcription
for a text prompt, confirming the Gateway audio path remains available.

A Chromium browser check exercised the real capture hook and voice hook with a
synthetic video stream: 1 FPS frames, preview, manual stop, avatar mode, hangup,
and a 400-pixel layout passed without page errors or horizontal overflow. The
picker's exact HTML/JS was also checked for all source buttons, explicit
selection, Escape cancellation, default Cancel focus, and literal rendering of
untrusted window titles. Browser inputs and WebSockets were simulated in that
check; the separate provider probes used real connections.

Final verification passed 764 frontend tests across 75 files, the frontend
production build, 1,084 backend tests (plus 117 subtests), and 26 Electron tests.
The backend reported two existing deprecation warnings. No new Windows installer was
built, and actual Windows desktop capture/preload execution and every PyWebView
runtime were not verified. Provider probes establish acceptance and visual
understanding on the configured account, not a guarantee of recognition accuracy
for every screen, custom-avatar entitlement, or quota on another account.
