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
import { PROVIDER_API_KEY_FIELD } from "./useSettings";
import { createFormatErrorMessageStub } from "../test/factories";

// providerOptions is ALL_PROVIDER_KEYS in practice: useSettings declares
// settingsProviders as useState<string[]>([]) and never calls its setter, so the
// `settingsProviders.length ? ... : ALL_PROVIDER_KEYS` ternary always takes the
// fallback branch. Derive it the same way so this test cannot drift.
const REAL_PROVIDER_OPTIONS = Object.keys(PROVIDER_API_KEY_FIELD);

// Verbatim from the user's live config.json default_models (2026-09-08). The
// AgentPlatform entry matters: its `default` is a TEXT model (gemini-2.5-flash)
// and `enabled` contains no native-audio model at all.
const REAL_CATALOG: Record<string, {
  defaultModel: string; availableModels: string[]; enabledModels: string[];
}> = {
  AgentPlatform: {
    defaultModel: "gemini-2.5-flash",
    availableModels: [
      "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.5-transcribe-live",
      "gemini-3.5-live-translate-preview", "gemini-3.5-flash",
    ],
    enabledModels: [
      "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.5-transcribe-live",
      "gemini-3.5-live-translate-preview",
    ],
  },
  Google: {
    defaultModel: "",
    availableModels: [
      "gemini-2.5-flash", "gemini-2.5-flash-native-audio-preview-12-2025",
      "gemini-3.1-flash-live-preview", "gemini-3.5-live-translate-preview",
      "gemini-3.5-transcribe", "gemini-3.5-transcribe-live", "gemini-3.7-flash",
    ],
    enabledModels: [
      "gemini-3.7-flash", "gemini-3.5-transcribe-live", "gemini-3.5-transcribe",
      "gemini-3.5-live-translate-preview", "gemini-3.1-flash-live-preview",
    ],
  },
  DashScope: {
    defaultModel: "",
    availableModels: [
      "qwen-audio-3.0-realtime-flash", "qwen-audio-3.0-realtime-plus",
      "qwen3.5-omni-plus-realtime-2026-03-15", "qwen-plus",
    ],
    enabledModels: [
      "qwen-audio-3.0-realtime-flash", "qwen-audio-3.0-realtime-plus",
      "qwen3.5-omni-plus-realtime-2026-03-15",
    ],
  },
};

const TARGET_PROVIDER = "AgentPlatform";
const TARGET_MODEL = "gemini-3.5-live-translate-preview";

function useAppWiring() {
  const chat = useChat({
    formatErrorMessage: createFormatErrorMessageStub(),
    providerOptions: REAL_PROVIDER_OPTIONS,
    providerModelCatalog: REAL_CATALOG,
    preferredProvider: "DashScope",
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

describe("AgentPlatform live-translate selection with the user's real catalog", () => {
  beforeEach(() => {
    localStorage.clear();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-test");
  });

  it("providerOptions really does contain AgentPlatform", () => {
    expect(REAL_PROVIDER_OPTIONS).toContain(TARGET_PROVIDER);
  });

  it("survives VoiceCallSettingsPopover.commitProviderModel", async () => {
    const { result } = renderHook(() => useAppWiring());

    // Verbatim replay of VoiceCallSettingsPopover.commitProviderModel().
    act(() => {
      const provider = TARGET_PROVIDER;
      const model = TARGET_MODEL;
      result.current.chat.onModelChoiceChange(buildModelChoiceValue(provider, model));
      if (provider !== result.current.voiceChat.voiceChatProvider) {
        result.current.voiceChat.onProviderChange(provider);
        const defaultVoice = result.current.voiceChat
          .voiceChatVoiceOptionsFor(provider, model)[0]?.value;
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
      expect(result.current.voiceChat.voiceChatProvider).toBe(TARGET_PROVIDER);
    });

    expect(
      result.current.voiceChat.voiceChatProvider,
      "provider must not fall back to DashScope"
    ).toBe(TARGET_PROVIDER);
    expect(
      result.current.voiceChat.voiceChatModel,
      "model must not fall back to a qwen-audio model"
    ).toBe(TARGET_MODEL);
  });

  it("exposes AgentPlatform live-translate in the realtime choices the popover renders", () => {
    const { result } = renderHook(() => useAppWiring());
    const group = result.current.voiceChat.voiceChatRealtimeChoicesByProvider
      .find((g) => g.provider === TARGET_PROVIDER);
    expect(group, "AgentPlatform must appear in voiceChatRealtimeChoicesByProvider").toBeDefined();
    expect(group?.models).toContain(TARGET_MODEL);
  });

  it("ignores chat-side realtime churn after an explicit voice pick (the live bug)", async () => {
    // Repro of the 22:07 production failure: user picked AgentPlatform +
    // live-translate in the voice picker, then the settings page reloaded and
    // pushed a different settingsProvider through useChat. With THIS catalog
    // DashScope's useChat default is qwen-audio-3.0-realtime-flash (every
    // enabled DashScope entry is realtime, so the text-model filter finds
    // nothing), and the old adoption effect dragged the call selection back
    // to DashScope before connect. Backend log:
    //   realtime_ws_open: provider_raw='DashScope' model='qwen-audio-3.0-realtime-flash'
    const { result, rerender } = renderHook(
      ({ preferred }: { preferred: string }) => {
        const chat = useChat({
          formatErrorMessage: createFormatErrorMessageStub(),
          providerOptions: REAL_PROVIDER_OPTIONS,
          providerModelCatalog: REAL_CATALOG,
          preferredProvider: preferred,
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
      },
      { initialProps: { preferred: "Google" } },
    );

    // 1. Explicit pick in the voice picker.
    act(() => {
      result.current.voiceChat.onProviderChange(TARGET_PROVIDER);
      result.current.voiceChat.onModelChange(TARGET_MODEL);
    });
    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe(TARGET_PROVIDER);
      expect(result.current.voiceChat.voiceChatModel).toBe(TARGET_MODEL);
    });

    // 2. Settings reload flips settingsProvider to DashScope; useChat's
    //    provider switch resets chatModel to DashScope's realtime default and
    //    the preferred* props into useVoiceChat change.
    rerender({ preferred: "DashScope" });
    await waitFor(() => {
      expect(result.current.chat.chatProvider).toBe("DashScope");
      expect(result.current.chat.chatModel).toBe("qwen-audio-3.0-realtime-flash");
    });

    // 3. The call selection must stay exactly what the user picked.
    expect(result.current.voiceChat.voiceChatProvider).toBe(TARGET_PROVIDER);
    expect(result.current.voiceChat.voiceChatModel).toBe(TARGET_MODEL);
  });

  it("still adopts a chat-side realtime pick when the user never used the voice picker", async () => {
    // The adoption path is not dead code: a realtime selection made through
    // the chat model list (no voice-picker interaction) must still propagate,
    // or connecting would use a stale default.
    const { result } = renderHook(() => useAppWiring());
    act(() => {
      result.current.chat.onModelChoiceChange(buildModelChoiceValue(TARGET_PROVIDER, TARGET_MODEL));
    });
    await waitFor(() => {
      expect(result.current.chat.chatModel).toBe(TARGET_MODEL);
    });
    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe(TARGET_PROVIDER);
      expect(result.current.voiceChat.voiceChatModel).toBe(TARGET_MODEL);
    });
  });
});
