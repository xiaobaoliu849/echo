# Vercel realtime canvas verification

Verified on 2026-09-17 against GitHub/local baseline
`09c2c4b0f5545f3e28a3709712bd410de834812c`.

## Finding: the pushed fix was incomplete

The canvas artifact reached the frontend before the backend acknowledged the
tool call. The acknowledgement included both `callId` and `call_id` inside the
normalized `function-call-output` item. The deployed Vercel Gateway rejected the
extra native OpenAI field with close code 1008 and the message
`WebSocket transform rejected frame`.

Controlled live tests used synthetic requests for a tiny HTML red square:

| Tool-result frame | Result |
| --- | --- |
| Baseline implementation, including `call_id` | Exact reported 1008 failure reproduced |
| Normalized fields only; no subsequent `response-create` | Post-tool response completed |
| Normalized fields only; with `response-create` | Post-tool response completed |
| Same normalized frame with `call_id` added back | Exact 1008 failure reproduced again |

The follow-up `response-create` was not the cause. The backend now sends only
`type`, `callId`, `name`, and `output` in the tool-result item.

## Additional corrections from adversarial review

- Transport errors now reach the existing tool-delivery failure handler.
  `tool_response_sent` is recorded only after the sends succeed. A successful
  WebSocket send is not an upstream acknowledgement.
- Canvas code still reaches the frontend intact but is omitted from the
  acknowledgement artifact. A 49,000-emoji canvas previously risked exceeding
  the 256 KB gateway frame limit when echoed as escaped JSON.
- Standalone background `interactionStatus` updates can defer and finalize a
  turn. An idle update paired with `turnComplete` waits for the corresponding
  terminal event, avoiding duplicate completion.
- React previews compile module syntax before evaluation, allowing named and
  anonymous default exports, React imports, and interactive hooks. Previously,
  generated imports/exports appeared inside a `try` block and failed to parse.
- Preview errors include compilation failures, accept messages only from the
  current iframe, and reset when the preview mode changes. Generated source is
  encoded so literal closing script tags cannot break the preview boot script.
  The iframe retains its `allow-scripts` sandbox without `allow-same-origin`.

## Verification

- Full backend suite: 927 tests and 99 subtests passed.
- Full frontend suite: 499 tests across 60 files passed.
- Frontend TypeScript check and production build passed.
- Regression coverage includes exact success/error wire envelopes, send
  failure, oversized Unicode artifacts, background completion ordering,
  exported React components, imported and locally declared hooks, interactive
  updates, malformed code, and iframe error isolation.
- Live tests of the final provider loop and actual `VoiceAgentToolSession`
  passed with both `google/gemini-3.8-live` and
  `google/gemini-3.8-live-extended-thinking`: one canvas artifact, post-tool
  audio, and a subsequent text request answered on the same connection.

Live probes used synthetic text input and a nonpersisting memory stub. They did
not exercise microphone capture, acoustic interruption, or a packaged Windows
installer. Preview execution tests run real Babel and React in jsdom; they do
not verify CDN availability in the user's browser. React previews still require
the existing external runtimes and self-contained components; arbitrary npm
imports are unsupported and now produce a visible error.

## Protocol references

- [Vercel normalized conversation item contract](https://github.com/vercel/ai/blob/main/packages/provider/src/realtime-model/v4/realtime-model-v4-conversation-item.ts)
- [Google realtime event mapping](https://github.com/vercel/ai/blob/main/packages/google/src/realtime/google-realtime-event-mapper.ts)
- [Gateway realtime transport](https://github.com/vercel/ai/blob/main/packages/gateway/src/gateway-realtime-model.ts)
- [Babel standalone API](https://babeljs.io/docs/babel-standalone)
