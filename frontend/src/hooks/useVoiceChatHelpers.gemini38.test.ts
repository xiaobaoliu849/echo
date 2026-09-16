import { describe, it, expect } from "vitest";
import {
  isRealtimeVoiceModel,
  resolveRealtimeModelOptions,
  GOOGLE_PROVIDER,
  AGENT_PLATFORM_PROVIDER,
  GOOGLE_3_8_LIVE_MODEL,
  GOOGLE_3_8_LIVE_THINKING_MODEL,
} from "./useVoiceChatHelpers";

describe("Gemini 3.8 Live models", () => {
  it("recognizes gemini-3.8-live and extended thinking as realtime models", () => {
    expect(GOOGLE_3_8_LIVE_MODEL).toBe("gemini-3.8-live");
    expect(GOOGLE_3_8_LIVE_THINKING_MODEL).toBe("gemini-3.8-live-extended-thinking");

    expect(isRealtimeVoiceModel(GOOGLE_PROVIDER, "gemini-3.8-live")).toBe(true);
    expect(isRealtimeVoiceModel(GOOGLE_PROVIDER, "gemini-3.8-live-extended-thinking")).toBe(true);
    expect(isRealtimeVoiceModel(AGENT_PLATFORM_PROVIDER, "gemini-3.8-live")).toBe(true);
    expect(isRealtimeVoiceModel(AGENT_PLATFORM_PROVIDER, "gemini-3.8-live-extended-thinking")).toBe(true);
  });

  it("includes gemini-3.8-live in resolveRealtimeModelOptions builtIns", () => {
    const models = resolveRealtimeModelOptions(GOOGLE_PROVIDER, {
      [GOOGLE_PROVIDER]: {
        defaultModel: "gemini-3.8-live",
        availableModels: [],
        enabledModels: [],
      },
    });

    expect(models).toContain("gemini-3.8-live");
    expect(models).toContain("gemini-3.8-live-extended-thinking");
  });

  it("includes gemini-3.8-live for AgentPlatform as well", () => {
    const models = resolveRealtimeModelOptions(AGENT_PLATFORM_PROVIDER, {
      [AGENT_PLATFORM_PROVIDER]: {
        defaultModel: "gemini-3.8-live",
        availableModels: [],
        enabledModels: [],
      },
    });

    expect(models).toContain("gemini-3.8-live");
    expect(models).toContain("gemini-3.8-live-extended-thinking");
  });
});
