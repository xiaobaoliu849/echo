import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import VoiceCallSettingsPopover from "./VoiceCallSettingsPopover";
import { createVoiceChatController } from "../test/factories";

const t = (zh: string, _en: string) => zh;

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, "innerHeight", { writable: true, configurable: true, value: 768 });
});

function renderPopover(overrides: Parameters<typeof createVoiceChatController>[0] = {}) {
  const voiceChat = createVoiceChatController({
    voiceChatProvider: "DashScope",
    voiceChatModel: "qwen3.5-omni-plus-realtime",
    voiceChatModelOptions: ["qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime", "qwen-audio-3.0-realtime-plus"],
    voiceChatRealtimeChoicesByProvider: [
      { provider: "DashScope", models: ["qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime", "qwen-audio-3.0-realtime-plus"] },
      { provider: "Google", models: ["gemini-3.1-flash-live-preview"] },
      { provider: "OpenAI", models: ["gpt-realtime-2"] },
    ],
    voiceChatVoice: "Tina",
    voiceChatVoiceLabel: "Tina · 甜甜 · 女声",
    voiceChatVoiceOptions: [
      { value: "Tina", label: "Tina · 甜甜 · 女声", description: "像温热的奶茶，甜甜的暖暖的" },
      { value: "Ethan", label: "Ethan · 晨煦 · 男声", description: "标准普通话，阳光温暖有活力" },
    ],
    ...overrides,
  });
  render(<VoiceCallSettingsPopover voiceChat={voiceChat} t={t} />);
  return voiceChat;
}

function openPanel() {
  fireEvent.click(screen.getByTitle("通话设置"));
  return screen.getByRole("dialog", { name: "通话设置" });
}

