# Echo robustness audit

## Working prompt

Audit Echo for real, reproducible bugs and improve its maintainability through small, verified changes. Prioritize data integrity, async lifecycle correctness, error recovery, and reliable user workflows. Establish a test baseline and reproduce each suspected bug before changing behavior. Add regression coverage for confirmed failures.

Simplify code around clear responsibilities: pages render UI, hooks coordinate feature state, API clients handle transport, backend routers validate and delegate, services own business behavior, repositories own persistence, and provider adapters own provider details. Reduce duplication and unnecessary state where doing so makes behavior easier to understand. Measure success by correctness and reduced conceptual complexity, rather than line count alone.

Preserve bilingual UI, provider-neutral contracts, voice interruption/replay/ordering semantics, local user data, and existing unrelated work. Extract large lifecycle modules incrementally with behavior-preserving tests. Follow AGENTS.md verification requirements. Report confirmed bugs separately from hypotheses, explain each change, and disclose untested behavior.

## First inspection: 2026-09-21

The repository already separates React feature hooks, FastAPI routers, services, and repositories. Improve those boundaries incrementally instead of replacing the architecture. Existing uncommitted desktop updater, packaging, and UI work was present before this audit and was left intact.

### Confirmed and fixed

`frontend/src/hooks/useLocalVoiceStatus.ts` cleared scheduled timers but did not invalidate pending setup requests. A request resolving after cancellation or unmount could restore old setup state and restart polling; a rejected request after unmount could restart retry polling.

Regression tests reproduced extra requests after cleanup. Each setup operation now owns a cancellation flag and its timer, with shared cleanup. Late responses from cancelled or replaced operations cannot update setup state or schedule more polling. Pending setup-start responses are also ignored after cleanup. This changes frontend watcher lifetime; it does not promise to stop backend installation merely because a page unmounts.

Six added cases cover cancellation during a request, unmount during a request, rejection after unmount, setup-start completion after unmount, transient failure recovery through completion, and a stale response from a replaced watcher.

### Verification

- Backend: 965 tests and 99 subtests passed using the existing Python environment. No installer was built.
- Frontend final full run: 524 tests passed across 62 files.
- Frontend production build: passed.
- Changed code whitespace check: passed.
- The initial frontend run had two application interaction failures when locating the Send button after input. Subsequent full and focused runs passed without modifying those interaction tests. The intermittent cause remains unresolved; rerun success is not evidence of a fix.

These checks validate the first patch, not every provider or desktop workflow. Live provider calls, hardware-dependent model installation, and packaged executable behavior were not exercised.

## Transcription history follow-up: 2026-09-21

Confirmed through failing hook or page tests and fixed:

- Single deletes swallowed every error and removed the cached record. Only an explicit HTTP 404 now counts as already deleted; other failures preserve the record and reach the page's error notice.
- Batch deletes removed failed IDs and synthesized a success response when the request failed. The cache now removes only IDs confirmed in `deleted`, retaining failed records for retry. Request failures propagate to the existing page error handling.
- Older list responses could overwrite a newer refresh or resurrect records after delete, update, or clear. A revision counter invalidates obsolete list results, including their errors and busy-state changes. Unmount invalidates pending refreshes.
- Status tabs merged filtered server results into the full cache without filtering the visible cards. The page now applies status and search together; the In Progress tab includes running, submitted, queued, and uploaded records, matching the backend listing semantics.
- The Refresh button passed a React mouse event into the hook's optional status argument. The unused argument was removed; refresh reads the selected filter directly.
- History refresh errors existed in hook state but were not displayed. The library now renders them through its error notice.
- Cache loading accepted arbitrary array members, including null and wrongly typed card fields. Invalid entries are excluded before reaching the UI, retaining valid cached records while the backend is unavailable.

Structure was simplified alongside the fixes: one effect persists committed history, one helper applies local history mutations and invalidates earlier snapshots, and the redundant prune/merge pass was removed. The hook is eight lines shorter despite the added validation and lifecycle protection.

