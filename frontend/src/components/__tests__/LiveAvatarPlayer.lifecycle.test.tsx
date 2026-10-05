import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LiveAvatarPlayer from "../LiveAvatarPlayer";

const playback = vi.hoisted(() => ({ append: vi.fn(), reset: vi.fn() }));
vi.mock("../../utils/liveAvatarPlayback", () => ({
  LiveAvatarPlayback: class {
    append = playback.append;
    reset = playback.reset;
  },
}));

describe("avatar stage lifecycle", () => {
  it("shows speaking for muxed avatar playback ahead of interim input and thinking, through PiP and reply completion", () => {
    const stream = new EventTarget();
    const { container, rerender } = render(
      <LiveAvatarPlayer stream={stream} isVoiceActive isUserSpeaking isThinking assistantReply="Streaming" />
    );
    const video = container.querySelector("video")!;
    act(() => stream.dispatchEvent(new MessageEvent("frame", {
      data: { mimeType: "video/mp4", data: "queued" },
    })));
    expect(screen.getByText("正在聆听")).toBeInTheDocument();
    fireEvent.playing(video);
    expect(screen.getByText("正在说话")).toBeInTheDocument();
    expect(container.firstChild).toHaveClass("state-speaking");
    expect(screen.queryByText("正在聆听")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("画中画悬浮"));
    rerender(<LiveAvatarPlayer stream={stream} isVoiceActive isUserSpeaking />);
    expect(container.querySelector("video")).toBe(video);
    expect(screen.getByText("正在说话")).toBeInTheDocument();
    fireEvent.waiting(video);
    expect(screen.getByText("正在聆听")).toBeInTheDocument();
    fireEvent.playing(video);
    expect(screen.getByText("正在说话")).toBeInTheDocument();
  });

  it.each(["waiting", "pause", "ended", "emptied", "error"])("clears muxed speaking on %s", (event) => {
    const { container } = render(<LiveAvatarPlayer stream={new EventTarget()} isVoiceActive isUserSpeaking />);
    const video = container.querySelector("video")!;
    fireEvent.playing(video);
    expect(screen.getByText("正在说话")).toBeInTheDocument();
    fireEvent(video, new Event(event));
    expect(screen.queryByText("正在说话")).not.toBeInTheDocument();
    expect(container.firstChild).toHaveClass("state-listening");
  });

  it.each(["interrupt", "reset"])("clears muxed speaking immediately on stream %s", (event) => {
    const stream = new EventTarget();
    const { container } = render(<LiveAvatarPlayer stream={stream} isVoiceActive />);
    fireEvent.playing(container.querySelector("video")!);
    act(() => stream.dispatchEvent(new Event(event)));
    expect(screen.queryByText("正在说话")).not.toBeInTheDocument();
    expect(container.firstChild).toHaveClass("state-idle");
  });

  it("clears muxed speaking when the stream changes or the call ends, and preserves separate audio speaking", () => {
    const stream = new EventTarget();
    const { container, rerender } = render(<LiveAvatarPlayer stream={stream} isVoiceActive />);
    fireEvent.playing(container.querySelector("video")!);
    rerender(<LiveAvatarPlayer stream={stream} />);
    expect(screen.queryByText("正在说话")).not.toBeInTheDocument();
    const nextStream = new EventTarget();
    rerender(<LiveAvatarPlayer stream={nextStream} isVoiceActive />);
    expect(screen.queryByText("正在说话")).not.toBeInTheDocument();
    rerender(<LiveAvatarPlayer stream={nextStream} isVoiceActive isAssistantSpeaking />);
    fireEvent.waiting(container.querySelector("video")!);
    expect(screen.getByText("正在说话")).toBeInTheDocument();
  });

  it("keeps one playback video through PiP, preserves initialization on interruption and releases it on unmount", () => {
    vi.clearAllMocks();
    const stream = new EventTarget();
    const { container, unmount } = render(<LiveAvatarPlayer stream={stream} isVoiceActive />);
    const video = container.querySelector("video");
    fireEvent.click(screen.getByTitle("画中画悬浮"));
    expect(container.querySelector("video")).toBe(video);
    fireEvent.click(screen.getByTitle("还原舞台"));
    expect(container.querySelector("video")).toBe(video);
    const frame = { mimeType: "video/mp4", data: "first" };
    act(() => stream.dispatchEvent(new MessageEvent("frame", { data: frame })));
    expect(playback.append).toHaveBeenCalledWith(frame);
    act(() => stream.dispatchEvent(new Event("interrupt")));
    expect(playback.reset).toHaveBeenLastCalledWith(true);
    act(() => stream.dispatchEvent(new Event("reset")));
    expect(playback.reset).toHaveBeenLastCalledWith();
    unmount();
    expect(playback.reset).toHaveBeenCalledTimes(3);
    act(() => stream.dispatchEvent(new MessageEvent("frame", { data: { ...frame, data: "late" } })));
    expect(playback.append).toHaveBeenCalledTimes(1);
  });
});
