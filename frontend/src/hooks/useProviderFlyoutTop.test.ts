import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useProviderFlyoutTop } from "./useProviderFlyoutTop";

describe("useProviderFlyoutTop", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns 0 flyoutTop when closed or activeProvider is empty", () => {
    const { result } = renderHook(() => useProviderFlyoutTop(false, ""));
    expect(result.current.flyoutTop).toBe(0);
  });

  it("calculates flyoutTop from bounding client rect and clamps within panel", () => {
    const { result } = renderHook(() => useProviderFlyoutTop(true, "DashScope"));

    // Set up mock panel and row
    const panel = document.createElement("div");
    const row = document.createElement("button");

    vi.spyOn(panel, "clientHeight", "get").mockReturnValue(400);
    vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({
      top: 100,
      bottom: 500,
      left: 0,
      right: 200,
      width: 200,
      height: 400,
      x: 0,
      y: 100,
      toJSON: () => {},
    });

    vi.spyOn(row, "getBoundingClientRect").mockReturnValue({
      top: 150,
      bottom: 186,
      left: 0,
      right: 200,
      width: 200,
      height: 36,
      x: 0,
      y: 150,
      toJSON: () => {},
    });

    act(() => {
      result.current.panelRef.current = panel;
      result.current.onRowRef("DashScope", row);
    });

    // Re-render hook with activeProvider set so effect triggers
    const { result: activeResult } = renderHook(() => {
      const hook = useProviderFlyoutTop(true, "DashScope");
      hook.panelRef.current = panel;
      hook.onRowRef("DashScope", row);
      return hook;
    });

    // visualTop = 150 - 100 = 50px
    expect(activeResult.current.flyoutTop).toBe(50);
  });

  it("updates flyoutTop on scroll of the scroll container", () => {
    const panel = document.createElement("div");
    const scrollContainer = document.createElement("div");
    scrollContainer.className = "vsVoiceLevel1Scroll";
    panel.appendChild(scrollContainer);

    const row = document.createElement("button");

    vi.spyOn(panel, "clientHeight", "get").mockReturnValue(400);
    vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({
      top: 100,
      bottom: 500,
      left: 0,
      right: 200,
      width: 200,
      height: 400,
      x: 0,
      y: 100,
      toJSON: () => {},
    });

    let rowTop = 150;
    vi.spyOn(row, "getBoundingClientRect").mockImplementation(() => ({
      top: rowTop,
      bottom: rowTop + 36,
      left: 0,
      right: 200,
      width: 200,
      height: 36,
      x: 0,
      y: rowTop,
      toJSON: () => {},
    }));

    const { result } = renderHook(() => {
      const hook = useProviderFlyoutTop(true, "DashScope");
      hook.panelRef.current = panel;
      hook.onRowRef("DashScope", row);
      return hook;
    });

    expect(result.current.flyoutTop).toBe(50);

    // Simulate scrolling down by 20px
    act(() => {
      rowTop = 130;
      scrollContainer.dispatchEvent(new Event("scroll"));
    });

    // visualTop = 130 - 100 = 30px
    expect(result.current.flyoutTop).toBe(30);
  });

  it("safely calls scrollToRow", () => {
    const row = document.createElement("button");
    const scrollSpy = vi.fn();
    row.scrollIntoView = scrollSpy;

    const { result } = renderHook(() => {
      const hook = useProviderFlyoutTop(true, "DashScope");
      hook.onRowRef("DashScope", row);
      return hook;
    });

    act(() => {
      result.current.scrollToRow("DashScope");
    });

    expect(scrollSpy).toHaveBeenCalledWith({ block: "nearest" });
  });
});