Verification: the final full frontend run passed **538 tests across 62 files**, and the TypeScript/production build passed. There are 14 additional tests relative to the preceding 524-test run, plus a corrected test that previously required swallowing a failed delete. Backend code was not changed in this follow-up; the preceding 965-test backend baseline remains the last backend run. No live provider, installer, or hardware verification was performed. The wider audit remains open.

## Chat streaming follow-up: 2026-09-21

Send and Regenerate had duplicated stream handling with the same observable failures. Twelve initial regression cases failed before the correction:

- Delayed memory setup could persist an obsolete conversation group after New Chat, restoring history, or unmounting, then attempt to start the old stream.
- Late text, reasoning, completion metadata, and non-abort errors could modify a restored conversation.
- Unmounting the hook left its streaming request alive.
- Stream callbacks updated the last assistant message rather than the reply that originated the request. Appending another message while streaming redirected reply content and memory metadata to the wrong messages.

Both actions now share `streamReply`, with one controller ownership check, cleanup on unmount, and updates targeted by message ID. Error cleanup removes only the originating empty reply. Attachments, provider/model choices, memory options, partial replies, and regeneration history semantics are preserved. This removes **162 lines** from `useChat.ts` while strengthening its lifecycle boundary.

The added test file contains 21 cases covering these failures and behavior preservation, including memory lookup failure, partial stream failure, a newer request staying busy after an obsolete failure, and identical attachment/request options during regeneration. Final verification: **559 frontend tests passed across 63 files**, and the production build passed. The initial full run's four new-test failures were an error-formatter fixture mismatch, corrected without changing production behavior. Existing application interaction tests passed on both full runs; the earlier intermittent Send-button issue is still not proven fixed.

Inspection also found that audio overview had epoch checks inside its agent polling loop but lacked equivalent checks around surrounding awaits and workspace selection operations. The follow-up below addresses those failures.

## Audio overview follow-up: 2026-09-21

Ten initial regression cases reproduced obsolete requests replacing a new draft, displaying an old error, attaching old audio to another podcast, continuing save/synthesis after abandoning an unsaved draft, clearing a newly selected podcast when an older deletion completed, and fetching/allocating audio after unmount. Two further failures reproduced old list responses replacing newer data and resurrecting a deleted podcast in the list.

The hook now uses a workspace revision for generation, retries, saves, synthesis, podcast selection, and agent-run selection. One await helper rejects obsolete results and errors; a new operation resets busy flags, and only its own completion can clear them. New Draft and unmount invalidate pending workspace work. Successful deletion invalidates older list snapshots without clearing a different selected podcast. Podcast and agent-run lists have independent request ordering so list refreshes do not interrupt generation.

Loading podcast details/audio is shared between podcast selection and agent-run selection. Blob URL revocation has one owner in the existing cleanup effect. Polling accepts both `draft_ready` and `completed` as successful terminal states.

Twenty added lifecycle tests cover these cases, late save/audio/agent results, retry abandonment, newer busy state surviving older failures, agent-history ordering, successful generation, and URL replacement/unmount cleanup. Final verification: **579 frontend tests passed across 64 files**, the TypeScript/production build passed, and changed-file whitespace checks passed. Existing podcast option and page interaction tests remain green. No backend code changed in this follow-up.

This is frontend lifetime protection, not backend cancellation: a request already sent may still finish and persist a podcast on the server. Further review is needed for edits made within the same draft while a save or generation is pending, and for backend cancellation/persistence consistency.

## Persistence follow-up: 2026-09-21

Two backend failures were reproduced before editing production code:

- `update_podcast` committed topic/language before saving its script in a separate transaction. A SQLite trigger simulating a failed script insert left the new metadata paired with the old script. Metadata and script now commit together, with `BEGIN IMMEDIATE` covering the existence check and write. Create, update, and script-only save share the line-writing implementation. Tests cover rollback, normalization, clearing lines, and missing records.
- `delete_job` swallowed errors deleting its authoritative JSON record, then removed artifacts and reported success. A simulated locked record reproduced this. The record must now be removed successfully before best-effort artifact cleanup; single deletion raises and batch deletion reports the ID as failed when the record is locked. This preserves files needed to open/retry the record.

