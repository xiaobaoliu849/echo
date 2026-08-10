import { describe, it, expect } from "vitest";
import {
  DASHSCOPE_PROVIDER,
  DEFAULT_PERSONAPLEX_VOICE,
  DOUBAO_PROVIDER,
  GOOGLE_PROVIDER,
  OPENAI_PROVIDER,
  PERSONAPLEX_PROVIDER,
  PERSONAPLEX_REALTIME_VOICES,
  resolveRealtimeProvider,
} from "./useVoiceChatHelpers";

// ---------------------------------------------------------------------------
// resolveRealtimeProvider
//
// This function silently falls back when a provider is not in its allow-list.
// A provider missing from that list therefore does not fail loudly — the UI
// keeps showing the provider the user picked while the socket connects to the
// fallback instead, which is how a PersonaPlex selection ended up reporting a
// Doubao 403.
// ---------------------------------------------------------------------------
describe("resolveRealtimeProvider", () => {
  const allProviders = [
    GOOGLE_PROVIDER,
    DASHSCOPE_PROVIDER,
    OPENAI_PROVIDER,
    DOUBAO_PROVIDER,
    PERSONAPLEX_PROVIDER,
  ];

  it("honours every realtime provider it is offered", () => {
    // Table-driven on purpose: adding a provider to the UI without adding it
    // here is exactly the omission that caused the misrouting.
    for (const provider of allProviders) {
      expect(resolveRealtimeProvider(provider, allProviders)).toBe(provider);
    }
  });

  it("keeps PersonaPlex instead of falling back to Doubao", () => {
    expect(resolveRealtimeProvider(PERSONAPLEX_PROVIDER, allProviders)).toBe(
      PERSONAPLEX_PROVIDER,
    );
  });

  it("falls back only when the preferred provider is unavailable", () => {
    expect(resolveRealtimeProvider(PERSONAPLEX_PROVIDER, [DOUBAO_PROVIDER])).toBe(
      DOUBAO_PROVIDER,
    );
  });

  it("falls back when no provider is preferred", () => {
    expect(resolveRealtimeProvider(undefined, allProviders)).toBe(DOUBAO_PROVIDER);
  });

  it("ignores a provider that is not a realtime provider at all", () => {
    expect(resolveRealtimeProvider("DeepSeek", allProviders)).toBe(DOUBAO_PROVIDER);
  });
});

// ---------------------------------------------------------------------------
// PersonaPlex voice defaults
// ---------------------------------------------------------------------------
describe("PersonaPlex voices", () => {
  it("uses a default voice that exists in the catalog", () => {
    // The backend falls back to this same name for unknown voices, so a
    // mismatch here would silently ignore the user's pick.
    expect(PERSONAPLEX_REALTIME_VOICES.some(v => v.value === DEFAULT_PERSONAPLEX_VOICE)).toBe(true);
  });

  it("names every voice prompt as a .pt file", () => {
    for (const voice of PERSONAPLEX_REALTIME_VOICES) {
      expect(voice.value.endsWith(".pt")).toBe(true);
    }
  });
});
