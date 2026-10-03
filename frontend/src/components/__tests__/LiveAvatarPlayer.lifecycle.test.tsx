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
