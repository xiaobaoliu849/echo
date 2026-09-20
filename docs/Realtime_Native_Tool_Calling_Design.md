# Realtime Native Tool Calling Design

Status: implementation specification  
Scope: realtime voice chat for Google Gemini Live and DashScope Qwen Omni Realtime  
Last updated: 2026-07-13

## 1. Problem statement

The prior VoiceSpirit implementation recognized tool intent from the completed user transcript, started a local task, suppressed provider output, and injected the result back as natural-language instructions. That compatibility path had no provider call identifier and raced the provider response. It could therefore misclassify a discussion about a tool as an invocation, discard an acknowledgement that the model had already generated, or cause the result to be interpreted as a new user turn.

The target architecture uses each provider's typed function-call protocol. Realtime providers that do not support native function calling are rejected rather than routed through a second, transcript-driven behavior.

## 2. Authoritative protocol behavior

### Gemini Live

- Function declarations are supplied in `LiveConnectConfig.tools`.
- A server `tool_call` contains one or more function calls with an `id`, `name`, and JSON arguments.
- VoiceSpirit executes each supported call and returns a `FunctionResponse` with the same `id` and `name` through `session.send_tool_response`.
- A server tool-call cancellation invalidates the matching local call. A late result must not be returned.
- The synchronous behavior is the default for the current Gemini model. The model resumes only after the typed response arrives.

References:

- <https://ai.google.dev/gemini-api/docs/live-api/tools>
- <https://ai.google.dev/api/live>
- <https://github.com/google-gemini/gemini-live-api-examples/blob/main/gemini-live-genai-python-sdk/gemini_live.py>

### Qwen Omni Realtime

- Tools are supplied in `session.update`.
- `response.function_call_arguments.done` contains `call_id`, `name`, and JSON arguments.
- VoiceSpirit sends `conversation.item.create` with item type `function_call_output` and the same `call_id`.
- Because VoiceSpirit configures `create_response: false`, it explicitly sends `response.create` after the output item.
- VoiceSpirit defaults to the moving `qwen3.5-omni-plus-realtime` alias. The 3.8 generation (`qwen3.8-omni-flash-realtime`) is supported and runs on the same profile but is not the default yet — its sessions are closed by the server right after they open in the configured workspace; see `docs/Qwen_3_8_Omni_Realtime.md`. Older Qwen 3 Omni Realtime models are rejected because their WebSocket API does not support Function Calling.

References:

- <https://help.aliyun.com/zh/model-studio/qwen-function-calling>
- <https://help.aliyun.com/zh/model-studio/omni-realtime-interaction-process>

## 3. Required invariants

1. Every native call has a non-empty provider `call_id`.
2. Exactly one terminal local event is recorded for a call: completed, failed, or cancelled.
3. A result is returned only through the provider's typed tool-response channel.
4. A cancelled or superseded call cannot trigger a later assistant response.
5. Native calls never depend on transcript keyword recognition.
6. Realtime chat does not silently downgrade to transcript keyword routing.
7. Tool arguments are validated and normalized before execution. Unknown names and malformed arguments produce typed error results.
8. Native synchronous calls do not inject prompts or start a competing assistant response.
9. Tool status is visible immediately. A spoken acknowledgement is optional UX, not an extra model turn.
10. Live translation never exposes or executes application tools.

## 4. Provider-neutral contract

`RealtimeToolCall` is the internal boundary:

```text
provider_call_id: provider correlation identifier
tool_name:        allow-listed function name
arguments:        decoded JSON object
provider:         Google or DashScope
```

The executor maps this contract to the existing `VoiceToolRequest`, preserving the current tool implementations and timeline events. The provider adapter alone is responsible for converting the result to Gemini `FunctionResponse` or Qwen `function_call_output`.

Supported declarations:

| Function | Required arguments | Confirmation |
| --- | --- | --- |
| `search_web` | `query` | no |
| `translate_text` | `text`, `target_language` | no |
| `summarize_transcript` | `text` | no |
| `synthesize_tts` | not exposed | requires a future confirmation flow |
| `create_audio_agent_run` | not exposed | requires a future confirmation flow |

`requires_confirmation` was previously metadata only; no executable confirmation flow existed. Consequently, side-effecting tools are deliberately absent from native declarations in this iteration. They must not be exposed until a frontend confirmation command and a backend pending-call state are implemented and tested.

## 5. State and cancellation

```text
LISTENING -> TOOL_REQUESTED -> TOOL_RUNNING -> RESULT_READY -> ANSWERING -> DONE
                         \-> FAILED
                         \-> CANCELLED
```

- `VoiceAgentToolSession` owns one task per provider call ID and may execute a Gemini batch concurrently.
- A true barge-in cancels every still-running native call before the next user turn is accepted.
- Provider cancellation is correlated by call ID. Unknown cancellation IDs are ignored.
- Result delivery and cancellation share a per-call lock, so exactly one path wins.
- Gemini responses from one server batch are collected and returned in one `send_tool_response` call.
- Session shutdown drains or cancels the task and does not send results after transport closure.

## 6. User experience

- Emit `tool_call_started` immediately, with both the VoiceSpirit turn ID and provider call ID.
- Use the existing status area for deterministic bilingual progress.
- Do not ask the model to say “let me check” before calling a tool.
- Fast calls return silently to the model. Longer calls may later use a local earcon or canned acknowledgement, but that audio must not become a conversation turn.
- Emit `tool_result_delivered` only after the typed provider response has been accepted.
- The provider generates one grounded final response after the tool result.

## 7. Model policy

| Provider/model | Route |
| --- | --- |
| Gemini Live chat | native function calling |
| Gemini Live Translate | no tools |
| Qwen 3.5 Omni Plus Realtime | native function calling |
| Older Qwen Omni Realtime | rejected with an actionable upgrade error |
| OpenAI Realtime | unchanged and outside this change |

Google and Qwen realtime chat have one tool-routing behavior only. Removing the fallback is intentional: a fallback would retain the races and ambiguous semantics this design exists to eliminate.

## 8. Implementation phases

1. Extract declarations, argument normalization, provider call contract, and model capability checks into a provider-neutral service module.
2. Extend `VoiceAgentToolSession` to execute a validated request with an optional provider call ID.
3. Register and consume Gemini native calls; add cancellation handling and typed responses.
4. Upgrade the Qwen default, register and consume Qwen 3.5 native calls using SDK `send_raw`, and reject old models.
5. Update frontend/API event metadata and status wording to reflect typed result delivery.
6. Add protocol, replay, cancellation, malformed-call, batching, and unsupported-model rejection tests.
7. Run focused tests, backend suite, frontend suite, production build, and repository hygiene checks.

## 9. Acceptance evidence

- Unit tests prove declaration schemas and argument validation.
- Google replay tests cover typed success/error responses, batched call-ID preservation, and provider cancellation.
- DashScope callback/replay tests cover event parsing, raw output item shape, explicit response creation, and old-model rejection.
- Tool-session tests cover concurrent calls, duplicate provider IDs, and cancellation/result-delivery races.
- Frontend tests cover native call metadata, non-duplicated assistant text, and status cleanup at turn completion.
- Final verification must run every command from `AGENTS.md` plus `git diff --check` before push.
