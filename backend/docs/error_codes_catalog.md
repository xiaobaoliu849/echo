# Backend Error Codes Catalog

This document is the consolidated error-code reference for VoiceSpirit (Echo) backend APIs.
All structured error responses use the standard envelope:

```json
{
  "detail": {
    "code": "ERROR_CODE_CONSTANT",
    "message": "Human readable error description",
    "meta": {
      "request_id": "...",
      "extra": "..."
    }
  }
}
```

## Observability & Tracing

- All HTTP responses include the `X-Request-ID` header.
- Structured error responses include `detail.meta.request_id` matching `X-Request-ID`.
- Global middleware normalizes FastAPI `HTTPException` and `RequestValidationError` into this catalog format.

---

## 1. Authentication (`AUTH_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `AUTH_TOKEN_MISSING` | `401` | Write request requires bearer token but none was provided. |
| `AUTH_TOKEN_INVALID` | `401/403` | Bearer token is invalid, expired, or revoked. |
| `AUTH_ADMIN_TOKEN_MISSING` | `401` | Admin-protected endpoint requires admin bearer token. |
| `AUTH_ADMIN_TOKEN_INVALID` | `403` | Provided token is not the configured admin token. |
| `AUTH_RATE_LIMITED` | `429` | IP or account rate limit exceeded; check `Retry-After` header. |
| `AUTH_REGISTER_FAILED` | `400` | Account registration failed (e.g. invalid email format, weak password, duplicate email). |
| `AUTH_LOGIN_FAILED` | `401` | Incorrect email or password. |
| `AUTH_CHANGE_PASSWORD_FAILED` | `400` | Password change failed (e.g. current password mismatch, new password policy violation). |

---

## 2. Audio Overview / Podcasts (`AUDIO_OVERVIEW_*`, `AUDIO_SCRIPT_*`, `AUDIO_SYNTHESIZE_*`, `AUDIO_MERGE_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `AUDIO_OVERVIEW_NOT_FOUND` | `404` | Podcast episode with specified ID does not exist. |
| `AUDIO_OVERVIEW_LIST_FAILED` | `500` | Failed to retrieve podcast list from database. |
| `AUDIO_OVERVIEW_GET_FAILED` | `500` | Failed to retrieve podcast details. |
| `AUDIO_OVERVIEW_GET_LATEST_FAILED` | `500` | Failed to retrieve latest podcast episode. |
| `AUDIO_OVERVIEW_AUDIO_GET_FAILED` | `500` | Failed to prepare audio file retrieval. |
| `AUDIO_OVERVIEW_AUDIO_MISSING` | `404` | Podcast record exists but has no synthesized audio path. |
| `AUDIO_OVERVIEW_AUDIO_FILE_NOT_FOUND` | `404` | Synthesized audio file referenced by podcast does not exist on disk. |
| `AUDIO_OVERVIEW_CREATE_BAD_REQUEST` | `400` | Invalid podcast creation payload. |
| `AUDIO_OVERVIEW_CREATE_FAILED` | `500` | Database insert failed during podcast creation. |
| `AUDIO_OVERVIEW_UPDATE_BAD_REQUEST` | `400` | Invalid podcast update payload. |
| `AUDIO_OVERVIEW_UPDATE_FAILED` | `500` | Database update failed during podcast modification. |
| `AUDIO_OVERVIEW_SCRIPT_BAD_REQUEST` | `400` | Invalid dialogue script lines in request payload. |
| `AUDIO_OVERVIEW_SCRIPT_SAVE_FAILED` | `500` | Failed to persist dialogue script lines to database. |
| `AUDIO_OVERVIEW_DELETE_FAILED` | `500` | Failed to delete podcast record and associated audio. |
| `AUDIO_SCRIPT_GENERATE_BAD_REQUEST` | `400` | Invalid script generation parameters (e.g. invalid topic length, turn count). |
| `AUDIO_SCRIPT_GENERATE_PROVIDER_ERROR` | `502` | Upstream LLM provider failed during dialogue script generation. |
| `AUDIO_SCRIPT_GENERATE_FAILED` | `500` | Unexpected failure during dialogue script generation. |
| `AUDIO_SYNTHESIZE_BAD_REQUEST` | `400` | Invalid synthesis request (e.g. empty dialogue script). |
| `AUDIO_SYNTHESIZE_RUNTIME_ERROR` | `503` | Audio synthesis failed due to engine runtime error. |
| `AUDIO_SYNTHESIZE_FAILED` | `500` | Unexpected server error during podcast synthesis. |
| `AUDIO_MERGE_STRATEGY_INVALID` | `400` | Unsupported audio `merge_strategy` specified. |
| `AUDIO_MERGE_PYDUB_FAILED` | `503` | Segment audio concatenation via `pydub` failed. |
| `AUDIO_MERGE_FFMPEG_FAILED` | `503` | Segment audio concatenation via `ffmpeg` failed. |
| `AUDIO_MERGE_ALL_FAILED` | `503` | All fallback merge strategies (`pydub -> ffmpeg -> concat`) failed. |
| `AUDIO_SEGMENT_SYNTHESIS_FAILED` | `503` | TTS synthesis failed for a specific dialogue segment. |
| `AUDIO_INTRO_MUSIC_EXPORT_FAILED` | `503` | Intro background music synthesis/merging failed. |
| `AUDIO_MERGE_UNKNOWN_ERROR` | `500` | Unexpected merge-layer failure. |

