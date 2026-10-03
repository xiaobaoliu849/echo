import { useCallback, useEffect, useRef, useState, type PointerEvent, type KeyboardEvent } from "react";

/** Move the same player without remounting its media or escaping the viewport. */
export function useFloatingAvatar(floating: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: number; x: number; y: number; left: number; top: number } | null>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const move = useCallback((left: number, top: number) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    setPosition({
      left: Math.max(8, Math.min(left, window.innerWidth - rect.width - 8)),
      top: Math.max(8, Math.min(top, window.innerHeight - rect.height - 8)),
    });
  }, []);

  useEffect(() => {
    if (!floating) {
      drag.current = null;
      setPosition(null);
      return;
    }
    // Escape chat/canvas containment without moving or remounting the video.
    ref.current?.showPopover?.();
    const keepVisible = () => {
      const rect = ref.current?.getBoundingClientRect();
      if (rect) move(rect.left, rect.top);
    };
    keepVisible();
    window.addEventListener("resize", keepVisible);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(keepVisible);
    if (ref.current) observer?.observe(ref.current);
    return () => {
      const player = ref.current;
      if (player?.hidePopover && player.matches(":popover-open")) player.hidePopover();
      window.removeEventListener("resize", keepVisible);
      observer?.disconnect();
      drag.current = null;
    };
  }, [floating, move]);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!floating || event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("button:not(.vsAvatarDragHandle), .vsAvatarCaptions")) return;
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, left: rect.left, top: rect.top };
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (start && start.id === event.pointerId) move(start.left + event.clientX - start.x, start.top + event.clientY - start.y);
  };
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.id !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const delta = { ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20] }[event.key];
    const rect = ref.current?.getBoundingClientRect();
    if (!delta || !rect || !floating) return;
    event.preventDefault();
    move(rect.left + delta[0], rect.top + delta[1]);
  };
  return {
    ref,
    style: floating && position ? { ...position, right: "auto", bottom: "auto" } : undefined,
    pointerProps: { onPointerDown, onPointerMove, onPointerUp: endDrag, onPointerCancel: endDrag, onLostPointerCapture: () => { drag.current = null; } },
    onKeyDown,
  };
}
