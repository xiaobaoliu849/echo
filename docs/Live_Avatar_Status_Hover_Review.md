# Live avatar status and hang-up review — 2026-10-05

## Fixes

Gemini avatar MP4 includes its speech track, so the separate PCM playback flag
does not describe avatar speech. The player now derives its speaking badge and
container state from either that flag or actual video playback during a call.
Frame receipt and server reply completion do not mark playback as finished.

The global `button.danger:hover:not(:disabled)` selector previously overrode the
avatar hover background. The avatar-specific selector now retains a translucent
red surface, white icon/text, and red border on hover and keyboard focus.

## Adversarial review

Performed by the implementing agent before pushing both commits. No blocking
findings remained after inspecting the full diff and checking these failure cases:

- Queued frames and blocked autoplay cannot set the video speaking state;
  the browser's `playing` event does. Buffering, pause, end, empty media, playback
  failure, interruption, reset, and stream replacement clear it.
- Lingering interim input or thinking cannot override active avatar speech.
  Clearing reply text and switching to PiP cannot prematurely clear playback.
  Ending the call suppresses video speaking; separate PCM speech still works.
- Ordered MP4 append, initialization reuse, interruption snapshots, and listener
  cleanup remain intact. The realtime hook and provider contracts are unchanged.
- Browser inspection verified actual pointer hover separately from keyboard
  focus: background `rgba(239, 68, 68, 0.5)`, white foreground, red border, no
  transform or brightness filter. Chinese and English labels remain readable,
  and clicking hang-up still ends the fixture call.

## Verification and limits

- Focused player/playback tests: 22 passed.
- Full frontend suite: 782 tests across 75 files passed.
- TypeScript and Vite production build passed.
- Backend suite: 1,084 tests and 117 subtests passed, with two existing
  dependency deprecation warnings.
- Browser checks used the real player and complete application stylesheet in
  a temporary local fixture, with simulated playback events. The fixture was
  removed. No paid Gemini session or packaged desktop playback was exercised.
- Backend tests used the available Python 3.12.3 runtime because the local
  Windows virtual environments refer to a missing interpreter. No installer
  build was performed.

## Follow-up: audio activity and canvas imports — 2026-10-05

The earlier `playing`-event fix was insufficient: continuous or silent avatar
video could keep the speaking badge active. The single original corner badge
and its layout are retained. Speech now requires energy in captured muxed audio
or the existing separate PCM flag. The existing microphone analyser determines
listening, takes priority during barge-in, and cannot be held active by stale ASR.
Video capture only feeds a silent analysis branch in the already-running call
AudioContext; it never redirects native media audio or creates another context.

The canvas runtime now loads the pinned React Lucide build and resolves
`lucide-react` imports. The tool declaration lists the available modules.
Unknown packages remain rejected; the iframe keeps `sandbox="allow-scripts"`
and errors still require the current iframe as their message source. Errors are
displayed once, with readable contrast and wrapping.

Adversarial self-review before pushing found no remaining blocking issues:

- Silent video, short pauses, simultaneous mic/output activity, lingering ASR,
  mute, waiting, media failure, suspended contexts, and late audio tracks were
  checked. Interruption, stream replacement, call end, and unmount release
  captured tracks, graph nodes, timers, and listeners without pausing the video.
- Named and namespace Lucide imports execute against the real pinned UMD build,
  including SVG props and interactive state. Unknown imports, script-tag
  escaping, error-source checks, and error reset remain covered.
- Real native MP4/AAC playback in the browser changed status between audible
  and silent sections. The canvas rendered imported icons and its Shop action
  worked. The temporary fixture and generated media were removed.
- The final layout has one status chip in the original header, no added status
  row, and no stylesheet changes. Regression tests assert the single-chip layout.

Final verification: 788 frontend tests across 75 files, TypeScript/Vite build,
1,084 backend tests, and 117 subtests passed. Backend tests reported the same two
dependency warnings. No paid Gemini session or Windows installer was run.
Audio capture support was checked in the browser, not every desktop runtime;
unsupported capture falls back to the separate PCM signal without inferring
speech from video. Canvas previews still require their existing CDN dependencies.

References: [media capture](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/captureStream),
[Lucide React](https://lucide.dev/guide/react/).