---

## 3. Chat & Translation (`CHAT_*`, `TRANSLATE_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `CHAT_BAD_REQUEST` | `400` | Invalid chat request payload (e.g. empty messages, invalid model). |
| `CHAT_PROVIDER_ERROR` | `502` | Upstream LLM provider returned an error or failed to respond. |
| `CHAT_INTERNAL_ERROR` | `500` | Unexpected error in chat completion handler. |
| `TRANSLATE_BAD_REQUEST` | `400` | Invalid text translation payload (e.g. empty text, invalid language). |
| `TRANSLATE_PROVIDER_ERROR` | `502` | Upstream translation provider failure. |
| `TRANSLATE_INTERNAL_ERROR` | `500` | Unexpected server error during text translation. |
| `TRANSLATE_IMAGE_BAD_REQUEST` | `400` | Invalid image translation payload or non-image MIME type. |
| `TRANSLATE_IMAGE_TOO_LARGE` | `400` | Uploaded image exceeds maximum size limit (20 MB). |
| `TRANSLATE_IMAGE_PROVIDER_ERROR` | `502` | Multimodal/OCR LLM provider failed during image translation. |
| `TRANSLATE_IMAGE_INTERNAL_ERROR` | `500` | Unexpected server error during image translation. |

---

## 4. Settings & Credentials (`SETTINGS_*`, `SECRET_*`, `FETCH_MODELS_*`, `DESKTOP_STATUS_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `SETTINGS_LOAD_FAILED` | `500` | Failed to read configuration from `config.json`. |
| `SETTINGS_BAD_REQUEST` | `400` | Settings patch validation failed (e.g. malformed JSON, invalid types). |
| `SETTINGS_UPDATE_FAILED` | `500` | Failed to save updated settings to `config.json`. |
| `SECRET_FIELD_UNKNOWN` | `404` | Requested field or custom provider ID is not a revealable secret. |
| `SECRET_REVEAL_FAILED` | `500` | Failed to read masked secret value. |
| `DESKTOP_STATUS_LOAD_FAILED` | `500` | Failed to load desktop preflight diagnostics. |
| `MISSING_API_KEY` | `400` | Provider API key is missing when required to fetch models. |
| `MISSING_BASE_URL` | `400` | Provider Base URL is missing when required to fetch models. |
| `INVALID_API_KEY_ENCODING` | `400` | Provider API key contains invalid non-ASCII characters. |
| `INVALID_BASE_URL_ENCODING` | `400` | Provider Base URL contains invalid non-ASCII characters. |
| `INVALID_HEADER_ENCODING` | `400` | Request headers contain non-ASCII characters that cannot be encoded. |
| `FETCH_MODELS_HTTP_ERROR` | `500` | Upstream provider `/models` endpoint returned HTTP error status. |
| `FETCH_MODELS_FAILED` | `500` | Network or connection failure while reaching provider models API. |
| `FETCH_MODELS_PARSE_FAILED` | `500` | Failed to parse model list JSON from provider response. |

---

