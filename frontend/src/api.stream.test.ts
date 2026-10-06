import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiTimeoutError, fetchSettings, streamChatCompletion } from "./api";

function createStreamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("chat stream parsing", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves leading spaces inside streamed delta chunks", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createStreamResponse([
        'event: delta\ndata: {"content":"Hello"}\n\n',
        'event: delta\ndata: {"content":" there"}\n\n',
        'event: done\ndata: {"memories_retrieved":1,"memory_saved":true}\n\n',
      ])
    );
    vi.stubGlobal("fetch", fetchMock);

    let output = "";
    let meta: { memoriesRetrieved: number; memorySaved: boolean } | undefined;
    await streamChatCompletion(
      {
        provider: "DashScope",
        model: "qwen-plus",
        messages: [{ role: "user", content: "hello" }],
      },
      {
        onDelta: (chunk) => {
          output += chunk;
        },
        onDone: (result) => {
          meta = result;
        },
      }
    );

    expect(output).toBe("Hello there");
    expect(meta).toEqual({ memoriesRetrieved: 1, memorySaved: true });
  });

  it("handles reasoning SSE events correctly", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createStreamResponse([
        'event: reasoning\ndata: {"content":"Analyzing..."}\n\n',
        'event: delta\ndata: {"content":"Final answer"}\n\n',
        'event: done\ndata: {"memories_retrieved":0,"memory_saved":false}\n\n',
      ])
    );
    vi.stubGlobal("fetch", fetchMock);

    let reasoningText = "";
    let deltaText = "";
    await streamChatCompletion(
      {
        provider: "DashScope",
        model: "qwen-max",
        messages: [{ role: "user", content: "test" }],
      },
      {
        onDelta: (chunk) => {
          deltaText += chunk;
        },
        onReasoning: (chunk) => {
          reasoningText += chunk;
        },
      }
    );

    expect(reasoningText).toBe("Analyzing...");
    expect(deltaText).toBe("Final answer");
  });

  it("skips a malformed SSE event instead of killing the whole stream", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createStreamResponse([
        'event: delta\ndata: {"content":"Hello"}\n\n',
        'event: delta\ndata: {this is not json\n\n',
        'event: delta\ndata: {"content":" world"}\n\n',
        'event: done\ndata: {"memories_retrieved":0,"memory_saved":false}\n\n',
      ])
    );
    vi.stubGlobal("fetch", fetchMock);

    let output = "";
    let doneCalled = false;
    await streamChatCompletion(
      {
        provider: "DashScope",
        model: "qwen-plus",
        messages: [{ role: "user", content: "hello" }],
      },
      {
        onDelta: (chunk) => {
          output += chunk;
        },
        onDone: () => {
          doneCalled = true;
        },
      }
    );

    expect(output).toBe("Hello world");
    expect(doneCalled).toBe(true);
  });

  it("rejects a stream that ends without a done event and keeps the partial text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      createStreamResponse(['event: delta\ndata: {"content":"Half an ans"}\n\n'])
    ));

    let output = "";
    const onDone = vi.fn();
    await expect(
      streamChatCompletion(
        { provider: "DashScope", model: "qwen-plus", messages: [{ role: "user", content: "hi" }] },
        { onDelta: (chunk) => { output += chunk; }, onDone }
      )
    ).rejects.toThrow();

    expect(output).toBe("Half an ans");
    expect(onDone).not.toHaveBeenCalled();
  });

  it("accepts a done event in the trailing buffer without a blank-line terminator", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      createStreamResponse([
        'event: delta\ndata: {"content":"ok"}\n\n',
        'event: done\ndata: {"memories_retrieved":0,"memory_saved":false}',
      ])
    ));

    const onDone = vi.fn();
    await streamChatCompletion(
      { provider: "DashScope", model: "qwen-plus", messages: [{ role: "user", content: "hi" }] },
      { onDelta: () => {}, onDone }
    );

    expect(onDone).toHaveBeenCalledTimes(1);
  });
});

describe("control-plane request timeout", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fails a hung settings request with ApiTimeoutError instead of waiting forever", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError"))
        );
      })
    ));

    const pending = fetchSettings();
    const assertion = expect(pending).rejects.toBeInstanceOf(ApiTimeoutError);
    await vi.advanceTimersByTimeAsync(30_000);
    await assertion;
  });
});
