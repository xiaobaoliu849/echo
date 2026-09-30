import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useTavusConversation from "./useTavusConversation";
import { createTavusConversation, endTavusConversation } from "../api";

const dailyMocks = vi.hoisted(() => ({
  createCallObject: vi.fn(),
}));

vi.mock("../api", () => ({
  createTavusConversation: vi.fn(),
  endTavusConversation: vi.fn(),
}));

vi.mock("@daily-co/daily-js", () => ({
  default: {
    createCallObject: dailyMocks.createCallObject,
  },
}));

type CallMock = {
  join: ReturnType<typeof vi.fn>;
  leave: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  participants: ReturnType<typeof vi.fn>;
  startCamera: ReturnType<typeof vi.fn>;
  enumerateDevices: ReturnType<typeof vi.fn>;
  setInputDevicesAsync: ReturnType<typeof vi.fn>;
  setOutputDeviceAsync: ReturnType<typeof vi.fn>;
  startLocalAudioLevelObserver: ReturnType<typeof vi.fn>;
  stopLocalAudioLevelObserver: ReturnType<typeof vi.fn>;
};

function createCallMock(): CallMock {
  return {
    join: vi.fn().mockResolvedValue({}),
    leave: vi.fn().mockResolvedValue(undefined),
    destroy: vi.fn(),
    on: vi.fn(),
    participants: vi.fn(() => ({})),
    startCamera: vi.fn().mockResolvedValue({}),
    enumerateDevices: vi.fn().mockResolvedValue({ devices: [] }),
    setInputDevicesAsync: vi.fn().mockResolvedValue({}),
    setOutputDeviceAsync: vi.fn().mockResolvedValue({}),
    startLocalAudioLevelObserver: vi.fn().mockResolvedValue(undefined),
    stopLocalAudioLevelObserver: vi.fn(),
  };
}

function getEventHandler(call: CallMock, eventName: string): (payload?: unknown) => void {
  const calls = call.on.mock.calls as Array<[string, (payload?: unknown) => void]>;
  const match = calls.find(([name]) => name === eventName);
  if (!match) {
    throw new Error(`Expected a registered ${eventName} handler`);
  }
  return match[1];
}

