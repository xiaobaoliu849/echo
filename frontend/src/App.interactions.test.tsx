import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import * as api from "./api";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    fetchApiRuntimeInfo: vi.fn(),
    fetchDesktopStatus: vi.fn().mockResolvedValue(null),
    fetchVoices: vi.fn(),
    fetchSpeakAudio: vi.fn(),
    fetchSettings: vi.fn(),
    listCustomVoices: vi.fn(),
    listAudioOverviewPodcasts: vi.fn(),
    getAudioOverviewPodcast: vi.fn(),
    fetchAudioOverviewPodcastAudio: vi.fn(),
    generateAudioOverviewScript: vi.fn(),
    createAudioOverviewPodcast: vi.fn(),
    updateAudioOverviewPodcast: vi.fn(),
    deleteAudioOverviewPodcast: vi.fn(),
    saveAudioOverviewScript: vi.fn(),
    synthesizeAudioOverviewPodcast: vi.fn(),
    updateSettings: vi.fn(),
    streamChatCompletion: vi.fn(),
    transcribeAudio: vi.fn(),
    createTranscriptionJob: vi.fn(),
    createTranscriptionJobFromUrl: vi.fn(),
    fetchTranscriptionJob: vi.fn(),
    createAudioAgentRun: vi.fn(),
    getAudioAgentRun: vi.fn(),
    listAudioAgentRunEvents: vi.fn(),
    listVoiceAgentSessions: vi.fn(),
    fetchVoiceAgentMetricsSummary: vi.fn(),
    fetchVoiceAgentSession: vi.fn(),
    listTavusPals: vi.fn(),
    listTavusFaces: vi.fn(),
    createTavusConversation: vi.fn(),
    endTavusConversation: vi.fn()
  };
});

const dailyMocks = vi.hoisted(() => ({ createCallObject: vi.fn() }));
vi.mock("@daily-co/daily-js", () => ({
  default: { createCallObject: dailyMocks.createCallObject }
}));

function createPalCallMock() {
  return {
    join: vi.fn().mockResolvedValue({}),
    leave: vi.fn().mockResolvedValue(undefined),
    destroy: vi.fn(),
    on: vi.fn(),
    participants: vi.fn(() => ({})),
    startCamera: vi.fn().mockResolvedValue({}),
    enumerateDevices: vi.fn().mockResolvedValue({ devices: [] }),
    setInputDevicesAsync: vi.fn().mockResolvedValue({}),
    setOutputDeviceAsync: vi.fn().mockResolvedValue({}),
    startLocalAudioLevelObserver: vi.fn().mockResolvedValue(undefined),
    stopLocalAudioLevelObserver: vi.fn(),
  };
}

const mockedFetchApiRuntimeInfo = vi.mocked(api.fetchApiRuntimeInfo);
const mockedFetchVoices = vi.mocked(api.fetchVoices);
const mockedFetchSpeakAudio = vi.mocked(api.fetchSpeakAudio);
const mockedFetchSettings = vi.mocked(api.fetchSettings);
const mockedUpdateSettings = vi.mocked(api.updateSettings);
const mockedListCustomVoices = vi.mocked(api.listCustomVoices);
const mockedListAudioOverviewPodcasts = vi.mocked(api.listAudioOverviewPodcasts);
const mockedGetAudioOverviewPodcast = vi.mocked(api.getAudioOverviewPodcast);
const mockedFetchAudioOverviewPodcastAudio = vi.mocked(api.fetchAudioOverviewPodcastAudio);
const mockedStreamChatCompletion = vi.mocked(api.streamChatCompletion);
const mockedTranscribeAudio = vi.mocked(api.transcribeAudio);
const mockedCreateTranscriptionJob = vi.mocked(api.createTranscriptionJob);
const mockedCreateTranscriptionJobFromUrl = vi.mocked(api.createTranscriptionJobFromUrl);
const mockedFetchTranscriptionJob = vi.mocked(api.fetchTranscriptionJob);
const mockedCreateAudioAgentRun = vi.mocked(api.createAudioAgentRun);
const mockedGetAudioAgentRun = vi.mocked(api.getAudioAgentRun);
const mockedListAudioAgentRunEvents = vi.mocked(api.listAudioAgentRunEvents);
const mockedListVoiceAgentSessions = vi.mocked(api.listVoiceAgentSessions);
const mockedFetchVoiceAgentMetricsSummary = vi.mocked(api.fetchVoiceAgentMetricsSummary);
const mockedFetchVoiceAgentSession = vi.mocked(api.fetchVoiceAgentSession);

