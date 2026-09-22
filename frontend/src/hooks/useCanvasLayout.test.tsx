import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCanvasLayout } from "./useCanvasLayout";

let containerWidth = 1200;
let measure: () => void;
const disconnect = vi.fn();

function Harness() {
  const layout = useCanvasLayout();
  return <div ref={layout.layoutRef} data-testid="layout" data-compact={layout.compact} data-resizing={layout.resizing}>
    <div role="separator" aria-valuenow={layout.width} {...layout.separatorProps} />
  </div>;
}

beforeEach(() => {
  localStorage.clear();
  containerWidth = 1200;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(() => ({
    width: containerWidth, right: containerWidth, left: 0, top: 0, bottom: 800, height: 800, x: 0, y: 0, toJSON: () => ({}),
  }));
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { measure = callback; }
    observe() {}
    disconnect = disconnect;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("canvas resizing", () => {
  it("supports keyboard resize, bounds, reset and persistence", () => {
    const { unmount } = render(<Harness />);
    const separator = screen.getByRole("separator");
    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    expect(separator).toHaveAttribute("aria-valuenow", "50");
    unmount();
    render(<Harness />);
    const restored = screen.getByRole("separator");
    expect(restored).toHaveAttribute("aria-valuenow", "50");
    fireEvent.keyDown(restored, { key: "End" });
    expect(Number(restored.getAttribute("aria-valuenow"))).toBeCloseTo(830 / 1190 * 100);
    fireEvent.keyDown(restored, { key: "ArrowLeft" });
    expect(Number(restored.getAttribute("aria-valuenow"))).toBeCloseTo(830 / 1190 * 100);
    fireEvent.keyDown(restored, { key: "Home" });
    expect(Number(restored.getAttribute("aria-valuenow"))).toBeCloseTo(320 / 1190 * 100);
    fireEvent.doubleClick(restored);
    expect(restored).toHaveAttribute("aria-valuenow", "48");
  });

  it("clamps on container shrink without losing the preferred width", () => {
    localStorage.setItem("echo.canvas.widthPercent", "70");
    const { unmount } = render(<Harness />);
    act(() => { containerWidth = 800; measure(); });
    expect(Number(screen.getByRole("separator").getAttribute("aria-valuenow"))).toBeCloseTo(430 / 790 * 100);
    act(() => { containerWidth = 540; measure(); });
    expect(screen.getByTestId("layout")).toHaveAttribute("data-compact", "true");
    act(() => { containerWidth = 1600; measure(); });
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "70");
    unmount();
    expect(disconnect).toHaveBeenCalled();
  });

  it("keeps dragging bounded and stops on pointer cancellation", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    render(<Harness />);
    const separator = screen.getByRole("separator");
    separator.setPointerCapture = vi.fn();
    fireEvent.pointerDown(separator, { button: 0, clientX: 620 });
    expect(screen.getByTestId("layout")).toHaveAttribute("data-resizing", "true");
    fireEvent.pointerMove(separator, { clientX: 500 });
    expect(Number(separator.getAttribute("aria-valuenow"))).toBeGreaterThan(48);
    fireEvent.pointerMove(separator, { clientX: -500 });
    expect(Number(separator.getAttribute("aria-valuenow"))).toBeCloseTo(830 / 1190 * 100);
    fireEvent.pointerCancel(separator);
    const width = separator.getAttribute("aria-valuenow");
    fireEvent.pointerMove(separator, { clientX: 1000 });
    expect(separator).toHaveAttribute("aria-valuenow", width);
    expect(screen.getByTestId("layout")).toHaveAttribute("data-resizing", "false");
    fireEvent.pointerDown(separator, { button: 0, clientX: 620 });
    act(() => { containerWidth = 540; measure(); });
    expect(screen.getByTestId("layout")).toHaveAttribute("data-resizing", "false");
  });
});
