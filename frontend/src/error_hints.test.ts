import { describe, expect, it } from "vitest";
import { buildErrorHints, detectSuggestedProvider, parseErrorCode, parseRequestId } from "./error_hints";

describe("error_hints", () => {
  it("parses error code from prefixed message", () => {
    expect(parseErrorCode("AUTH_TOKEN_INVALID: Invalid Bearer token.")).toBe(
      "AUTH_TOKEN_INVALID"
    );
  });

  it("parses request_id from metadata suffix", () => {
    expect(parseRequestId("x failed (request_id: req_123-abc)")).toBe("req_123-abc");
  });

  it("returns exact error hints for known code", () => {
    expect(buildErrorHints("AUTH_TOKEN_MISSING: Missing Bearer token.")).toEqual([
      "Set token in client env (VITE_API_TOKEN) and retry.",
      "Ensure request includes Authorization: Bearer <token>."
    ]);
  });

  it("returns prefix error hints for grouped code", () => {
    expect(buildErrorHints("CHAT_PROVIDER_ERROR_TIMEOUT: upstream timeout")).toEqual([
      "Check provider API key / endpoint / model in Settings.",
      "Retry after confirming outbound network from backend."
    ]);
  });

  it("returns provider-specific hints for TRANSCRIPTION errors", () => {
    expect(buildErrorHints("TRANSCRIPTION_ERROR: Google Gemini Transcribe failed")).toEqual([
      "Check google_api_key in Settings → Google Gemini.",
      "Ensure outbound network proxy can connect to Google generativelanguage APIs."
    ]);
    expect(buildErrorHints("TRANSCRIPTION_ERROR: Deepgram ASR failed")).toEqual([
      "Check deepgram_api_key in Settings → Deepgram.",
      "Verify Deepgram account quota and model nova-3 availability."
    ]);
    expect(buildErrorHints("TRANSCRIPTION_ERROR: OpenAI Whisper failed")).toEqual([
      "Check openai_api_key in Settings → OpenAI.",
      "Ensure OpenAI balance is active and model whisper-1 is available."
    ]);
  });

  it("returns provider-specific hints for VOICE clone/design errors", () => {
    expect(
      buildErrorHints("VOICE_CLONE_PROVIDER_ERROR: Gemini voice clone failed (404)")
    ).toEqual([
      "Record 10–30 seconds of natural speech for the sample, then record the exact Google consent statement separately with the same speaker.",
      "If Google still returns 500, try the same two clips in Google AI Studio Voice Replication and keep the provider request ID for support."
    ]);
    expect(
      buildErrorHints("VOICE_DESIGN_PROVIDER_ERROR: Qwen voice design failed")
    ).toEqual([
      "Check dashscope_api_key in Settings → 阿里云 DashScope.",
      "Verify DashScope Voice Design/Clone service quota on Alibaba Cloud console."
    ]);
  });

  it("detects suggested provider target correctly", () => {
    expect(detectSuggestedProvider("Google API key not configured")).toEqual({
      provider: "Google",
      category: "provider",
      labelZh: "Google Gemini",
      labelEn: "Google Gemini"
    });
    expect(detectSuggestedProvider("Deepgram ASR request failed")).toEqual({
      provider: "Deepgram",
      category: "provider",
      labelZh: "Deepgram",
      labelEn: "Deepgram"
    });
    expect(detectSuggestedProvider("DashScope API key missing")).toEqual({
      provider: "DashScope",
      category: "provider",
      labelZh: "阿里云 DashScope",
      labelEn: "Alibaba DashScope"
    });
    expect(detectSuggestedProvider("random text with no provider")).toBeNull();
  });

  it("returns no hints when no code is available", () => {
    expect(buildErrorHints("unexpected failure")).toEqual([]);
  });
});
