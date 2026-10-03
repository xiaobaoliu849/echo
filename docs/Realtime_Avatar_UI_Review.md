# Realtime avatar UI review — 2026-10-03

## Result

The call occupies the conversation area instead of the composer. A large
portrait sits beside a bounded transcript pane. Portrait sizing observes only
its media pane and controls; growing text never enters that calculation. The
transcript scrolls independently and retains full words, including completed
turns. User input appears above the assistant response, with provisional speech
visibly marked. New speech is brought into view even when an old reply remains.
Readers who scroll back can keep reading without each new token moving them.

Wide and compact windows use the same two-pane design, with proportions and
spacing adapted to the chat pane's width. Source media dimensions determine the
portrait aspect ratio, avoiding a wide black backdrop. A compact composer keeps
text and attachments available. There is one transcript surface: opening full
Conversation history replaces the transcript pane with the ordinary message
list and moves the same video into the draggable floating window. Hangup returns
to normal conversation history.

The floating player keeps pointer capture, keyboard movement from its grip,
cancellation, and viewport clamping. Native popover presentation escapes canvas
containment without remounting media. Older runtimes retain the fixed fallback.

## Input transcription latency

Gemini input transcription chunks are forwarded immediately as cumulative,
provisional snapshots, including before the native interruption boundary. They
carry no old turn ID and cannot commit history, interrupt playback, cancel tools,
or write memory. Existing confirmation and interruption decisions remain the
source of canonical history. Confirmed input is published before memory lookup.

The frontend respects explicit turn IDs when confirming repeated provisional
updates: corrections within one turn replace that turn's input rather than
creating duplicate history. Existing tests still cover genuine new turns,
withdrawn previews, backchannels, interruption, and identical repeated utterances.

These changes remove application-side withholding and reply masking. They do
not control when Google first produces ASR text. Google's Live API exposes input
transcription as server events; no extra recognition provider was introduced.

## OPTIONS preflight repair

The backend previously allowed only frontend ports 5173 and 3000. Status polling
with X-Client-ID triggers preflight across origins. The middleware now permits
HTTP loopback origins on localhost, 127.0.0.1, and [::1] across local ports,
including preview/fallback ports. External, LAN, lookalike, and null origins are
still rejected. Authentication and middleware ordering are unchanged. Supplied
logs did not include Origin, so the precise failing origin is unconfirmed.
Restart the backend/application to apply the middleware change.

## Overall review

- Inspected the full frontend/backend diff before pushing.
- Kept one video mounted through stage, history, floating mode, and restoration.
- Kept ordered playback, interruption snapshots, reset, and unmount semantics.
- Removed duplicate captions and transcript-dependent portrait sizing.
- Preserved full transcript text, repeated utterances, and bilingual labels.
- Checked visible keyboard focus, selectable text, and usable call controls.
- Rejected untrusted CORS origins in explicit regression tests.
- Kept generated frontend output, local configuration, and review fixtures out
  of version control.

## Verification and limits

- Full frontend suite: 742 tests across 73 files.
- Frontend TypeScript and Vite production build passed.
- Full backend suite: 1,077 tests and 109 subtests passed; two existing
  deprecation warnings from Starlette/AnyIO and pydub/audioop.
- Browser review at 1440×1000 and 420×600, including full history, mouse dragging,
  restore, and canvas. Adding 20 history rows and a 9,000-character response kept
  the portrait dimensions unchanged: 398×708 on the wide window and 165×294 on
  the compact window. The body did not overflow; only the transcript scrolled.
- New input remained visible above a lingering long response. The floating
  window used the top layer and moved successfully after a mouse drag.
- Regression tests block memory lookup and native boundary handling to verify
  that captions are already delivered while canonical state stays protected.

Review was performed by the implementing agent. Visual checks used a local
portrait fixture, which was removed afterward. No paid provider session or new
Windows installer was run; live Google ASR timing and packaged desktop playback
remain unmeasured. This source change does not create an installer release.

## Design skill discovery

The curated skill listing includes figma-generate-design,
figma-implement-design, and figma-create-design-system-rules. No dedicated
realtime-avatar skill was present. No skills or plugins were installed; the
implementation uses Echo's existing React and bilingual patterns.

References: [Google Live API](https://ai.google.dev/api/live),
[FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/),
[MDN pointer capture](https://developer.mozilla.org/en-US/docs/Web/API/Element/setPointerCapture),
[OpenAI curated skills](https://github.com/openai/skills/tree/main/skills/.curated).