## 5. TTS & Document Extraction (`TTS_*`, `PDF_EXTRACT_*`, `TTS_POLISH_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `TTS_VOICES_BAD_REQUEST` | `400` | Invalid query parameters for voice listing. |
| `TTS_VOICES_INTERNAL_ERROR` | `500` | Voice list retrieval failed unexpectedly. |
| `TTS_SPEAK_BAD_REQUEST` | `400` | Invalid TTS synthesis parameters (e.g. empty text, unsupported engine). |
| `TTS_SPEAK_DEPENDENCY_ERROR` | `503` | Required TTS runtime dependency missing or unavailable (e.g. `edge-tts`). |
| `TTS_SPEAK_INTERNAL_ERROR` | `500` | Unexpected server error during TTS synthesis. |
| `PDF_EXTRACT_MISSING_DEP` | `400` | PDF extraction library (`pypdf`) is not installed. |
| `PDF_EXTRACT_BAD_REQUEST` | `400` | Uploaded file is not a valid PDF or could not be parsed. |
| `PDF_EXTRACT_TOO_LARGE` | `400` | PDF file exceeds maximum upload size (50 MB). |
| `PDF_EXTRACT_ENCRYPTED` | `400` | PDF is password-protected and cannot be decrypted without user password. |
| `PDF_EXTRACT_INTERNAL_ERROR` | `500` | Unexpected server error during PDF text extraction. |
| `TTS_POLISH_BAD_REQUEST` | `400` | Input text for TTS polishing is empty or invalid. |
| `TTS_POLISH_INTERNAL_ERROR` | `500` | LLM text polishing for TTS failed. |

---

## 6. Voice Design & Voice Cloning (`VOICE_*`)

| Code Prefix / Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `VOICE_DESIGN_*` | `400/502/500` | Voice design parameter validation, provider API, or server errors. |
| `VOICE_CLONE_*` | `400/502/500` | Voice cloning audio upload, reference training, or provider errors. |
| `VOICE_LIST_*` | `400/502/500` | Custom voice listing request/provider/internal errors. |
| `VOICE_DELETE_*` | `400/502/500` | Custom voice deletion request/provider/internal errors. |

---

## 7. Speech-to-Text & Audio Transcription (`TRANSCRIPTION_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `TRANSCRIPTION_FILE_MISSING` | `400` | No audio file provided in upload request. |
| `TRANSCRIPTION_UNSUPPORTED_FORMAT` | `400` | Audio format extension is not in supported list (`.mp3`, `.wav`, `.m4a`, etc.). |
| `TRANSCRIPTION_FILE_TOO_LARGE` | `413` | Audio upload exceeds maximum transcription file size (4 GB). |
| `TRANSCRIPTION_VALIDATION_ERROR` | `400` | Invalid transcription parameters (e.g. empty transcript, invalid chunk parameters). |
| `TRANSCRIPTION_ERROR` | `500` | Unexpected failure during transcription processing. |
| `TRANSCRIPTION_JOB_BAD_REQUEST` | `400` | Invalid transcription job request (e.g. invalid URL, missing job ID). |
| `TRANSCRIPTION_JOB_CREATE_FAILED` | `500` | Failed to initialize transcription job in database. |
| `TRANSCRIPTION_JOB_LIST_FAILED` | `500` | Failed to list transcription jobs from database. |
| `TRANSCRIPTION_JOB_NOT_FOUND` | `404` | Transcription job with specified ID does not exist. |
| `TRANSCRIPTION_JOB_GET_FAILED` | `500` | Failed to retrieve transcription job details. |
| `TRANSCRIPTION_JOB_RETRY_FAILED` | `500` | Failed to schedule retry for transcription job. |
| `TRANSCRIPTION_JOB_RENAME_FAILED` | `500` | Failed to update transcription job title. |
| `TRANSCRIPTION_JOB_DELETE_FAILED` | `500` | Failed to delete transcription job record or artifacts. |
| `TRANSCRIPTION_NOT_COMPLETED` | `400` | Requested operation requires job status `completed` (job is still in-flight or failed). |
| `TRANSCRIPTION_TRANSCRIPT_NOT_FOUND` | `404` | Transcript text file does not exist on disk for this job. |
| `TRANSCRIPTION_MEMORY_UNAVAILABLE` | `400` | EverMem long-term memory is not configured for transcript persistence. |
| `TRANSCRIPTION_MEMORY_SAVE_FAILED` | `500` | Failed to save transcript memory to EverMem. |
| `TRANSCRIPTION_AUDIO_NOT_FOUND` | `404` | Audio file for transcription job does not exist on disk. |
| `TRANSCRIPTION_WORDS_NOT_FOUND` | `404` | Word-level timestamp data not found for transcription job. |
| `TRANSCRIPTION_WORDS_READ_FAILED` | `500` | Failed to read word-level timestamp JSON data. |
| `TRANSCRIPTION_TRANSLATE_FAILED` | `500` | LLM translation of transcription subtitles failed. |
| `TRANSCRIPTION_BURN_FAILED` | `500` | FFmpeg video subtitle burning operation failed. |
| `TRANSCRIPTION_VIDEO_NOT_FOUND` | `404` | Burned subtitled video file not found on disk. |

