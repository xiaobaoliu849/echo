import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

class FakeTrack {
  stop = vi.fn();
}

class FakeMediaStream {
  private readonly track = new FakeTrack();
  getTracks() {
    return [this.track];
  }
}

class FakeAudioNode {
  disconnect = vi.fn();
  connect = vi.fn();
}

class FakeProcessorNode extends FakeAudioNode {
  onaudioprocess: ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null = null;
}

class FakeGainNode extends FakeAudioNode {
  gain = {
    value: 1,
    cancelScheduledValues: vi.fn(),
    setTargetAtTime: vi.fn((value: number) => {
      this.gain.value = value;
    }),
  };
}

class FakeAnalyser extends FakeAudioNode {
  fftSize = 64;
  frequencyBinCount = 32;
  getByteFrequencyData = vi.fn();
}

class FakeBufferSource extends FakeAudioNode {
  buffer = null;
  start = vi.fn();
  stop = vi.fn();
  addEventListener = vi.fn();
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  static processors: FakeProcessorNode[] = [];
  static gains: FakeGainNode[] = [];
  static bufferSources: FakeBufferSource[] = [];
  currentTime = 0;
  state = "running";
  destination = new FakeAudioNode();
  createGain = vi.fn(() => {
    const g = new FakeGainNode();
    FakeAudioContext.gains.push(g);
    return g;
  });
  createAnalyser = vi.fn(() => new FakeAnalyser());
  createBuffer = vi.fn(() => ({ getChannelData: () => new Float32Array(0) }));
  createBufferSource = vi.fn(() => {
    const s = new FakeBufferSource();
    FakeAudioContext.bufferSources.push(s);
    return s;
  });
  createMediaStreamSource = vi.fn(() => new FakeAudioNode());
  createScriptProcessor = vi.fn(() => {
    const p = new FakeProcessorNode();
    FakeAudioContext.processors.push(p);
    return p;
  });
  resume = vi.fn(async () => {});
  close = vi.fn(async () => {});
  constructor() {
    FakeAudioContext.instances.push(this);
  }
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  url: string;
  binaryType = "arraybuffer";
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
    setTimeout(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen?.();
    }, 0);
  }
  send = vi.fn();
  close = vi.fn(() => {
    this.readyState = FakeWebSocket.CLOSED;
  });
}

const PROVIDER_OPTIONS = ["DashScope", "Google", "AgentPlatform", "OpenAI", "DeepSeek"];

const CATALOG = {
  DashScope: {
    defaultModel: "qwen-plus",
    availableModels: ["qwen-max", "qwen-plus", "qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime", "qwen-audio-3.0-realtime-plus"],
    enabledModels: ["qwen-max", "qwen-plus", "qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime", "qwen-audio-3.0-realtime-plus"],
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

describe("AgentPlatform live-translate realtime call wiring", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    FakeAudioContext.instances = [];
    FakeAudioContext.processors = [];
    FakeAudioContext.gains = [];
    FakeAudioContext.bufferSources = [];
    localStorage.clear();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-test");
    Object.defineProperty(window, "AudioContext", {
      value: FakeAudioContext,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, "WebSocket", {
      value: FakeWebSocket,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn(async () => new FakeMediaStream()),
      },
      configurable: true,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    ensureEverMemConversationGroupIdMock.mockReset();
  });

  it("opens the WS with provider=AgentPlatform and model=gemini-3.5-live-translate-preview", async () => {
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

    // Start the realtime call (click connect)
    await act(async () => {
      await result.current.voiceChat.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    expect(socket, "a WebSocket must have been opened").toBeDefined();
    const socketUrl = new URL(socket.url);
    expect(socketUrl.searchParams.get("provider")).toBe("AgentPlatform");
    expect(socketUrl.searchParams.get("model")).toBe("gemini-3.5-live-translate-preview");
    // live-translate params must be present
    expect(socketUrl.searchParams.get("target_language_code")).toBeTruthy();
    expect(socketUrl.searchParams.get("translation_mode")).toBe("unidirectional");
  });

  it("connects with AgentPlatform live-translate when chosen via chat model select only", async () => {
    const { result } = renderHook(() => useAppWiring());

    // Simulate picking the model in the CHAT model dropdown (no explicit
    // voiceChat.onProviderChange / onModelChange). The sync effect in
    // useVoiceChat must adopt this realtime selection.
    act(() => {
      result.current.chat.onModelChoiceChange(
        buildModelChoiceValue("AgentPlatform", "gemini-3.5-live-translate-preview")
      );
    });

    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
      expect(result.current.voiceChat.voiceChatModel).toBe("gemini-3.5-live-translate-preview");
    });

    await act(async () => {
      await result.current.voiceChat.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    expect(socket, "a WebSocket must have been opened").toBeDefined();
    const socketUrl = new URL(socket.url);
    expect(socketUrl.searchParams.get("provider")).toBe("AgentPlatform");
    expect(socketUrl.searchParams.get("model")).toBe("gemini-3.5-live-translate-preview");
    expect(socketUrl.searchParams.get("target_language_code")).toBeTruthy();
  });

  it("keeps AgentPlatform live-translate after connect, not qwen-audio", async () => {
    const { result } = renderHook(() => useAppWiring());

    act(() => {
      result.current.chat.onModelChoiceChange(
        buildModelChoiceValue("AgentPlatform", "gemini-3.5-live-translate-preview")
      );
      result.current.voiceChat.onProviderChange("AgentPlatform");
      result.current.voiceChat.onModelChange("gemini-3.5-live-translate-preview");
    });

    await waitFor(() => {
      expect(result.current.voiceChat.voiceChatModel).toBe("gemini-3.5-live-translate-preview");
    });

    await act(async () => {
      await result.current.voiceChat.onToggleRecording();
    });

    // After connecting, the committed selection must NOT have drifted to a
    // qwen-audio / DashScope model.
    expect(result.current.voiceChat.voiceChatProvider).toBe("AgentPlatform");
    expect(result.current.voiceChat.voiceChatModel).toBe("gemini-3.5-live-translate-preview");
    expect(result.current.voiceChat.voiceChatLiveTranslate).toBe(true);
  });
});