describe("useTavusConversation", () => {
  const formatErrorStub = (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback;

  beforeEach(() => {
    vi.mocked(createTavusConversation).mockReset();
    vi.mocked(endTavusConversation).mockReset();
    vi.mocked(endTavusConversation).mockResolvedValue(undefined);
    dailyMocks.createCallObject.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("creates a conversation, checks devices, and joins the room", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-1",
      conversation_url: "https://tavus.daily.co/room?t=token",
      meeting_token: "meeting-token-1",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start({ palId: "pal-1" });
    });

    expect(createTavusConversation).toHaveBeenCalledWith({
      palId: "pal-1",
      conversationName: undefined,
      faceId: undefined,
      properties: undefined,
      testMode: undefined,
    });
    expect(dailyMocks.createCallObject).toHaveBeenCalledOnce();
    expect(call.startCamera).toHaveBeenCalledOnce();
    expect(result.current.status).toBe("prejoin");
    expect(call.join).not.toHaveBeenCalled();
    await act(async () => {
      await result.current.join();
    });
    expect(call.join).toHaveBeenCalledWith({
      url: "https://tavus.daily.co/room?t=token",
      token: "meeting-token-1",
      userName: "Echo User",
    });
    expect(result.current.status).toBe("connected");
    expect(result.current.errorMessage).toBe("");
  });

  it("joins public rooms by URL when no meeting token is issued", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-1b",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
      await result.current.join();
    });

    expect(call.join).toHaveBeenCalledWith({
      url: "https://tavus.daily.co/room?t=token",
      userName: "Echo User",
    });
    expect(result.current.status).toBe("connected");
  });

  it("lets a camera-in-use prejoin continue without video", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "camera-busy",
      conversation_url: "https://tavus.daily.co/camera-busy",
    });
    const call = createCallMock();
    call.startCamera.mockImplementation(async () => {
      getEventHandler(call, "camera-error")({
        error: { type: "cam-in-use" },
        errorMsg: { errorMsg: "Another app is using your camera", videoOk: false, audioOk: true },
      });
      return {};
    });
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); });
    expect(result.current.status).toBe("prejoin");
    expect(result.current.cameraError).toContain("摄像头");
    await act(async () => { await result.current.join({ videoOff: true }); });
    expect(call.join).toHaveBeenCalledWith(expect.objectContaining({ startVideoOff: true }));
    expect(result.current.status).toBe("connected");
  });

  it("retries an unavailable camera and enables video when it recovers", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "retry-camera",
      conversation_url: "https://tavus.daily.co/retry-camera",
    });
    const call = createCallMock();
    call.startCamera.mockImplementationOnce(async () => {
      getEventHandler(call, "camera-error")({
        error: { type: "cam-in-use" },
        errorMsg: { videoOk: false, audioOk: true },
      });
      return {};
    });
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); });
    expect(result.current.cameraError).toContain("摄像头");
    await act(async () => { await result.current.retryCamera(); });
    expect(call.startCamera).toHaveBeenCalledTimes(2);
    expect(result.current.cameraError).toBe("");
    await act(async () => { await result.current.join(); });
    expect(call.join).not.toHaveBeenCalledWith(expect.objectContaining({ startVideoOff: true }));
  });

  it("waits for a camera switch before allowing the room to join", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "switch-camera",
      conversation_url: "https://tavus.daily.co/switch-camera",
    });
    let finishSwitch!: () => void;
    const call = createCallMock();
    call.setInputDevicesAsync.mockReturnValue(new Promise((resolve) => {
      finishSwitch = () => resolve({});
    }));
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); });
    let selection!: Promise<void>;
    act(() => { selection = result.current.selectCamera("other-camera"); });
    expect(result.current.isCheckingDevices).toBe(true);
    await act(async () => { await result.current.join(); });
    expect(call.join).not.toHaveBeenCalled();
    await act(async () => { finishSwitch(); await selection; });
    expect(result.current.isCheckingDevices).toBe(false);
    await act(async () => { await result.current.join(); });
    expect(call.join).toHaveBeenCalledOnce();
  });


  it("releases devices and the created room when prejoin is cancelled", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "cancelled-room",
      conversation_url: "https://tavus.daily.co/cancelled-room",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); });
    act(() => { result.current.cancelPrejoin(); });
    expect(call.join).not.toHaveBeenCalled();
    expect(call.destroy).toHaveBeenCalledOnce();
    expect(endTavusConversation).toHaveBeenCalledWith("cancelled-room");
    expect(result.current.status).toBe("idle");
  });

  it("synchronizes remote media tracks and clears them on leave", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "track-room",
      conversation_url: "https://tavus.daily.co/track-room",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); await result.current.join(); });
    const audioTrack = { kind: "audio" } as MediaStreamTrack;
    const videoTrack = { kind: "video" } as MediaStreamTrack;
    call.participants.mockReturnValue({
      local: { local: true },
      pal: { local: false, tracks: {
        audio: { persistentTrack: audioTrack }, video: { track: videoTrack },
      } },
    });
    act(() => { getEventHandler(call, "track-started")(); });
    expect(result.current.remoteAudioTrack).toBe(audioTrack);
    expect(result.current.remoteVideoTrack).toBe(videoTrack);
    act(() => { result.current.leave(); });
    expect(result.current.remoteAudioTrack).toBeNull();
    expect(result.current.remoteVideoTrack).toBeNull();
  });

  it("stops rendering remote media when Daily marks a track off", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "remote-off",
      conversation_url: "https://tavus.daily.co/remote-off",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); await result.current.join(); });
    const audioTrack = { kind: "audio" } as MediaStreamTrack;
    const videoTrack = { kind: "video" } as MediaStreamTrack;
    call.participants.mockReturnValue({
      pal: { local: false, tracks: {
        audio: { state: "playable", track: audioTrack, persistentTrack: audioTrack },
        video: { state: "playable", track: videoTrack, persistentTrack: videoTrack },
      } },
    });
    act(() => { getEventHandler(call, "participant-updated")(); });
    expect(result.current.remoteAudioTrack).toBe(audioTrack);
    expect(result.current.remoteVideoTrack).toBe(videoTrack);
    call.participants.mockReturnValue({
      pal: { local: false, tracks: {
        audio: { state: "off", persistentTrack: audioTrack },
        video: { state: "off", persistentTrack: videoTrack },
      } },
    });
    act(() => { getEventHandler(call, "participant-updated")(); });
    expect(result.current.remoteAudioTrack).toBeNull();
    expect(result.current.remoteVideoTrack).toBeNull();
  });

  it("selects the requested camera and microphone before joining", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "device-room",
      conversation_url: "https://tavus.daily.co/device-room",
    });
    const call = createCallMock();
    call.enumerateDevices.mockResolvedValue({ devices: [
      { kind: "videoinput", deviceId: "camera-2", label: "External Camera" },
      { kind: "audioinput", deviceId: "mic-2", label: "External Mic" },
      { kind: "audiooutput", deviceId: "speaker-2", label: "External Speaker" },
    ] });
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); });
    expect(result.current.cameras).toHaveLength(1);
    await act(async () => {
      await result.current.selectCamera("camera-2");
      await result.current.selectMicrophone("mic-2");
      await result.current.selectSpeaker("speaker-2");
    });
    expect(call.setInputDevicesAsync).toHaveBeenCalledWith({ videoDeviceId: "camera-2" });
    expect(call.setInputDevicesAsync).toHaveBeenCalledWith({ audioDeviceId: "mic-2" });
    expect(call.setOutputDeviceAsync).toHaveBeenCalledWith({ outputDeviceId: "speaker-2" });
  });

  it.each(["leave", "unmount"])("archives the latest transcript exactly once on %s", async (endMode) => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "archive-call", conversation_url: "https://tavus.daily.co/archive-call",
    });
    const call = createCallMock();
    const onConversationEnded = vi.fn();
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result, unmount } = renderHook(() => useTavusConversation({
      formatErrorMessage: formatErrorStub, onConversationEnded,
    }));
    await act(async () => { await result.current.start({ palName: "Mia" }); await result.current.join(); });
    act(() => {
      getEventHandler(call, "app-message")({ data: {
        event_type: "conversation.utterance.streaming", properties: { role: "pal", text: "Final unfinished reply" },
      } });
      // End in the same batch, before React has rendered the last text update.
      if (endMode === "leave") result.current.leave();
      else unmount();
    });
    expect(onConversationEnded).toHaveBeenCalledOnce();
    expect(onConversationEnded).toHaveBeenCalledWith(
      [expect.objectContaining({ text: "Final unfinished reply", isFinal: false })], "Mia", "archive-call",
    );
    if (endMode === "leave") {
      act(() => { result.current.leave(); });
      unmount();
      expect(onConversationEnded).toHaveBeenCalledOnce();
    }
  });

  it("does not join while the prejoin camera check is pending", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "pending-camera",
      conversation_url: "https://tavus.daily.co/pending-camera",
    });
    let releaseCamera!: () => void;
    const call = createCallMock();
    call.startCamera.mockReturnValue(new Promise((resolve) => {
      releaseCamera = () => resolve({});
    }));
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    let startPromise!: Promise<void>;
    act(() => { startPromise = result.current.start(); });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.status).toBe("creating");
    await act(async () => { await result.current.join(); });
    expect(call.join).not.toHaveBeenCalled();
    await act(async () => { releaseCamera(); await startPromise; });
    expect(result.current.status).toBe("prejoin");
  });

  it("ends an orphaned conversation upstream when joining fails", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-6",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    call.join.mockRejectedValue(new Error("join failed"));
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));

    await act(async () => {
      await result.current.start();
      await result.current.join();
    });

    expect(endTavusConversation).toHaveBeenCalledWith("conv-6");
    expect(result.current.status).toBe("idle");
    expect(result.current.errorMessage).toBe("join failed");
  });

  it("resets to idle and surfaces the message when creation fails", async () => {
    vi.mocked(createTavusConversation).mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));

    await act(async () => {
      await result.current.start();
      await result.current.join();
    });

    expect(result.current.status).toBe("idle");
    expect(result.current.errorMessage).toBe("boom");
    expect(dailyMocks.createCallObject).not.toHaveBeenCalled();
  });

  it("destroys the call and ends the conversation upstream on leave", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-2",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
      await result.current.join();
    });

    act(() => {
      result.current.leave();
    });

    expect(call.leave).toHaveBeenCalled();
    expect(call.destroy).toHaveBeenCalled();
    expect(endTavusConversation).toHaveBeenCalledWith("conv-2");
    expect(result.current.status).toBe("ended");
  });

  it("auto-leaves shortly after the PAL is the last participant to leave", async () => {
    vi.useFakeTimers();
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-3",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
      await result.current.join();
    });

    const participantLeft = getEventHandler(call, "participant-left");
    act(() => {
      participantLeft();
    });
    expect(endTavusConversation).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1600);
    });

    expect(endTavusConversation).toHaveBeenCalledWith("conv-3");
  });

  it("keeps the call alive when other participants remain", async () => {
    vi.useFakeTimers();
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-4",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    call.participants.mockReturnValue({ remote: { session_id: "r1" } });
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
      await result.current.join();
    });

    const participantLeft = getEventHandler(call, "participant-left");
    act(() => {
      participantLeft();
    });
    await act(async () => {
      vi.advanceTimersByTime(1600);
    });

    expect(endTavusConversation).not.toHaveBeenCalled();
  });

  it("ends a late-created room after unmount and prevents duplicate starts", async () => {
    let resolveCreate!: (value: { conversation_id: string; conversation_url: string }) => void;
    vi.mocked(createTavusConversation).mockReturnValue(new Promise((resolve) => { resolveCreate = resolve; }));
    const { result, unmount } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    let pending!: Promise<void>;
    act(() => { pending = result.current.start(); });
    await act(async () => { await result.current.start(); await result.current.join(); });
    expect(createTavusConversation).toHaveBeenCalledTimes(1);
    unmount();
    await act(async () => {
      resolveCreate({ conversation_id: "late-room", conversation_url: "https://tavus.daily.co/late" });
      await pending;
    });
    expect(dailyMocks.createCallObject).not.toHaveBeenCalled();
    expect(endTavusConversation).toHaveBeenCalledWith("late-room");
  });

  it("auto-leaves when only the local participant remains", async () => {
    vi.useFakeTimers();
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "local-only", conversation_url: "https://tavus.daily.co/room",
    });
    const call = createCallMock();
    call.participants.mockReturnValue({ local: { local: true, session_id: "self" } });
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); await result.current.join(); });
    act(() => { getEventHandler(call, "participant-left")(); });
    await act(async () => { vi.advanceTimersByTime(1600); });
    expect(endTavusConversation).toHaveBeenCalledWith("local-only");
  });

  it("ignores a previous call's delayed leave event after restarting", async () => {
    vi.mocked(createTavusConversation)
      .mockResolvedValueOnce({ conversation_id: "old", conversation_url: "https://tavus.daily.co/old" })
      .mockResolvedValueOnce({ conversation_id: "new", conversation_url: "https://tavus.daily.co/new" });
    const oldCall = createCallMock();
    dailyMocks.createCallObject.mockReturnValueOnce(oldCall).mockReturnValueOnce(createCallMock());
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); await result.current.join(); });
    act(() => { result.current.leave(); });
    await act(async () => { await result.current.start(); await result.current.join(); });
    act(() => { getEventHandler(oldCall, "left-meeting")(); });
    expect(result.current.status).toBe("connected");
    expect(endTavusConversation).not.toHaveBeenCalledWith("new");
  });

  it("keeps a room when a remote participant rejoins during the grace period", async () => {
    vi.useFakeTimers();
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "rejoined", conversation_url: "https://tavus.daily.co/room",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);
    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => { await result.current.start(); await result.current.join(); });
    act(() => { getEventHandler(call, "participant-left")(); });
    call.participants.mockReturnValue({ remote: { local: false, session_id: "pal" } });
    await act(async () => { vi.advanceTimersByTime(1600); });
    expect(endTavusConversation).not.toHaveBeenCalled();
  });

  it("cleans up the call when the hook unmounts mid-conversation", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-5",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result, unmount } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
      await result.current.join();
    });

    unmount();

    expect(call.destroy).toHaveBeenCalled();
    expect(endTavusConversation).toHaveBeenCalledWith("conv-5");
  });

  it("handles conversation.utterance and streaming app messages with official Tavus properties payload", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-cvi",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start({ palName: "Gloria" });
      await result.current.join();
    });

    const appMessageHandler = getEventHandler(call, "app-message");

    // 1. Official Tavus streaming message with properties
    act(() => {
      appMessageHandler({
        data: {
          event_type: "conversation.utterance.streaming",
          properties: {
            role: "pal",
            text: "Hello there,",
          },
          participant_name: "Gloria",
        },
      });
    });

    expect(result.current.transcripts.length).toBe(1);
    expect(result.current.transcripts[0].speaker).toBe("pal");
    expect(result.current.transcripts[0].speakerName).toBe("Gloria");
    expect(result.current.transcripts[0].text).toBe("Hello there,");
    expect(result.current.transcripts[0].isFinal).toBe(false);
    expect(result.current.activeSubtitle?.text).toBe("Hello there,");

    // 2. Final completed utterance from Gloria
    act(() => {
      appMessageHandler({
        data: {
          event_type: "conversation.utterance",
          properties: {
            role: "pal",
            text: "Hello there, how can I help you today?",
          },
          participant_name: "Gloria",
        },
      });
    });

    // In-place update within 5s for non-final preceding item
    expect(result.current.transcripts.length).toBe(1);
    expect(result.current.transcripts[0].text).toBe("Hello there, how can I help you today?");
    expect(result.current.transcripts[0].isFinal).toBe(true);

    // 3. User utterance with official properties
    act(() => {
      appMessageHandler({
        data: {
          event_type: "conversation.utterance",
          properties: {
            role: "user",
            text: "Nice to meet you!",
          },
        },
      });
    });

    expect(result.current.transcripts.length).toBe(2);
    expect(result.current.transcripts[1].speaker).toBe("user");
    expect(result.current.transcripts[1].text).toBe("Nice to meet you!");
  });

  it("handles Daily native transcription-message events", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-transcription",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start({ palName: "Gloria" });
      await result.current.join();
    });

    const transcriptionHandler = getEventHandler(call, "transcription-message");

    act(() => {
      transcriptionHandler({
        action: "transcription-message",
        text: "I am speaking via Daily transcription",
        participantId: "remote-pal",
        isFinal: true,
      });
    });

    expect(result.current.transcripts.length).toBe(1);
    expect(result.current.transcripts[0].speaker).toBe("pal");
    expect(result.current.transcripts[0].speakerName).toBe("Gloria");
    expect(result.current.transcripts[0].text).toBe("I am speaking via Daily transcription");
  });

  it("groups streaming utterances by turn_idx and seals a superseded turn", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-turns",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start({ palName: "Gloria" });
      await result.current.join();
    });
    const appMessageHandler = getEventHandler(call, "app-message");

    const streaming = (text: string, turnIdx: number, seq: number) => ({
      data: {
        event_type: "conversation.utterance.streaming",
        properties: { role: "pal", text },
        turn_idx: turnIdx,
        seq,
      },
    });

    act(() => appMessageHandler(streaming("Hello", 1, 1)));
    act(() => appMessageHandler(streaming("Hello there", 1, 2)));
    expect(result.current.transcripts.length).toBe(1);
    expect(result.current.transcripts[0].text).toBe("Hello there");
    expect(result.current.transcripts[0].isFinal).toBe(false);

    // Same speaker but a new turn_idx: seal the previous turn, start fresh.
    act(() => appMessageHandler(streaming("Next answer", 2, 3)));
    expect(result.current.transcripts.length).toBe(2);
    expect(result.current.transcripts[0].isFinal).toBe(true);
    expect(result.current.transcripts[1].text).toBe("Next answer");
    expect(result.current.transcripts[1].isFinal).toBe(false);
  });

  it("uses the interaction event timestamp instead of the local clock", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-ts",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start({ palName: "Gloria" });
      await result.current.join();
    });
    const appMessageHandler = getEventHandler(call, "app-message");

    act(() => {
      appMessageHandler({
        data: {
          event_type: "conversation.utterance",
          properties: { role: "pal", text: "timestamped" },
          timestamp: 1759000000, // Unix epoch seconds, per Tavus docs
        },
      });
    });

    expect(result.current.transcripts[0].timestamp).toBe(1759000000 * 1000);
  });

  it("drops out-of-order utterance events by seq", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-seq",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start({ palName: "Gloria" });
      await result.current.join();
    });
    const appMessageHandler = getEventHandler(call, "app-message");

    const streaming = (text: string, seq: number) => ({
      data: {
        event_type: "conversation.utterance.streaming",
        properties: { role: "pal", text },
        turn_idx: 1,
        seq,
      },
    });

    act(() => appMessageHandler(streaming("newer words", 10)));
    act(() => appMessageHandler(streaming("stale words", 5)));
    expect(result.current.transcripts.length).toBe(1);
    expect(result.current.transcripts[0].text).toBe("newer words");
  });

  it("tracks PAL speaking state and seals the turn on interruption", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-speaking",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start({ palName: "Gloria" });
      await result.current.join();
    });
    const appMessageHandler = getEventHandler(call, "app-message");

    // Legacy duplicate events say "replica" instead of "pal".
    act(() => {
      appMessageHandler({
        data: { event_type: "conversation.started_speaking", properties: { role: "replica" }, seq: 1 },
      });
    });
    expect(result.current.isPalSpeaking).toBe(true);

    act(() => {
      appMessageHandler({
        data: {
          event_type: "conversation.utterance.streaming",
          properties: { role: "pal", text: "I was saying something" },
          turn_idx: 1,
          seq: 2,
        },
      });
    });
    expect(result.current.transcripts[0].isFinal).toBe(false);

    act(() => {
      appMessageHandler({
        data: {
          event_type: "conversation.stopped_speaking",
          properties: { role: "pal", interrupted: true, duration: 1.2 },
          seq: 3,
        },
      });
    });
    expect(result.current.isPalSpeaking).toBe(false);
    expect(result.current.transcripts[0].isFinal).toBe(true);
  });

  it("auto-leaves on conversation.left and cancels when the PAL rejoins", async () => {
    vi.useFakeTimers();
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-presence",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createCallObject.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
      await result.current.join();
    });
    const appMessageHandler = getEventHandler(call, "app-message");

    const presence = (eventType: string) => ({
      data: { event_type: eventType, properties: { role: "pal" } },
    });

    // PAL leaves, then rejoins inside the grace period: no auto-leave.
    act(() => appMessageHandler(presence("conversation.left")));
    act(() => appMessageHandler(presence("conversation.joined")));
    await act(async () => {
      vi.advanceTimersByTime(1600);
    });
    expect(endTavusConversation).not.toHaveBeenCalled();

    // PAL leaves for real: auto-leave after the grace period.
    act(() => appMessageHandler(presence("conversation.left")));
    await act(async () => {
      vi.advanceTimersByTime(1600);
    });
    expect(endTavusConversation).toHaveBeenCalledWith("conv-presence");
  });
});
