import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import useAudioOverview from "./useAudioOverview";
import { createFormatErrorMessageStub } from "../test/factories";
import {
  createAudioAgentRun,
  createAudioOverviewPodcast,
  fetchAudioOverviewPodcastAudio,
  getAudioAgentRun,
  getAudioOverviewPodcast,
  listAudioAgentRunEvents,
  listAudioOverviewPodcasts,
  synthesizeAudioOverviewPodcast
} from "../api";

vi.mock("../api", () => ({
  createAudioAgentRun: vi.fn(),
  createAudioOverviewPodcast: vi.fn(),
  deleteAudioOverviewPodcast: vi.fn(),
  executeAudioAgentRun: vi.fn(),
  fetchAudioOverviewPodcastAudio: vi.fn(),
  fetchVoices: vi.fn().mockResolvedValue({ voices: [] }),
  generateAudioOverviewScript: vi.fn(),
  getAudioAgentRun: vi.fn(),
  getEverMemRuntimeConfig: vi.fn(() => ({ enabled: false })),
  getAudioOverviewPodcast: vi.fn(),
  listAudioAgentRunEvents: vi.fn(),
  listCustomVoices: vi.fn().mockResolvedValue({ voices: [] }),
  listAudioOverviewPodcasts: vi.fn().mockResolvedValue({ podcasts: [] }),
  saveAudioOverviewScript: vi.fn(),
  synthesizeAudioAgentRun: vi.fn(),
  synthesizeAudioOverviewPodcast: vi.fn(),
  updateAudioOverviewPodcast: vi.fn()
}));

