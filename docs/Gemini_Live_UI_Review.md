# Gemini Live UI repair and adversarial review

## Refined request

Improve Echo's Google Agent Platform / Gemini 3.8 Live experience so users can
choose an avatar face, voice, and accent together in a clear bilingual interface.
Remove the intrusive standby bar after calls and when opening history. Keep
model, face, and voice names consistent across setup and active calls. Diagnose
unsupported faces accurately rather than implying an account problem. Preserve
the source video without synthetic background blur. Continue the existing
backend accent and avatar-error work, verify behavior, and perform an
adversarial review before pushing to GitHub.

## Review scope and resolved findings

- **Unverified catalog:** Sarah was a guessed preset. Real regional SDK
  handshakes and Google's official Multimodal Live API notebook catalog
  verified the 11 prebuilt avatars (Ben, Leo, Kai, Jay, Paul, Sam, Ingrid, Kira,
  Vera, Carmen, Piper) while rejecting Sarah. The UI now offers all 11
  prebuilt avatars and an exact-name entry for Cloud Studio's other custom faces.
- **Inaccessible choices:** Selecting Avatar previously closed the picker
  before users could choose a voice. It now opens one compact preferences
  panel, with independent face, voice, and accent choices.
- **Stale typed startup:** The stable typed-call callback captured initial
  settings. It now invokes the latest session-start function; regression tests
  check the actual WebSocket URL after preferences change.
- **History leakage:** The stage mounts only while a call is active. Message
  replacement closes the settings portal, stops playback, and rejects late
  events from the previous connection.
- **False default label:** An empty custom name previously would look like
  Ben in the summary. It now says to choose a face, disables Done, and remains
  rejected by the existing session validation.
- **Playback lifetime:** PiP retains the same video element. Interruption
  preserves MP4 initialization, a full reset clears it, and unmount removes
  listeners and releases playback. Ordered-fragment and provider replay tests
  remain unchanged.
- **Prompt safety and provider isolation:** Only fixed server-owned accent
  instructions are used. Unknown IDs are ignored. The frontend sends accents
  only for supported Gemini choices; Live Translate does not receive accent
  instructions. Existing provider-selection tests continue to pass.
- **Visual checks:** Browser checks confirmed independent Leo/Kore/British
  choices, a compact idle composer, theme-matching setup controls, and a
  scrollable panel with a persistent Done action. The source video uses
  contain sizing; the artificial blurred video/canvas duplicate is removed.

This review was performed in the implementation chat, with adversarial
regression cases and direct Cloud handshakes. It is not an independent audit.

## Verification boundaries

Final verification passed: 731 frontend tests across 71 files, the frontend
production build, and 1,073 backend tests (plus 99 subtests). The backend suite
reported two existing deprecation warnings. No installer was built. Regional
handshakes establish face and
voice configuration acceptance on the configured account, not voice quality,
accent accuracy, custom-avatar entitlement, or playback in every packaged
desktop runtime. Accent instructions guide the model and may vary. Provider
video blur cannot be sharpened by removing Echo's background effect.
