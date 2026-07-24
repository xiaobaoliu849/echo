import { describe, it, expect } from "vitest";
import {
  isLiveTranslateModel,
  isRealtimeVoiceModel,
  formatVoiceChatSecondaryLabel,
  DASHSCOPE_PROVIDER,
  GOOGLE_PROVIDER,
} from "./useVoiceChatHelpers";

describe("isLiveTranslateModel", () => {
  it("recognizes Google live-translate models", () => {
    expect(isLiveTranslateModel(GOOGLE_PROVIDER, "gemini-3.5-live-translate-preview")).toBe(true);
  });

  it("recognizes DashScope livetranslate models (3.5 only; legacy qwen3 removed)", () => {
    expect(isLiveTranslateModel(DASHSCOPE_PROVIDER, "qwen3.5-livetranslate-flash-realtime")).toBe(true);
    expect(isLiveTranslateModel(DASHSCOPE_PROVIDER, "qwen3-livetranslate-flash-realtime")).toBe(false);
  });

  it("rejects non-translate realtime models", () => {
    expect(isLiveTranslateModel(DASHSCOPE_PROVIDER, "qwen3.5-omni-plus-realtime")).toBe(false);
    expect(isLiveTranslateModel(GOOGLE_PROVIDER, "gemini-2.5-flash-native-audio-preview-12-2025")).toBe(false);
    expect(isLiveTranslateModel(DASHSCOPE_PROVIDER, "")).toBe(false);
  });
});

describe("isRealtimeVoiceModel (DashScope livetranslate)", () => {
  it("treats livetranslate as a realtime voice model", () => {
    expect(isRealtimeVoiceModel(DASHSCOPE_PROVIDER, "qwen3.5-livetranslate-flash-realtime")).toBe(true);
    expect(isRealtimeVoiceModel(DASHSCOPE_PROVIDER, "qwen3-livetranslate-flash-realtime")).toBe(false);
    expect(
      isRealtimeVoiceModel(DASHSCOPE_PROVIDER, "qwen3.5-livetranslate-flash-realtime-2026-05-19")
    ).toBe(true);
  });

  it("still recognizes omni and qwen-audio realtime models", () => {
    expect(isRealtimeVoiceModel(DASHSCOPE_PROVIDER, "qwen3.5-omni-plus-realtime")).toBe(true);
    expect(isRealtimeVoiceModel(DASHSCOPE_PROVIDER, "qwen-audio-3.0-realtime-plus")).toBe(true);
  });

  it("rejects non-realtime DashScope models", () => {
    expect(isRealtimeVoiceModel(DASHSCOPE_PROVIDER, "qwen-mt-plus")).toBe(false);
    expect(isRealtimeVoiceModel(DASHSCOPE_PROVIDER, "qwen-plus")).toBe(false);
  });
});

describe("formatVoiceChatSecondaryLabel", () => {
  const t = (zh: string, _en: string) => zh;
  const base = {
    liveTranslate: false,
    voiceCloneEnabled: false,
    translationMode: "unidirectional" as const,
    sourceLanguageCode: "zh-Hans",
    targetLanguageCode: "en",
    voiceLabel: "Tina · 甜甜 · 女声",
    t,
  };

  it("shows the voice label for normal realtime models", () => {
    expect(formatVoiceChatSecondaryLabel(base)).toBe("Tina · 甜甜 · 女声");
  });

  it("shows Voice Clone instead of the default voice when clone is enabled", () => {
    expect(formatVoiceChatSecondaryLabel({ ...base, voiceCloneEnabled: true })).toBe("声音复刻 (本人音色)");
  });

  it("shows the language pair instead of a stale voice label for live-translate models", () => {
    expect(formatVoiceChatSecondaryLabel({ ...base, liveTranslate: true })).toBe("单向翻译 (中文 → English)");
  });

  it("prioritizes Voice Clone over the language pair for live-translate models", () => {
    expect(
      formatVoiceChatSecondaryLabel({ ...base, liveTranslate: true, voiceCloneEnabled: true })
    ).toBe("声音复刻 (本人)");
  });
});

describe("formatVoiceChatSecondaryLabel (DashScope unidirectional guard)", () => {
  const t = (zh: string, _en: string) => zh;

  it("always renders 单向翻译 for DashScope LiveTranslate even if mode says bidirectional", () => {
    // qwen3.5-livetranslate only supports a single target_language (see 时时翻译.txt);
    // the label must never claim 双向互翻 for it.
    expect(
      formatVoiceChatSecondaryLabel({
        liveTranslate: true,
        voiceCloneEnabled: false,
        translationMode: "bidirectional",
        sourceLanguageCode: "zh-Hans",
        targetLanguageCode: "en",
        voiceLabel: "Tina",
        provider: DASHSCOPE_PROVIDER,
        model: "qwen3.5-livetranslate-flash-realtime",
        t,
      })
    ).toBe("单向翻译 (中文 → English)");
  });

  it("keeps 双向互翻 for Google live-translate which supports it", () => {
    expect(
      formatVoiceChatSecondaryLabel({
        liveTranslate: true,
        voiceCloneEnabled: false,
        translationMode: "bidirectional",
        sourceLanguageCode: "zh-Hans",
        targetLanguageCode: "en",
        voiceLabel: "Puck",
        provider: GOOGLE_PROVIDER,
        model: "gemini-3.5-live-translate-preview",
        t,
      })
    ).toBe("双向互翻 (中文 ⇄ English)");
  });
});
