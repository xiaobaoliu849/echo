# Unified live conversation layout — 2026-10-04

Avatar calls use a compact text composer, leaving the conversation area for the
portrait and transcript. Screen sharing sits beside the history action, with
a source label, small preview, and explicit stop/cancel action when active.
Unsupported capture and errors remain visible. History retains sharing controls
and the same mounted avatar player.

Tavus opens with a transcript beside its video instead of an overlapping drawer.
Both providers use the same transcript surface, typography, and pane proportions.
Tavus retains camera controls and its own media transport. Captions are available
when the transcript is hidden. The transcript follows new speech until the reader
scrolls back. All new interface labels have Chinese and English variants.

## Adversarial review

The implementing agent reviewed the diff and exercised rendered React components
in headless Edge using temporary fixtures, without paid provider calls.

- A first narrow layout stacked the portrait above the transcript, reducing the
  portrait to 56×99 at 340×520. Keeping portrait and transcript beside one another
  raised it to 114×202 while retaining independent transcript scrolling.
- A subtitle action had no visible effect with Tavus's transcript open. It is
  now offered when the transcript is hidden, keeping one conversation text surface.
- PiP covered the history restore button in short windows. A smaller short-window
  PiP keeps the toolbar reachable. Normal clicks through history and restoration
  passed after this correction.
- Long replies did not resize the portrait: approximately 349×621 before and after
  a 12,600-character reply in a 1440×900 window with active sharing.
- The empty avatar composer measured 54 px high across the reviewed sizes.
- Reviewed Chinese layouts at 1440×900, 1024×650, 420×700, and 340×520 for both
  providers. English sharing, stopping, and history/transcript restoration passed
  at 768×420, 420×600, and 340×520; an avatar canvas split passed at 768×420. Body bounds stayed
  inside the viewport and no browser page errors occurred.
- Regression coverage verifies complete transcript text, follow/scroll-back
  behavior, capture cancellation/errors, sharing through history mode, and media
  identity across view switches. Existing playback and interruption tests pass.

## Verification and limits

- Frontend: 768 tests in 75 files passed; TypeScript and Vite production build passed.
- Backend: 1,084 tests and 117 subtests passed; two dependency deprecation warnings.
- Temporary review fixtures, generated output, and local configuration are excluded
  from the commit.

This review validates layout and application interactions with fixtures. It does
not measure live Tavus/Google media quality or packaged Windows behavior. No new
installer was created.

Reference: [Tavus's official React UI example](https://github.com/Tavus-Engineering/santa-template),
which groups camera, microphone, and screen-sharing actions in conversation controls.
