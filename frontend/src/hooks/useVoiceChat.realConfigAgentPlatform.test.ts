import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { ensureEverMemConversationGroupIdMock } = vi.hoisted(() => ({
  ensureEverMemConversationGroupIdMock: vi.fn(),
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    ensureEverMemConversationGroupId: ensureEverMemConversationGroupIdMock,
    fetchVoiceAgentMetricsSummary: vi.fn(),
    fetchVoiceAgentSession: vi.fn(),
    listVoiceAgentSessions: vi.fn(),
  };
});

import useChat, { buildModelChoiceValue, isVoiceRealtimeModel } from "./useChat";
import useVoiceChat from "./useVoiceChat";
import { createFormatErrorMessageStub } from "../test/factories";

// ── Real backend SETTINGS_PROVIDERS (tuple(PROVIDER_KEY_MAP.keys())) ──
const REAL_PROVIDER_OPTIONS = [
  "DashScope", "Google", "AgentPlatform", "Tavus", "Doubao", "Cartesia", "Gradium",
  "DeepSeek", "Xiaomi", "OpenRouter", "SiliconFlow", "Groq", "OpenAI",
  "PersonaPlex", "GLM4Voice", "Ollama", "ElevenLabs", "Deepgram", "AssemblyAI",
  "Soniox", "GPT-SoVITS",
];

// ── Real providerModelCatalog: keys come ONLY from config.json default_models.
// The live config has NO AgentPlatform entry, so catalog["AgentPlatform"] is
// undefined. That is the whole point of this regression test. ──
const REAL_CATALOG: Record<string, {
  defaultModel: string; availableModels: string[]; enabledModels: string[];
}> = {
  DashScope: {
    defaultModel: "",
    availableModels: ["qwen-max", "qwen-plus", "qwen-audio-3.0-realtime-flash"],
    enabledModels: [
      "qwen-audio-3.0-realtime-flash",
      "qwen-audio-3.0-realtime-plus",
      "qwen3.5-omni-plus-realtime-2026-03-15",
    ],
  },
  Google: {
    defaultModel: "",
    availableModels: ["gemini-2.5-flash", "gemini-3.5-live-translate-preview"],
    enabledModels: [
      "gemini-3.7-flash",
      "gemini-3.5-transcribe-live",
      "gemini-3.5-transcribe",
      "gemini-3.5-live-translate-preview",
      "gemini-3.1-flash-live-preview",
    ],
  },
  DeepSeek: { defaultModel: "deepseek-chat", availableModels: ["deepseek-chat"], enabledModels: [] },
  Xiaomi: { defaultModel: "", availableModels: [], enabledModels: [] },
  Tavus: { defaultModel: "", availableModels: [], enabledModels: [] },
  // NOTE: no AgentPlatform key — matches the real config.json.
};

const TARGET_MODEL = "gemini-3.5-live-translate-preview";
const AGENT_PLATFORM_DEFAULT = "gemini-live-2.5-flash-native-audio";

function useAppWiring() {
  const chat = useChat({
    formatErrorMessage: createFormatErrorMessageStub(),
    providerOptions: REAL_PROVIDER_OPTIONS,
    providerModelCatalog: REAL_CATALOG,
    preferredProvider: "DashScope", // settings.settingsProvider default
    language: "zh-CN",
  });
  const voiceChat = useVoiceChat({
    formatErrorMessage: createFormatErrorMessageStub(),
    providerOptions: REAL_PROVIDER_OPTIONS,
    providerModelCatalog: REAL_CATALOG,
    preferredProvider: chat.chatProvider,
    preferredModel: chat.chatModel,
    language: "zh-CN",
  });
  return { chat, voiceChat };
}

describe("AgentPlatform selection with the real (AgentPlatform-less) model catalog", () => {
  beforeEach(() => {
    localStorage.clear();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-test");
  });

  it("keeps gemini-3.5-live-translate-preview after VoiceCallSettingsPopover.commitProviderModel", async () => {
    const { result } = renderHook(() => useAppWiring());

    // Faithful replay of VoiceCallSettingsPopover.commitProviderModel(), which
    // is the exact code path a user hits when picking the model in the UI.
    act(() => {
      const provider = "AgentPlatform";
      const model = TARGET_MODEL;
      result.current.chat.onModelChoiceChange(buildModelChoiceValue(provider, model));
      if (provider !== result.current.voiceChat.voiceChatProvider) {
        result.current.voiceChat.onProviderChange(provider);
        const defaultVoice = result.current.voiceChat.voiceChatVoiceOptionsFor(provider, model)[0]?.value;
        if (defaultVoice) {
          result.current.voiceChat.onVoiceChange(defaultVoice);
        }
      }
      if (isVoiceRealtimeModel(provider, model)) {
        result.current.voiceChat.onModelChange(model);
      }
    });

    // Let every settle/validation effect run to completion.
    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
    });

    expect(
      result.current.voiceChat.voiceChatModel,
      `voiceChatModel must stay on the picked live-translate model, not snap to ${AGENT_PLATFORM_DEFAULT}`
    ).toBe(TARGET_MODEL);
    expect(result.current.voiceChat.voiceChatLiveTranslate).toBe(true);
  });

  it("keeps the selection when picked through the chat model dropdown only", async () => {
    const { result } = renderHook(() => useAppWiring());

    act(() => {
      result.current.chat.onModelChoiceChange(
        buildModelChoiceValue("AgentPlatform", TARGET_MODEL)
      );
    });

    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
    });
    expect(result.current.voiceChat.voiceChatModel).toBe(TARGET_MODEL);
  });
});
