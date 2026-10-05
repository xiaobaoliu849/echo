import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LiveAvatarPlayer from "../LiveAvatarPlayer";

const playback = vi.hoisted(() => ({ append: vi.fn(), reset: vi.fn() }));
vi.mock("../../utils/liveAvatarPlayback", () => ({
  LiveAvatarPlayback: class {
    append = playback.append;
    reset = playback.reset;
  },
}));

describe("avatar stage lifecycle", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance"] }));
  afterEach(() => {
    vi.useRealTimers();
    delete (HTMLVideoElement.prototype as HTMLVideoElement & { captureStream?: () => MediaStream }).captureStream;
  });

  function audio() {
    const node = () => ({ connect: vi.fn(), disconnect: vi.fn() });
    const context = { state: "running", destination: {}, createMediaStreamSource: vi.fn(node),
      createAnalyser: vi.fn(() => meter), createGain: vi.fn(() => ({ ...node(), gain: { value: 1 } })) };
    let volume = 0;
    const meter = { ...node(), context, fftSize: 1024,
      getFloatTimeDomainData: (samples: Float32Array) => samples.fill(volume) };
    const track = { readyState: "live", stop: vi.fn() };
    const capture = Object.assign(new EventTarget(), { getAudioTracks: () => [track], getTracks: () => [track] });
    Object.defineProperty(HTMLVideoElement.prototype, "captureStream", { value: () => capture, configurable: true });
    return { context: context as unknown as AudioContext, rawContext: context, capture, track,
      attach: (video: HTMLVideoElement) => Object.defineProperty(video, "captureStream", { value: () => capture, configurable: true }),
      sound: (value: number) => { volume = value; } };
  }
  const tick = (ms = 80) => act(() => vi.advanceTimersByTime(ms));
  const avatarChip = (container: HTMLElement) => container.querySelector(".vsAvatarStateChip")!;

  it("ignores continuous silent video and stale interim input, tracks actual audio through PiP and reply completion", () => {
    const stream = new EventTarget();
    const media = audio();
    const { container, rerender } = render(<LiveAvatarPlayer stream={stream} audioContext={media.context} isVoiceActive assistantReply="Streaming" />);
    const video = container.querySelector("video")!;
    media.attach(video);
    act(() => stream.dispatchEvent(new MessageEvent("frame", { data: { mimeType: "image/png", data: "portrait" } })));
    // Switch back to the video path; arrival alone cannot mean speech.
    act(() => stream.dispatchEvent(new MessageEvent("frame", { data: { mimeType: "video/mp4", data: "queued" } })));
    fireEvent.playing(video);
    tick(1000);
    expect(avatarChip(container)).not.toHaveClass("speaking");
    media.sound(0.04);
    tick();
    expect(avatarChip(container)).toHaveClass("speaking");
    fireEvent.click(screen.getByTitle("画中画悬浮"));
    rerender(<LiveAvatarPlayer stream={stream} audioContext={media.context} isVoiceActive />);
    expect(container.querySelector("video")).toBe(video);
    expect(avatarChip(container)).toHaveClass("speaking");
    media.sound(0);
    tick(240);
    expect(avatarChip(container)).toHaveClass("speaking");
    tick(160);
    expect(avatarChip(container)).toHaveTextContent("在线就绪");
    expect(avatarChip(container)).not.toHaveClass("speaking");
  });

  it.each(["waiting", "pause", "ended", "emptied", "error"])("clears muxed speaking on %s", (event) => {
    const media = audio();
    const { container } = render(<LiveAvatarPlayer stream={new EventTarget()} audioContext={media.context} isVoiceActive />);
    const video = container.querySelector("video")!;
    media.attach(video);
    media.sound(0.04);
    fireEvent.playing(video);
    tick();
    expect(avatarChip(container)).toHaveClass("speaking");
    fireEvent(video, new Event(event));
    expect(avatarChip(container)).not.toHaveClass("speaking");
  });

  it.each(["interrupt", "reset"])("clears capture on %s and reconnects the next video without stopping native playback", (event) => {
    const stream = new EventTarget();
    const media = audio();
    const { container, unmount } = render(<LiveAvatarPlayer stream={stream} audioContext={media.context} isVoiceActive />);
    const video = container.querySelector("video")!;
    const pause = vi.spyOn(video, "pause").mockImplementation(() => {});
    media.attach(video);
    media.sound(0.04);
    fireEvent.playing(video);
    tick();
    act(() => stream.dispatchEvent(new Event(event)));
    expect(avatarChip(container)).not.toHaveClass("speaking");
    expect(media.track.stop).toHaveBeenCalledTimes(1);
    fireEvent.playing(video);
    tick();
    expect(avatarChip(container)).toHaveClass("speaking");
    expect(pause).not.toHaveBeenCalled();
    unmount();
    expect(media.track.stop).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("prioritizes listening during barge-in, detects mic silence despite stale ASR, and respects mute", () => {
    const stream = new EventTarget();
    const media = audio();
    const micContext = { state: "running" };
    let micVolume = 0.1;
    const mic = { fftSize: 64, context: micContext,
      getFloatTimeDomainData: (samples: Float32Array) => samples.fill(micVolume) } as unknown as AnalyserNode;
    const props = { stream, audioContext: media.context, micAnalyser: mic, isVoiceActive: true, isUserSpeaking: true };
    const { container, rerender } = render(<LiveAvatarPlayer {...props} />);
    media.attach(container.querySelector("video")!);
    media.sound(0.04);
    fireEvent.playing(container.querySelector("video")!);
    tick(160);
    expect(avatarChip(container)).toHaveTextContent("正在聆听");
    expect(container.querySelectorAll(".vsAvatarStateChip")).toHaveLength(1);
    expect(container.querySelector(".vsAvatarActivityBar")).toBeNull();
    micVolume = 0;
    tick(400);
    expect(avatarChip(container)).toHaveTextContent("正在说话");
    rerender(<LiveAvatarPlayer {...props} isMuted />);
    expect(avatarChip(container)).toHaveClass("speaking");
  });

  it("does not infer speech without capture support and preserves the separate PCM flag", () => {
    const stream = new EventTarget();
    const { container, rerender } = render(<LiveAvatarPlayer stream={stream} isVoiceActive />);
    fireEvent.playing(container.querySelector("video")!);
    expect(avatarChip(container)).not.toHaveClass("speaking");
    rerender(<LiveAvatarPlayer stream={stream} isVoiceActive isAssistantSpeaking />);
    expect(avatarChip(container)).toHaveClass("speaking");
    rerender(<LiveAvatarPlayer stream={new EventTarget()} />);
    expect(avatarChip(container)).not.toHaveClass("speaking");
  });

  it("discovers a late audio track and clears activity while its context is suspended", () => {
    const media = audio();
    media.track.readyState = "ended";
    const { container } = render(<LiveAvatarPlayer stream={new EventTarget()} audioContext={media.context} isVoiceActive />);
    media.attach(container.querySelector("video")!);
    media.sound(0.04);
    fireEvent.playing(container.querySelector("video")!);
    tick();
    expect(avatarChip(container)).not.toHaveClass("speaking");
    expect(media.rawContext.createMediaStreamSource).not.toHaveBeenCalled();
    media.track.readyState = "live";
    act(() => media.capture.dispatchEvent(new Event("addtrack")));
    tick();
    expect(avatarChip(container)).toHaveClass("speaking");
    media.rawContext.state = "suspended";
    tick();
    expect(avatarChip(container)).not.toHaveClass("speaking");
    media.rawContext.state = "running";
    tick();
    expect(avatarChip(container)).toHaveClass("speaking");
  });

  it("releases the old meter on stream replacement and call end", () => {
    const media = audio();
    const first = new EventTarget();
    const { container, rerender } = render(<LiveAvatarPlayer stream={first} audioContext={media.context} isVoiceActive />);
    media.attach(container.querySelector("video")!);
    media.sound(0.04);
    fireEvent.playing(container.querySelector("video")!);
    tick();
    expect(avatarChip(container)).toHaveClass("speaking");
    const next = new EventTarget();
    rerender(<LiveAvatarPlayer stream={next} audioContext={media.context} isVoiceActive />);
    expect(media.track.stop).toHaveBeenCalledTimes(1);
    expect(avatarChip(container)).not.toHaveClass("speaking");
    act(() => first.dispatchEvent(new Event("reset")));
    expect(media.track.stop).toHaveBeenCalledTimes(1);
    fireEvent.playing(container.querySelector("video")!);
    tick();
    rerender(<LiveAvatarPlayer stream={next} audioContext={media.context} />);
    expect(avatarChip(container)).not.toHaveClass("speaking");
    expect(media.track.stop).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("leaves video playback intact if capture fails", () => {
    const media = audio();
    const { container } = render(<LiveAvatarPlayer stream={new EventTarget()} audioContext={media.context} isVoiceActive />);
    const video = container.querySelector("video")!;
    Object.defineProperty(video, "captureStream", { value: () => { throw new Error("Unavailable"); }, configurable: true });
    const pause = vi.spyOn(video, "pause").mockImplementation(() => {});
    fireEvent.playing(video);
    tick();
    expect(avatarChip(container)).not.toHaveClass("speaking");
    expect(pause).not.toHaveBeenCalled();
    expect(media.rawContext.createMediaStreamSource).not.toHaveBeenCalled();
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
