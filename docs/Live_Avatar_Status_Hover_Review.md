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