---

## 8. EverMemOS Long-Term Memory (`EVERMEM_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `EVERMEM_NOT_CONFIGURED` | `400` | EverMem is not enabled or API key is not configured for the request. |
| `EVERMEM_CONVERSATION_META_FAILED` | `502` | EverMemOS upstream API failed to return conversation metadata. |
| `EVERMEM_GROUP_ID_MISSING` | `502` | EverMemOS response did not include a valid `group_id`. |

---

## 9. Tavus Video PAL (`TAVUS_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `TAVUS_NOT_CONFIGURED` | `400` | Tavus API key is missing. Configure it in PAL settings or `TAVUS_API_KEY`. |
| `TAVUS_PAL_ID_MISSING` | `400` | PAL ID is required to initiate a video avatar conversation. |
| `TAVUS_AUTH_REJECTED` | `502` | Tavus upstream rejected the provided API key (401/403). |
| `TAVUS_UPSTREAM_ERROR` | `502` | Tavus upstream API returned an error during PAL listing or conversation creation. |

---

## 10. Voice Chat & Agent Runs (`VOICE_AGENT_*`, `AGENT_RUN_*`, `AUDIO_AGENT_*`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `VOICE_AGENT_SESSION_NOT_FOUND` | `404` | Voice chat session ID does not exist in `voice_spirit.db`. |
| `AGENT_RUN_NOT_FOUND` | `404` | Canonical agent run ID does not exist in `voice_spirit.db`. |
| `AUDIO_AGENT_RUN_BAD_REQUEST` | `400` | Invalid audio research agent run parameters. |
| `AUDIO_AGENT_RUN_NOT_FOUND` | `404` | Audio agent run with specified ID does not exist. |
| `AUDIO_AGENT_RUN_CREATE_FAILED` | `500` | Failed to initialize audio agent run in database. |
| `AUDIO_AGENT_RUN_LIST_FAILED` | `500` | Failed to list audio agent runs. |
| `AUDIO_AGENT_RUN_GET_FAILED` | `500` | Failed to retrieve audio agent run record. |
| `AUDIO_AGENT_EVENT_LIST_FAILED` | `500` | Failed to retrieve event stream for audio agent run. |
| `AUDIO_AGENT_RUN_EXECUTE_FAILED` | `500` | Failed to schedule background execution for audio agent run. |
| `AUDIO_AGENT_RUN_SYNTHESIZE_FAILED` | `500` | Failed to trigger podcast synthesis for audio agent draft. |
| `AUDIO_AGENT_CANCEL_FAILED` | `500` | Failed to cancel active audio agent run. |
| `AUDIO_AGENT_RETRY_FAILED` | `500` | Failed to retry failed audio agent run step. |

---

## 11. Global / Request Validation (`REQUEST_VALIDATION_ERROR`, `UNHANDLED_EXCEPTION`)

| Code | Typical HTTP | Meaning |
| --- | --- | --- |
| `REQUEST_VALIDATION_ERROR` | `422` | FastAPI request body / query parameter schema validation failure. |
| `UNHANDLED_EXCEPTION` | `500` | Uncaught server exception caught by top-level error handler middleware. |

---

## Related Documents

- Audio Overview merge and synthesis details: `backend/docs/audio_overview_error_codes.md`
- Authentication behavior and token sources: `backend/docs/authentication.md`
