import { describe, it, expect } from "vitest";
import {
  CARTESIA_PROVIDER,
  DASHSCOPE_PROVIDER,
  DEFAULT_PERSONAPLEX_VOICE,
  DOUBAO_PROVIDER,
  GLM4VOICE_PROVIDER,
  GOOGLE_PROVIDER,
  GOOGLE_REALTIME_VOICES,
  OPENAI_PROVIDER,
  PERSONAPLEX_PROVIDER,
  PERSONAPLEX_REALTIME_VOICES,
  TAVUS_PROVIDER,
  getProviderBadge,
  getProviderSortOrder,
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
    DASHSCOPE_PROVIDER,
    GOOGLE_PROVIDER,
    TAVUS_PROVIDER,
    DOUBAO_PROVIDER,
    CARTESIA_PROVIDER,
    OPENAI_PROVIDER,
    PERSONAPLEX_PROVIDER,
    GLM4VOICE_PROVIDER,
  ];

  it("honours every realtime provider it is offered", () => {
    // Table-driven on purpose: adding a provider to the UI without adding it
    // here is exactly the omission that caused the misrouting.
    for (const provider of allProviders) {
      expect(resolveRealtimeProvider(provider, allProviders)).toBe(provider);
    }
  });

  it("keeps Tavus provider without falling back", () => {
    expect(resolveRealtimeProvider(TAVUS_PROVIDER, allProviders)).toBe(
      TAVUS_PROVIDER,
    );
  });

  it("keeps the local GLM4Voice provider without falling back", () => {
    expect(resolveRealtimeProvider(GLM4VOICE_PROVIDER, allProviders)).toBe(
      GLM4VOICE_PROVIDER,
    );
  });

  it("keeps PersonaPlex instead of falling back to DashScope", () => {
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
    expect(resolveRealtimeProvider(undefined, allProviders)).toBe(DASHSCOPE_PROVIDER);
  });

  it("ignores a provider that is not a realtime provider at all", () => {
    expect(resolveRealtimeProvider("DeepSeek", allProviders)).toBe(DASHSCOPE_PROVIDER);
  });

  it("assigns proper provider sort orders and capability badges", () => {
    expect(getProviderSortOrder("DashScope")).toBeLessThan(getProviderSortOrder("Google"));
    expect(getProviderSortOrder("Google")).toBeLessThan(getProviderSortOrder("Tavus"));
    expect(getProviderSortOrder("Tavus")).toBeLessThan(getProviderSortOrder("OpenAI"));
    expect(getProviderSortOrder("OpenAI")).toBeLessThan(getProviderSortOrder("PersonaPlex"));

    const t = (zh: string, _en: string) => zh;
    expect(getProviderBadge("DashScope", t)).toEqual({ label: "实时语音", type: "realtime" });
    expect(getProviderBadge("Tavus", t)).toEqual({ label: "视频分身", type: "video" });
    expect(getProviderBadge("PersonaPlex", t)).toEqual({ label: "本地实时", type: "local" });
    expect(getProviderBadge("GLM4Voice", t)).toEqual({ label: "本地实时", type: "local" });
    expect(getProviderBadge("Ollama", t)).toEqual({ label: "本地文本", type: "local" });
    expect(getProviderBadge("DeepSeek", t)).toEqual({ label: "文本", type: "text" });
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

// ---------------------------------------------------------------------------
// Google Gemini Live voices
// ---------------------------------------------------------------------------
describe("Google Gemini Live voices", () => {
  it("includes all 30 prebuilt voices with valid values and labels", () => {
    expect(GOOGLE_REALTIME_VOICES).toHaveLength(30);
    expect(GOOGLE_REALTIME_VOICES.some((v) => v.value === "Puck")).toBe(true);
    expect(GOOGLE_REALTIME_VOICES.some((v) => v.value === "Aoede")).toBe(true);
    expect(GOOGLE_REALTIME_VOICES.some((v) => v.value === "Charon")).toBe(true);
    expect(GOOGLE_REALTIME_VOICES.some((v) => v.value === "Kore")).toBe(true);
    expect(GOOGLE_REALTIME_VOICES.some((v) => v.value === "Fenrir")).toBe(true);
  });

  it("does not include invalid or unofficial voices", () => {
    expect(GOOGLE_REALTIME_VOICES.some((v) => v.value === "Lyra")).toBe(false);
  });
});

