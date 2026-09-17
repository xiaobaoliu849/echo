import { describe, it, expect } from "vitest";
import {
  isRealtimeVoiceModel,
  resolveRealtimeModelOptions,
  formatRealtimeVoiceOptions,
  resolveRealtimeFallbackModel,
  VERCEL_PROVIDER,
  VERCEL_GEMINI_3_8_LIVE,
  VERCEL_GEMINI_3_8_LIVE_THINKING,
  DEFAULT_VERCEL_MODEL,
} from "./useVoiceChatHelpers";
import { formatModelHint } from "./useChat";

describe("Vercel AI Gateway Gemini 3.8 Live models", () => {
  it("recognizes Vercel Gemini 3.8 live and extended thinking as realtime models", () => {
    expect(VERCEL_GEMINI_3_8_LIVE).toBe("google/gemini-3.8-live");
    expect(VERCEL_GEMINI_3_8_LIVE_THINKING).toBe("google/gemini-3.8-live-extended-thinking");

    expect(isRealtimeVoiceModel(VERCEL_PROVIDER, "google/gemini-3.8-live")).toBe(true);
    expect(isRealtimeVoiceModel(VERCEL_PROVIDER, "google/gemini-3.8-live-extended-thinking")).toBe(true);
    expect(isRealtimeVoiceModel(VERCEL_PROVIDER, "openai/gpt-realtime-2")).toBe(true);
    expect(isRealtimeVoiceModel(VERCEL_PROVIDER, "spacexai/grok-voice-think-fast-1.0")).toBe(true);

    expect(isRealtimeVoiceModel(VERCEL_PROVIDER, "openai/gpt-4o")).toBe(false);
    expect(isRealtimeVoiceModel(VERCEL_PROVIDER, "")).toBe(false);
  });

  it("includes Gemini 3.8 live models in resolveRealtimeModelOptions builtIns for Vercel", () => {
    const models = resolveRealtimeModelOptions(VERCEL_PROVIDER, {
      [VERCEL_PROVIDER]: {
        defaultModel: DEFAULT_VERCEL_MODEL,
        availableModels: [],
        enabledModels: [],
      },
    });

    expect(models).toContain("google/gemini-3.8-live");
    expect(models).toContain("google/gemini-3.8-live-extended-thinking");
    expect(models).toContain(DEFAULT_VERCEL_MODEL);
  });

  it("returns Google voices for Google models and OpenAI voices for OpenAI models under Vercel", () => {
    // For Gemini models under Vercel
    const googleOptions = formatRealtimeVoiceOptions(VERCEL_PROVIDER, "zh-CN", "google/gemini-3.8-live");
    const googleVoiceValues = googleOptions.map((o) => o.value);
    expect(googleVoiceValues).toContain("Puck");
    expect(googleVoiceValues).toContain("Aoede");
    expect(googleVoiceValues).toContain("Zephyr");
    expect(googleVoiceValues).not.toContain("alloy");

    // For OpenAI models under Vercel
    const openaiOptions = formatRealtimeVoiceOptions(VERCEL_PROVIDER, "zh-CN", "openai/gpt-realtime-2");
    const openaiVoiceValues = openaiOptions.map((o) => o.value);
    expect(openaiVoiceValues).toContain("alloy");
    expect(openaiVoiceValues).toContain("echo");
    expect(openaiVoiceValues).not.toContain("Puck");
  });

  it("resolves default fallback model for Vercel", () => {
    expect(resolveRealtimeFallbackModel(VERCEL_PROVIDER)).toBe(DEFAULT_VERCEL_MODEL);
  });

  it("formats appropriate model hints in bilingual UI", () => {
    const t = (zh: string, _en: string) => zh;
    expect(formatModelHint(VERCEL_PROVIDER, "google/gemini-3.8-live", t)).toBe("Gemini 3.8 极速实时");
    expect(formatModelHint(VERCEL_PROVIDER, "google/gemini-3.8-live-extended-thinking", t)).toBe("Gemini 3.8 深度思考实时");
    expect(formatModelHint(VERCEL_PROVIDER, "openai/gpt-realtime-2", t)).toBe("Vercel Gateway 实时语音");
  });
});
