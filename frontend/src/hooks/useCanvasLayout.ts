import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

const STORAGE_KEY = "echo.canvas.widthPercent";
const DEFAULT_WIDTH = 48;
const DIVIDER_WIDTH = 10;

export function useCanvasLayout(enabled = true) {
  const layoutRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ pointerId: number; offset: number } | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [resizing, setResizing] = useState(false);
  const [preferredWidth, setPreferredWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(STORAGE_KEY));
      return saved >= 25 && saved <= 75 ? saved : DEFAULT_WIDTH;
    } catch { return DEFAULT_WIDTH; }
  });

  useEffect(() => {
    const element = layoutRef.current;
    if (!element) return;
    const measure = () => setContainerWidth(element.getBoundingClientRect().width);
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Keep both panes usable; stacked layouts depend on the workspace, not the viewport.
  const compact = containerWidth > 0 && containerWidth < 760;
  const available = Math.max(1, containerWidth - DIVIDER_WIDTH);
  const min = Math.min(50, Math.max(25, 320 / available * 100));
  const max = Math.max(min, Math.min(75, (available - 360) / available * 100));
  const width = Math.min(max, Math.max(min, preferredWidth));

  useEffect(() => {
    if (!enabled || compact) {
      drag.current = null;
      setResizing(false);
    }
  }, [enabled, compact]);

  const updateWidth = (value: number) => {
    const next = Math.min(max, Math.max(min, value));
    setPreferredWidth(next);
    try { localStorage.setItem(STORAGE_KEY, String(next)); } catch { /* Storage can be unavailable. */ }
  };

  const stopDragging = () => {
    drag.current = null;
    setResizing(false);
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || drag.current || !enabled || compact || !layoutRef.current) return;
    event.preventDefault();
    const bounds = layoutRef.current.getBoundingClientRect();
    drag.current = { pointerId: event.pointerId, offset: bounds.right - event.clientX - available * width / 100 };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus();
    setResizing(true);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId || !layoutRef.current || compact) return;
    const bounds = layoutRef.current.getBoundingClientRect();
    updateWidth((bounds.right - event.clientX - drag.current.offset) / available * 100);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const values: Record<string, number> = {
      ArrowLeft: width + 2, ArrowRight: width - 2, Home: min, End: max, Enter: DEFAULT_WIDTH,
    };
    if (event.key in values) {
      event.preventDefault();
      updateWidth(values[event.key]);
    }
  };

  return {
    layoutRef, compact, resizing, width, min, max,
    separatorProps: {
      onPointerDown, onPointerMove, onPointerUp: stopDragging,
      onPointerCancel: stopDragging, onLostPointerCapture: stopDragging,
      onKeyDown, onDoubleClick: () => updateWidth(DEFAULT_WIDTH),
    },
  };
}
