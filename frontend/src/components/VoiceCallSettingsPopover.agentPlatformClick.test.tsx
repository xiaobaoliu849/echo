import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

import VoiceCallSettingsPopover from "./VoiceCallSettingsPopover";
import useChat from "../hooks/useChat";
import useVoiceChat from "../hooks/useVoiceChat";
import { PROVIDER_API_KEY_FIELD } from "../hooks/useSettings";
import { createFormatErrorMessageStub } from "../test/factories";

const REAL_PROVIDER_OPTIONS = Object.keys(PROVIDER_API_KEY_FIELD);

// Verbatim from the user's live config.json default_models (2026-09-08).
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

const TARGET_MODEL = "gemini-3.5-live-translate-preview";
const t = (zh: string) => zh;

/** Renders the real popover over the real hooks and mirrors committed state
 *  into the DOM so assertions read exactly what the app would send. */
function Harness() {
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
  return (
    <>
      <div data-testid="committed">
        {`${voiceChat.voiceChatProvider}|${voiceChat.voiceChatModel}`}
      </div>
      <VoiceCallSettingsPopover voiceChat={voiceChat} chat={chat} t={t} />
    </>
  );
}

describe("VoiceCallSettingsPopover — picking AgentPlatform live-translate by clicking", () => {
  beforeEach(() => {
    localStorage.clear();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-test");
  });

  it("commits AgentPlatform + live-translate, not DashScope/qwen-audio", async () => {
    render(<Harness />);

    // Open the cascade.
    fireEvent.click(document.querySelector(".vsVoiceSettingsSummary") as HTMLElement);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());

    // Level 1: the AgentPlatform provider row must exist and be clickable.
    const providerRows = Array.from(
      document.querySelectorAll(".vsVoiceSettingsProviderRow")
    ) as HTMLElement[];
    const labels = providerRows.map((r) => r.textContent || "");
    const agentRow = providerRows.find((r) => /Agent\s*Platform|谷歌云|Vertex/i.test(r.textContent || ""));
    expect(
      agentRow,
      `AgentPlatform row missing from Level 1. Rows: ${JSON.stringify(labels)}`
    ).toBeTruthy();
    fireEvent.click(agentRow!);

    // Level 2: the live-translate model row for that provider.
    await waitFor(() => {
      const rows = Array.from(document.querySelectorAll(".vsVoiceSettingsRowLabel"));
      expect(rows.some((r) => r.textContent?.trim() === TARGET_MODEL)).toBe(true);
    });
    const modelLabel = Array.from(
      document.querySelectorAll(".vsVoiceSettingsRowLabel")
    ).find((r) => r.textContent?.trim() === TARGET_MODEL)!;
    fireEvent.click(modelLabel.closest("button")!);

    // Committed state is what onToggleRecording() puts on the WebSocket URL.
    await waitFor(() => {
      expect(screen.getByTestId("committed").textContent).toBe(
        `AgentPlatform|${TARGET_MODEL}`
      );
    });
  });
});
