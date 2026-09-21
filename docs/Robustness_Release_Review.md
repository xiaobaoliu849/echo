# Echo robustness change review — 2026-09-21

This review covers the fixes on `codex/robustness-transcription-review`, based on upstream `f55072c`. It is a source-code review checkpoint, not a packaged application release. The application version is unchanged.

## Changes and separate commits

| Commit | User-visible correction |
| --- | --- |
| `36f9b62` | Cancelled or replaced local voice setup watchers cannot restart polling from late responses. |
| `2fbcbc9` | Chat send/regenerate share reply handling; abandoned streams cannot overwrite newer messages. |
| `abe60ea` | Transcription history excludes auxiliary JSON and invalid job identities; failed record deletion preserves its artifacts. |
| `c721276` | History filtering, refresh, deletion, and stale responses are corrected; detail-load failures show an error instead of an apparently empty successful transcript. |
| `5645d84` | Podcast metadata and script updates commit or roll back together. |
| `9e8a796` | Older podcast operations cannot overwrite a newer workspace; save responses preserve edits made while saving. |
| `0e88916` | The chat interaction test's outer timeout accommodates its existing lazy-load query timeout. |

The fixes consolidate duplicated chat streaming, transcription record reading, and podcast script persistence. Regression tests focus on observable failures and deferred request ordering. The audit prompt, evidence, and remaining work are recorded in `Robustness_Audit.md`.

## Verification

Verification uses a separate clean checkout of code commit `0e88916`, with dependencies installed from the tracked frontend lockfile. Uncommitted updater changes and local runtime data are absent.

- Frontend: 577 tests across 63 files passed.
- TypeScript and Vite production build: passed.
- Backend: 984 tests and 99 subtests passed after the build.
- Git whitespace check: passed.

The first backend run started before the frontend build finished: 982 tests and 99 subtests passed, while two desktop asset tests failed because `frontend/dist/index.html` was absent. The full backend suite was then rerun after the build. This was a verification-order error, not evidence of an application regression.

## Limits and remaining work

The broader application audit remains open. Concurrent transcription record writes/deletion, further realtime lifecycle review, and incremental module extraction still require investigation. Frontend cancellation guards do not cancel requests already executing on the backend.

Live provider transcription, microphone/hardware flows, and packaged installers were not exercised. Existing saved transcripts with no text cannot be recovered by these fixes; the UI now reports their state accurately. No user recordings or saved records were modified.

Pre-existing desktop updater, packaging, and related settings/UI changes remain local and are excluded from this branch's new commits. No installer, release tag, or version bump is included.
