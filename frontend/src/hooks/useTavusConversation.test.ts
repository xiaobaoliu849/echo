import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useTavusConversation from "./useTavusConversation";
import { createTavusConversation, endTavusConversation } from "../api";

const dailyMocks = vi.hoisted(() => ({
  createFrame: vi.fn(),
}));

vi.mock("../api", () => ({
  createTavusConversation: vi.fn(),
  endTavusConversation: vi.fn(),
}));

vi.mock("@daily-co/daily-js", () => ({
  default: {
    createFrame: dailyMocks.createFrame,
  },
}));

type CallMock = {
  join: ReturnType<typeof vi.fn>;
  leave: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  participants: ReturnType<typeof vi.fn>;
};

function createCallMock(): CallMock {
  return {
    join: vi.fn().mockResolvedValue({}),
    leave: vi.fn().mockResolvedValue(undefined),
    destroy: vi.fn(),
    on: vi.fn(),
    participants: vi.fn(() => ({})),
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
    dailyMocks.createFrame.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("creates a conversation, attaches a frame, and joins the room", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-1",
      conversation_url: "https://tavus.daily.co/room?t=token",
      meeting_token: "meeting-token-1",
    });
    const call = createCallMock();
    dailyMocks.createFrame.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    const container = document.createElement("div");
    act(() => result.current.attachVideoContainer(container));

    await act(async () => {
      await result.current.start({ palId: "pal-1" });
    });

    expect(createTavusConversation).toHaveBeenCalledWith({
      palId: "pal-1",
      conversationName: undefined,
    });
    expect(dailyMocks.createFrame).toHaveBeenCalledWith(container);
    expect(call.join).toHaveBeenCalledWith({
      url: "https://tavus.daily.co/room?t=token",
      token: "meeting-token-1",
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
    dailyMocks.createFrame.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
    });

    expect(call.join).toHaveBeenCalledWith({ url: "https://tavus.daily.co/room?t=token" });
    expect(result.current.status).toBe("connected");
  });

  it("ends an orphaned conversation upstream when joining fails", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-6",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    call.join.mockRejectedValue(new Error("join failed"));
    dailyMocks.createFrame.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));

    await act(async () => {
      await result.current.start();
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
    });

    expect(result.current.status).toBe("idle");
    expect(result.current.errorMessage).toBe("boom");
    expect(dailyMocks.createFrame).not.toHaveBeenCalled();
  });

  it("destroys the frame and ends the conversation upstream on leave", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-2",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createFrame.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
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
    dailyMocks.createFrame.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
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
    dailyMocks.createFrame.mockReturnValue(call);

    const { result } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
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

  it("cleans up the call when the hook unmounts mid-conversation", async () => {
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-5",
      conversation_url: "https://tavus.daily.co/room?t=token",
    });
    const call = createCallMock();
    dailyMocks.createFrame.mockReturnValue(call);

    const { result, unmount } = renderHook(() => useTavusConversation({ formatErrorMessage: formatErrorStub }));
    await act(async () => {
      await result.current.start();
    });

    unmount();

    expect(call.destroy).toHaveBeenCalled();
    expect(endTavusConversation).toHaveBeenCalledWith("conv-5");
  });
});
