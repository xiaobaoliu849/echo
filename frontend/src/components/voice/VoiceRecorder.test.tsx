import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { VoiceRecorder } from "./VoiceRecorder";

describe("VoiceRecorder", () => {
  it("renders idle state with start recording button and prompts", () => {
    const handleComplete = vi.fn();

    render(<VoiceRecorder onRecordingComplete={handleComplete} />);

    expect(screen.getByRole("button", { name: /开始录音/i })).toBeInTheDocument();
    expect(screen.getByText(/朗读示例范本/i)).toBeInTheDocument();
    expect(screen.getByText(/换一句/i)).toBeInTheDocument();
  });

  it("cycles to next sample prompt when '换一句' is clicked", () => {
    const handleComplete = vi.fn();

    render(<VoiceRecorder onRecordingComplete={handleComplete} />);

    const nextBtn = screen.getByRole("button", { name: /换一句/i });
    const initialText = screen.getByText(/清晨的阳光/i);
    expect(initialText).toBeInTheDocument();

    fireEvent.click(nextBtn);
    expect(screen.getByText(/海浪轻柔地拍打着礁石/i)).toBeInTheDocument();
  });

  it("shows error notice when mediaDevices are not available and user clicks record", async () => {
    const handleComplete = vi.fn();

    render(<VoiceRecorder onRecordingComplete={handleComplete} />);

    const recordBtn = screen.getByRole("button", { name: /开始录音/i });
    fireEvent.click(recordBtn);

    // In JSDOM, navigator.mediaDevices is typically undefined or empty
    const notice = await screen.findByText(/不支持录音功能|启动麦克风录音失败/i);
    expect(notice).toBeInTheDocument();
  });

  it("renders completed state with AudioPreviewPlayer when currentFile is passed", () => {
    const handleComplete = vi.fn();
    const mockFile = new File(["dummy recorded"], "recorded_sample.webm", {
      type: "audio/webm",
    });

    render(
      <VoiceRecorder
        onRecordingComplete={handleComplete}
        currentFile={mockFile}
      />
    );

    expect(screen.getByText(/录音已完成/i)).toBeInTheDocument();
    expect(screen.getByText(/录制的声纹样本/i)).toBeInTheDocument();
    expect(screen.getByText("WEBM")).toBeInTheDocument();
  });
});
