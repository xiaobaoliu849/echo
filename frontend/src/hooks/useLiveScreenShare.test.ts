import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useLiveScreenShare from "./useLiveScreenShare";
import { supportsLiveScreenShare } from "../utils/liveScreenShare";

class Track extends EventTarget {
  label = "Lesson window";
  readyState = "live";
  stop = vi.fn(() => { this.readyState = "ended"; });
}

describe("Live screen sharing lifecycle", () => {
  let track: Track;
  let stream: MediaStream;
  let socket: WebSocket;
  let connection: WebSocket | null;
  let getDisplayMedia: ReturnType<typeof vi.fn>;
  let drawImage: ReturnType<typeof vi.fn>;
  let toDataURL: ReturnType<typeof vi.fn<(type?: string, quality?: number) => string>>;
  const mount = () => renderHook(({ enabled }) => useLiveScreenShare({ enabled, getConnection: () => connection, language: "en-US" }), { initialProps: { enabled: true } });

  beforeEach(() => {
    vi.useFakeTimers();
    track = new Track();
    stream = { getVideoTracks: () => [track], getTracks: () => [track] } as unknown as MediaStream;
    socket = { readyState: WebSocket.OPEN, bufferedAmount: 0, send: vi.fn() } as unknown as WebSocket;
    connection = socket;
    getDisplayMedia = vi.fn().mockResolvedValue(stream);
    vi.stubGlobal("navigator", { mediaDevices: { getDisplayMedia } });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(1920);
    vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(1080);
    drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D);
    toDataURL = vi.fn().mockReturnValue("data:image/jpeg;base64,/9j/2Q==");
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockImplementation((...args) => toDataURL(...args));
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it.each(["Google", "AgentPlatform", "VertexAI"])("allows ordinary and avatar input on %s", provider => {
    expect(supportsLiveScreenShare(provider, "gemini-3.8-live")).toBe(true);
    expect(supportsLiveScreenShare(provider, "gemini-3.5-live-translate-preview")).toBe(false);
  });
  it("keeps unsupported gateway and private-thinking models disabled", () => {
    expect(supportsLiveScreenShare("Vercel", "google/gemini-3.8-live")).toBe(false);
    expect(supportsLiveScreenShare("Google", "gemini-3.8-live-extended-thinking")).toBe(false);
  });
  it("sends bounded 1 FPS visual context without creating turns and stops on browser Stop sharing", async () => {
    const { result } = mount();
    await act(async () => { await result.current.start(); });
    expect(getDisplayMedia).toHaveBeenCalledWith({ video: { frameRate: { ideal: 1, max: 1 } }, audio: false });
    expect(result.current.sharing).toBe(true);
    expect(result.current.source).toBe("Lesson window");
    expect(drawImage.mock.calls[0].slice(1)).toEqual([0, 0, 768, 432]);
    expect(JSON.parse(vi.mocked(socket.send).mock.calls[0][0] as string)).toEqual({ type: "screen_frame", mime_type: "image/jpeg", data: "/9j/2Q==" });
    act(() => { vi.advanceTimersByTime(999); });
    expect(socket.send).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(1); });
    expect(socket.send).toHaveBeenCalledTimes(2);
    act(() => { track.dispatchEvent(new Event("ended")); vi.advanceTimersByTime(3000); });
    expect(track.stop).toHaveBeenCalled();
    expect(result.current.sharing).toBe(false);
    expect(result.current.stream).toBeNull();
    expect(socket.send).toHaveBeenCalledTimes(3);
    expect(JSON.parse(vi.mocked(socket.send).mock.calls[2][0] as string)).toEqual({ type: "screen_share_stopped" });
  });
  it("drops oversized frames and congested socket frames without growing a queue", async () => {
    toDataURL.mockReturnValue(`data:image/jpeg;base64,${"A".repeat(140000)}`);
    const { result } = mount();
    await act(async () => { await result.current.start(); });
    expect(socket.send).not.toHaveBeenCalled();
    expect(toDataURL).toHaveBeenCalledTimes(2);
    Object.assign(socket, { bufferedAmount: 200000 });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(toDataURL).toHaveBeenCalledTimes(2);
    expect(result.current.sharing).toBe(true);
  });
  it("releases a picker result that arrives after hangup", async () => {
    let resolve!: (stream: MediaStream) => void;
    getDisplayMedia.mockReturnValue(new Promise<MediaStream>(r => { resolve = r; }));
    const { result, rerender } = mount();
    let pending!: Promise<void>;
    act(() => { pending = result.current.start(); });
    expect(result.current.pending).toBe(true);
    rerender({ enabled: false });
    await act(async () => { resolve(stream); await pending; });
    expect(track.stop).toHaveBeenCalled();
    expect(result.current.sharing).toBe(false);
    expect(socket.send).not.toHaveBeenCalled();
  });
  it("never sends old screen frames to a replacement connection", async () => {
    const { result } = mount();
    await act(async () => { await result.current.start(); });
    connection = { readyState: WebSocket.OPEN, send: vi.fn() } as unknown as WebSocket;
    act(() => { vi.advanceTimersByTime(1000); });
    expect(result.current.sharing).toBe(false);
    expect(socket.send).toHaveBeenCalledTimes(1);
    expect(connection.send).not.toHaveBeenCalled();
    expect(track.stop).toHaveBeenCalled();
  });
  it("cancellation is quiet and unmount releases the source", async () => {
    getDisplayMedia.mockRejectedValueOnce(new DOMException("Canceled", "NotAllowedError"));
    const { result, unmount } = mount();
    await act(async () => { await result.current.start(); });
    expect(result.current.error).toBe("");
    expect(result.current.pending).toBe(false);
    await act(async () => { await result.current.start(); });
    unmount();
    expect(track.stop).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("ignores duplicate clicks while a picker is pending", async () => {
    let resolve!: (stream: MediaStream) => void;
    getDisplayMedia.mockReturnValue(new Promise<MediaStream>(r => { resolve = r; }));
    const { result } = mount();
    let pending!: Promise<void>;
    act(() => { pending = result.current.start(); void result.current.start(); });
    expect(getDisplayMedia).toHaveBeenCalledTimes(1);
    act(() => { result.current.stop(); });
    await act(async () => { resolve(stream); await pending; });
    expect(track.stop).toHaveBeenCalled();
    expect(socket.send).not.toHaveBeenCalled();
  });
  it("never opens a picker for an unsupported or disconnected session", async () => {
    const { result, rerender } = mount();
    rerender({ enabled: false });
    await act(async () => { await result.current.start(); });
    rerender({ enabled: true });
    connection = null;
    await act(async () => { await result.current.start(); });
    expect(getDisplayMedia).not.toHaveBeenCalled();
  });
});
