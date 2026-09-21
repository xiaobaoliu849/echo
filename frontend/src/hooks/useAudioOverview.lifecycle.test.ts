import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FormEvent } from "react";
import * as api from "../api";
import useAudioOverview from "./useAudioOverview";

vi.mock("../api", () => ({
  createAudioAgentRun: vi.fn(), executeAudioAgentRun: vi.fn(),
  getAudioAgentRun: vi.fn(), listAudioAgentRunEvents: vi.fn(), listAudioAgentRuns: vi.fn(),
  createAudioOverviewPodcast: vi.fn(), updateAudioOverviewPodcast: vi.fn(), saveAudioOverviewScript: vi.fn(),
  deleteAudioOverviewPodcast: vi.fn(), fetchAudioOverviewPodcastAudio: vi.fn(),
  getAudioOverviewPodcast: vi.fn(), listAudioOverviewPodcasts: vi.fn(),
  synthesizeAudioAgentRun: vi.fn(), synthesizeAudioOverviewPodcast: vi.fn(),
  getEverMemRuntimeConfig: vi.fn(), fetchVoices: vi.fn(), listCustomVoices: vi.fn(),
}));

const options = { voices: [], formatErrorMessage: (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback };
const submit = { preventDefault() {} } as FormEvent;
const podcast = (id = 1): api.AudioOverviewPodcast => ({
  id, topic: `Podcast ${id}`, language: "en", audio_path: null,
  created_at: "2026-09-21", updated_at: "2026-09-21",
  script_lines: [{ role: "A", text: "Hello" }, { role: "B", text: "World" }],
});
const run = (status = "draft_ready"): api.AudioAgentRunDetail => ({
  id: 10, podcast_id: 1, topic: "Agent topic", language: "en", status,
  current_step: "persist_draft", provider: "DashScope", model: "qwen-plus", use_memory: false,
  input_payload: {}, result_payload: {}, error_code: "", error_message: "",
  created_at: "", updated_at: "", completed_at: "", steps: [], sources: [],
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchVoices).mockResolvedValue({ count: 0, voices: [] });
  vi.mocked(api.listCustomVoices).mockImplementation(async voice_type => ({ voice_type, count: 0, voices: [] }));
  vi.mocked(api.getEverMemRuntimeConfig).mockReturnValue({ enabled: false } as ReturnType<typeof api.getEverMemRuntimeConfig>);
  vi.mocked(api.listAudioOverviewPodcasts).mockResolvedValue({ count: 0, podcasts: [] });
  vi.mocked(api.listAudioAgentRunEvents).mockResolvedValue({ count: 0, events: [] });
  vi.mocked(api.getAudioOverviewPodcast).mockImplementation(async id => podcast(id));
  vi.mocked(api.createAudioOverviewPodcast).mockResolvedValue(podcast());
  vi.mocked(api.updateAudioOverviewPodcast).mockResolvedValue(podcast());
  vi.mocked(api.saveAudioOverviewScript).mockResolvedValue(podcast());
  vi.mocked(api.createAudioAgentRun).mockResolvedValue(run());
  vi.mocked(api.getAudioAgentRun).mockResolvedValue(run());
  vi.mocked(api.fetchAudioOverviewPodcastAudio).mockResolvedValue(new Blob(["audio"]));
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:audio") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
});

