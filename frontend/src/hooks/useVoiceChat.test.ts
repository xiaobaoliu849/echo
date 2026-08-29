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

import { configureEverMemRuntime, persistEverMemConversationGroupId } from "../api";
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

class FakeBufferSourceNode extends FakeAudioNode {
  buffer: { duration: number } | null = null;
  start = vi.fn();
  stop = vi.fn();
  addEventListener = vi.fn();
}

class FakeAnalyserNode extends FakeAudioNode {
  fftSize = 64;
  frequencyBinCount = 32;
  getByteFrequencyData = vi.fn();
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  static processors: FakeProcessorNode[] = [];
  static gains: FakeGainNode[] = [];
  static bufferSources: FakeBufferSourceNode[] = [];
  state = "running";
  currentTime = 0;
  sampleRate = 48000;
  destination = {};

  constructor() {
    FakeAudioContext.instances.push(this);
  }

  resume = vi.fn(async (): Promise<void> => undefined);
  close = vi.fn(async () => undefined);
  createMediaStreamSource = vi.fn(() => new FakeAudioNode());
  createScriptProcessor = vi.fn(() => {
    const processor = new FakeProcessorNode();
    FakeAudioContext.processors.push(processor);
    return processor;
  });
  createGain = vi.fn(() => {
    const gain = new FakeGainNode();
    FakeAudioContext.gains.push(gain);
    return gain;
  });
  createBuffer = vi.fn((_channels: number, length: number, sampleRate: number) => ({
    duration: length / sampleRate,
    getChannelData: () => new Float32Array(length),
  }));
  createBufferSource = vi.fn(() => {
    const source = new FakeBufferSourceNode();
    FakeAudioContext.bufferSources.push(source);
    return source;
  });
  createAnalyser = vi.fn(() => new FakeAnalyserNode());
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;

