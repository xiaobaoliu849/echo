import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LiveAvatarPlayer from "../LiveAvatarPlayer";

describe("floating avatar movement", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    vi.stubGlobal("PointerEvent", class extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit) { super(type, init); this.pointerId = init.pointerId ?? 1; }
    });
    vi.stubGlobal("innerWidth", 1024);
    vi.stubGlobal("innerHeight", 768);
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  function setup() {
    const mute = vi.fn();
    const { container } = render(<LiveAvatarPlayer stream={new EventTarget()} isVoiceActive onToggleMute={mute} />);
    const player = container.querySelector<HTMLDivElement>(".vsLiveAvatarPlayer")!;
    vi.spyOn(player, "getBoundingClientRect").mockImplementation(() => ({
      left: parseFloat(player.style.left) || 800, top: parseFloat(player.style.top) || 460,
      width: 200, height: 300,
    } as DOMRect));
    player.setPointerCapture = vi.fn();
    player.releasePointerCapture = vi.fn();
    player.hasPointerCapture = () => true;
    fireEvent.click(screen.getByTitle("画中画悬浮"));
    return { player, mute };
  }

  it("captures a drag, clamps to the viewport and releases on cancellation", () => {
    const { player } = setup();
    fireEvent.pointerDown(screen.getByLabelText("移动分身窗口"), { button: 0, pointerId: 7, clientX: 850, clientY: 480 });
    expect(player.setPointerCapture).toHaveBeenCalledWith(7);
    fireEvent.pointerMove(player, { pointerId: 7, clientX: 350, clientY: 180 });
    expect(player.style.left).toBe("300px");
    expect(player.style.top).toBe("160px");
    fireEvent.pointerMove(player, { pointerId: 7, clientX: -1000, clientY: -1000 });
    expect(player.style.left).toBe("8px");
    expect(player.style.top).toBe("8px");
    fireEvent.pointerCancel(player, { pointerId: 7 });
    expect(player.releasePointerCapture).toHaveBeenCalledWith(7);
    fireEvent.pointerMove(player, { pointerId: 7, clientX: 850, clientY: 480 });
    expect(player.style.left).toBe("8px");
  });

  it("supports keyboard movement, resize recovery and clickable call controls", () => {
    const { player, mute } = setup();
    fireEvent.keyDown(screen.getByLabelText("移动分身窗口"), { key: "ArrowLeft" });
    expect(player.style.left).toBe("780px");
    fireEvent.pointerDown(screen.getByTitle("静音麦克风 (M)"), { button: 0, pointerId: 1 });
    fireEvent.click(screen.getByTitle("静音麦克风 (M)"));
    expect(mute).toHaveBeenCalledOnce();
    expect(player.setPointerCapture).not.toHaveBeenCalled();
    vi.stubGlobal("innerWidth", 600);
    vi.stubGlobal("innerHeight", 500);
    act(() => window.dispatchEvent(new Event("resize")));
    expect(player.style.left).toBe("392px");
    expect(player.style.top).toBe("192px");
    fireEvent.click(screen.getByTitle("还原舞台"));
    expect(player.style.left).toBe("");
  });
});
