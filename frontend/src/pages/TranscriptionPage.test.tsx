import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { API_BASE_URL } from "../api";
import { TranscriptionPage } from "./TranscriptionPage";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    transcribeAudio: vi.fn(),
    createTranscriptionJobFromUrl: vi.fn(),
    fetchTranscriptionJob: vi.fn(),
    listTranscriptionJobs: vi.fn().mockResolvedValue({ jobs: [] })
  };
});

const mockedTranscribeAudio = vi.mocked(api.transcribeAudio);
const mockedCreateTranscriptionJobFromUrl = vi.mocked(api.createTranscriptionJobFromUrl);
const mockedFetchTranscriptionJob = vi.mocked(api.fetchTranscriptionJob);

describe("TranscriptionPage", () => {
  beforeEach(() => {
    mockedTranscribeAudio.mockResolvedValue({
      transcript: "同步转写结果",
      memory_saved: true
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
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("transcribes a local audio file", async () => {
    render(<TranscriptionPage />);

    // Open the new transcription modal
    fireEvent.click(screen.getByRole("button", { name: /新建转写/ }));

    // Default mode is local — find the file input inside the modal
    const fileInput = screen.getByLabelText("选择转写音频");
    const audioFile = new File(["audio"], "note.wav", { type: "audio/wav" });
    fireEvent.change(fileInput, { target: { files: [audioFile] } });
    fireEvent.click(screen.getByRole("button", { name: "开始转写" }));

    expect(mockedTranscribeAudio.mock.calls[0][0]).toBe(audioFile);

    // After transcription, we enter detail view — transcript is shown as text content
    expect(await screen.findByText("同步转写结果")).toBeInTheDocument();
    expect(screen.getByText("已入记忆")).toBeInTheDocument();
  });

  it("resolves relative transcription audio URLs against the backend API origin", async () => {
    mockedTranscribeAudio.mockResolvedValueOnce({
      transcript: "同步转写结果",
      job_id: "tx_sync_audio_001",
      source_url: "/api/transcription/jobs/tx_sync_audio_001/audio",
      memory_saved: true
    });

    render(<TranscriptionPage />);

    fireEvent.click(screen.getByRole("button", { name: /新建转写/ }));

    const fileInput = screen.getByLabelText("选择转写音频");
    const audioFile = new File(["audio"], "note.wav", { type: "audio/wav" });
    fireEvent.change(fileInput, { target: { files: [audioFile] } });
    fireEvent.click(screen.getByRole("button", { name: "开始转写" }));

    await waitFor(() => {
      const audio = document.querySelector("audio");
      expect(audio).not.toBeNull();
      expect(audio).toHaveAttribute(
        "src",
        `${API_BASE_URL}/api/transcription/jobs/tx_sync_audio_001/audio`
      );
    });
  });

  it("polls a remote async transcription job until completion", async () => {
    vi.spyOn(window, "setTimeout").mockImplementation(((handler: TimerHandler) => {
      if (typeof handler === "function") {
        handler();
      }
      return 0 as unknown as number;
    }) as typeof window.setTimeout);
    render(<TranscriptionPage />);

    // Open the new transcription modal
    fireEvent.click(screen.getByRole("button", { name: /新建转写/ }));

    // Switch to Remote mode
    fireEvent.click(screen.getByRole("button", { name: "链式转写" }));

    fireEvent.change(screen.getByPlaceholderText("https://example.com/meeting.wav"), {
      target: { value: "https://example.com/audio/demo.wav" }
    });
    fireEvent.click(screen.getByRole("button", { name: "提交异步任务" }));

    expect(mockedCreateTranscriptionJobFromUrl).toHaveBeenCalledWith(
      "https://example.com/audio/demo.wav",
      "qwen-filetrans"
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(mockedFetchTranscriptionJob).toHaveBeenCalledWith("tx_url_001");
    expect(screen.getByText("转写完成。")).toBeInTheDocument();
    expect(screen.getByText("已入记忆")).toBeInTheDocument();
  });
});
