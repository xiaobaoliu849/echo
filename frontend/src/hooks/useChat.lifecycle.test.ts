import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FormEvent } from "react";
import {
  ensureEverMemConversationGroupId,
  getPersistedEverMemConversationGroupId,
  streamChatCompletion,
} from "../api";
import useChat from "./useChat";

vi.mock("../api", async () => ({
  ...await vi.importActual<typeof import("../api")>("../api"),
  ensureEverMemConversationGroupId: vi.fn(),
  streamChatCompletion: vi.fn(),
}));

const options = {
  formatErrorMessage: (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback,
  providerOptions: ["DashScope"],
  preferredProvider: "DashScope",
  providerModelCatalog: { DashScope: { defaultModel: "qwen-plus", availableModels: ["qwen-plus"] } },
};
const submitEvent = { preventDefault: () => {} } as FormEvent;
const restored = [
  { id: "restored-user", role: "user" as const, content: "Saved question" },
  { id: "restored-reply", role: "assistant" as const, content: "Saved answer" },
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

describe.each(["send", "regenerate"] as const)("chat %s lifecycle", (operation) => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    vi.mocked(ensureEverMemConversationGroupId).mockResolvedValue("group-current");
  });
  afterEach(() => { localStorage.clear(); });

  function begin() {
    const hook = renderHook(() => useChat(options));
    act(() => {
      if (operation === "send") hook.result.current.onInputChange("Question");
      else hook.result.current.replaceSession(restored);
    });
    let pending!: Promise<void>;
    act(() => {
      pending = operation === "send"
        ? hook.result.current.onSubmit(submitEvent)
        : hook.result.current.onRegenerateMessage(1);
    });
    return { ...hook, pending };
  }

  it.each(["new", "restore", "unmount"])("ignores late memory setup after %s", async (action) => {
    const memory = deferred<string>();
    vi.mocked(ensureEverMemConversationGroupId).mockReturnValue(memory.promise);
    const { result, pending, unmount } = begin();
    act(() => {
      if (action === "new") result.current.onNewSession();
      else if (action === "restore") result.current.replaceSession(restored, "group-restored");
      else unmount();
    });
    await act(async () => { memory.resolve("group-obsolete"); await pending; });
    expect(streamChatCompletion).not.toHaveBeenCalled();
    expect(getPersistedEverMemConversationGroupId("chat")).toBe(action === "restore" ? "group-restored" : "");
  });

  it("ignores stale deltas, reasoning, metadata and errors after restoring a session", async () => {
    const stream = deferred<void>();
    vi.mocked(streamChatCompletion).mockReturnValue(stream.promise);
    const { result, pending } = begin();
    await act(async () => {});
    const [, handlers, request] = vi.mocked(streamChatCompletion).mock.calls[0];
    act(() => { result.current.replaceSession(restored, "group-restored"); });
    expect(request?.signal?.aborted).toBe(true);
    await act(async () => {
      handlers.onDelta("Old reply");
      handlers.onReasoning?.("Old reasoning");
      handlers.onDone?.({ memorySaved: true, memoriesRetrieved: 4 });
      stream.reject(new Error("Old connection failed"));
      await pending;
    });
    expect(result.current.chatMessages).toEqual(restored);
    expect(result.current.chatError).toBe("");
    expect(result.current.chatBusy).toBe(false);
  });

  it("aborts the transport when the hook unmounts", async () => {
    const stream = deferred<void>();
    vi.mocked(streamChatCompletion).mockReturnValue(stream.promise);
    const { pending, unmount } = begin();
    await act(async () => {});
    const request = vi.mocked(streamChatCompletion).mock.calls[0][2];
    unmount();
    expect(request?.signal?.aborted).toBe(true);
    await act(async () => { stream.resolve(); await pending; });
  });

  it("updates the originating reply even when another message is appended", async () => {
    const stream = deferred<void>();
    vi.mocked(streamChatCompletion).mockReturnValue(stream.promise);
    const { result, pending } = begin();
    await act(async () => {});
    const handlers = vi.mocked(streamChatCompletion).mock.calls[0][1];
    act(() => { result.current.injectMessage("assistant", "Independent message"); });
    await act(async () => {
      handlers.onDelta("Correct reply");
      handlers.onReasoning?.("Reasoning");
      handlers.onDone?.({ memorySaved: true, memoriesRetrieved: 2 });
      stream.resolve();
      await pending;
    });
    expect(result.current.chatMessages[0].memorySaved).toBe(true);
    expect(result.current.chatMessages[1]).toMatchObject({ content: "Correct reply", reasoningContent: "Reasoning", memoriesUsed: 2 });
    expect(result.current.chatMessages[2].content).toBe("Independent message");
  });

  it.each([false, true])("handles a current stream failure with partial content: %s", async (hasContent) => {
    const stream = deferred<void>();
    vi.mocked(streamChatCompletion).mockReturnValue(stream.promise);
    const { result, pending } = begin();
    await act(async () => {});
    const handlers = vi.mocked(streamChatCompletion).mock.calls[0][1];
    await act(async () => {
      if (hasContent) handlers.onDelta("Partial reply");
      stream.reject(new Error("Connection lost"));
      await pending;
    });
    expect(result.current.chatMessages).toHaveLength(hasContent ? 2 : 1);
    if (hasContent) expect(result.current.chatMessages[1].content).toBe("Partial reply");
    expect(result.current.chatError).toContain("Connection lost");
    expect(result.current.chatBusy).toBe(false);
  });

  it("continues without memory if memory setup fails", async () => {
    vi.mocked(ensureEverMemConversationGroupId).mockRejectedValue(new Error("Memory offline"));
    vi.mocked(streamChatCompletion).mockImplementation(async (_, handlers) => { handlers.onDelta("Reply without memory"); });
    const { result, pending } = begin();
    await act(async () => { await pending; });
    expect(result.current.chatMessages[1].content).toBe("Reply without memory");
    expect(result.current.chatError).toBe("");
  });

  it("leaves the new request busy when the obsolete request fails", async () => {
    const oldStream = deferred<void>();
    const newStream = deferred<void>();
    vi.mocked(streamChatCompletion).mockReturnValueOnce(oldStream.promise).mockReturnValueOnce(newStream.promise);
    const { result, pending } = begin();
    await act(async () => {});
    act(() => { result.current.onNewSession(); });
    act(() => { result.current.onInputChange("New question"); });
    let next!: Promise<void>;
    await act(async () => { next = result.current.onSubmit(submitEvent); });
    await act(async () => { oldStream.reject(new Error("Old failure")); await pending; });
    expect(result.current.chatBusy).toBe(true);
    expect(result.current.chatError).toBe("");
    expect(result.current.chatMessages[0].content).toBe("New question");
    await act(async () => { newStream.resolve(); await next; });
    expect(result.current.chatBusy).toBe(false);
  });
});

it("preserves attachments and request options when regenerating a reply", async () => {
  vi.resetAllMocks();
  vi.mocked(ensureEverMemConversationGroupId).mockResolvedValue("");
  vi.mocked(streamChatCompletion).mockImplementation(async (_, handlers) => { handlers.onDelta("Answer"); });
  const { result } = renderHook(() => useChat(options));
  const attachment = { name: "notes.txt", content: "Important evidence" };
  act(() => {
    result.current.onInputChange("Summarize");
    result.current.addChatAttachment(attachment);
    result.current.setUseMemory(false);
    result.current.setDeepThinking(true);
  });
  await act(async () => { await result.current.onSubmit(submitEvent); });
  expect(result.current.chatMessages[0].attachments).toEqual([attachment]);
  await act(async () => { await result.current.onRegenerateMessage(1); });
  const requests = vi.mocked(streamChatCompletion).mock.calls.map(call => call[0]);
  expect(requests[1]).toEqual(requests[0]);
  expect(requests[1]).toMatchObject({ provider: "DashScope", model: "qwen-plus", use_memory: false, deep_thinking: true });
  expect(requests[1].messages[0].content).toContain("Important evidence");
  expect(result.current.chatMessages).toHaveLength(2);
});
