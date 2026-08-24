# Robustness Audit — 2026-08-24

Full-project robustness review (5 parallel review passes: HTTP/streaming layer,
realtime voice WebSockets, TTS/audio pipelines, frontend, config/security
boundary). **14 P1 findings were fixed the same day** (backend 577 tests + 89
subtests, frontend 277 tests green). This document records what was fixed and
the remaining P2 backlog with concrete file/line references.

> Note: line numbers refer to the tree at audit time and may drift as code changes.

## P1 — all FIXED on 2026-08-24

| # | Area | Problem | Fix |
|---|------|---------|-----|
| 1 | config | Non-atomic `config.json` writes + silent wipe-to-empty on parse failure → permanent loss of all API keys | tmp+`os.replace`+fsync in `save_all`, `.bak` of previous good content, memory snapshot preserved on read failure, save refused while disk unreadable (`config_loader.py`) |
| 2 | auth | Transcription jobs/transcripts readable without token even when auth enabled | `/api/transcription` added to sensitive-read prefixes; `/public/transcription` kept as deliberate capability URL (64-bit random ids, cloud ASR fetcher cannot send Bearer) |
| 3 | CORS | `"null"` origin allowed with credentials; CORS middleware innermost so 401s lacked CORS headers; SPA fallback used string-prefix containment | Removed `"null"`; CORSMiddleware registered last (outermost); `is_relative_to` containment |
| 4 | settings | GET /api/settings returned every API key/token in plaintext | Masked with `__MASKED__` sentinel; PUT resolves sentinel back to stored values; fetch-models endpoint does the same |
| 5 | evermem | Client-controlled `X-EverMem-Url` got the server-side Bearer key attached (SSRF/key exfiltration) | http(s)-only URLs; env key attached only when target host matches the trusted default |
| 6 | realtime | Qwen-Audio teardown used `FIRST_EXCEPTION` → normal client disconnect stranded upstream socket/recorder (zombie sessions) | Replaced with `_run_duplex_tasks`; explicit `websockets.exceptions` import (v15 lazy loader) |
| 7 | realtime | Doubao `openspeech_state` was a local of the receive loop → any text/media input raised NameError and killed the session | State hoisted to `_run_doubao_session`, shared by both duplex loops |
| 8 | frontend | `useVoiceChat.startSession` did not re-check session epoch after three awaits → mic stayed hot, panel bricked after switching sessions mid-connect | Epoch re-checks after EverMem/getUserMedia/AudioContext.resume awaits; stale invocation releases only its own resources |
| 9 | frontend | `RealtimeTranscriptionPanel.aliveRef` never reset after StrictMode mount→cleanup→mount → realtime ASR unusable in dev | Re-armed at effect body start |
| 10 | llm | SSE streams closed early by upstream reported as normal `done` (silent truncation) | `saw_done`/`saw_finish_reason`/`saw_completed` tracking; truncated streams raise instead |
| 11 | translate | Image upload slurped into RAM before validation, no size cap → multi-GB RSS spike/OOM | Content-type checked first, streamed read with 20 MB cap |
| 12 | transcription | Deleting a job did not cancel its background chunked pipeline (kept spending ASR budget, resurrected deleted record); task exceptions silently lost | `_BACKGROUND_TASKS` keyed by job id, cancel-on-delete (single + batch), done-callback logs failures |
| 13 | transcription | Job eviction never removed `uploads/` source media → orphaned multi-GB files forever | Eviction reads the record first and deletes managed uploads (never files outside `jobs_dir/uploads`) |
| 14 | documents/audio_overview | pypdf parsing blocked the event loop with no size cap; encrypted PDFs → 500; `temp_audio/audio_overview` had no eviction and delete_podcast orphaned audio | Streamed read + 50 MB cap, parsing via `asyncio.to_thread`, encryption → 400, per-page tolerance, `has_text` flag; new 200-file/72h eviction, superseded-take cleanup, delete removes managed audio |

## P2 backlog (39 items, unfixed)

### Network resilience

