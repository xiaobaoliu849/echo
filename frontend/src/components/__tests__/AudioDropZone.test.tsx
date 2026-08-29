import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AudioDropZone } from "../AudioDropZone";

describe("AudioDropZone", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders default empty dropzone state with instructions and format pills", () => {
    const onFileDrop = vi.fn();
    render(<AudioDropZone onFileDrop={onFileDrop} />);

    expect(screen.getByText("拖拽音视频文件至此处，或点击浏览选择")).toBeInTheDocument();
    expect(screen.getByText("支持所有常见音视频格式，视频将自动抽取音轨")).toBeInTheDocument();
    expect(screen.getByText("MP3")).toBeInTheDocument();
    expect(screen.getByText("WAV")).toBeInTheDocument();
    expect(screen.getByText("MP4")).toBeInTheDocument();
  });

  it("handles drag over and drag leave styling state", () => {
    const onFileDrop = vi.fn();
    const { container } = render(<AudioDropZone onFileDrop={onFileDrop} />);
    const dropzone = container.querySelector(".vsAudioDropZone")!;

    fireEvent.dragOver(dropzone);
    expect(dropzone).toHaveClass("dragging");

    fireEvent.dragLeave(dropzone);
    expect(dropzone).not.toHaveClass("dragging");
  });

  it("accepts valid audio file on drop and triggers onFileDrop", () => {
    const onFileDrop = vi.fn();
    const { container } = render(<AudioDropZone onFileDrop={onFileDrop} />);
    const dropzone = container.querySelector(".vsAudioDropZone")!;

    const fakeAudioFile = new File(["audio-bytes"], "podcast.mp3", { type: "audio/mpeg" });

    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [fakeAudioFile],
      },
    });

    expect(onFileDrop).toHaveBeenCalledTimes(1);
    expect(onFileDrop).toHaveBeenCalledWith(fakeAudioFile);
    expect(screen.getByText("podcast.mp3")).toBeInTheDocument();
    expect(screen.getByText(/🎵 音频/)).toBeInTheDocument();
  });

  it("accepts video file on drop and displays video badge", () => {
    const onFileDrop = vi.fn();
    const { container } = render(<AudioDropZone onFileDrop={onFileDrop} />);
    const dropzone = container.querySelector(".vsAudioDropZone")!;

    const fakeVideoFile = new File(["video-bytes"], "interview.mp4", { type: "video/mp4" });

    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [fakeVideoFile],
      },
    });

    expect(onFileDrop).toHaveBeenCalledTimes(1);
    expect(onFileDrop).toHaveBeenCalledWith(fakeVideoFile);
    expect(screen.getByText("interview.mp4")).toBeInTheDocument();
    expect(screen.getByText(/🎬 视频音轨/)).toBeInTheDocument();
  });

  it("rejects unsupported file on drop with an alert", () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    const onFileDrop = vi.fn();
    const { container } = render(<AudioDropZone onFileDrop={onFileDrop} />);
    const dropzone = container.querySelector(".vsAudioDropZone")!;

    const unsupportedFile = new File(["data"], "document.pdf", { type: "application/pdf" });

    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [unsupportedFile],
      },
    });

    expect(alertSpy).toHaveBeenCalledTimes(1);
    expect(alertSpy).toHaveBeenCalledWith(expect.stringContaining("不支持的文件格式"));
    expect(onFileDrop).not.toHaveBeenCalled();
  });

  it("handles file input change event", () => {
    const onFileDrop = vi.fn();
    render(<AudioDropZone onFileDrop={onFileDrop} />);

    const input = screen.getByLabelText("选择音视频文件");
    const testFile = new File(["sample"], "recording.wav", { type: "audio/wav" });

    fireEvent.change(input, {
      target: { files: [testFile] },
    });

    expect(onFileDrop).toHaveBeenCalledWith(testFile);
  });

  it("renders controlled selectedFile prop with file size and custom readyText", () => {
    const onFileDrop = vi.fn();
    const controlledFile = new File([new ArrayBuffer(1024 * 1024 * 5)], "lecture.m4a", { type: "audio/m4a" });

    render(
      <AudioDropZone
        onFileDrop={onFileDrop}
        selectedFile={controlledFile}
        readyText="Ready to transcribe now!"
      />
    );

    expect(screen.getByText("lecture.m4a")).toBeInTheDocument();
    expect(screen.getByText(/5 MB/)).toBeInTheDocument();
    expect(screen.getByText(/Ready to transcribe now!/)).toBeInTheDocument();
  });

  it("disables file input when isProcessing is true", () => {
    const onFileDrop = vi.fn();
    render(<AudioDropZone onFileDrop={onFileDrop} isProcessing={true} />);

    const input = screen.getByLabelText("选择音视频文件");
    expect(input).toBeDisabled();
  });
});
