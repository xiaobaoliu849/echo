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
    fireEvent.click(playBtn);
  });
});