1. `llm_service.py` — New `httpx.AsyncClient` per call with scalar `timeout=180`
   (connect timeout = 180 s: blackholed host hangs ~3 min). No retry on
   idempotent status-poll GETs. Fix: shared module-level AsyncClient with
   `Timeout(connect=10, read=…)`; one retry on poll GETs.
2. `transcription_service.py:1286` (+ :1254/:1273/:1619/:1644/:1687/:1716;
   `llm_service.py` non-stream paths) — `.json()` without decode guard; an
   HTML error page (proxy/captive portal) becomes a confusing 500. Worst case:
   AssemblyAI poll loop dies after a successful 100 MB upload.
3. AssemblyAI polling (`transcription_service.py:1277-1294`) — zero tolerance
   for transient poll errors plus a hard 6-minute ceiling; long recordings hit
   "timed out" while AssemblyAI keeps processing remotely. Tolerate N
   consecutive failures; scale max_polls with probed duration.
4. `llm_service.py` `reason_about_text` — bare `except Exception: pass`; with
   EverMem configured but down, every job-status poll re-runs a ~60 s LLM +
   add_memory cycle forever. Narrow the except, log it, add per-job
   "memory attempted" marker.
5. `routers/tts.py` engine generators — raw `httpx.TransportError` surfaces as
   500 "internal" instead of the intended 503 dependency error; GPT-SoVITS
   retries a POST timeout with a GET (240 s per line, original exception
   swallowed).
6. `realtime_openai_provider.py:415-418` — any upstream `error` event ends the
   session; VAD races produce benign transient errors that kill calls. Add a
   benign-pattern allowlist like Qwen-Audio's.
7. `realtime_constants.py:379-385` via `realtime_qwen_audio_provider.py:146` —
   `struct.unpack` raises on odd-length binary frames, killing the send task.
   Truncate to `count*2` or guard.
8. `realtime_dashscope_client.py:287-290,336-341` — fire-and-forget spawned
   sends give no failure signal and no ordering guarantee; upstream death is
   only noticed via ping timeout (~30–50 s). Serialize sends through one
   writer queue and record first failure loudly.
9. `tts_service.py:1491-1525` (Azure SSE) — `.get()` without timeout can hang
   the daemon thread; the done marker is discarded when bytes were already
   read. Wrap in timeout and requeue until drained.

### Task lifecycle

10. Local chunked transcription jobs stay "running" forever after backend
    restart (in-memory task lost; persisted JSON keeps running). Startup sweep
    of transient statuses without `source_url` → mark failed.
11. `audio_agent_service.py` — cancellation is advisory: synthesis ignores
    checkpoints and terminal updates overwrite `cancelled` with
    `completed`/`draft_ready`. Re-check status right before each terminal
    update.
12. `routers/audio_agent.py:426-440` — run stream polls forever with no
    deadline; no startup reconciliation for interrupted runs (stuck rows only
    recoverable via undiscoverable execute endpoint). Add max poll duration +
    startup sweep marking stale non-terminal runs failed.
13. `realtime_glm4voice_provider.py:194-239` / `realtime_personaplex_provider.py:262-312`
    — turn-idle timer not cancelled when the receive loop is cancelled
    mid-turn → ghost timer fires into a closed socket. try/finally around loop body.

### Cache/file hygiene

14. `tts_service.py:296-299` — second `sorted(...)` pass in `_cleanup_old_cache`
    outside try/except; a vanishing file's `stat()` during eviction crashes an
    unrelated request with 500 (same TOCTOU shape at :1246/:1277).
15. `tts_service.py:281,297 vs 320` — eviction filter misses `.tmp` files that
    `_atomic_write_bytes`/Edge/ChatTTS create; crash mid-write leaks them
    permanently (no startup sweep either).
16. `tts_service.py:317-340` + `routers/tts.py:177-187` — Windows
    `os.replace` fails with PermissionError while Starlette streams the same
    cache file → concurrent same-text requests get spurious 503. Catch and
    fall back to a unique name.