Two frontend regression cases also reproduced edits being overwritten while a save was pending, for both new and existing podcasts. Save responses now apply normalization only to unchanged editor fields, while preserving the server-assigned ID for the next save. The create/update endpoint already persists the script, so the redundant second script-save request was removed.

Cross-boundary verification: **970 backend tests and 99 subtests passed; 581 frontend tests across 64 files passed; production build and changed-file whitespace checks passed.**

One full frontend run timed out in the first chat interaction test: its lazy-load query explicitly allowed 10 seconds, but Vitest's outer default stopped the entire test after 5 seconds. That single test now has a 15-second outer allowance for the existing load timeout plus assertions. This corrects the observed timeout mismatch, not a proven product defect. It does not establish the cause of every earlier intermittent Send-button lookup failure.

Remaining persistence questions include concurrent JSON job updates/deletion and atomic file replacement. Direct JSON writes remain an audit candidate; the duplicated record decoding was subsequently consolidated in the transcription follow-up below. Backend tasks already sent remain outside the frontend workspace cancellation guarantee.

## Transcription opening follow-up: 2026-09-21

The library scanned every `tx_*.json` file as a job. Translation sidecars, empty objects, and mismatched record IDs could therefore produce duplicate or empty-looking entries. A regression fixture reproduced four listed entries where only one real job existed. Listing now uses the same validated reader as detail loading; sidecars and records whose stored ID does not match their filename are excluded. No user files are deleted or migrated.

A second regression reproduced a failed detail request silently falling back to a completed record with blank text. Detail loading now clears previous errors and exposes request failures. The empty detail state distinguishes an unavailable transcript from a saved record with no text, without asserting that the audio had no speech. Existing genuinely empty transcripts require retranscription; these changes do not reconstruct missing text or establish why a provider originally returned an empty result.

The focused frontend history/page suite passed all 34 tests. The backend recovery/metadata suite passed all 13 tests. See `Robustness_Release_Review.md` for clean-checkout verification of the published changes; earlier counts in this audit are historical and include the then-current local workspace.

## Remaining work, in order

1. **Transcription history integrity: initial fixes verified.** Deletion outcomes, stale list responses, malformed cache data, status filtering, and refresh errors are covered above. Continue checking interactions between concurrent job operations and background processing during the broader async and service audit.
2. **Async lifecycle audit.** Initial local voice setup, transcription-history, chat stream, audio workspace, and pending podcast-save corrections are verified above. Continue with transcription job actions, realtime voice reconnects, and backend cancellation/persistence interactions. Use deferred-response tests around observable behavior. Acceptance: stopped operations stay stopped and older results cannot replace newer state.
3. **Intermittent interaction tests.** The observed inner/outer timeout mismatch is corrected. The earlier Send-button lookup failures still need a demonstrated cause if reproducible; passing later runs alone is insufficient evidence of resolution.
4. **Transcription boundaries.** Inspect `backend/routers/transcription.py` and `backend/services/transcription_service.py` for business logic in transport code, repeated provider dispatch, and mixed persistence responsibilities. Their size makes them review candidates, not proven design defects. Extract one coherent responsibility at a time with existing behavior covered.
5. **Voice lifecycle boundaries.** Review `frontend/src/hooks/useVoiceChat.ts` and the realtime provider services. Identify independently testable responsibilities before extraction. Preserve interruption, ordering, replay, and cleanup semantics in each step.
6. **Shared code and styles.** Review `frontend/src/api/client.ts`, repeated request/error handling, and `frontend/src/styles.css`. Consolidate only demonstrated duplication. Verify feature behavior and visual layout when moving styles.
7. **Desktop verification.** Review updater changes in their own scope, run the Electron tests, and follow `docs/Windows_Packaging.md` for isolated build and executable checks when that scope is undertaken.

## Completion standard for each patch

Record the trigger and user impact; show a failing reproduction for a bug; make the smallest coherent correction; run relevant tests and required broader checks; report limitations. Keep speculative cleanup in this backlog until inspection justifies it. Use specialized skills when a task needs their capabilities, such as browser inspection or visual verification; the initial code audit requires no additional skill installation.