describe("useAudioOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAudioOverviewPodcasts).mockResolvedValue({ count: 0, podcasts: [] });
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: {
        writeText: vi.fn().mockResolvedValue(undefined)
      },
      configurable: true
    });
  });

  it("switches workspace mode to multi-dialogue", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const voices = [
      { name: "voice-a", short_name: "A", locale: "zh-CN", gender: "Male" },
      { name: "voice-b", short_name: "B", locale: "zh-CN", gender: "Female" }
    ];

    const { result } = renderHook(() =>
      useAudioOverview({ voices, formatErrorMessage })
    );

    await act(async () => {
      result.current.onWorkspaceModeChange("multi_dialogue");
    });

    expect(result.current.audioOverviewWorkspaceMode).toBe("multi_dialogue");
    expect(result.current.audioOverviewWorkspaceTitle).toBe("多人对话工作台");
    expect(result.current.audioOverviewWorkspaceDescription).toContain("角色讨论");
  });

  it("copies exported script using custom speaker labels", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const voices = [
      { name: "voice-a", short_name: "A", locale: "zh-CN", gender: "Male" },
      { name: "voice-b", short_name: "B", locale: "zh-CN", gender: "Female" }
    ];

    const { result } = renderHook(() =>
      useAudioOverview({ voices, formatErrorMessage })
    );

    act(() => {
      result.current.onSpeakerAChange("主持人晨");
      result.current.onSpeakerBChange("主持人林");
      result.current.onAddLine();
      result.current.onLineTextChange(0, "今天我们聊聊记忆系统。");
      result.current.onAddLine();
      result.current.onLineRoleChange(1, "B");
      result.current.onLineTextChange(1, "那就从长期记忆如何融入工作流开始。");
    });

    await act(async () => {
      await result.current.onCopyScript();
    });

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining("主持人晨")
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining("主持人林")
    );
  });

  it("passes research inputs to the audio agent and syncs the draft podcast", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const run = {
      id: 22,
      podcast_id: 44,
      topic: "AI research",
      language: "zh",
      status: "draft_ready",
      current_step: "persist_draft",
      provider: "DashScope",
      model: "qwen-plus",
      use_memory: false,
      input_payload: {},
      result_payload: {
        provider: "DashScope",
        model: "qwen-plus",
        research_brief: "Source mix: web_search=1"
      },
      error_code: "",
      error_message: "",
      created_at: "",
      updated_at: "",
      completed_at: "",
      steps: [],
      sources: [],
    };
    vi.mocked(createAudioAgentRun).mockResolvedValue(run);
    vi.mocked(getAudioAgentRun).mockResolvedValue(run);
    vi.mocked(listAudioAgentRunEvents).mockResolvedValue({ count: 0, events: [] });
    vi.mocked(getAudioOverviewPodcast).mockResolvedValue({
      id: 44,
      topic: "AI research",
      language: "zh",
      audio_path: null,
      created_at: "",
      updated_at: "",
      script_lines: [
        { role: "A", text: "开场" },
        { role: "B", text: "分析" }
      ]
    });

    const { result } = renderHook(() =>
      useAudioOverview({ voices: [], formatErrorMessage })
    );

    act(() => {
      result.current.onTopicChange("AI research");
      result.current.onSourceTextChange("manual notes");
      result.current.onSourceUrlsTextChange("https://example.com/a\n\nhttps://example.com/b");
      result.current.onGenerationConstraintsChange("cite sources");
      result.current.onTurnCountChange("6");
    });

    await act(async () => {
      await result.current.onGenerateScript({ preventDefault() {} } as any);
    });

    expect(createAudioAgentRun).toHaveBeenCalledWith(
      expect.objectContaining({
        topic: "AI research",
        source_text: "manual notes",
        source_urls: ["https://example.com/a", "https://example.com/b"],
        generation_constraints: "cite sources",
        turn_count: 6,
        auto_execute: true
      })
    );
    expect(result.current.audioOverviewPodcastId).toBe(44);
    expect(result.current.audioOverviewScriptLines).toHaveLength(2);
    expect(result.current.audioAgentStatus).toBe("draft_ready");
  });

  it("surfaces failed agent runs and enables retry", async () => {
    const formatErrorMessage = (error: unknown, fallback: string) =>
      error instanceof Error ? `${fallback} ${error.message}` : fallback;
    const queued = {
      id: 23,
      podcast_id: null,
      topic: "AI research",
      language: "zh",
      status: "queued",
      current_step: "retrieve",
      provider: "DashScope",
      model: "",
      use_memory: false,
      input_payload: {},
      result_payload: {},
      error_code: "",
      error_message: "",
      created_at: "",
      updated_at: "",
      completed_at: "",
      steps: [],
      sources: [],
    };
    const failed = {
      ...queued,
      status: "failed",
      error_code: "AUDIO_AGENT_EXECUTION_PROVIDER_ERROR",
      error_message: "Provider failed"
    };
    vi.mocked(createAudioAgentRun).mockResolvedValue(queued);
    vi.mocked(getAudioAgentRun).mockResolvedValue(failed);
    vi.mocked(listAudioAgentRunEvents).mockResolvedValue({ count: 0, events: [] });

    const { result } = renderHook(() =>
      useAudioOverview({ voices: [], formatErrorMessage })
    );

    act(() => {
      result.current.onTopicChange("AI research");
    });

    await act(async () => {
      await result.current.onGenerateScript({ preventDefault() {} } as any);
    });

    expect(result.current.audioAgentStatus).toBe("failed");
    expect(result.current.audioAgentCanRetry).toBe(true);
    expect(result.current.audioOverviewError).toContain("Provider failed");
  });

  it("passes intro music settings when synthesizing a podcast", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    vi.mocked(createAudioOverviewPodcast).mockResolvedValue({
      id: 55,
      topic: "AI research",
      language: "zh",
      audio_path: null,
      created_at: "",
      updated_at: "",
      script_lines: [
        { role: "A", text: "开场" },
        { role: "B", text: "分析" }
      ]
    });
    vi.mocked(synthesizeAudioOverviewPodcast).mockResolvedValue({
      podcast_id: 55,
      audio_path: "podcast.mp3",
      audio_download_url: "/api/audio-overview/podcasts/55/audio",
      line_count: 2,
      voice_a: "voice-a",
      voice_b: "voice-b",
      rate: "+0%",
      cache_hits: 0,
      gap_ms: 250,
      gap_ms_applied: 250,
      merge_strategy: "pydub",
      intro_music: true,
      intro_music_style: "bright",
      intro_music_duration_ms: 3200
    });
    vi.mocked(fetchAudioOverviewPodcastAudio).mockResolvedValue(
      new Blob(["audio"], { type: "audio/mpeg" })
    );

    const { result } = renderHook(() =>
      useAudioOverview({ voices: [], formatErrorMessage })
    );

    act(() => {
      result.current.onTopicChange("AI research");
      result.current.onAddLine();
      result.current.onLineTextChange(0, "开场");
      result.current.onAddLine();
      result.current.onLineRoleChange(1, "B");
      result.current.onLineTextChange(1, "分析");
      result.current.onIntroMusicChange(true);
      result.current.onIntroMusicStyleChange("bright");
      result.current.onIntroMusicDurationChange("3200");
    });

    await act(async () => {
      await result.current.onSynthesize();
    });

    expect(synthesizeAudioOverviewPodcast).toHaveBeenCalledWith(
      55,
      expect.objectContaining({
        intro_music: true,
        intro_music_style: "bright",
        intro_music_duration_ms: 3200
      })
    );
    expect(result.current.audioOverviewInfo).toContain("bright/3200ms");
  });
});