  readyState = FakeWebSocket.CONNECTING;
  binaryType = "";
  sent: Array<string | ArrayBuffer> = [];
  onopen: (() => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;

  constructor(public readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(payload: string | ArrayBuffer) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
  }

  emitOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  emitMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  emitClose(code = 1000, reason = "") {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }
}

describe("useVoiceChat", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    FakeAudioContext.instances = [];
    FakeAudioContext.processors = [];
    FakeAudioContext.gains = [];
    FakeAudioContext.bufferSources = [];
    localStorage.clear();
    configureEverMemRuntime({
      enabled: true,
      api_url: "https://memory.example.com",
      api_key: "memory-key",
      scope_id: "workspace-main",
      temporary_session: false,
      remember_chat: true,
      remember_voice_chat: true,
      remember_recordings: true,
      remember_podcast: true,
      remember_tts: true,
      store_transcript_fulltext: false,
    });
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
    vi.useRealTimers();
    ensureEverMemConversationGroupIdMock.mockReset();
    fetchVoiceAgentMetricsSummaryMock.mockReset();
    fetchVoiceAgentSessionMock.mockReset();
    listVoiceAgentSessionsMock.mockReset();
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("waits for session_open before streaming microphone audio", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-audio-gate");
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.1-flash-live-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.1-flash-live-preview",
            availableModels: ["gemini-3.1-flash-live-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
    });
    const processor = FakeAudioContext.processors[0];
    expect(processor).toBeDefined();

    const audioPayloads = () => socket.sent.filter((item) => typeof item !== "string");
    const beforeAudioPayloadCount = audioPayloads().length;
    act(() => {
      processor.onaudioprocess?.({
        inputBuffer: { getChannelData: () => new Float32Array([0.1, -0.1, 0.05]) },
      });
    });
    expect(audioPayloads()).toHaveLength(beforeAudioPayloadCount);

    act(() => {
      socket.emitMessage({
        type: "session_open",
        provider: "Google",
        model: "gemini-3.1-flash-live-preview",
        voice: "Puck",
      });
      processor.onaudioprocess?.({
        inputBuffer: { getChannelData: () => new Float32Array([0.1, -0.1, 0.05]) },
      });
    });

    expect(audioPayloads().length).toBeGreaterThan(beforeAudioPayloadCount);
  });

  it("ignores stale websocket close events after a new realtime session starts", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-001");
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope", "Google"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3-omni-flash-realtime-2025-12-01",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3-omni-flash-realtime-2025-12-01",
            availableModels: ["qwen3-omni-flash-realtime-2025-12-01"],
          },
          Google: {
            defaultModel: "gemini-2.5-flash-native-audio-preview-12-2025",
            availableModels: ["gemini-2.5-flash-native-audio-preview-12-2025"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const firstSocket = FakeWebSocket.instances[0];
    expect(firstSocket).toBeDefined();

    act(() => {
      firstSocket.emitOpen();
      firstSocket.emitMessage({
        type: "session_open",
        provider: "DashScope",
        model: "qwen3-omni-flash-realtime-2025-12-01",
        voice: "Cherry",
      });
    });

    expect(result.current.voiceChatConnected).toBe(true);

    act(() => {
      result.current.onToggleRecording();
    });

    expect(result.current.voiceChatConnected).toBe(false);

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const secondSocket = FakeWebSocket.instances[1];
    expect(secondSocket).toBeDefined();

    act(() => {
      secondSocket.emitOpen();
      secondSocket.emitMessage({
        type: "session_open",
        provider: "DashScope",
        model: "qwen3-omni-flash-realtime-2025-12-01",
        voice: "Cherry",
      });
    });

    expect(result.current.voiceChatConnected).toBe(true);

    act(() => {
      firstSocket.emitClose();
    });

    expect(result.current.voiceChatConnected).toBe(true);
    expect(result.current.voiceChatStatus).toContain("实时会话已连接");
  });

  it("sends the current EverMem group_id in websocket config and refreshes it after reset", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock
      .mockResolvedValueOnce("voice-group-001")
      .mockResolvedValueOnce("voice-group-002");

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3-omni-flash-realtime-2025-12-01",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3-omni-flash-realtime-2025-12-01",
            availableModels: ["qwen3-omni-flash-realtime-2025-12-01"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });
    const firstSocket = FakeWebSocket.instances[0];
    act(() => {
      firstSocket.emitOpen();
    });
    expect(JSON.parse(String(firstSocket.sent[0]))).toMatchObject({
      type: "config",
      memory: {
        group_id: "voice-group-001",
      },
    });

    act(() => {
      result.current.onResetSession();
    });

    await act(async () => {
      await result.current.onToggleRecording();
    });
    const secondSocket = FakeWebSocket.instances[1];
    act(() => {
      secondSocket.emitOpen();
    });
    expect(JSON.parse(String(secondSocket.sent[0]))).toMatchObject({
      type: "config",
      memory: {
        group_id: "voice-group-002",
      },
    });
    expect(ensureEverMemConversationGroupIdMock.mock.calls).toEqual([
      ["voice_chat", ""],
      ["voice_chat", ""],
    ]);
  });

  it("restores a persisted EverMem group_id after remount", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    persistEverMemConversationGroupId("voice_chat", "voice-group-restore");
    ensureEverMemConversationGroupIdMock.mockImplementation(async (_scene, currentGroupId) => currentGroupId);

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3-omni-flash-realtime-2025-12-01",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3-omni-flash-realtime-2025-12-01",
            availableModels: ["qwen3-omni-flash-realtime-2025-12-01"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
    });

    expect(ensureEverMemConversationGroupIdMock).toHaveBeenCalledWith("voice_chat", "voice-group-restore");
    expect(JSON.parse(String(socket.sent[0]))).toMatchObject({
      type: "config",
      memory: {
        group_id: "voice-group-restore",
      },
    });
  });

  it("falls back to a realtime voice model even when provider defaults point to text models", () => {
    const formatErrorMessage = createFormatErrorMessageStub();

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen-plus",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen-plus",
            availableModels: ["qwen-plus", "qwen-max"],
          },
        },
      })
    );

    expect(result.current.voiceChatModel).toBe("qwen3.5-omni-plus-realtime");
    expect(result.current.voiceChatModelOptions).toEqual([
      "qwen3.5-omni-plus-realtime",
      "qwen3.5-livetranslate-flash-realtime",
      "qwen-audio-3.0-realtime-plus",
      "qwen-audio-3.0-realtime-flash",
    ]);
  });

  it("keeps configured DashScope realtime models outside the built-in defaults", () => {
    const formatErrorMessage = createFormatErrorMessageStub();

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3.5-omni-plus-realtime-2026-03-15",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3.5-omni-plus-realtime-2026-03-15",
            availableModels: ["qwen3.5-omni-plus-realtime-2026-03-15"],
          },
        },
      })
    );

    expect(result.current.voiceChatModel).toBe("qwen3.5-omni-plus-realtime-2026-03-15");
    expect(result.current.voiceChatModelOptions).toContain("qwen3.5-omni-plus-realtime-2026-03-15");
  });

  it("filters old and lookalike Qwen realtime models without compatibility fallback", () => {
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage: createFormatErrorMessageStub(),
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3-omni-flash-realtime-2025-12-01",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3-omni-flash-realtime-2025-12-01",
            availableModels: [
              "qwen3-omni-flash-realtime-2025-12-01",
              "custom-qwen3.5-omni-plus-realtime",
              "qwen3.5-omni-plus-realtime-fake",
              "qwen3.5-omni-plus-livetranslate",
              "qwen3.5-omni-flash-realtime",
            ],
          },
        },
      })
    );

    expect(result.current.voiceChatModel).toBe("qwen3.5-omni-plus-realtime");
    expect(result.current.voiceChatModelOptions).toEqual([
      "qwen3.5-omni-plus-realtime",
      "qwen3.5-livetranslate-flash-realtime",
      "qwen-audio-3.0-realtime-plus",
      "qwen-audio-3.0-realtime-flash",
      "qwen3.5-omni-flash-realtime",
    ]);
  });

  it("uses longan voices for Qwen Audio realtime models", async () => {
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage: createFormatErrorMessageStub(),
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen-audio-3.0-realtime-plus",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen-audio-3.0-realtime-plus",
            availableModels: ["qwen-audio-3.0-realtime-plus"],
          },
        },
      })
    );

    expect(result.current.voiceChatModel).toBe("qwen-audio-3.0-realtime-plus");
    expect(result.current.voiceChatVoiceOptions.map((item) => item.value)).toContain("longanqian");
    expect(result.current.voiceChatVoiceOptions.map((item) => item.value)).not.toContain("Cherry");
    await waitFor(() => expect(result.current.voiceChatVoice).toBe("longanqian"));
  });

  it("adds Live Translate target language parameters to the websocket URL", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-live-translate");

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    act(() => {
      result.current.onTargetLanguageCodeChange("zh-Hans");
      result.current.onEchoTargetLanguageChange(false);
    });

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socketUrl = new URL(FakeWebSocket.instances[0].url);
    expect(socketUrl.searchParams.get("provider")).toBe("Google");
    expect(socketUrl.searchParams.get("model")).toBe("gemini-3.5-live-translate-preview");
    expect(socketUrl.searchParams.get("target_language_code")).toBe("zh-Hans");
    expect(socketUrl.searchParams.get("echo_target_language")).toBe("false");
  });

  it("exposes the full Google Live Translate target language list", () => {
    const formatErrorMessage = createFormatErrorMessageStub();

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    const values = result.current.voiceChatTargetLanguageOptions.map((item) => item.value);
    expect(values.length).toBeGreaterThanOrEqual(70);
    expect(values).toEqual(expect.arrayContaining(["af", "en", "ja", "ko", "pl", "pt-PT", "zh-Hans", "zh-Hant", "zu"]));
  });

  it("uses Chinese-friendly Live Translate language labels", () => {
    const formatErrorMessage = createFormatErrorMessageStub();

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
        language: "zh-CN",
      })
    );

    expect(result.current.voiceChatTargetLanguageOptions[0].value).toBe("zh-Hans");
    expect(result.current.voiceChatTargetLanguageOptions.find((item) => item.value === "ja")?.label).toContain("日语");
  });

  it("commits completed Live Translate pairs when a new source segment starts", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-live-translate");

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "Google",
        model: "gemini-3.5-live-translate-preview",
        voice: "Puck",
        mode: "live_translate",
        target_language_code: "zh-Hans",
        echo_target_language: true,
      });
      socket.emitMessage({ type: "user_transcript", text: "あ、もしもし。" });
      socket.emitMessage({ type: "assistant_text", text: "喂，你好。" });
      socket.emitMessage({ type: "user_transcript", text: "今何時ですか？" });
    });

    expect(result.current.sessionSummary).toEqual([
      { role: "user", content: "あ、もしもし。", memorySaved: false, id: expect.any(String) },
      {
        role: "assistant",
        content: "喂，你好。",
        memoriesUsed: undefined,
        memorySourceSummary: undefined,
        memoryRetrievalAttempted: false,
        id: expect.any(String),
      },
    ]);
    expect(result.current.voiceChatTranscript).toBe("今何時ですか？");
    expect(result.current.voiceChatReply).toBe("");
  });

  it("archives each completed Live Translate pair before streaming the next sentence", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-live-translate-turns");

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "Google",
        model: "gemini-3.5-live-translate-preview",
        voice: "Puck",
        mode: "live_translate",
      });
      socket.emitMessage({ type: "user_transcript", text: "How are you?", turn_id: "turn-1" });
      socket.emitMessage({ type: "assistant_text", text: "你好吗？", turn_id: "turn-1" });
      socket.emitMessage({ type: "turn_complete", turn_id: "turn-1" });
      socket.emitMessage({ type: "user_transcript", text: "Nice to meet you.", turn_id: "turn-2" });
    });

    expect(result.current.voiceChatMessages).toEqual([
      { role: "user", content: "How are you?", memorySaved: false, turnId: "turn-1", id: expect.any(String) },
      {
        role: "assistant",
        content: "你好吗？",
        memoriesUsed: undefined,
        memorySourceSummary: undefined,
        memoryRetrievalAttempted: false,
        turnId: "turn-1",
        interrupted: undefined,
        toolCalls: undefined,
        id: expect.any(String),
      },
    ]);
    expect(result.current.voiceChatTranscript).toBe("Nice to meet you.");
    expect(result.current.voiceChatReply).toBe("");
  });

  it("splits cumulative Google Live Translate transcripts after each short pause", async () => {
    vi.useFakeTimers();
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-live-translate-cumulative");

    const { result, unmount } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "Google",
        model: "gemini-3.5-live-translate-preview",
        voice: "Puck",
        mode: "live_translate",
      });
      socket.emitMessage({ type: "user_transcript", text: "Hello, can you hear me?" });
      // The Google backend emits assistant transcripts as verbatim deltas (see
      // _merge_streaming_text in realtime_google_provider.py and the replay test
      // test_google_output_transcription_emits_only_novel_overlapping_text). The
      // user side, by contrast, is sent cumulatively.
      socket.emitMessage({ type: "assistant_text", text: "もしもし、聞こえますか？" });
      vi.advanceTimersByTime(900);
    });

    expect(result.current.voiceChatMessages).toHaveLength(2);

    act(() => {
      socket.emitMessage({
        type: "user_transcript",
        text: "Hello, can you hear me?Uh, can you tell me your name?",
      });
      socket.emitMessage({
        type: "assistant_text",
        text: "あの、お名前を教えていただけますか？",
      });
      vi.advanceTimersByTime(900);
    });

    act(() => {
      socket.emitMessage({
        type: "user_transcript",
        text: "Hello, can you hear me?Uh, can you tell me your name?I want to go to bed.",
      });
      socket.emitMessage({
        type: "assistant_text",
        text: "寝たいんです。",
      });
      vi.advanceTimersByTime(900);
    });

    expect(result.current.voiceChatMessages.map((message) => message.content)).toEqual([
      "Hello, can you hear me?",
      "もしもし、聞こえますか？",
      "Uh, can you tell me your name?",
      "あの、お名前を教えていただけますか？",
      "I want to go to bed.",
      "寝たいんです。",
    ]);
    expect(result.current.voiceChatTranscript).toBe("");
    expect(result.current.voiceChatReply).toBe("");

    unmount();
    vi.useRealTimers();
  });

  it("waits for a lagging Live Translate target before committing the pair", async () => {
    vi.useFakeTimers();
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-live-translate-lagging");

    const { result, unmount } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "Google",
        model: "gemini-3.5-live-translate-preview",
        voice: "Puck",
        mode: "live_translate",
      });
      socket.emitMessage({ type: "user_transcript", text: "Hey, I wanted to chat." });
      socket.emitMessage({ type: "assistant_text", text: "ねえ、話" });
      vi.advanceTimersByTime(1200);
    });

    expect(result.current.voiceChatMessages).toEqual([]);
    expect(result.current.voiceChatReply).toBe("ねえ、話");

    act(() => {
      socket.emitMessage({ type: "assistant_text", text: "したいんだけど。" });
      vi.advanceTimersByTime(900);
    });

    expect(result.current.voiceChatMessages.map((message) => message.content)).toEqual([
      "Hey, I wanted to chat.",
      "ねえ、話したいんだけど。",
    ]);
    expect(result.current.voiceChatTranscript).toBe("");
    expect(result.current.voiceChatReply).toBe("");

    unmount();
    vi.useRealTimers();
  });

  it("does not split Live Translate while local speech is still active", async () => {
    vi.useFakeTimers();
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-live-translate-vad");

    const { result, unmount } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "Google",
        model: "gemini-3.5-live-translate-preview",
        voice: "Puck",
        mode: "live_translate",
      });
    });
    const processor = FakeAudioContext.processors[0];
    const emitAudioFrame = (samples: Float32Array) => {
      processor.onaudioprocess?.({ inputBuffer: { getChannelData: () => samples } });
    };

    act(() => {
      emitAudioFrame(new Float32Array([0.1, 0.1, 0.1, 0.1]));
      emitAudioFrame(new Float32Array([0.1, 0.1, 0.1, 0.1]));
      socket.emitMessage({ type: "user_transcript", text: "This is still one sentence." });
      socket.emitMessage({ type: "assistant_text", text: "これはまだ一つの文です。" });
      vi.advanceTimersByTime(2000);
    });

    expect(result.current.voiceChatMessages).toEqual([]);

    act(() => {
      for (let index = 0; index < 5; index += 1) {
        emitAudioFrame(new Float32Array([0, 0, 0, 0]));
      }
      vi.advanceTimersByTime(900);
    });

    expect(result.current.voiceChatMessages.map((message) => message.content)).toEqual([
      "This is still one sentence.",
      "これはまだ一つの文です。",
    ]);

    unmount();
    vi.useRealTimers();
  });

  it("coalesces short Latin Live Translate fragments into one active turn", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-live-translate");

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "Google",
        model: "gemini-3.5-live-translate-preview",
        voice: "Puck",
        mode: "live_translate",
        target_language_code: "ja",
        echo_target_language: true,
      });
      socket.emitMessage({ type: "user_transcript", text: "Um, do you know" });
      socket.emitMessage({ type: "assistant_text", text: "あの、" });
      socket.emitMessage({ type: "user_transcript", text: "the" });
      socket.emitMessage({ type: "assistant_text", text: "ご存知ですか？" });
      socket.emitMessage({ type: "user_transcript", text: "Longcha?" });
      socket.emitMessage({ type: "assistant_text", text: "ロンチャを。" });
    });

    expect(result.current.sessionSummary).toEqual([]);
    expect(result.current.voiceChatTranscript).toBe("Um, do you know the Longcha?");
    expect(result.current.voiceChatReply).toBe("あの、ご存知ですか？ロンチャを。");
  });

  it("exposes the first active Live Translate pair for sidebar archiving before turn completion", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-first-live");

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.5-live-translate-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.5-live-translate-preview",
            availableModels: ["gemini-3.5-live-translate-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "Google",
        model: "gemini-3.5-live-translate-preview",
        voice: "Puck",
        mode: "live_translate",
        target_language_code: "zh-Hans",
        echo_target_language: true,
      });
      socket.emitMessage({ type: "user_transcript", text: "Hello, can you hear me?" });
      socket.emitMessage({ type: "assistant_text", text: "你好，听得到。" });
    });

    expect(result.current.sessionSummary).toEqual([]);
    expect(result.current.voiceChatArchiveMessages).toEqual([
      { role: "user", content: "Hello, can you hear me?", memorySaved: false },
      {
        role: "assistant",
        content: "你好，听得到。",
        memoriesUsed: undefined,
        memorySourceSummary: undefined,
        memoryRetrievalAttempted: false,
      },
    ]);
  });

  it("keeps the full voice session history instead of truncating older turns", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-full-history");

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3-omni-flash-realtime-2025-12-01",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3-omni-flash-realtime-2025-12-01",
            availableModels: ["qwen3-omni-flash-realtime-2025-12-01"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "DashScope",
        model: "qwen3-omni-flash-realtime-2025-12-01",
        voice: "Cherry",
        mode: "voice_chat",
      });
      for (let i = 1; i <= 8; i += 1) {
        socket.emitMessage({ type: "user_transcript", text: `第 ${i} 轮用户` });
        socket.emitMessage({ type: "assistant_text", text: `第 ${i} 轮助手` });
        socket.emitMessage({ type: "turn_complete" });
      }
    });

    expect(result.current.voiceChatMessages).toHaveLength(16);
    expect(result.current.sessionSummary).toHaveLength(16);
    expect(result.current.sessionSummary[0]).toMatchObject({ role: "user", content: "第 1 轮用户" });
  });

  it("tracks voice agent tool progress and grounded search sources", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-001");

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3-omni-flash-realtime-2025-12-01",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3-omni-flash-realtime-2025-12-01",
            availableModels: ["qwen3-omni-flash-realtime-2025-12-01"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const toolSocket = FakeWebSocket.instances[0];
    act(() => {
      toolSocket.emitOpen();
      toolSocket.emitMessage({
        type: "user_transcript",
        text: "帮我搜索 AI voice agent 的资料",
      });
      toolSocket.emitMessage({
        type: "tool_call_started",
        tool_name: "search_web",
        turn_id: "voice-turn-1",
        tool_call_id: "voice-tool-1",
        provider_call_id: "call-qwen-1",
        route: "native",
        query: "AI voice agent",
        message: "正在搜索相关资料...",
      });
    });

    expect(result.current.voiceChatAgentToolStatus).toBe("正在搜索相关资料...");
    expect(result.current.voiceChatAgentRunMeta).toBe("voice-turn-1 · search_web");
    expect(result.current.voiceChatAgentSources).toEqual([]);

    act(() => {
      toolSocket.emitMessage({
        type: "agent_result",
        turn_id: "voice-turn-1",
        query: "AI voice agent",
        answer: "我查到这些信息，可以先按来源做一个简要整合。",
        source_count: 1,
        elapsed_ms: 320,
        sources: [
          {
            title: "Research source",
            uri: "https://example.com/research",
            snippet: "Fetched research content",
            source_type: "web_search",
          },
        ],
      });
    });

    expect(result.current.voiceChatReply).toBe("");
    expect(result.current.voiceChatAgentToolStatus).toBe("已基于 1 个来源生成搜索摘要");
    expect(result.current.voiceChatAgentRunMeta).toBe("voice-turn-1 · 1 sources · 320ms");
    expect(result.current.voiceChatAgentSources).toEqual([
      {
        title: "Research source",
        uri: "https://example.com/research",
        snippet: "Fetched research content",
        source_type: "web_search",
      },
    ]);

    act(() => {
      toolSocket.emitMessage({
        type: "tool_result_delivered",
        provider: "DashScope",
        tool_name: "search_web",
        turn_id: "voice-turn-1",
        tool_call_id: "voice-tool-1",
        provider_call_id: "call-qwen-1",
        query: "AI voice agent",
        source_count: 1,
        elapsed_ms: 320,
        status: "completed",
        sources: [
          {
            title: "Research source",
            uri: "https://example.com/research",
            snippet: "Fetched research content",
            source_type: "web_search",
          },
        ],
      });
    });

    expect(result.current.voiceChatAgentToolStatus).toBe("工具结果已交给模型，正在生成回答…");
    expect(result.current.voiceChatStatus).toBe("正在基于工具结果回答…");

    act(() => {
      toolSocket.emitMessage({ type: "assistant_text", text: "这是模型基于工具结果生成的最终回答。" });
      toolSocket.emitMessage({ type: "turn_complete" });
    });

    expect(result.current.voiceChatMessages).toHaveLength(2);
    expect(result.current.voiceChatAgentToolStatus).toBe("");
    expect(result.current.voiceChatAgentRunMeta).toBe("");
    expect(result.current.voiceChatAgentSources).toEqual([]);
    expect(result.current.voiceChatMessages[0]).toMatchObject({
      role: "user",
      content: "帮我搜索 AI voice agent 的资料",
    });
    expect(result.current.voiceChatMessages[1]).toMatchObject({
      role: "assistant",
      content: "这是模型基于工具结果生成的最终回答。",
      toolCalls: expect.arrayContaining([
        expect.objectContaining({
          status: "started",
          tool_name: "search_web",
          turn_id: "voice-turn-1",
          query: "AI voice agent",
        }),
        expect.objectContaining({
          status: "result",
          query: "AI voice agent",
          source_count: 1,
          sources: [
            expect.objectContaining({
              title: "Research source",
              uri: "https://example.com/research",
            }),
          ],
        }),
        expect.objectContaining({
          status: "result_delivered",
          provider: "DashScope",
          tool_name: "search_web",
          sources: [
            expect.objectContaining({
              title: "Research source",
              uri: "https://example.com/research",
            }),
          ],
        }),
      ]),
    });
  });

  it("loads persisted voice agent sessions and exports the selected detail as JSON", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    fetchVoiceAgentMetricsSummaryMock.mockResolvedValue({
      provider: "all",
      session_count: 1,
      turn_count: 1,
      completed_turn_count: 1,
      interrupted_turn_count: 0,
      decision_count: 0,
      classifications: {},
      false_interruption_rate: null,
      first_audio_ms: { count: 1, avg: 80, p50: 80, p95: 80, min: 80, max: 80 },
      interruption_decision_ms: { count: 0, avg: null, p50: null, p95: null, min: null, max: null },
      interruption_stop_ms: { count: 0, avg: null, p50: null, p95: null, min: null, max: null },
      turn_completion_ms: { count: 1, avg: 3000, p50: 3000, p95: 3000, min: 3000, max: 3000 },
      providers: [],
    });
    listVoiceAgentSessionsMock.mockResolvedValue({
      count: 1,
      sessions: [
        {
          id: "voice-session-1",
          provider: "DashScope",
          model: "qwen3-omni-flash-realtime-2025-12-01",
          voice: "Cherry",
          status: "closed",
          started_at: "2026-07-07 10:00:00",
          ended_at: "2026-07-07 10:01:00",
          meta: { transport: "websocket" },
        },
      ],
    });
    fetchVoiceAgentSessionMock.mockResolvedValue({
      id: "voice-session-1",
      provider: "DashScope",
      model: "qwen3-omni-flash-realtime-2025-12-01",
      voice: "Cherry",
      status: "closed",
      started_at: "2026-07-07 10:00:00",
      ended_at: "2026-07-07 10:01:00",
      meta: { transport: "websocket" },
      turns: [
        {
          id: 1,
          session_id: "voice-session-1",
          turn_id: "voice-tool-1",
          user_text: "帮我搜索 voice agent",
          assistant_text: "已整理来源。",
          memory_payload: { saved_count: 1 },
          completed: true,
          started_at: "2026-07-07 10:00:01",
          completed_at: "2026-07-07 10:00:04",
        },
      ],
      tool_events: [
        {
          id: 2,
          session_id: "voice-session-1",
          turn_id: "voice-tool-1",
          event_type: "agent_result",
          tool_name: "search_web",
          query: "voice agent",
          payload: { answer: "已整理来源。" },
          created_at: "2026-07-07 10:00:03",
        },
      ],
      timeline: [
        {
          id: "session:voice-session-1:open",
          event_type: "session_open",
          source: "session",
          turn_id: "",
          tool_name: "",
          query: "",
          text: "",
          timestamp: "2026-07-07 10:00:00",
          payload: { provider: "DashScope" },
        },
        {
          id: "turn:1:user",
          event_type: "user_transcript",
          source: "turn",
          turn_id: "voice-tool-1",
          tool_name: "",
          query: "",
          text: "帮我搜索 voice agent",
          timestamp: "2026-07-07 10:00:01",
          payload: { completed: true },
        },
        {
          id: "tool_event:2",
          event_type: "agent_result",
          source: "tool_event",
          turn_id: "voice-tool-1",
          tool_name: "search_web",
          query: "voice agent",
          text: "已整理来源。",
          timestamp: "2026-07-07 10:00:03",
          payload: { answer: "已整理来源。" },
        },
      ],
    });

    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3-omni-flash-realtime-2025-12-01",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3-omni-flash-realtime-2025-12-01",
            availableModels: ["qwen3-omni-flash-realtime-2025-12-01"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onLoadVoiceAgentHistory();
    });

    expect(listVoiceAgentSessionsMock).toHaveBeenCalledWith(20);
    expect(fetchVoiceAgentMetricsSummaryMock).toHaveBeenCalledWith(200);
    expect(result.current.voiceAgentHistorySessions).toHaveLength(1);
    expect(result.current.voiceAgentMetricsSummary?.first_audio_ms.p50).toBe(80);
    expect(result.current.voiceAgentHistorySessions[0].id).toBe("voice-session-1");

    await act(async () => {
      await result.current.onOpenVoiceAgentSession("voice-session-1");
    });

    expect(fetchVoiceAgentSessionMock).toHaveBeenCalledWith("voice-session-1");
    expect(result.current.voiceAgentHistoryDetail?.turns[0].user_text).toBe("帮我搜索 voice agent");
    expect(result.current.voiceAgentHistoryDetail?.tool_events[0].event_type).toBe("agent_result");

    let exported = "";
    act(() => {
      exported = result.current.onExportVoiceAgentSession();
    });

    const parsed = JSON.parse(exported);
    expect(parsed.session.id).toBe("voice-session-1");
    expect(parsed.session.turns[0].assistant_text).toBe("已整理来源。");
    expect(parsed.session.timeline[2].event_type).toBe("agent_result");
    expect(result.current.voiceAgentHistoryExportText).toContain("\"voice-session-1\"");

    fetchVoiceAgentSessionMock.mockRejectedValueOnce(new Error("not found"));
    await act(async () => {
      await result.current.onOpenVoiceAgentSession("missing-session");
    });

    expect(fetchVoiceAgentSessionMock).toHaveBeenCalledWith("missing-session");
    expect(result.current.voiceAgentHistoryDetail).toBeNull();
    expect(result.current.voiceAgentHistoryExportText).toBe("");
    expect(result.current.voiceAgentHistoryError).toBe("加载历史语音 Agent 会话详情失败。");
  });

  it("ducks on a candidate, resumes backchannels, and archives confirmed interruptions", async () => {
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-interruption");
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage: createFormatErrorMessageStub(),
        providerOptions: ["OpenAI"],
        preferredProvider: "OpenAI",
        preferredModel: "gpt-realtime-2",
        providerModelCatalog: {
          OpenAI: { defaultModel: "gpt-realtime-2", availableModels: ["gpt-realtime-2"] },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({ type: "session_open", provider: "OpenAI", model: "gpt-realtime-2", voice: "alloy" });
      socket.emitMessage({ type: "user_transcript", text: "继续解释", turn_id: "voice-turn-1" });
      socket.emitMessage({ type: "assistant_text", text: "这是还没说完的回答", turn_id: "voice-turn-1" });
      socket.emitMessage({
        type: "tool_call_started",
        tool_name: "search_web",
        turn_id: "voice-turn-1",
        tool_call_id: "voice-tool-interrupted",
        provider_call_id: "provider-tool-interrupted",
        route: "native",
        query: "interrupted query",
        message: "正在搜索相关资料...",
      });
      socket.emitMessage({
        type: "interruption_pending",
        candidate_id: "interruption-1",
        provider: "OpenAI",
        interrupted_turn_id: "voice-turn-1",
      });
    });

    expect(result.current.voiceChatInterruptionState.phase).toBe("evaluating");
    expect(result.current.voiceChatAgentToolStatus).toBe("正在搜索相关资料...");
    expect(FakeAudioContext.gains[0].gain.value).toBe(0.18);

    act(() => {
      socket.emitMessage({
        type: "interruption_decision",
        candidate_id: "interruption-1",
        classification: "BACKCHANNEL",
        rule: "backchannel_pattern:^嗯(嗯)?$",
        decision: "resume",
        transcript: "嗯嗯",
        provider: "OpenAI",
        interrupted_turn_id: "voice-turn-1",
        elapsed_ms: 37,
      });
    });

    expect(result.current.voiceChatMessages).toHaveLength(0);
    expect(result.current.voiceChatReply).toBe("这是还没说完的回答");
    expect(result.current.voiceChatMetrics.falseInterruptionRate).toBe(1);
    expect(FakeAudioContext.gains[0].gain.value).toBe(1);

    await act(async () => {
      socket.emitMessage({
        type: "assistant_audio",
        audio: "AAA=",
        encoding: "pcm_s16le",
        sample_rate: 24000,
        turn_id: "voice-turn-1",
        first_audio_ms: 84,
      });
      socket.emitMessage({
        type: "interruption_pending",
        candidate_id: "interruption-2",
        provider: "OpenAI",
        interrupted_turn_id: "voice-turn-1",
      });
      socket.emitMessage({
        type: "interruption_decision",
        candidate_id: "interruption-2",
        classification: "TRUE_BARGE_IN",
        rule: "non_backchannel_speech",
        decision: "cancel",
        transcript: "等一下",
        provider: "OpenAI",
        interrupted_turn_id: "voice-turn-1",
        elapsed_ms: 42,
        stop_latency_ms: 42,
      });
      await Promise.resolve();
    });

    expect(FakeAudioContext.bufferSources[0].stop).toHaveBeenCalledTimes(1);
    expect(
      socket.sent.some(
        (payload) => typeof payload === "string" && payload.includes('"type":"interruption_client_stopped"')
      )
    ).toBe(true);
    expect(result.current.voiceChatMessages).toHaveLength(0);

    act(() => {
      socket.emitMessage({
        type: "interrupted",
        candidate_id: "interruption-2",
        turn_id: "voice-turn-1",
        interrupted: true,
        stop_latency_ms: 42,
      });
    });

    expect(result.current.voiceChatAssistantInterrupted).toBe(true);
    expect(result.current.voiceChatAgentToolStatus).toBe("");
    expect(result.current.voiceChatAgentRunMeta).toBe("");
    expect(result.current.voiceChatAgentSources).toEqual([]);
    expect(result.current.voiceChatMetrics.firstAudioMs).toBe(84);
    expect(result.current.voiceChatMetrics.decisionCount).toBe(2);
    expect(result.current.voiceChatMetrics.falseInterruptionRate).toBe(0.5);
    expect(result.current.voiceChatMetrics.interruptionStopMs).not.toBeNull();
    expect(FakeAudioContext.bufferSources[0].stop).toHaveBeenCalledTimes(1);
    expect(result.current.voiceChatMessages).toEqual([
      expect.objectContaining({ role: "user", content: "继续解释", turnId: "voice-turn-1" }),
      expect.objectContaining({
        role: "assistant",
        content: "这是还没说完的回答",
        turnId: "voice-turn-1",
        interrupted: true,
      }),
    ]);

    act(() => {
      socket.emitMessage({ type: "user_transcript", text: "现在继续", turn_id: "voice-turn-2" });
      socket.emitMessage({ type: "assistant_text", text: "这是新一轮", turn_id: "voice-turn-2" });
      socket.emitMessage({
        type: "interrupted",
        candidate_id: "interruption-2",
        turn_id: "voice-turn-1",
        interrupted: true,
      });
      socket.emitMessage({ type: "turn_complete", turn_id: "voice-turn-1", interrupted: true });
    });

    expect(result.current.voiceChatReply).toBe("这是新一轮");
    expect(result.current.voiceChatMessages).toHaveLength(2);
    expect(result.current.voiceChatAssistantInterrupted).toBe(false);
  });

  it("recovers while timeout is pending and still accepts the authoritative decision", async () => {
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-timeout");
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage: createFormatErrorMessageStub(),
        providerOptions: ["OpenAI"],
        preferredProvider: "OpenAI",
        preferredModel: "gpt-realtime-2",
        providerModelCatalog: {
          OpenAI: { defaultModel: "gpt-realtime-2", availableModels: ["gpt-realtime-2"] },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emitOpen();
      socket.emitMessage({ type: "session_open", provider: "OpenAI", model: "gpt-realtime-2", voice: "alloy" });
      socket.emitMessage({ type: "user_transcript", text: "解释一下", turn_id: "voice-turn-timeout" });
      socket.emitMessage({ type: "assistant_text", text: "正在回答", turn_id: "voice-turn-timeout" });
      socket.emitMessage({
        type: "assistant_audio",
        audio: "AAA=",
        encoding: "pcm_s16le",
        sample_rate: 24000,
        turn_id: "voice-turn-timeout",
      });
      socket.emitMessage({
        type: "interruption_pending",
        candidate_id: "interruption-timeout",
        provider: "OpenAI",
        interrupted_turn_id: "voice-turn-timeout",
      });
    });
    expect(result.current.voiceChatInterruptionState.phase).toBe("evaluating");

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2600));
    });

    expect(result.current.voiceChatInterruptionState.phase).toBe("idle");
    expect(FakeAudioContext.gains[0].gain.value).toBe(1);
    expect(
      socket.sent.some(
        (payload) => typeof payload === "string" && payload.includes('"type":"interruption_timeout"')
      )
    ).toBe(true);

    act(() => {
      socket.emitMessage({
        type: "interruption_decision",
        candidate_id: "interruption-timeout",
        classification: "TRUE_BARGE_IN",
        rule: "non_backchannel_speech",
        decision: "cancel",
        transcript: "等一下",
        provider: "OpenAI",
        interrupted_turn_id: "voice-turn-timeout",
        elapsed_ms: 2800,
      });
      socket.emitMessage({
        type: "interrupted",
        candidate_id: "interruption-timeout",
        turn_id: "voice-turn-timeout",
        interrupted: true,
      });
    });

    expect(FakeAudioContext.bufferSources[0].stop).toHaveBeenCalledTimes(1);
    expect(result.current.voiceChatInterruptionState.phase).toBe("interrupted");
    expect(result.current.voiceChatAssistantInterrupted).toBe(true);
    expect(result.current.voiceChatMetrics.interruptionStopMs).not.toBeNull();
    expect(result.current.voiceChatMessages).toEqual([
      expect.objectContaining({ role: "user", content: "解释一下", turnId: "voice-turn-timeout" }),
      expect.objectContaining({
        role: "assistant",
        content: "正在回答",
        turnId: "voice-turn-timeout",
        interrupted: true,
      }),
    ]);
  }, 5000);

  it("does not schedule stale audio after interruption while the audio context resumes", async () => {
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-resume-race");
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage: createFormatErrorMessageStub(),
        providerOptions: ["OpenAI"],
        preferredProvider: "OpenAI",
        preferredModel: "gpt-realtime-2",
        providerModelCatalog: {
          OpenAI: { defaultModel: "gpt-realtime-2", availableModels: ["gpt-realtime-2"] },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });
    const socket = FakeWebSocket.instances[0];
    const context = FakeAudioContext.instances[0];
    let finishResume: (() => void) | undefined;
    const resumePromise = new Promise<void>((resolve) => {
      finishResume = resolve;
    });
    context.state = "suspended";
    context.resume = vi.fn(() => resumePromise);

    act(() => {
      socket.emitOpen();
      socket.emitMessage({ type: "session_open", provider: "OpenAI", model: "gpt-realtime-2", voice: "alloy" });
      socket.emitMessage({ type: "user_transcript", text: "解释一下", turn_id: "voice-turn-race" });
      socket.emitMessage({
        type: "assistant_audio",
        audio: "AAA=",
        encoding: "pcm_s16le",
        sample_rate: 24000,
        turn_id: "voice-turn-race",
      });
      socket.emitMessage({
        type: "interruption_pending",
        candidate_id: "interruption-race",
        provider: "OpenAI",
        interrupted_turn_id: "voice-turn-race",
      });
      socket.emitMessage({
        type: "interruption_decision",
        candidate_id: "interruption-race",
        classification: "TRUE_BARGE_IN",
        rule: "non_backchannel_speech",
        decision: "cancel",
        transcript: "等一下",
        provider: "OpenAI",
        interrupted_turn_id: "voice-turn-race",
        elapsed_ms: 30,
      });
    });

    await act(async () => {
      finishResume?.();
      await resumePromise;
    });

    expect(context.resume).toHaveBeenCalledTimes(1);
    expect(FakeAudioContext.bufferSources).toHaveLength(0);
  });

  it("handles Qwen LiveTranslate streaming without duplicating messages or previews", async () => {
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-livetranslate");
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage: createFormatErrorMessageStub(),
        providerOptions: ["DashScope"],
        preferredProvider: "DashScope",
        preferredModel: "qwen3.5-livetranslate-flash-realtime",
        providerModelCatalog: {
          DashScope: {
            defaultModel: "qwen3.5-livetranslate-flash-realtime",
            availableModels: ["qwen3.5-livetranslate-flash-realtime"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.emitOpen();
      socket.emitMessage({
        type: "session_open",
        provider: "DashScope",
        model: "qwen3.5-livetranslate-flash-realtime",
        voice: "Tina",
        mode: "live_translate",
      });
      // Source ASR arrives
      socket.emitMessage({
        type: "user_transcript",
        text: "今天的太阳好大",
        turn_id: "lt-turn-1",
      });
      // First confirmed translation chunk arrives
      socket.emitMessage({
        type: "assistant_text",
        text: "今日の太陽、",
        turn_id: "lt-turn-1",
      });
      // Speculative preview (stash) arrives
      socket.emitMessage({
        type: "translation_preview",
        text: "今日の太陽、",
        tentative: "すごく大きいですね。",
        turn_id: "lt-turn-1",
      });
      // Final confirmed translation chunk arrives
      socket.emitMessage({
        type: "assistant_text",
        text: "すごく大きいですね。",
        turn_id: "lt-turn-1",
      });
      // Turn complete arrives
      socket.emitMessage({
        type: "turn_complete",
        turn_id: "lt-turn-1",
      });
    });

    expect(result.current.voiceChatMessages).toEqual([
      expect.objectContaining({ role: "user", content: "今天的太阳好大", turnId: "lt-turn-1" }),
      expect.objectContaining({
        role: "assistant",
        content: "今日の太陽、すごく大きいですね。",
        turnId: "lt-turn-1",
      }),
    ]);
    expect(result.current.voiceChatReply).toBe("");
    expect(result.current.voiceChatTranscript).toBe("");
  });

  it("correctly resolves Doubao provider and defaults to doubao-realtime model and voice", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["DashScope", "Doubao"],
        preferredProvider: "Doubao",
        preferredModel: "doubao-realtime",
        providerModelCatalog: {
          Doubao: {
            defaultModel: "doubao-realtime",
            availableModels: ["doubao-realtime"],
          },
          DashScope: {
            defaultModel: "qwen3.5-omni-plus-realtime",
            availableModels: ["qwen3.5-omni-plus-realtime"],
          },
        },
      })
    );

    expect(result.current.voiceChatProvider).toBe("Doubao");
    expect(result.current.voiceChatModel).toBe("doubao-realtime");
    expect(result.current.voiceChatVoice).toBe("zh_female_vv_jupiter_bigtts");
  });

  it("sends text and image attachments over websocket and updates conversation messages", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    ensureEverMemConversationGroupIdMock.mockResolvedValue("voice-group-multimodal");
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        providerOptions: ["Google"],
        preferredProvider: "Google",
        preferredModel: "gemini-3.1-flash-live-preview",
        providerModelCatalog: {
          Google: {
            defaultModel: "gemini-3.1-flash-live-preview",
            availableModels: ["gemini-3.1-flash-live-preview"],
          },
        },
      })
    );

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const ws = FakeWebSocket.instances[0];
    expect(ws).toBeDefined();

    act(() => {
      ws.emitOpen();
      ws.emitMessage({ type: "session_open", model: "gemini-3.1-flash-live-preview" });
    });

    expect(result.current.voiceChatConnected).toBe(true);

    // Send plain text message
    act(() => {
      const sent = result.current.sendTextMessage("这是文字测试");
      expect(sent).toBe(true);
    });

    expect(ws.sent).toContain(JSON.stringify({ type: "text_input", text: "这是文字测试" }));
    expect(result.current.voiceChatMessages).toHaveLength(1);
    expect(result.current.voiceChatMessages[0].content).toBe("这是文字测试");

    // Send image attachment message
    act(() => {
      const sent = result.current.sendTextMessage("看这张图片", [
        { name: "test.png", content: "[Image]", type: "image", mimeType: "image/png", dataUrl: "data:image/png;base64,ABC" },
      ]);
      expect(sent).toBe(true);
    });

    expect(ws.sent).toContain(
      JSON.stringify({
        type: "media_input",
        media_type: "image",
        mime_type: "image/png",
        data: "data:image/png;base64,ABC",
        text: "看这张图片",
      })
    );
    expect(result.current.voiceChatMessages).toHaveLength(2);
    expect(result.current.voiceChatMessages[1].content).toBe("看这张图片");
    expect(result.current.voiceChatMessages[1].attachments).toHaveLength(1);
  });

  it("exposes reactive micAnalyser and assistantAnalyser instances on session start and clears them on stop", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceChat({
        formatErrorMessage,
        preferredProvider: "Google",
        preferredModel: "gemini-3.1-flash-live-preview",
      })
    );

    expect(result.current.micAnalyser).toBeNull();
    expect(result.current.assistantAnalyser).toBeNull();

    await act(async () => {
      await result.current.onToggleRecording();
    });

    const ws = FakeWebSocket.instances[0];
    expect(ws).toBeDefined();

    act(() => {
      ws.emitOpen();
      ws.emitMessage({ type: "session_open", model: "gemini-3.1-flash-live-preview" });
    });

    expect(result.current.voiceChatConnected).toBe(true);
    expect(result.current.micAnalyser).not.toBeNull();
    expect(result.current.assistantAnalyser).not.toBeNull();

    await act(async () => {
      await result.current.onToggleRecording();
    });

    expect(result.current.voiceChatConnected).toBe(false);
    expect(result.current.micAnalyser).toBeNull();
    expect(result.current.assistantAnalyser).toBeNull();
  });
});
