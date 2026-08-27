import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import RealtimeTranscriptionPanel, { joinSegments, formatElapsed, formatTimestampDisplay } from "./RealtimeTranscriptionPanel";

vi.mock("../../utils/desktopFileSave", () => ({
  exportTextFile: vi.fn().mockResolvedValue({ kind: "saved-browser" }),
}));

vi.mock("../../api", () => ({
  buildRealtimeTranscriptionWebSocketUrl: vi.fn(() => "ws://127.0.0.1:8000/api/transcription/realtime"),
  saveTranscriptionText: vi.fn().mockResolvedValue({ id: "job-123", file_name: "test.txt" }),
}));

describe("RealtimeTranscriptionPanel helpers", () => {
  it("joins segments with language-aware spacing", () => {
    expect(joinSegments(["Hello", "world"])).toBe("Hello world");
    expect(joinSegments(["你好", "世界"])).toBe("你好世界");
    expect(joinSegments(["Hello", "世界"])).toBe("Hello世界");
    expect(joinSegments(["你好", "world"])).toBe("你好world");
  });

  it("formats elapsed time", () => {
    expect(formatElapsed(0)).toBe("00:00");
    expect(formatElapsed(65)).toBe("01:05");
    expect(formatElapsed(3600)).toBe("60:00");
  });

  it("formats timestamp display", () => {
    expect(formatTimestampDisplay(0)).toBe("00:00");
    expect(formatTimestampDisplay(125)).toBe("02:05");
  });
});

describe("RealtimeTranscriptionPanel component", () => {
  const onComplete = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders initial controls, model list and view mode switchers", () => {
    render(<RealtimeTranscriptionPanel onComplete={onComplete} />);
    expect(screen.getByText(/识别引擎/i)).toBeInTheDocument();
    expect(screen.getByText(/识别语种/i)).toBeInTheDocument();
    expect(screen.getByText(/文稿模式/i)).toBeInTheDocument();
    expect(screen.getByText(/字幕时间轴/i)).toBeInTheDocument();
    expect(screen.getByText(/大字实时字幕/i)).toBeInTheDocument();
    expect(screen.getByText(/开始实时流式转写/i)).toBeInTheDocument();
  });

  it("switches between view modes smoothly", () => {
    render(<RealtimeTranscriptionPanel onComplete={onComplete} />);

    // Switch to Timeline Cues
    fireEvent.click(screen.getByText(/字幕时间轴/i));
    expect(screen.getByText(/暂无字幕段落/i)).toBeInTheDocument();

    // Switch to Live Banner
    fireEvent.click(screen.getByText(/大字实时字幕/i));
    expect(screen.getByText(/实时大字字幕提词/i)).toBeInTheDocument();

    // Switch back to Transcript
    fireEvent.click(screen.getByText(/文稿模式/i));
    expect(screen.getByText(/转写文字将在此实时呈现/i)).toBeInTheDocument();
  });
});