17. `audio_overview_service.py:593-598` — `_merge_with_ffmpeg` subprocess.run
    has no timeout (unlike audio_tools helpers); hung ffmpeg leaks thread +
    request forever.
18. `audio_overview_service.py:527-538,643-644` — concat fallback blindly byte-
    copies across container formats (WAV segments concatenated into `.mp3`)
    returning unplayable "success". Refuse when extensions differ.
19. `routers/audio_overview.py:287-291` — download route loads whole MP3 via
    `read_bytes()` inside async route; return FileResponse (streams + range).
20. `routers/documents.py` polish — 30 000-char input but `max_tokens=4096`;
    long texts come back silently cut off mid-sentence. Chunk + concatenate.
21. `transcription_service.py:1074,1153,1230` — whole-file RAM read when
    ffmpeg is missing regardless of size before provider rejects >25 MB.
    Pre-check size against provider cap / fail fast when ffmpeg absent.
22. `routers/audio_overview.py:274` — fallback path still points at legacy
    repo-root temp dir the service no longer writes to.

### Frontend

23. `pages/ChatPage.tsx:438-456` — TTS playback race: overlapping speaker
    clicks leak blob URLs and play two audio tracks simultaneously. Re-check/
    revoke current refs after each await (or generation token).
24. `api/client.ts:953-964` — `streamChatCompletion` never calls
    `reader.cancel()` on early exit; reader lock + connection pinned until
    server closes. try/finally with cancel.
25. `components/AppSidebar.tsx:68,97` + `hooks/useSettings.ts:480` — raw
    localStorage access without try/catch; storage-disabled contexts crash the
    app behind the ErrorBoundary. Route through safeStorage helpers.
26. `hooks/useTranscriptionHistory.ts:98-119` — out-of-order responses race on
    fast filter switches (failed jobs shown under completed filter). Request-id guard.
27. `pages/TranscriptionPage.tsx:543` — retry failures swallowed
    (`.catch(() => {})`), zero user feedback.
28. `TranscriptionPage.tsx:350-355` + `RealtimeTranscriptionPanel.tsx:402-405` —
    clipboard writes without `.catch`; denial looks like success.
29. `components/chat/ChatInputBar.tsx:162-203` — SpeechRecognition dictation
    not stopped on unmount; browser keeps listening after tab switch.

### Config/security boundary

30. `services/settings_service.py:344-348` — historical note: masking now done
    (see P1 #4); remaining gap: none known for GET, but keep write-only-update
    ergonomics in mind when adding new secret fields to the template.
31. `config_loader.update()` merges onto cached snapshot without
    `reload(force=True)` first — external edits (manual tweak, second instance)
    are silently reverted by the next PUT.
32. `PUT /api/settings {"merge": false}` replaces the whole file with only the
    patched sections — one call permanently deletes other sections. Drop
    replace mode or restrict removals.
33. `routers/voices.py:164-182` — clone upload fully buffered before the 20 MB
    check; no global request size limit anywhere. Chunked cap or early
    Content-Length rejection.
34. Startup fragility — module-level singletons open SQLite/config before any
    error handling; unwritable APPDATA kills startup with no diagnostics and
    no degraded mode. Wrap init with clear fatal messaging.
35. Settings defaults are merged into responses only, never persisted; any
    future required key depends on every reader using `.get()`. Consider
    persisting the template once on first run.

### Realtime misc

36. `realtime_qwen_audio_provider.py:346-347` — bare `except Exception: break`
    around upstream recv swallows drops silently; emit error/session_closed
    before breaking.
37. `realtime_voice_service.py:559-585` — interruption-timeout finalize races
    a late terminal event → duplicate memory_write/turn_complete events.
    Per-session lock or funnel through receive loop.
38. `routers/voice_chat.py:324-326` — handler-level recovery `send_json/close`
    unguarded; secondary exception masks the original and dumps tracebacks.
    Check `client_state` first.
39. `main.py` root endpoint exposes `auth_enabled` state publicly (minor
    fingerprinting; fine for localhost-only desktop use, revisit if ever
    exposed beyond loopback).