describe("VoiceCallSettingsPopover", () => {
  it("shows the current model and voice in the summary button", () => {
    renderPopover();
    const summary = screen.getByTitle("通话设置");
    expect(summary).toHaveTextContent("qwen3.5-omni-plus-realtime · Tina · 甜甜 · 女声");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows Voice Clone in the summary button when Voice Clone is enabled", () => {
    renderPopover({
      voiceChatProvider: "DashScope",
      voiceChatModel: "qwen3.5-livetranslate-flash-realtime",
      voiceChatLiveTranslate: true,
      voiceChatEnableVoiceClone: true,
    });
    const summary = screen.getByTitle("通话设置");
    expect(summary).toHaveTextContent("qwen3.5-livetranslate-flash-realtime · 声音复刻 (本人)");
  });

  it("opens only Level 1 on panel toggle and flies out Level 2/3 on hover", () => {
    renderPopover();
    openPanel();
    // Only Level 1 provider list is open initially
    expect(screen.getByText("DashScope")).toBeInTheDocument();

    // Hover Level 1 Provider to open Level 2 (Specific Models)
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    expect(screen.getByText("全模态实时")).toBeInTheDocument();
    expect(screen.getByText("Qwen-Audio 原生实时")).toBeInTheDocument();

    // Hover a realtime model in Level 2 to auto-open the Voice flyout in Level 3
    fireEvent.mouseEnter(screen.getByText("qwen3.5-omni-plus-realtime"));
    expect(screen.getByText("像温热的奶茶，甜甜的暖暖的")).toBeInTheDocument();
    const selectedVoice = screen.getByText("Tina · 甜甜 · 女声").closest("button");
    expect(selectedVoice).toHaveClass("selected");
  });

  it("calls onVoiceChange and closes the panel when a voice is picked in Voice flyout", () => {
    const voiceChat = renderPopover();
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    fireEvent.mouseEnter(screen.getByText("qwen3.5-omni-plus-realtime"));
    fireEvent.click(screen.getByText("Ethan · 晨煦 · 男声"));
    expect(voiceChat.onVoiceChange).toHaveBeenCalledWith("Ethan");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("switches the model directly in Level 2", () => {
    const voiceChat = renderPopover();
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    fireEvent.click(screen.getByText("qwen-audio-3.0-realtime-plus"));
    expect(voiceChat.onModelChange).toHaveBeenCalledWith("qwen-audio-3.0-realtime-plus");
    expect(voiceChat.onProviderChange).not.toHaveBeenCalled();
  });

  it("switches provider in Level 1 and selects model in Level 2", () => {
    const voiceChat = renderPopover();
    openPanel();
    expect(screen.queryByText("gemini-3.1-flash-live-preview")).not.toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByText("Google"));
    fireEvent.click(screen.getByText("gemini-3.1-flash-live-preview"));
    expect(voiceChat.onProviderChange).toHaveBeenCalledWith("Google");
    expect(voiceChat.onModelChange).toHaveBeenCalledWith("gemini-3.1-flash-live-preview");
  });

  it("always shows a Done button in the footer that closes the panel", () => {
    renderPopover();
    openPanel();
    fireEvent.click(screen.getByText("完成"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens model management from Level 1 footer and closes panel", () => {
    const voiceChat = createVoiceChatController();
    const onOpenSettings = vi.fn();
    render(<VoiceCallSettingsPopover voiceChat={voiceChat} t={t} onOpenSettings={onOpenSettings} />);
    openPanel();
    fireEvent.click(screen.getByText("管理模型"));
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("merges realtime choices (including qwen-audio) into Level 2 even when chat prop is present", () => {
    const voiceChat = createVoiceChatController({
      voiceChatRealtimeChoicesByProvider: [
        { provider: "DashScope", models: ["qwen3.5-omni-plus-realtime", "qwen-audio-3.0-realtime-plus"] },
      ],
    });
    const chat = {
      chatProvider: "DashScope",
      chatModel: "qwen-max",
      chatProviderOptions: ["DashScope"],
      chatModelChoices: [
        { provider: "DashScope", model: "qwen-max", label: "DashScope / qwen-max", value: "DashScope\u001fqwen-max" },
      ],
      onProviderChange: vi.fn(),
      onModelChoiceChange: vi.fn(),
    } as unknown as Parameters<typeof VoiceCallSettingsPopover>[0]["chat"];

    render(<VoiceCallSettingsPopover voiceChat={voiceChat} chat={chat} t={t} />);
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    expect(screen.getByText("qwen-max")).toBeInTheDocument();
    expect(screen.getByText("qwen-audio-3.0-realtime-plus")).toBeInTheDocument();
  });

  it("hides the translation category for providers without live-translate support", () => {
    renderPopover();
    openPanel();
    fireEvent.mouseEnter(screen.getByText("OpenAI"));
    expect(screen.queryByText("🌐 同传与复刻")).not.toBeInTheDocument();
  });

  it("keeps panel open and auto-navigates to translation category when selecting a live-translate model", () => {
    const voiceChat = renderPopover();
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    fireEvent.click(screen.getByText("qwen3.5-livetranslate-flash-realtime"));
    expect(voiceChat.onModelChange).toHaveBeenCalledWith("qwen3.5-livetranslate-flash-realtime");
    // Popover remains open
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // Auto-navigates to Level 3 translation settings card
    expect(screen.getByText("常用目标语")).toBeInTheDocument();
  });

  it("hides the translation category for Google models (including Google live-translate)", () => {
    renderPopover({
      voiceChatProvider: "Google",
      voiceChatModel: "gemini-3.5-live-translate-preview",
      voiceChatLiveTranslate: true,
      voiceChatTranslationMode: "bidirectional",
      voiceChatSourceLanguageCode: "zh-Hans",
      voiceChatTargetLanguageCode: "en",
      voiceChatTargetLanguageOptions: [
        { value: "zh-Hans", label: "中文 / Chinese (Simplified) (zh-Hans)" },
        { value: "en", label: "英语 / English (en)" },
        { value: "ja", label: "日语 / Japanese (ja)" },
      ],
      voiceChatEchoTargetLanguage: true,
    });
    openPanel();
    fireEvent.mouseEnter(screen.getByText("Google"));
    // 同传与复刻 is a DashScope LiveTranslate-only feature; Google models never show it.
    expect(screen.queryByText("🌐 同传与复刻")).not.toBeInTheDocument();
  });

  it("shows unidirectional-only translation UI for Google live-translate", () => {
    const voiceChat = renderPopover({
      voiceChatProvider: "Google",
      voiceChatModel: "gemini-3.5-live-translate-preview",
      voiceChatLiveTranslate: true,
      voiceChatTranslationMode: "unidirectional",
      voiceChatTargetLanguageCode: "en",
      voiceChatTargetLanguageOptions: [
        { value: "zh-Hans", label: "中文 / Chinese (Simplified) (zh-Hans)" },
        { value: "en", label: "英语 / English (en)" },
        { value: "ja", label: "日语 / Japanese (ja)" },
      ],
      voiceChatRealtimeChoicesByProvider: [
        { provider: "Google", models: ["gemini-3.1-flash-live-preview", "gemini-3.5-live-translate-preview"] },
      ],
    });
    openPanel();
    fireEvent.mouseEnter(screen.getByText("Google"));
    fireEvent.mouseEnter(screen.getByText("gemini-3.5-live-translate-preview"));

    expect(screen.getByText("单向同传 (翻译为目标语言)")).toBeInTheDocument();
    expect(screen.getByText("自动识别输入语言（70+ 种）· 输出自动复刻说话人音色")).toBeInTheDocument();
    expect(screen.queryByText("双向互翻 ⇄")).not.toBeInTheDocument();
    expect(screen.queryByText("源语言")).not.toBeInTheDocument();
    expect(screen.getByText("🎯 目标同传语言")).toBeInTheDocument();

    fireEvent.click(screen.getByText("日语"));
    expect(voiceChat.onTargetLanguageCodeChange).toHaveBeenCalledWith("ja");
  });

  it("hides the translation category for DashScope voice models (omni / audio)", () => {
    renderPopover(); // DashScope qwen3.5-omni-plus-realtime by default
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    expect(screen.queryByText("🌐 同传与复刻")).not.toBeInTheDocument();
  });

  it("shows target language only UI for DashScope live-translate models in Translate category", () => {
    const voiceChat = renderPopover({
      voiceChatProvider: "DashScope",
      voiceChatModel: "qwen3.5-livetranslate-flash-realtime",
      voiceChatLiveTranslate: true,
      voiceChatTranslationMode: "unidirectional",
      voiceChatSourceLanguageCode: "zh-Hans",
      voiceChatTargetLanguageCode: "en",
    });
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    fireEvent.mouseEnter(screen.getByText("qwen3.5-livetranslate-flash-realtime"));
    expect(screen.getByText("单向同传 (翻译为目标语言)")).toBeInTheDocument();
    expect(screen.queryByText("双向互翻 ⇄")).not.toBeInTheDocument();
    expect(screen.getByText("🎯 目标同传语言")).toBeInTheDocument();
    expect(screen.queryByText("源语言")).not.toBeInTheDocument();

    // Click target language pill
    fireEvent.click(screen.getByText("日语"));
    expect(voiceChat.onTargetLanguageCodeChange).toHaveBeenCalledWith("ja");
  });

  it("shows target language only UI when hovering qwen3.5-livetranslate-flash-realtime in Level 2 even if active model was omni", () => {
    const chat = {
      chatProvider: "DashScope",
      chatModel: "qwen3.5-omni-plus-realtime",
      chatProviderOptions: ["DashScope"],
      chatModelChoices: [
        { provider: "DashScope", model: "qwen3.5-omni-plus-realtime", label: "DashScope / qwen3.5-omni-plus-realtime", value: "DashScope\u001fqwen3.5-omni-plus-realtime" },
        { provider: "DashScope", model: "qwen3.5-livetranslate-flash-realtime", label: "DashScope / qwen3.5-livetranslate-flash-realtime", value: "DashScope\u001fqwen3.5-livetranslate-flash-realtime" },
      ],
      onProviderChange: vi.fn(),
      onModelChoiceChange: vi.fn(),
    } as unknown as Parameters<typeof VoiceCallSettingsPopover>[0]["chat"];

    const voiceChat = createVoiceChatController({
      voiceChatProvider: "DashScope",
      voiceChatModel: "qwen3.5-omni-plus-realtime",
      voiceChatLiveTranslate: false,
      voiceChatModelOptions: ["qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime"],
      voiceChatRealtimeChoicesByProvider: [
        { provider: "DashScope", models: ["qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime"] },
      ],
    });

    render(<VoiceCallSettingsPopover voiceChat={voiceChat} chat={chat} t={t} />);
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    fireEvent.mouseEnter(screen.getByText("qwen3.5-livetranslate-flash-realtime"));

    expect(screen.getByText("单向同传 (翻译为目标语言)")).toBeInTheDocument();
    expect(screen.queryByText("双向互翻 ⇄")).not.toBeInTheDocument();
    expect(screen.getByText("🎯 目标同传语言")).toBeInTheDocument();
  });

  it("toggles the echo switch in unidirectional mode", () => {
    const voiceChat = renderPopover({
      voiceChatLiveTranslate: true,
      voiceChatTranslationMode: "unidirectional",
      voiceChatEchoTargetLanguage: true,
    });
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    fireEvent.mouseEnter(screen.getByText("qwen3.5-livetranslate-flash-realtime"));
    fireEvent.click(screen.getByLabelText("同语回放"));
    expect(voiceChat.onEchoTargetLanguageChange).toHaveBeenCalledWith(false);
  });

  it("toggles Voice Clone switch and mode frequency pills for DashScope LiveTranslate in Translate flyout", () => {
    const voiceChat = renderPopover({
      voiceChatProvider: "DashScope",
      voiceChatModel: "qwen3.5-livetranslate-flash-realtime",
      voiceChatLiveTranslate: true,
      voiceChatEnableVoiceClone: true,
      voiceChatVoiceCloneFrequency: "once",
    });
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    fireEvent.mouseEnter(screen.getByText("qwen3.5-livetranslate-flash-realtime"));
    expect(screen.getByText("声音复刻 (用本人音色朗读)")).toBeInTheDocument();
    expect(screen.getByText("单人实时复刻")).toBeInTheDocument();
    expect(screen.getByText("动态实时复刻")).toBeInTheDocument();

    // Frequency pill click
    fireEvent.click(screen.getByText("动态实时复刻"));
    expect(voiceChat.onVoiceCloneFrequencyChange).toHaveBeenCalledWith("always");

    // Toggle off
    fireEvent.click(screen.getByLabelText("声音复刻 (用本人音色朗读)"));
    expect(voiceChat.onVoiceCloneToggle).toHaveBeenCalledWith(false);
  });

  it("closes on Escape and on outside click", () => {
    renderPopover();
    openPanel();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    openPanel();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("caps the panel height to the space above the button", () => {
    Object.defineProperty(window, "innerHeight", { writable: true, configurable: true, value: 500 });
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
      top: 380, bottom: 414, left: 0, right: 320, width: 320, height: 34, x: 0, y: 380, toJSON: () => ({}),
    } as DOMRect);
    renderPopover();
    const dialog = openPanel();
    expect(dialog.className).not.toContain("below");
    expect(dialog.style.maxHeight).toBe("364px");
  });

  it("opens downward when there is more space below the button", () => {
    Object.defineProperty(window, "innerHeight", { writable: true, configurable: true, value: 500 });
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
      top: 60, bottom: 94, left: 0, right: 320, width: 320, height: 34, x: 0, y: 60, toJSON: () => ({}),
    } as DOMRect);
    renderPopover();
    const dialog = openPanel();
    expect(dialog.className).toContain("below");
    expect(dialog.style.maxHeight).toBe("390px");
  });

  it("does not open when disabled", () => {
    const voiceChat = createVoiceChatController();
    render(<VoiceCallSettingsPopover voiceChat={voiceChat} t={t} disabled />);
    const summary = screen.getByTitle("通话设置");
    expect(summary).toBeDisabled();
    fireEvent.click(summary);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