const mockAgentRunDetail = {
  id: 1,
  podcast_id: 99,
  topic: "新主题",
  language: "zh",
  status: "draft_ready",
  current_step: "persist_draft",
  provider: "DashScope",
  model: "qwen-plus",
  use_memory: true,
  input_payload: {},
  result_payload: {
    provider: "DashScope",
    model: "qwen-plus",
    script_lines: [
      { role: "A", text: "测试生成1" },
      { role: "B", text: "测试生成2" }
    ]
  },
  error_code: "",
  error_message: "",
  created_at: "2026-03-07T10:00:00Z",
  updated_at: "2026-03-07T10:00:00Z",
  completed_at: "2026-03-07T10:00:00Z",
  steps: [],
  sources: []
};

function setClipboardWriteText(writeText: (value: string) => Promise<void>) {
  Object.defineProperty(globalThis.navigator, "clipboard", {
    value: { writeText },
    configurable: true
  });
}

describe("App interactions", () => {
  beforeEach(() => {
    localStorage.clear();
    dailyMocks.createCallObject.mockReset();
    vi.mocked(api.listTavusPals).mockResolvedValue({ pals: [{ pal_id: "mia", pal_name: "Mia" }] });
    vi.mocked(api.listTavusFaces).mockResolvedValue({ faces: [] });
    vi.mocked(api.createTavusConversation).mockReset();
    vi.mocked(api.endTavusConversation).mockReset();
    vi.mocked(api.endTavusConversation).mockResolvedValue(undefined);
    mockedFetchApiRuntimeInfo.mockResolvedValue({
      status: "ok",
      phase: "B",
      auth_mode: "write-only-with-admin-settings",
      auth_enabled: false,
      version: "test",
      raw: {
        name: "Echo",
        status: "ok",
        auth_mode: "write-only-with-admin-settings"
      }
    });
    mockedFetchVoices.mockResolvedValue({
      count: 2,
      voices: [
        {
          name: "zh-CN-XiaoxiaoNeural",
          short_name: "Xiaoxiao",
          locale: "zh-CN",
          gender: "Female"
        },
        {
          name: "zh-CN-YunxiNeural",
          short_name: "Yunxi",
          locale: "zh-CN",
          gender: "Male"
        }
      ]
    });
    mockedFetchSettings.mockResolvedValue({
      config_path: "/tmp/config.json",
      providers: ["DashScope", "Google", "Xiaomi"],
      settings: {
        api_keys: { dashscope_api_key: "", xiaomi_api_key: "" },
        api_urls: { DashScope: "", Xiaomi: "" },
        default_models: {
          DashScope: { default: "qwen-plus", available: ["qwen-plus"] },
          Xiaomi: { default: "mimo-v2.5-pro", available: ["mimo-v2.5-pro", "mimo-v2.5"] }
        },
        general_settings: {},
        memory_settings: {},
        output_directory: "/tmp",
        tts_settings: {},
        qwen_tts_settings: {},
        transcription_settings: {},
        minimax: {},
        xiaomi: { api_key: "", api_url: "" },
        ui_settings: {},
        shortcuts: {}
      }
    });
    mockedListCustomVoices.mockResolvedValue({
      voice_type: "voice_design",
      count: 0,
      voices: []
    });
    mockedFetchSpeakAudio.mockResolvedValue({
      blob: new Blob(["tts"], { type: "audio/mpeg" }),
      memorySaved: true
    });
    mockedTranscribeAudio.mockResolvedValue({
      transcript: "同步转写结果",
      memory_saved: true
    });
    mockedCreateTranscriptionJob.mockResolvedValue({
      job_id: "tx_local_001",
      mode: "async",
      status: "uploaded",
      file_name: "meeting.wav",
      error: "Use /api/transcription/jobs/from-url for true DashScope async transcription.",
      memory_saved: false
    });
    mockedCreateTranscriptionJobFromUrl.mockResolvedValue({
      job_id: "tx_url_001",
      remote_job_id: "remote-url-job-001",
      mode: "async",
      status: "submitted",
      file_name: "demo.wav",
      memory_saved: false
    });
    mockedFetchTranscriptionJob.mockResolvedValue({
      job_id: "tx_url_001",
      remote_job_id: "remote-url-job-001",
      mode: "async",
      status: "completed",
      file_name: "demo.wav",
      transcript: "异步转写完成",
      memory_saved: true
    });
    mockedStreamChatCompletion.mockImplementation(async (_payload, handlers) => {
      handlers.onDelta("这是助手的回复。");
      handlers.onDone?.({ memoriesRetrieved: 2, memorySaved: true });
    });
    mockedListAudioOverviewPodcasts.mockResolvedValue({
      count: 1,
      podcasts: [
        {
          id: 12,
          topic: "AI 与未来交通",
          language: "zh",
          audio_path: "/tmp/podcast.mp3",
          created_at: "2026-03-07T10:00:00Z",
          updated_at: "2026-03-07T10:00:00Z",
          script_lines: [
            { role: "A", text: "第一段内容" },
            { role: "B", text: "第二段内容" }
          ]
        }
      ]
    });
    mockedGetAudioOverviewPodcast.mockResolvedValue({
      id: 12,
      topic: "AI 与未来交通",
      language: "zh",
      audio_path: "/tmp/podcast.mp3",
      created_at: "2026-03-07T10:00:00Z",
      updated_at: "2026-03-07T10:00:00Z",
      script_lines: [
        { role: "A", text: "第一段内容" },
        { role: "B", text: "第二段内容" }
      ]
    });
    mockedFetchAudioOverviewPodcastAudio.mockResolvedValue(
      new Blob(["audio"], { type: "audio/mpeg" })
    );
    mockedCreateAudioAgentRun.mockResolvedValue(mockAgentRunDetail);
    mockedGetAudioAgentRun.mockResolvedValue(mockAgentRunDetail);
    mockedListAudioAgentRunEvents.mockResolvedValue({
      count: 0,
      events: []
    });
    mockedListVoiceAgentSessions.mockResolvedValue({
      count: 1,
      sessions: [{
        id: "voice-session-1",
        provider: "OpenAI",
        model: "gpt-realtime",
        voice: "alloy",
        status: "closed",
        started_at: "2026-07-12T10:00:00Z"
      }]
    });
    const emptyDistribution = { count: 0, avg: null, p50: null, p95: null, min: null, max: null };
    mockedFetchVoiceAgentMetricsSummary.mockResolvedValue({
      provider: "all",
      session_count: 1,
      turn_count: 1,
      completed_turn_count: 1,
      interrupted_turn_count: 0,
      decision_count: 0,
      classifications: {},
      false_interruption_rate: null,
      first_audio_ms: emptyDistribution,
      interruption_decision_ms: emptyDistribution,
      interruption_stop_ms: emptyDistribution,
      turn_completion_ms: emptyDistribution,
      providers: []
    });
    mockedFetchVoiceAgentSession.mockResolvedValue({
      id: "voice-session-1",
      provider: "OpenAI",
      model: "gpt-realtime",
      voice: "alloy",
      status: "closed",
      started_at: "2026-07-12T10:00:00Z",
      turns: [],
      tool_events: [],
      timeline: [],
      agent_run_links: [{
        id: 1,
        agent_run_id: "audio_agent:1",
        voice_session_id: "voice-session-1",
        voice_turn_id: "voice-turn-1",
        relation_type: "created_by",
        created_at: "2026-07-12T10:00:01Z",
        run: {
          id: "audio_agent:1",
          run_type: "audio_agent",
          source_kind: "audio_agent",
          source_run_id: "1",
          title: "新主题",
          status: "draft_ready",
          current_step: "persist_draft",
          provider: "DashScope",
          model: "qwen-plus",
          created_at: "2026-07-12T10:00:01Z",
          updated_at: "2026-07-12T10:00:02Z"
        }
      }]
    });

    Object.defineProperty(globalThis.URL, "createObjectURL", {
      value: vi.fn(() => "blob:test-url"),
      configurable: true
    });
    Object.defineProperty(globalThis.URL, "revokeObjectURL", {
      value: vi.fn(),
      configurable: true
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("sends a quick chat prompt and renders the streamed reply", async () => {
    render(<App />);

    // The first mount loads ChatPage's lazy module. Windows packaging CI can
    // exceed Testing Library's 1s default while other workers compile modules.
    // The test's outer timeout must also allow this 10s load plus assertions.
    const textarea = await screen.findByPlaceholderText(/输入聊天内容/, {}, { timeout: 10000 });
    fireEvent.change(textarea, { target: { value: "请帮我起草一封语气专业但不生硬的项目进度更新邮件。" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(mockedStreamChatCompletion).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "DashScope",
          model: "qwen-plus",
          messages: [
            {
              role: "user",
              content: "请帮我起草一封语气专业但不生硬的项目进度更新邮件。"
            }
          ]
        }),
        expect.any(Object),
        expect.any(Object)
      );
    });
    expect(await screen.findByText("这是助手的回复。")).toBeInTheDocument();

    // EverMem UI Badges verification
    expect(await screen.findByText("✓ 已记忆")).toBeInTheDocument();
    expect(await screen.findByText(/🧠 回忆了 2 条/)).toBeInTheDocument();
  }, 15000);

  it("archives the previous conversation into the sidebar and restores it on click", async () => {
    render(<App />);

    const textarea = await screen.findByPlaceholderText(/输入聊天内容/);
    fireEvent.change(textarea, { target: { value: "请帮我起草一封语气专业但不生硬的项目进度更新邮件。" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(screen.getByText("这是助手的回复。")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "新建对话" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "更多操作" })).toBeInTheDocument();
      expect(screen.getByText(/请帮我起草一封语气专业但不生硬的项目进度更新/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/请帮我起草一封语气专业但不生硬的项目进度更新/));

    await waitFor(() => {
      expect(screen.getByText("这是助手的回复。")).toBeInTheDocument();
    });
  });

  it("automatically saves the active conversation into the sidebar history", async () => {
    render(<App />);

    const textarea = await screen.findByPlaceholderText(/输入聊天内容/);
    fireEvent.change(textarea, { target: { value: "请帮我起草一封语气专业但不生硬的项目进度更新邮件。" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(screen.getByText("这是助手的回复。")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "更多操作" })).toBeInTheDocument();
      expect(
        Array.from(document.querySelectorAll(".vsHistoryText")).some((item) =>
          item.textContent?.includes("请帮我起草一封语气专业但不生硬的项目进度更新")
        )
      ).toBe(true);
    });
  });

  it("preserves chat and separate PAL calls across navigation, autosave, and reload", async () => {
    const calls = [createPalCallMock(), createPalCallMock(), createPalCallMock()];
    for (let index = 0; index < calls.length; index += 1) {
      dailyMocks.createCallObject.mockReturnValueOnce(calls[index]);
      vi.mocked(api.createTavusConversation).mockResolvedValueOnce({
        conversation_id: `pal-call-${index}`, conversation_url: `https://tavus.daily.co/call-${index}`,
      });
    }
    const readHistory = () => JSON.parse(localStorage.getItem("vs_conversation_history") || "[]") as Array<{
      id: string;
      content: string;
      chatMessages: api.ChatMessage[];
      voiceMessages: api.ChatMessage[];
    }>;
    const settingsResponse = await mockedFetchSettings();
    mockedFetchSettings.mockResolvedValue({ ...settingsResponse, providers: [...settingsResponse.providers, "Tavus"] });
    const { unmount } = render(<App />);
    const textarea = await screen.findByPlaceholderText(/输入聊天内容/, {}, { timeout: 10000 });
    fireEvent.change(textarea, { target: { value: "Keep this chat" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(readHistory()).toHaveLength(1));
    const originalChatId = readHistory()[0].id;
    fireEvent.click(screen.getByTitle("通话设置"));
    fireEvent.mouseEnter(screen.getByText("Tavus"));
    fireEvent.click(screen.getByText("打开视频分身"));
    await waitFor(() => expect(screen.getByTestId("pal-select")).toHaveValue("mia"));

    for (let index = 0; index < calls.length; index += 1) {
      fireEvent.click(await screen.findByTestId("pal-start-button"));
      fireEvent.click(await screen.findByTestId("pal-join-button"));
      await screen.findByTestId("pal-leave-button");
      const incoming = calls[index].on.mock.calls.find(([name]) => name === "app-message")?.[1];
      expect(incoming).toBeDefined();
      act(() => {
        incoming?.({ data: {
          event_type: "conversation.utterance.streaming", properties: { role: "user", text: "Same opening phrase" },
        } });
        incoming?.({ data: {
          event_type: "conversation.utterance.streaming", properties: { role: "pal", text: "Same final reply" },
        } });
        // Two calls have identical content; distinct calls must still survive.
        if (index < 2) fireEvent.click(screen.getByTestId("pal-leave-button"));
        else fireEvent.click(screen.getByTestId("nav-tts"));
      });
      await waitFor(() => expect(readHistory()).toHaveLength(index + 2));
      if (index < 2) fireEvent.click(screen.getByTestId("pal-dismiss-summary-button"));
    }
    expect(vi.mocked(api.endTavusConversation)).toHaveBeenCalledWith("pal-call-2");
    expect(readHistory().find((entry) => entry.id === originalChatId)?.chatMessages[0].content).toBe("Keep this chat");
    expect(new Set(readHistory().map((entry) => entry.id)).size).toBe(4);
    const historyChat = Array.from(document.querySelectorAll(".vsHistoryText"))
      .find((item) => item.textContent === "Keep this chat");
    expect(historyChat).toBeDefined();
    fireEvent.click(historyChat!);
    fireEvent.click(await screen.findByRole("button", { name: "新建对话" }));
    expect(readHistory()).toHaveLength(4);
    expect(readHistory().find((entry) => entry.id === originalChatId)?.chatMessages[0].content).toBe("Keep this chat");
    const palHistory = Array.from(document.querySelectorAll(".vsHistoryText"))
      .find((item) => item.textContent === "[视频 Mia] Same opening phrase");
    expect(palHistory).toBeDefined();
    fireEvent.click(palHistory!);
    // Restoring a PAL archive must not strip its call identity during autosave.
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 550)); });
    expect(readHistory()).toHaveLength(4);
    expect(readHistory().filter((entry) => entry.id !== originalChatId).map((entry) => entry.content))
      .toEqual(Array(3).fill("[视频 Mia] Same opening phrase"));
    unmount();
    render(<App />);
    expect(document.querySelectorAll(".vsHistoryRow")).toHaveLength(4);
  }, 15000);

  it.each(["[视频 Mia] Meeting", "[Video Mia] Meeting"])(
    "keeps legacy video title %s after restoring, renaming, and deleting", async (content) => {
      const legacy = {
        id: "legacy-pal", content, chatMessages: [],
        voiceMessages: [{ role: "user", content: "Meeting" }, { role: "assistant", content: "Last reply" }],
        chatGroupId: "", voiceGroupId: "", updatedAt: 1,
      };
      const textChat = {
        id: "other-chat", content: "Other chat", chatMessages: [{ role: "user", content: "Other chat" }],
        voiceMessages: [], chatGroupId: "", voiceGroupId: "", updatedAt: 2,
      };
      localStorage.setItem("vs_conversation_history", JSON.stringify([legacy, textChat]));
      const readHistory = () => JSON.parse(localStorage.getItem("vs_conversation_history") || "[]") as Array<{
        id: string; content: string; kind?: string; titleCustomized?: boolean;
      }>;
      render(<App />);
      await screen.findByPlaceholderText(/输入聊天内容/, {}, { timeout: 10000 });
      fireEvent.click(screen.getByText(content));
      // New session flushes the restored messages synchronously before clearing them.
      fireEvent.click(screen.getByRole("button", { name: "新建对话" }));
      expect(readHistory().find((entry) => entry.id === legacy.id))
        .toMatchObject({ content, kind: "video" });
      fireEvent.click(screen.getByText(content));
      fireEvent.click(screen.getByTestId(`history-more-${legacy.id}`));
      fireEvent.click(screen.getByRole("menuitem", { name: /重命名/ }));
      const renameInput = screen.getByDisplayValue(content);
      fireEvent.change(renameInput, { target: { value: "My video meeting" } });
      fireEvent.keyDown(renameInput, { key: "Enter" });
      fireEvent.click(screen.getByText("Other chat"));
      expect(readHistory().find((entry) => entry.id === legacy.id))
        .toMatchObject({ content: "My video meeting", kind: "video", titleCustomized: true });
      fireEvent.click(screen.getByText("My video meeting"));
      fireEvent.click(screen.getByTestId(`history-more-${legacy.id}`));
      fireEvent.click(screen.getByRole("menuitem", { name: /删除历史/ }));
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 550)); });
      fireEvent.click(screen.getByRole("button", { name: "新建对话" }));
      expect(readHistory().find((entry) => entry.id === legacy.id)).toBeUndefined();
      expect(readHistory()).toHaveLength(1);
    },
  );

  it("does not duplicate a restored conversation when starting a new chat", async () => {
    render(<App />);

    const textarea = await screen.findByPlaceholderText(/输入聊天内容/);
    fireEvent.change(textarea, { target: { value: "请帮我起草一封语气专业但不生硬的项目进度更新邮件。" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(screen.getByText("这是助手的回复。")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "新建对话" }));

    const historyItem = await screen.findByText(/请帮我起草一封语气专业但不生硬的项目进度更新/);
    fireEvent.click(historyItem);
    fireEvent.click(screen.getByRole("button", { name: "新建对话" }));

    await waitFor(() => {
      const rows = document.querySelectorAll(".vsHistoryRow");
      expect(rows).toHaveLength(1);
    });
  });

  it("deletes a single archived conversation from the sidebar", async () => {
    render(<App />);

    const textarea = await screen.findByPlaceholderText(/输入聊天内容/);
    fireEvent.change(textarea, { target: { value: "请帮我起草一封语气专业但不生硬的项目进度更新邮件。" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(screen.getByText("这是助手的回复。")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "新建对话" }));

    // ChatGPT-style: open ⋯ menu first, then choose Delete
    const moreButton = await screen.findByRole("button", { name: "更多操作" });
    fireEvent.click(moreButton);

    const deleteButton = await screen.findByRole("menuitem", {
      name: /删除历史 请帮我起草一封语气专业但不生硬的项目进度更新/,
    });
    fireEvent.click(deleteButton);

    await waitFor(() => {
      expect(screen.queryByText(/请帮我起草一封语气专业但不生硬的项目进度更新/)).not.toBeInTheDocument();
    });
  });

  it("generates TTS audio preview from the current text", async () => {
    render(<App />);

    const ttsBtn = screen.getByTestId("nav-tts");
    fireEvent.click(ttsBtn);
    fireEvent.click(await screen.findByRole("button", { name: "生成音频" }));

    await waitFor(() => {
      expect(mockedFetchSpeakAudio).toHaveBeenCalledWith(
        expect.objectContaining({
          text: "你好，这是 Echo 的语音测试。",
          rate: "+0%"
        })
      );
    });
    expect(await screen.findByRole("button", { name: "导出音频" })).toBeInTheDocument();
    expect(screen.getByText("已将本次语音生成偏好写入长期记忆。")).toBeInTheDocument();
    expect(document.querySelector("audio")).toHaveAttribute("src", "blob:test-url");
  });

  it("transcribes a local audio file from the transcription center", async () => {
    render(<App />);

    const transcribeBtn = screen.getByTestId("nav-transcription");
    fireEvent.click(transcribeBtn);

    // Open the new transcription modal
    fireEvent.click(await screen.findByRole("button", { name: /新建转写/ }));

    const fileInput = screen.getByLabelText("选择转写音频或视频");
    const audioFile = new File(["audio"], "note.wav", { type: "audio/wav" });
    fireEvent.change(fileInput, { target: { files: [audioFile] } });
    fireEvent.click(screen.getByRole("button", { name: "开始转写" }));

    await waitFor(() => {
      expect(mockedTranscribeAudio.mock.calls[0][0]).toBe(audioFile);
    });
    expect(await screen.findByText("同步转写结果")).toBeInTheDocument();
    expect(screen.getByText("转写完成。")).toBeInTheDocument();
  });

  it("reveals and copies backend runtime details", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboardWriteText(writeText);

    render(<App />);

    const settingsBtn = screen.getByTestId("nav-settings");
    fireEvent.click(settingsBtn);
    fireEvent.click(await screen.findByRole("button", { name: /^系统$/ }));
    fireEvent.click(screen.getByRole("button", { name: "显示系统运行时日志" }));

    await waitFor(() => {
      const runtimeDetails = document.querySelector("pre.runtimeDetails");
      expect(runtimeDetails).not.toBeNull();
      expect(runtimeDetails?.textContent).toContain('"name": "Echo"');
    });

    fireEvent.click(screen.getByRole("button", { name: "复制运行时信息" }));

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        JSON.stringify(
          {
            name: "Echo",
            status: "ok",
            auth_mode: "write-only-with-admin-settings"
          },
          null,
          2
        )
      );
    });
    expect(screen.getByRole("button", { name: "已复制到剪贴板！" })).toBeInTheDocument();
  });

  it("loads a podcast and reveals the script editor and synth bar", async () => {
    render(<App />);

    const podcastBtn1 = screen.getByTestId("nav-audio_overview");
    fireEvent.click(podcastBtn1);
    expect(await screen.findByRole("searchbox", { name: "搜索播客" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "编辑播客脚本" })).not.toBeInTheDocument();

    fireEvent.click(await screen.findByText("AI 与未来交通"));

    await waitFor(() => {
      expect(screen.getByText("已载入播客 #12。")).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "编辑播客脚本" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("第一段内容")).toBeInTheDocument();
    expect(screen.getByDisplayValue("第二段内容")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /合成/ })).toBeInTheDocument();
  });

  it("copies the loaded podcast script to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboardWriteText(writeText);

    render(<App />);

    const podcastBtn2 = screen.getByTestId("nav-audio_overview");
    fireEvent.click(podcastBtn2);
    fireEvent.click(await screen.findByText("AI 与未来交通"));

    await waitFor(() => {
      expect(screen.getByText("已载入播客 #12。")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /复制脚本/i }));

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("1. 主播 A：第一段内容\n\n2. 主播 B：第二段内容");
    });
    expect(screen.getByText("脚本已复制到剪贴板。")).toBeInTheDocument();
  });

  it("exports the loaded podcast script as a text file", async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => { });

    render(<App />);

    const podcastBtn3 = screen.getByTestId("nav-audio_overview");
    fireEvent.click(podcastBtn3);
    fireEvent.click(await screen.findByText("AI 与未来交通"));

    await waitFor(() => {
      expect(screen.getByText("已载入播客 #12。")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /导出脚本/i }));

    expect(clickSpy).toHaveBeenCalled();
    expect(screen.getByText("脚本已导出为文本文件。")).toBeInTheDocument();
  });
  it("saves settings and shows success message", async () => {
    mockedFetchSettings.mockResolvedValue({
      config_path: "/tmp/config.json",
      providers: ["DashScope", "Google"],
      settings: {
        api_keys: { dashscope_api_key: "" },
        api_urls: { DashScope: "" },
        default_models: { DashScope: { default: "qwen-plus", available: ["qwen-plus", "qwen-max"] } },
        general_settings: {},
        memory_settings: {},
        output_directory: "/tmp",
        tts_settings: {},
        qwen_tts_settings: {},
        transcription_settings: {},
        minimax: {},
        xiaomi: { api_key: "", api_url: "" },
        ui_settings: {},
        shortcuts: {}
      }
    });

    mockedUpdateSettings.mockResolvedValue({
      config_path: "/tmp/config.json",
      providers: ["DashScope", "Google"],
      settings: {
        api_keys: { dashscope_api_key: "new-key" },
        api_urls: { DashScope: "" },
        default_models: { DashScope: { default: "qwen-max", available: ["qwen-plus", "qwen-max"] } },
        general_settings: {},
        memory_settings: {},
        output_directory: "/tmp",
        tts_settings: {},
        qwen_tts_settings: {},
        transcription_settings: {},
        minimax: {},
        xiaomi: { api_key: "", api_url: "" },
        ui_settings: {},
        shortcuts: {}
      }
    });

    render(<App />);
    const settingsBtn2 = screen.getByTestId("nav-settings");
    fireEvent.click(settingsBtn2);

    await screen.findByDisplayValue("qwen-plus");

    const apiKeyInput = screen.getByPlaceholderText("输入供应商 API Key");
    fireEvent.change(apiKeyInput, { target: { value: "new-key" } });

    const modelSelect = screen.getByLabelText("默认主模型");
    fireEvent.change(modelSelect, { target: { value: "qwen-max" } });

    fireEvent.click(screen.getByRole("button", { name: /^转写$/ }));

    const publicBaseUrlInput = screen.getByPlaceholderText("https://files.example.com");
    fireEvent.change(publicBaseUrlInput, {
      target: { value: "https://cdn.example.com/transcription" }
    });
    fireEvent.change(screen.getByTestId("transcription-upload-mode"), {
      target: { value: "s3" }
    });
    fireEvent.change(screen.getByPlaceholderText("例如: echo-assets"), {
      target: { value: "echo-assets" }
    });
    fireEvent.change(screen.getByPlaceholderText("例如: us-east-1"), {
      target: { value: "us-east-1" }
    });
    fireEvent.change(screen.getByPlaceholderText("例如: https://s3.example.com"), {
      target: { value: "https://s3.example.com" }
    });
    fireEvent.change(screen.getByPlaceholderText("例如: voice-jobs/"), {
      target: { value: "voice-jobs" }
    });
    fireEvent.change(screen.getByPlaceholderText("输入 Access Key ID"), {
      target: { value: "key-id" }
    });
    fireEvent.change(screen.getByPlaceholderText("输入 Secret Access Key"), {
      target: { value: "secret" }
    });
    const saveButton = screen.getByRole("button", { name: "保存" });
    const settingsForm = saveButton.closest("form");
    expect(settingsForm).not.toBeNull();
    fireEvent.submit(settingsForm!);

    await waitFor(() => {
      expect(mockedUpdateSettings).toHaveBeenCalled();
    });

    expect(mockedUpdateSettings).toHaveBeenLastCalledWith(
      expect.objectContaining({
        api_keys: { dashscope_api_key: "new-key" },
        default_models: expect.objectContaining({
          DashScope: expect.objectContaining({
            default: "qwen-max"
          })
        })
      })
    );

    expect(await screen.findByText("设置已保存。")).toBeInTheDocument();
  });

  it("generates an audio overview script", async () => {
    localStorage.setItem("evermem_enabled", "true");
    localStorage.setItem("evermem_url", "https://api.evermind.ai");
    mockedCreateAudioAgentRun.mockResolvedValue(mockAgentRunDetail);
    mockedGetAudioAgentRun.mockResolvedValue(mockAgentRunDetail);
    mockedListAudioAgentRunEvents.mockResolvedValue({
      count: 0,
      events: []
    });
    mockedGetAudioOverviewPodcast.mockResolvedValue({
      id: 99,
      topic: "新主题",
      language: "zh",
      audio_path: "",
      script_lines: [
        { role: "A", text: "测试生成1" },
        { role: "B", text: "测试生成2" }
      ],
      created_at: "2026-03-07T10:00:00Z",
      updated_at: "2026-03-07T10:00:00Z"
    });

    render(<App />);
    const podcastBtn4 = screen.getByTestId("nav-audio_overview");
    fireEvent.click(podcastBtn4);

    fireEvent.click(screen.getByRole("button", { name: /新建播客/ }));
    fireEvent.click(screen.getByRole("button", { name: "设置与参考资料" }));
    expect(screen.getByLabelText(/使用 EverMem 长期记忆辅助脚本生成/)).toBeChecked();

    const topicInput = screen.getByPlaceholderText("输入你想讨论的话题，例如：AI 如何改变个人学习习惯？");
    fireEvent.change(topicInput, { target: { value: "新主题" } });

    fireEvent.click(screen.getByRole("button", { name: "生成脚本" }));

    await waitFor(() => {
      expect(mockedCreateAudioAgentRun).toHaveBeenCalledWith(
        expect.objectContaining({
          topic: "新主题",
          use_memory: true
        })
      );
    });

    expect(
      await screen.findByText("Agent 已完成检索与写稿，并保存为播客 #99。")
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("测试生成1")).toBeInTheDocument();
  });
});
