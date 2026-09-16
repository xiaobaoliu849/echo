import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import useCanvas from "./useCanvas";
import { streamCanvasGenerate } from "../api";

vi.mock("../api", () => ({
  streamCanvasGenerate: vi.fn()
}));

describe("useCanvas", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should initialize with default state", () => {
    const { result } = renderHook(() => useCanvas());
    expect(result.current.messages).toEqual([]);
    expect(result.current.currentCode).toBe("");
    expect(result.current.codeHistory).toEqual([]);
    expect(result.current.isGenerating).toBe(false);
    expect(result.current.mode).toBe("react");
    expect(result.current.activeView).toBe("preview");
  });

  it("should generate from prompt", async () => {
    const mockStream = vi.mocked(streamCanvasGenerate).mockImplementation(async (_payload, handlers) => {
      handlers.onDelta("const App = () => <div>Hello</div>;");
      handlers.onDone?.();
    });

    const { result } = renderHook(() => useCanvas());

    await act(async () => {
      await result.current.generateFromPrompt("build a button");
    });

    expect(mockStream).toHaveBeenCalled();
    expect(result.current.messages.length).toBe(2);
    expect(result.current.currentCode).toContain("const App");
    expect(result.current.codeHistory.length).toBe(1);
  });

  it("should revise code", async () => {
    const { result } = renderHook(() => useCanvas());
    
    // Fake existing code
    act(() => {
      // Need to push to history/current code somehow, but it's internal.
      // We can just call reviseCode and see if it runs
    });

    const mockStream = vi.mocked(streamCanvasGenerate).mockResolvedValue(undefined);

    await act(async () => {
      await result.current.reviseCode("make it red");
    });

    expect(mockStream).toHaveBeenCalled();
  });

  it("should handle undo and clear", () => {
    const { result } = renderHook(() => useCanvas());
    
    act(() => {
      result.current.clearCanvas();
    });
    
    expect(result.current.messages.length).toBe(0);
    
    act(() => {
      result.current.undo();
    });
    expect(result.current.currentCode).toBe("");
  });
});
