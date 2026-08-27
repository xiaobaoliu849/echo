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
    getTranscriptionJobWords: vi.fn().mockResolvedValue([]),
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
    vi.restoreAllMocks();
  });

  it("transcribes a local audio file", async () => {
    render(<TranscriptionPage />);

    // Open the new transcription modal
    fireEvent.click(screen.getByRole("button", { name: /新建转写/ }));

    // Default mode is local — find the file input inside the modal
    const fileInput = screen.getByLabelText("选择转写音频或视频");
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

    const fileInput = screen.getByLabelText("选择转写音频或视频");
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

  it("resolves relative audio URLs when a job is opened from history", async () => {
    // The server-fetch path (not just the fresh-upload path) has to prefix the
    // API origin too: under `npm run dev` there is no proxy on :5173, so a
    // root-relative src would 404 and kill the player.
    vi.mocked(api.listTranscriptionJobs).mockResolvedValue({
      jobs: [
        {
          job_id: "tx_hist_001",
          mode: "sync",
          status: "completed",
          file_name: "历史录音.m4a",
          has_transcript: true,
          memory_saved: false,
          source_url: "/api/transcription/jobs/tx_hist_001/audio",
          updated_at: "2026-08-09T10:00:00Z",
        },
      ],
    } as unknown as Awaited<ReturnType<typeof api.listTranscriptionJobs>>);
    mockedFetchTranscriptionJob.mockResolvedValue({
      job_id: "tx_hist_001",
      mode: "sync",
      status: "completed",
      file_name: "历史录音.m4a",
      transcript: "历史转写内容",
      has_transcript: true,
      memory_saved: false,
      source_url: "/api/transcription/jobs/tx_hist_001/audio",
    } as unknown as Awaited<ReturnType<typeof api.fetchTranscriptionJob>>);

    render(<TranscriptionPage initialTab="library" />);

    const card = await screen.findByText("历史录音.m4a");
    fireEvent.click(card);

    await waitFor(() => {
      const audio = document.querySelector("audio");
      expect(audio).not.toBeNull();
      expect(audio).toHaveAttribute(
        "src",
        `${API_BASE_URL}/api/transcription/jobs/tx_hist_001/audio`
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

  it("exports SRT subtitle via a DOM-appended download link", async () => {
    mockedTranscribeAudio.mockResolvedValueOnce({
      transcript: "你好世界。这是一段测试。",
      memory_saved: false,
    });

    render(<TranscriptionPage />);

    // Trigger a local transcription to enter detail view
    fireEvent.click(screen.getByRole("button", { name: /新建转写/ }));
    const fileInput = screen.getByLabelText("选择转写音频或视频");
    const audioFile = new File(["audio"], "test.wav", { type: "audio/wav" });
    fireEvent.change(fileInput, { target: { files: [audioFile] } });
    fireEvent.click(screen.getByRole("button", { name: "开始转写" }));

    // Wait for detail view with transcript
    await waitFor(() => {
      expect(screen.getByText(/你好世界/)).toBeInTheDocument();
    });

    // Spy on DOM manipulation for the download link
    const appendSpy = vi.spyOn(document.body, "appendChild");
    const revokeURLSpy = vi.spyOn(URL, "revokeObjectURL");
    const createURLSpy = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");

    // Open export menu and click SRT
    fireEvent.click(screen.getByRole("button", { name: /导出/ }));
    fireEvent.click(screen.getByText(/导出 SRT 字幕/));

    // Verify the <a> element was appended to the DOM before clicking
    const appendedLink = appendSpy.mock.calls.find(
      ([node]) => node instanceof HTMLAnchorElement
    );
    expect(appendedLink).toBeDefined();

    const anchor = appendedLink![0] as HTMLAnchorElement;
    expect(anchor.download).toBe("test.srt");
    expect(anchor.href).toContain("blob:");

    // Verify the blob URL was revoked after download
    expect(revokeURLSpy).toHaveBeenCalledWith("blob:mock-url");

    appendSpy.mockRestore();
    revokeURLSpy.mockRestore();
    createURLSpy.mockRestore();
  });

  it("exports SRT subtitle via the pywebview bridge in desktop mode", async () => {
    mockedTranscribeAudio.mockResolvedValueOnce({
      transcript: "你好世界。这是一段测试。",
      memory_saved: false,
    });
    const saveTextFile = vi
      .fn()
      .mockResolvedValue({ ok: true, cancelled: false, path: "C:/exports/test.srt" });
    (window as any).pywebview = { api: { save_text_file: saveTextFile } };
    const appendSpy = vi.spyOn(document.body, "appendChild");

    try {
      render(<TranscriptionPage />);

      fireEvent.click(screen.getByRole("button", { name: /新建转写/ }));
      const fileInput = screen.getByLabelText("选择转写音频或视频");
      const audioFile = new File(["audio"], "test.wav", { type: "audio/wav" });
      fireEvent.change(fileInput, { target: { files: [audioFile] } });
      fireEvent.click(screen.getByRole("button", { name: "开始转写" }));

      await waitFor(() => {
        expect(screen.getByText(/你好世界/)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /导出/ }));
      fireEvent.click(screen.getByText(/导出 SRT 字幕/));

      await waitFor(() => {
        expect(saveTextFile).toHaveBeenCalledTimes(1);
      });

      const payload = saveTextFile.mock.calls[0][0];
      expect(payload.filename).toBe("test.srt");
      const rawBytes = Uint8Array.from(atob(payload.data_base64), (c) =>
        c.charCodeAt(0)
      );
      // SRT exports carry a BOM so CJK stays readable in legacy Windows players.
      expect([...rawBytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
      const decoded = new TextDecoder().decode(rawBytes);
      expect(decoded).toContain("-->");
      expect(decoded).toContain("你好世界");

      // Desktop bridge path must not fall back to an anchor download.
      expect(
        appendSpy.mock.calls.some(([node]) => node instanceof HTMLAnchorElement)
      ).toBe(false);

      expect(await screen.findByText(/文件已导出/)).toBeInTheDocument();
    } finally {
      appendSpy.mockRestore();
      delete (window as any).pywebview;
    }
  });

  it("surfaces an error when the desktop export bridge fails", async () => {
    mockedTranscribeAudio.mockResolvedValueOnce({
      transcript: "你好世界。这是一段测试。",
      memory_saved: false,
    });
    const saveTextFile = vi
      .fn()
      .mockResolvedValue({ ok: false, cancelled: false, message: "disk full" });
    (window as any).pywebview = { api: { save_text_file: saveTextFile } };

    try {
      render(<TranscriptionPage />);

      fireEvent.click(screen.getByRole("button", { name: /新建转写/ }));
      const fileInput = screen.getByLabelText("选择转写音频或视频");
      const audioFile = new File(["audio"], "test.wav", { type: "audio/wav" });
      fireEvent.change(fileInput, { target: { files: [audioFile] } });
      fireEvent.click(screen.getByRole("button", { name: "开始转写" }));

      await waitFor(() => {
        expect(screen.getByText(/你好世界/)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /导出/ }));
      fireEvent.click(screen.getByText(/导出 VTT 字幕/));

      expect(await screen.findByText(/导出失败/)).toBeInTheDocument();
    } finally {
      delete (window as any).pywebview;
    }
  });

  it("fails a history card immediately when the job record is gone server-side", async () => {
    localStorage.clear();
    vi.mocked(api.listTranscriptionJobs).mockResolvedValue({
      jobs: [
        {
          job_id: "tx_gone_001",
          mode: "async",
          status: "queued",
          file_name: "丢失的会议.mp4",
          has_transcript: false,
          memory_saved: false,
          updated_at: "2026-08-27T10:00:00Z",
        },
      ],
    } as unknown as Awaited<ReturnType<typeof api.listTranscriptionJobs>>);
    mockedFetchTranscriptionJob.mockRejectedValue(
      new api.ApiRequestError(
        "TRANSCRIPTION_JOB_NOT_FOUND: Transcription job not found: tx_gone_001",
        404,
        { code: "TRANSCRIPTION_JOB_NOT_FOUND" }
      )
    );

    render(<TranscriptionPage initialTab="library" />);

    const card = await screen.findByText("丢失的会议.mp4");
    fireEvent.click(card);

    // Terminal failed state, never the stale "任务排队中" spinner.
    expect(
      (await screen.findAllByText(/服务器上已不存在该任务记录/)).length
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/任务排队中/)).not.toBeInTheDocument();

    // Exactly one request FOR THIS JOB: the opening fetch. The previous
    // behaviour rebuilt a fake "queued" job and started polling a record
    // that no longer exists.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    const cardCalls = mockedFetchTranscriptionJob.mock.calls.filter(
      ([jobId]) => jobId === "tx_gone_001"
    );
    expect(cardCalls).toHaveLength(1);

    const stored = JSON.parse(localStorage.getItem("vs_transcription_history") || "[]");
    const entry = stored.find((item: { job_id: string }) => item.job_id === "tx_gone_001");
    expect(entry?.status).toBe("failed");
  });

  it("stops polling and fails fast when an in-flight async job disappears", async () => {
    localStorage.clear();
    mockedCreateTranscriptionJobFromUrl.mockResolvedValueOnce({
      job_id: "tx_vanish_001",
      remote_job_id: "remote-vanish-001",
      mode: "async",
      status: "submitted",
      file_name: "vanish.wav",
      memory_saved: false,
    });
    mockedFetchTranscriptionJob.mockRejectedValue(
      new api.ApiRequestError(
        "TRANSCRIPTION_JOB_NOT_FOUND: Transcription job not found: tx_vanish_001",
        404,
        { code: "TRANSCRIPTION_JOB_NOT_FOUND" }
      )
    );

    render(<TranscriptionPage />);

    fireEvent.click(screen.getByRole("button", { name: /新建转写/ }));
    fireEvent.click(screen.getByRole("button", { name: "链式转写" }));
    fireEvent.change(screen.getByPlaceholderText("https://example.com/meeting.wav"), {
      target: { value: "https://example.com/audio/vanish.wav" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交异步任务" }));

    expect(
      await screen.findAllByText(/转写失败：服务器上已不存在该任务记录/)
    ).toBeTruthy();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    const pollCalls = mockedFetchTranscriptionJob.mock.calls.filter(
      ([jobId]) => jobId === "tx_vanish_001"
    );
    expect(pollCalls).toHaveLength(1);

    const stored = JSON.parse(localStorage.getItem("vs_transcription_history") || "[]");
    const entry = stored.find((item: { job_id: string }) => item.job_id === "tx_vanish_001");
    expect(entry?.status).toBe("failed");
  });
});
