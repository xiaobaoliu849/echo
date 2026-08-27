import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listTranscriptionJobs, retryTranscriptionJob, deleteTranscriptionJob } from "../api";
import { useTranscriptionHistory } from "./useTranscriptionHistory";

vi.mock("../api", () => ({
  listTranscriptionJobs: vi.fn(),
  retryTranscriptionJob: vi.fn(),
  deleteTranscriptionJob: vi.fn(),
}));

describe("useTranscriptionHistory", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(listTranscriptionJobs).mockReset();
    vi.mocked(retryTranscriptionJob).mockReset();
    vi.mocked(deleteTranscriptionJob).mockReset();
    vi.mocked(listTranscriptionJobs).mockResolvedValue({
      count: 1,
      jobs: [
        {
          job_id: "tx_001",
          mode: "async",
          status: "completed",
          file_name: "meeting.wav",
          updated_at: "2026-03-09T12:00:00Z",
          has_transcript: true,
          memory_saved: true,
        },
      ],
    });
  });

  it("loads history from backend and persists it locally", async () => {
    const { result } = renderHook(() => useTranscriptionHistory());

    await waitFor(() => {
      expect(result.current.historyBusy).toBe(false);
    });

    expect(vi.mocked(listTranscriptionJobs)).toHaveBeenCalledWith({
      statuses: undefined,
      limit: 50,
    });
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0]?.job_id).toBe("tx_001");
    expect(JSON.parse(localStorage.getItem("vs_transcription_history") || "[]")).toHaveLength(1);
  });

  it("retries a failed job and updates cached history", async () => {
    vi.mocked(retryTranscriptionJob).mockResolvedValue({
      job_id: "tx_001",
      mode: "async",
      status: "submitted",
      file_name: "meeting.wav",
      updated_at: "2026-03-09T12:05:00Z",
      has_transcript: false,
      memory_saved: false,
      remote_job_id: "remote_retry_001",
    });

    const { result } = renderHook(() => useTranscriptionHistory());

    await waitFor(() => {
      expect(result.current.historyBusy).toBe(false);
    });

    await act(async () => {
      await result.current.retryJob("tx_001");
    });

    expect(vi.mocked(retryTranscriptionJob)).toHaveBeenCalledWith("tx_001");
    expect(result.current.history[0]?.status).toBe("submitted");
    expect(result.current.history[0]?.remote_job_id).toBe("remote_retry_001");
  });

  it("deletes a job from server and removes it locally", async () => {
    vi.mocked(deleteTranscriptionJob).mockResolvedValue(undefined);

    const { result } = renderHook(() => useTranscriptionHistory());

    await waitFor(() => {
      expect(result.current.historyBusy).toBe(false);
    });

    expect(result.current.history).toHaveLength(1);

    await act(async () => {
      await result.current.removeJob("tx_001");
    });

    expect(vi.mocked(deleteTranscriptionJob)).toHaveBeenCalledWith("tx_001");
    expect(result.current.history).toHaveLength(0);
    expect(JSON.parse(localStorage.getItem("vs_transcription_history") || "[]")).toHaveLength(0);
  });

  it("removes job locally even if server delete fails", async () => {
    vi.mocked(deleteTranscriptionJob).mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useTranscriptionHistory());

    await waitFor(() => {
      expect(result.current.historyBusy).toBe(false);
    });

    expect(result.current.history).toHaveLength(1);

    await act(async () => {
      await result.current.removeJob("tx_001");
    });

    expect(vi.mocked(deleteTranscriptionJob)).toHaveBeenCalledWith("tx_001");
    expect(result.current.history).toHaveLength(0);
  });

  it("switches filters and requests matching backend statuses", async () => {
    const { result } = renderHook(() => useTranscriptionHistory());

    await waitFor(() => {
      expect(result.current.historyBusy).toBe(false);
    });

    vi.mocked(listTranscriptionJobs).mockClear();

    await act(async () => {
      result.current.setActiveFilter("failed");
    });

    await waitFor(() => {
      expect(vi.mocked(listTranscriptionJobs)).toHaveBeenCalledWith({
        statuses: ["failed"],
        limit: 50,
      });
    });
  });

  it("marks a cached entry failed when the backend reports it missing", async () => {
    const { result } = renderHook(() => useTranscriptionHistory());

    await waitFor(() => {
      expect(result.current.historyBusy).toBe(false);
    });

    act(() => {
      result.current.markMissingJob("tx_001");
      result.current.markMissingJob("tx_unknown");
    });

    await waitFor(() => {
      expect(result.current.history[0]?.status).toBe("failed");
    });

    // Unknown ids leave the cache untouched.
    expect(result.current.history).toHaveLength(1);

    const stored = JSON.parse(localStorage.getItem("vs_transcription_history") || "[]");
    expect(stored).toHaveLength(1);
    expect(stored[0].job_id).toBe("tx_001");
    expect(stored[0].status).toBe("failed");
    expect(String(stored[0].error)).toContain("转写记录已失效");
  });
});
