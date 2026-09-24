import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AudioPreviewPlayer } from "./AudioPreviewPlayer";

describe("AudioPreviewPlayer", () => {
  it("renders file information and badges correctly", () => {
    const mockFile = new File(["sample content"], "my_voice_sample.wav", {
      type: "audio/wav",
    });

    render(
      <AudioPreviewPlayer
        file={mockFile}
        title="Custom Sample Title"
      />
    );

    expect(screen.getByText("Custom Sample Title")).toBeInTheDocument();
    expect(screen.getByText("WAV")).toBeInTheDocument();
  });

  it("handles remove and replace action callbacks", () => {
    const mockFile = new File(["sample content"], "sample.mp3", {
      type: "audio/mpeg",
    });
    const handleRemove = vi.fn();
    const handleReplace = vi.fn();

    render(
      <AudioPreviewPlayer
        file={mockFile}
        onRemove={handleRemove}
        onReplace={handleReplace}
      />
    );

    const replaceBtn = screen.getByRole("button", { name: /重选 \/ 重录/i });
    fireEvent.click(replaceBtn);
    expect(handleReplace).toHaveBeenCalledTimes(1);

    const removeBtn = screen.getByTitle(/移除音频/i);
    fireEvent.click(removeBtn);
    expect(handleRemove).toHaveBeenCalledTimes(1);
  });

  it("allows toggling play and pause", () => {
    const mockFile = new File(["sample content"], "test.webm", {
      type: "audio/webm",
    });

    render(<AudioPreviewPlayer file={mockFile} />);

    const playBtn = screen.getByLabelText(/试听样本/i);
    expect(playBtn).toBeInTheDocument();
    expect(playBtn).toHaveClass("vsAudioPreviewPlayBtn");
    fireEvent.click(playBtn);
  });

  it("displays duration badge and enables scrubber when initialDuration is provided", () => {
    const mockFile = new File(["sample content"], "voice_record.webm", {
      type: "audio/webm",
    });

    render(
      <AudioPreviewPlayer
        file={mockFile}
        initialDuration={15}
      />
    );

    expect(screen.getByText("⏱️ 00:15")).toBeInTheDocument();
    expect(screen.getByText("00:15")).toBeInTheDocument();

    const slider = screen.getByLabelText(/播放进度/i) as HTMLInputElement;
    expect(slider).toBeInTheDocument();
    expect(slider).not.toBeDisabled();
    expect(slider.max).toBe("15");
  });

  it("decodes duration using AudioContext when available", async () => {
    const mockFile = new File(["dummy raw audio"], "custom.wav", {
      type: "audio/wav",
    });

    const mockDecodeAudioData = vi.fn().mockResolvedValue({
      duration: 25.4,
      numberOfChannels: 1,
      sampleRate: 44100,
    });
    const mockClose = vi.fn().mockResolvedValue(undefined);

    class MockAudioContext {
      decodeAudioData = mockDecodeAudioData;
      close = mockClose;
      state = "running";
    }

    vi.stubGlobal("AudioContext", MockAudioContext);

    try {
      render(<AudioPreviewPlayer file={mockFile} />);

      const durationBadge = await screen.findByText("⏱️ 00:25");
      expect(durationBadge).toBeInTheDocument();
      expect(mockDecodeAudioData).toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
