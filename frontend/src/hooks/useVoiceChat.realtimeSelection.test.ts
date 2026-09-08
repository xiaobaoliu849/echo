import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const {
  ensureEverMemConversationGroupIdMock,
  fetchVoiceAgentMetricsSummaryMock,
  fetchVoiceAgentSessionMock,
  listVoiceAgentSessionsMock,
} = vi.hoisted(() => ({
  ensureEverMemConversationGroupIdMock: vi.fn(),
  fetchVoiceAgentMetricsSummaryMock: vi.fn(),
  fetchVoiceAgentSessionMock: vi.fn(),
  listVoiceAgentSessionsMock: vi.fn(),
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    ensureEverMemConversationGroupId: ensureEverMemConversationGroupIdMock,
    fetchVoiceAgentMetricsSummary: fetchVoiceAgentMetricsSummaryMock,
    fetchVoiceAgentSession: fetchVoiceAgentSessionMock,
    listVoiceAgentSessions: listVoiceAgentSessionsMock,
  };
});

import useChat, { buildModelChoiceValue } from "./useChat";
import useVoiceChat from "./useVoiceChat";
import { createFormatErrorMessageStub } from "../test/factories";

const PROVIDER_OPTIONS = ["DashScope", "Google", "AgentPlatform", "OpenAI", "DeepSeek"];

const CATALOG = {
  DashScope: {
    defaultModel: "qwen-plus",
    availableModels: ["qwen-max", "qwen-plus", "qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime"],
    enabledModels: ["qwen-max", "qwen-plus", "qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime"],
  },
  Google: {
    defaultModel: "gemini-2.5-flash",
    availableModels: ["gemini-2.5-flash", "gemini-2.5-flash-native-audio-preview-12-2025", "gemini-3.5-live-translate-preview"],
    enabledModels: ["gemini-2.5-flash", "gemini-2.5-flash-native-audio-preview-12-2025", "gemini-3.5-live-translate-preview"],
  },
  AgentPlatform: {
    defaultModel: "gemini-2.5-flash",
    availableModels: ["gemini-2.5-flash", "gemini-live-2.5-flash-native-audio", "gemini-3.5-live-translate-preview"],
    enabledModels: ["gemini-2.5-flash", "gemini-live-2.5-flash-native-audio", "gemini-3.5-live-translate-preview"],
  },
  OpenAI: { defaultModel: "gpt-4o", availableModels: ["gpt-4o"], enabledModels: ["gpt-4o"] },
  DeepSeek: { defaultModel: "deepseek-chat", availableModels: ["deepseek-chat"], enabledModels: ["deepseek-chat"] },
};

function useAppWiring() {
  const chat = useChat({
    formatErrorMessage: createFormatErrorMessageStub(),
    providerOptions: PROVIDER_OPTIONS,
    providerModelCatalog: CATALOG,
    preferredProvider: "DashScope",
    language: "zh-CN",
  });
  const voiceChat = useVoiceChat({
    formatErrorMessage: createFormatErrorMessageStub(),
    providerOptions: PROVIDER_OPTIONS,
    providerModelCatalog: CATALOG,
    preferredProvider: chat.chatProvider,
    preferredModel: chat.chatModel,
    language: "zh-CN",
  });
  return { chat, voiceChat };
}

describe("AgentPlatform live-translate selection must not fall back to DashScope", () => {
  it("keeps AgentPlatform when the voice popover commits the live-translate model", async () => {
    const { result } = renderHook(() => useAppWiring());

    // Simulate VoiceCallSettingsPopover.commitProviderModel("AgentPlatform", "gemini-3.5-live-translate-preview")
    act(() => {
      result.current.chat.onModelChoiceChange(
        buildModelChoiceValue("AgentPlatform", "gemini-3.5-live-translate-preview")
      );
      result.current.voiceChat.onProviderChange("AgentPlatform");
      result.current.voiceChat.onModelChange("gemini-3.5-live-translate-preview");
    });

    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
      expect(result.current.voiceChat.voiceChatModel).toBe("gemini-3.5-live-translate-preview");
    });

    // State must remain stable after all sync effects settle
    await waitFor(() => {
      expect(result.current.chat.chatProvider).toBe("AgentPlatform");
      expect(result.current.chat.chatModel).toBe("gemini-3.5-live-translate-preview");
      expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
      expect(result.current.voiceChat.voiceChatModel).toBe("gemini-3.5-live-translate-preview");
    });
  });

  it("keeps AgentPlatform when the model is picked via the chat model select only", async () => {
    const { result } = renderHook(() => useAppWiring());

    act(() => {
      result.current.chat.onModelChoiceChange(
        buildModelChoiceValue("AgentPlatform", "gemini-3.5-live-translate-preview")
      );
    });

    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
      expect(result.current.voiceChat.voiceChatModel).toBe("gemini-3.5-live-translate-preview");
    });
  });

  it("does not clobber the voice selection when chat later switches to a text model", async () => {
    const { result } = renderHook(() => useAppWiring());

    // 1. Pick AgentPlatform live-translate for the call (popover keeps chat in sync)
    act(() => {
      result.current.chat.onModelChoiceChange(
        buildModelChoiceValue("AgentPlatform", "gemini-3.5-live-translate-preview")
      );
      result.current.voiceChat.onProviderChange("AgentPlatform");
      result.current.voiceChat.onModelChange("gemini-3.5-live-translate-preview");
    });
    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
    });

    // 2. User then switches the CHAT model to a DashScope text model to type
    act(() => {
      result.current.chat.onModelChoiceChange(buildModelChoiceValue("DashScope", "qwen-plus"));
    });

    // The voice-call selection should survive a chat-side text model change
    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
      expect(result.current.voiceChat.voiceChatModel).toBe("gemini-3.5-live-translate-preview");
    });
  });
});
