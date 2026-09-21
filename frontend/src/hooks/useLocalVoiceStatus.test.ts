import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { derivePhase, useLocalVoiceStatus } from "./useLocalVoiceStatus";
import { cancelLocalVoiceSetup, fetchLocalVoiceSetupJob, fetchLocalVoiceStatus, startLocalVoiceSetup } from "../api/client";
import type { LocalVoiceProviderStatus, LocalVoiceSetupJob } from "../api/types";

vi.mock("../api/client", () => ({
  cancelLocalVoiceSetup: vi.fn(),
  fetchLocalVoiceSetupJob: vi.fn(),
  fetchLocalVoiceStatus: vi.fn(),
  startLocalVoiceSetup: vi.fn(),
  startLocalVoiceServer: vi.fn(),
  stopLocalVoiceServer: vi.fn(),
}));

describe("setup polling cleanup", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    vi.mocked(startLocalVoiceSetup).mockResolvedValue({ job_id: "j1", status: "running" });
    vi.mocked(cancelLocalVoiceSetup).mockResolvedValue(undefined);
    vi.mocked(fetchLocalVoiceStatus).mockResolvedValue({ providers: [makeStatus()] });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it.each(["cancel", "unmount"])("does not revive polling after %s while a request is pending", async (action) => {
    let resolve!: (job: LocalVoiceSetupJob) => void;
    vi.mocked(fetchLocalVoiceSetupJob).mockReturnValue(new Promise((done) => { resolve = done; }));
    const { result, unmount } = renderHook(() => useLocalVoiceStatus(false));
    await act(async () => { await result.current.refresh(); await result.current.setup("GLM4Voice"); });
    if (action === "cancel") {
      await act(async () => { await result.current.cancelSetup("GLM4Voice"); });
    } else {
      unmount();
    }
    await act(async () => {
      resolve({ job_id: "j1", status: "running" });
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(fetchLocalVoiceSetupJob).toHaveBeenCalledTimes(1);
    if (action === "cancel") expect(result.current.providers.GLM4Voice.setupJob).toBeNull();
    unmount();
  });

  it("does not schedule retries when an in-flight request fails after unmount", async () => {
    let reject!: (error: Error) => void;
    vi.mocked(fetchLocalVoiceSetupJob).mockReturnValue(new Promise((_, fail) => { reject = fail; }));
    const { result, unmount } = renderHook(() => useLocalVoiceStatus(false));
    await act(async () => { await result.current.setup("GLM4Voice"); });
    unmount();
    await act(async () => {
      reject(new Error("network unavailable"));
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(fetchLocalVoiceSetupJob).toHaveBeenCalledTimes(1);
  });

  it("does not start polling when the setup request completes after unmount", async () => {
    let resolve!: (job: LocalVoiceSetupJob) => void;
    vi.mocked(startLocalVoiceSetup).mockReturnValue(new Promise((done) => { resolve = done; }));
    const { result, unmount } = renderHook(() => useLocalVoiceStatus(false));
    let pending!: Promise<void>;
    act(() => { pending = result.current.setup("GLM4Voice"); });
    unmount();
    await act(async () => {
      resolve({ job_id: "j1", status: "running" });
      await pending;
    });
    expect(fetchLocalVoiceSetupJob).not.toHaveBeenCalled();
  });

  it("retries transient failures and stops polling after completion", async () => {
    vi.mocked(fetchLocalVoiceSetupJob)
      .mockRejectedValueOnce(new Error("temporarily offline"))
      .mockResolvedValueOnce({ job_id: "j1", status: "running" })
      .mockResolvedValueOnce({ job_id: "j1", status: "done" });
    const { result, unmount } = renderHook(() => useLocalVoiceStatus(false));
    await act(async () => { await result.current.setup("GLM4Voice"); });
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(fetchLocalVoiceSetupJob).toHaveBeenCalledTimes(3);
    expect(result.current.providers.GLM4Voice.setupJob?.status).toBe("done");
    unmount();
  });

  it("ignores a late response from a replaced setup watcher", async () => {
    let resolveOld!: (job: LocalVoiceSetupJob) => void;
    vi.mocked(fetchLocalVoiceSetupJob)
      .mockReturnValueOnce(new Promise((done) => { resolveOld = done; }))
      .mockResolvedValue({ job_id: "j2", status: "running" });
    const { result, unmount } = renderHook(() => useLocalVoiceStatus(false));
    await act(async () => { await result.current.refresh(); await result.current.setup("GLM4Voice"); });
    vi.mocked(startLocalVoiceSetup).mockResolvedValue({ job_id: "j2", status: "running" });
    await act(async () => { await result.current.setup("GLM4Voice"); });
    await act(async () => { resolveOld({ job_id: "j1", status: "error", error: "old failure" }); });
    expect(result.current.providers.GLM4Voice.setupJob?.job_id).toBe("j2");
    expect(result.current.providers.GLM4Voice.error).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(fetchLocalVoiceSetupJob).toHaveBeenCalledTimes(3);
    expect(fetchLocalVoiceSetupJob).toHaveBeenLastCalledWith("j2");
    unmount();
  });
});

function makeStatus(overrides: Partial<LocalVoiceProviderStatus> = {}): LocalVoiceProviderStatus {
  return {
    provider: "GLM4Voice",
    server_running: false,
    installed: false,
    models_downloaded: false,
    requirements: { min_vram_gb: 10, approx_download_gb: 25 },
    gpu: { available: false },
    disk_free_gb: 500,
    ...overrides,
  };
}

describe("derivePhase", () => {
  it("is not-installed for a fresh machine", () => {
    expect(derivePhase(makeStatus(), null, false, null)).toBe("not-installed");
  });

  it("prioritizes a running setup job over everything else", () => {
    const job = { job_id: "j1", status: "running" as const, percent: 42 };
    expect(derivePhase(makeStatus({ installed: true, server_running: true }), job, false, null)).toBe("installing");
  });

  it("reports running when the server port answers", () => {
    expect(derivePhase(makeStatus({ server_running: true }), null, false, null)).toBe("running");
  });

  it("reports starting while the start request is in flight", () => {
    expect(derivePhase(makeStatus({ installed: true }), null, true, null)).toBe("starting");
  });

  it("reports installed when setup completed but the server is stopped", () => {
    expect(derivePhase(makeStatus({ installed: true, models_downloaded: true }), null, false, null)).toBe("installed");
  });

  it("surfaces errors over the bare not-installed state", () => {
    expect(derivePhase(makeStatus(), null, false, "boom")).toBe("error");
  });
});