describe("podcast workspace lifecycle", () => {
  it.each(["success", "failure"])("ignores a late podcast %s after opening a new draft", async outcome => {
    const detail = deferred<api.AudioOverviewPodcast>();
    vi.mocked(api.getAudioOverviewPodcast).mockReturnValue(detail.promise);
    const { result } = renderHook(() => useAudioOverview(options));
    let pending!: Promise<void>;
    act(() => { pending = result.current.onLoadPodcast(1); });
    act(() => { result.current.onNewDraft(); result.current.onTopicChange("New topic"); });
    await act(async () => {
      if (outcome === "success") detail.resolve(podcast());
      else detail.reject(new Error("Obsolete failure"));
      await pending;
    });
    expect(result.current.audioOverviewTopic).toBe("New topic");
    expect(result.current.audioOverviewPodcastId).toBeNull();
    expect(result.current.audioOverviewError).toBe("");
  });

  it("does not attach old audio to a newer podcast", async () => {
    const audio = deferred<Blob>();
    vi.mocked(api.getAudioOverviewPodcast).mockResolvedValueOnce({ ...podcast(), audio_path: "old.mp3" });
    vi.mocked(api.fetchAudioOverviewPodcastAudio).mockReturnValue(audio.promise);
    const { result } = renderHook(() => useAudioOverview(options));
    let pending!: Promise<void>;
    await act(async () => { pending = result.current.onLoadPodcast(1); });
    await act(async () => { await result.current.onLoadPodcast(2); });
    await act(async () => { audio.resolve(new Blob(["old audio"])); await pending; });
    expect(result.current.audioOverviewPodcastId).toBe(2);
    expect(result.current.audioOverviewAudioUrl).toBe("");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it.each(["create", "draft", "poll"])("ignores generation abandoned during %s", async phase => {
    const pendingRun = deferred<api.AudioAgentRunDetail>();
    const pendingDraft = deferred<api.AudioOverviewPodcast>();
    if (phase === "create") vi.mocked(api.createAudioAgentRun).mockReturnValue(pendingRun.promise);
    if (phase === "draft") vi.mocked(api.getAudioOverviewPodcast).mockReturnValue(pendingDraft.promise);
    if (phase === "poll") {
      vi.mocked(api.createAudioAgentRun).mockResolvedValue(run("running"));
      vi.mocked(api.getAudioAgentRun).mockReturnValue(pendingRun.promise);
    }
    const { result } = renderHook(() => useAudioOverview(options));
    let pending!: Promise<void>;
    await act(async () => { pending = result.current.onGenerateScript(submit); });
    act(() => { result.current.onNewDraft(); result.current.onTopicChange("New topic"); });
    await act(async () => {
      pendingRun.resolve(run()); pendingDraft.resolve(podcast()); await pending;
    });
    expect(result.current.audioOverviewTopic).toBe("New topic");
    expect(result.current.audioOverviewPodcastId).toBeNull();
    expect(result.current.audioAgentRunId).toBeNull();
    expect(result.current.audioOverviewBusy).toBe(false);
  });

  it.each(["save", "synthesize"])("does not continue %s after abandoning an unsaved draft", async action => {
    const created = deferred<api.AudioOverviewPodcast>();
    vi.mocked(api.createAudioOverviewPodcast).mockReturnValue(created.promise);
    const { result } = renderHook(() => useAudioOverview(options));
    act(() => {
      result.current.onAddLine(); result.current.onLineTextChange(0, "Hello");
      result.current.onAddLine(); result.current.onLineTextChange(1, "World");
    });
    let pending!: Promise<void>;
    act(() => { pending = action === "save" ? result.current.onSaveScript() : result.current.onSynthesize(); });
    act(() => { result.current.onNewDraft(); });
    await act(async () => { created.resolve(podcast()); await pending; });
    expect(api.saveAudioOverviewScript).not.toHaveBeenCalled();
    expect(api.synthesizeAudioOverviewPodcast).not.toHaveBeenCalled();
    expect(result.current.audioOverviewPodcastId).toBeNull();
    expect(result.current.audioOverviewSaving).toBe(false);
    expect(result.current.audioOverviewSynthBusy).toBe(false);
  });

  it.each(["new", "existing"])("preserves edits made while saving a %s podcast and saves them on the next request", async kind => {
    const response = deferred<api.AudioOverviewPodcast>();
    const { result } = renderHook(() => useAudioOverview(options));
    if (kind === "existing") {
      await act(async () => { await result.current.onLoadPodcast(1); });
      vi.mocked(api.updateAudioOverviewPodcast).mockReturnValueOnce(response.promise);
    } else {
      act(() => {
        result.current.onTopicChange("Original");
        result.current.onLanguageChange("en");
        result.current.onAddLine(); result.current.onLineTextChange(0, "Hello");
        result.current.onAddLine(); result.current.onLineTextChange(1, "World");
      });
      vi.mocked(api.createAudioOverviewPodcast).mockReturnValueOnce(response.promise);
    }
    let pending!: Promise<void>;
    act(() => { pending = result.current.onSaveScript(); });
    act(() => {
      result.current.onTopicChange("Edited while saving");
      result.current.onLanguageChange("zh");
      result.current.onLineTextChange(0, "New text");
    });
    await act(async () => { response.resolve(podcast()); await pending; });
    expect(result.current.audioOverviewPodcastId).toBe(1);
    expect(result.current.audioOverviewTopic).toBe("Edited while saving");
    expect(result.current.audioOverviewLanguage).toBe("zh");
    expect(result.current.audioOverviewScriptLines[0].text).toBe("New text");
    await act(async () => { await result.current.onSaveScript(); });
    expect(api.updateAudioOverviewPodcast).toHaveBeenLastCalledWith(1, expect.objectContaining({
      topic: "Edited while saving", language: "zh", script_lines: expect.arrayContaining([{ role: "A", text: "New text" }]),
    }));
    expect(api.createAudioOverviewPodcast).toHaveBeenCalledTimes(kind === "new" ? 1 : 0);
    expect(api.saveAudioOverviewScript).not.toHaveBeenCalled();
  });

  it("does not clear a newly selected podcast when an older delete completes", async () => {
    const deleted = deferred<void>();
    vi.mocked(api.deleteAudioOverviewPodcast).mockReturnValue(deleted.promise);
    const { result } = renderHook(() => useAudioOverview(options));
    await act(async () => { await result.current.onLoadPodcast(1); });
    let pending!: Promise<void>;
    act(() => { pending = result.current.onDeletePodcastById(1); });
    await act(async () => { await result.current.onLoadPodcast(2); });
    await act(async () => { deleted.resolve(); await pending; });
    expect(result.current.audioOverviewPodcastId).toBe(2);
    expect(result.current.audioOverviewTopic).toBe("Podcast 2");
  });

  it("does not fetch or allocate audio after unmounting during a detail request", async () => {
    const detail = deferred<api.AudioOverviewPodcast>();
    vi.mocked(api.getAudioOverviewPodcast).mockReturnValue(detail.promise);
    const { result, unmount } = renderHook(() => useAudioOverview(options));
    let pending!: Promise<void>;
    act(() => { pending = result.current.onLoadPodcast(1); });
    unmount();
    await act(async () => { detail.resolve({ ...podcast(), audio_path: "audio.mp3" }); await pending; });
    expect(api.fetchAudioOverviewPodcastAudio).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("does not restore a deleted podcast from a stale list response", async () => {
    const listing = deferred<api.AudioOverviewPodcastListResponse>();
    vi.mocked(api.listAudioOverviewPodcasts).mockReturnValue(listing.promise);
    const { result } = renderHook(() => useAudioOverview(options));
    await act(async () => { await result.current.onDeletePodcastById(1); });
    await act(async () => { listing.resolve({ count: 1, podcasts: [podcast()] }); });
    expect(result.current.audioOverviewPodcasts).toEqual([]);
    expect(result.current.audioOverviewListBusy).toBe(false);
  });

  it("ignores an older list response after a newer refresh", async () => {
    const listing = deferred<api.AudioOverviewPodcastListResponse>();
    vi.mocked(api.listAudioOverviewPodcasts).mockReturnValueOnce(listing.promise);
    const { result } = renderHook(() => useAudioOverview(options));
    await act(async () => { await result.current.onRefreshList(); });
    await act(async () => { listing.resolve({ count: 1, podcasts: [podcast()] }); });
    expect(result.current.audioOverviewPodcasts).toEqual([]);
  });

  it.each(["save", "audio", "agent"])("ignores a late %s result after switching podcasts", async phase => {
    const saved = deferred<api.AudioOverviewPodcast>();
    const audio = deferred<Blob>();
    const agent = deferred<api.AudioAgentRunDetail>();
    const { result } = renderHook(() => useAudioOverview(options));
    await act(async () => { await result.current.onLoadPodcast(1); });
    let pending!: Promise<void>;
    if (phase === "save") {
      vi.mocked(api.updateAudioOverviewPodcast).mockReturnValue(saved.promise);
      await act(async () => { pending = result.current.onSaveScript(); });
    } else if (phase === "audio") {
      vi.mocked(api.synthesizeAudioOverviewPodcast).mockResolvedValue({
        podcast_id: 1, audio_path: "audio.mp3", audio_download_url: "", line_count: 2,
        voice_a: "A", voice_b: "B", rate: "+0%", gap_ms: 0, gap_ms_applied: 0,
        cache_hits: 0, merge_strategy: "auto", intro_music: false, intro_music_style: "off", intro_music_duration_ms: 0,
      });
      vi.mocked(api.fetchAudioOverviewPodcastAudio).mockReturnValue(audio.promise);
      await act(async () => { pending = result.current.onSynthesize(); });
    } else {
      vi.mocked(api.getAudioAgentRun).mockReturnValue(agent.promise);
      act(() => { pending = result.current.onOpenAgentRunById(10); });
    }
    await act(async () => { await result.current.onLoadPodcast(2); });
    await act(async () => {
      saved.resolve(podcast()); audio.resolve(new Blob(["old"])); agent.resolve(run()); await pending;
    });
    expect(result.current.audioOverviewPodcastId).toBe(2);
    expect(result.current.audioOverviewAudioUrl).toBe("");
    expect(result.current.audioAgentRunId).toBeNull();
    expect(result.current.audioOverviewError).toBe("");
  });

  it("finishes generation when the polling endpoint reports completed", async () => {
    vi.mocked(api.createAudioAgentRun).mockResolvedValue(run("running"));
    vi.mocked(api.getAudioAgentRun).mockResolvedValue(run("completed"));
    const { result } = renderHook(() => useAudioOverview(options));
    await act(async () => { await result.current.onGenerateScript(submit); });
    expect(result.current.audioOverviewPodcastId).toBe(1);
    expect(result.current.audioOverviewScriptLines).toEqual(podcast().script_lines);
    expect(result.current.audioOverviewBusy).toBe(false);
    expect(api.getAudioAgentRun).toHaveBeenCalledTimes(1);
  });

  it("ignores a retry response after opening a new draft", async () => {
    const retry = deferred<api.AudioAgentRunDetail>();
    vi.mocked(api.getAudioAgentRun).mockResolvedValue(run("failed"));
    vi.mocked(api.executeAudioAgentRun).mockReturnValue(retry.promise);
    const { result } = renderHook(() => useAudioOverview(options));
    await act(async () => { await result.current.onOpenAgentRunById(10); });
    let pending!: Promise<void>;
    act(() => { pending = result.current.onRetryAgentRun(); });
    act(() => { result.current.onNewDraft(); });
    await act(async () => { retry.resolve(run()); await pending; });
    expect(result.current.audioAgentRunId).toBeNull();
    expect(result.current.audioOverviewPodcastId).toBeNull();
    expect(result.current.audioOverviewBusy).toBe(false);
  });

  it("does not clear the new operation's busy state when an old request fails", async () => {
    const old = deferred<api.AudioOverviewPodcast>();
    const current = deferred<api.AudioAgentRunDetail>();
    vi.mocked(api.getAudioOverviewPodcast).mockReturnValueOnce(old.promise);
    vi.mocked(api.createAudioAgentRun).mockReturnValue(current.promise);
    const { result } = renderHook(() => useAudioOverview(options));
    let previous!: Promise<void>;
    let next!: Promise<void>;
    act(() => { previous = result.current.onLoadPodcast(1); });
    act(() => { next = result.current.onGenerateScript(submit); });
    await act(async () => { old.reject(new Error("Old failure")); await previous; });
    expect(result.current.audioOverviewBusy).toBe(true);
    expect(result.current.audioOverviewError).toBe("");
    await act(async () => { current.resolve(run()); await next; });
    expect(result.current.audioOverviewBusy).toBe(false);
  });

  it("keeps the latest agent history when an older request finishes last", async () => {
    const old = deferred<api.AudioAgentRunListResponse>();
    vi.mocked(api.listAudioAgentRuns).mockReturnValueOnce(old.promise).mockResolvedValue({ count: 0, runs: [] });
    const { result } = renderHook(() => useAudioOverview(options));
    let pending!: Promise<void>;
    act(() => { pending = result.current.onLoadAgentRunHistory(); });
    await act(async () => { await result.current.onLoadAgentRunHistory(); });
    await act(async () => { old.resolve({ count: 1, runs: [run()] }); await pending; });
    expect(result.current.agentRunHistory).toEqual([]);
    expect(result.current.agentRunHistoryBusy).toBe(false);
  });

  it("releases the previous audio URL on replacement and the current URL on unmount", async () => {
    vi.mocked(api.getAudioOverviewPodcast).mockImplementation(async id => ({ ...podcast(id), audio_path: "audio.mp3" }));
    vi.mocked(URL.createObjectURL).mockReturnValueOnce("blob:first").mockReturnValueOnce("blob:second");
    const { result, unmount } = renderHook(() => useAudioOverview(options));
    await act(async () => { await result.current.onLoadPodcast(1); });
    expect(result.current.audioOverviewAudioUrl).toBe("blob:first");
    await act(async () => { await result.current.onLoadPodcast(2); });
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:first");
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
    expect(URL.revokeObjectURL).toHaveBeenLastCalledWith("blob:second");
  });
});
