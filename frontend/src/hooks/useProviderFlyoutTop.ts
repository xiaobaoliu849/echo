import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState, type RefObject } from "react";

const FLYOUT_VIEWPORT_MARGIN = 12;
const FLYOUT_MAX_HEIGHT = 720;

/**
 * Keeps a cascading flyout (absolutely positioned inside the settings panel)
 * inside the window. It starts on the browsed row (`preferredTop`, relative to
 * the panel) and slides up only as far as its content needs, so a long list
 * uses the whole window height before it scrolls. The panel itself opens
 * upward and is only as tall as its rows, so sizing a flyout against the
 * panel's max height pushes it off the bottom of the window.
 */
export function useFlyoutViewportFit(panelRef: RefObject<HTMLElement | null>, preferredTop: number) {
  const flyoutRef = useRef<HTMLDivElement | null>(null);
  const [, bumpResize] = useReducer((n: number) => n + 1, 0);

  useEffect(() => {
    window.addEventListener("resize", bumpResize);
    return () => window.removeEventListener("resize", bumpResize);
  }, []);

  // Runs after every render: content (coach fields, voice lists) changes the
  // flyout's height without changing any input of this hook. The position is
  // written straight onto the element so measuring never costs a re-render.
  useLayoutEffect(() => {
    const flyout = flyoutRef.current;
    const panel = panelRef.current;
    if (!flyout || !panel) return;
    const panelRect = panel.getBoundingClientRect();
    if (panelRect.height === 0) {
      // Not laid out (hidden, or a test DOM): keep the row alignment.
      flyout.style.top = `${preferredTop}px`;
      flyout.style.maxHeight = "";
      return;
    }
    const viewportHeight = window.innerHeight;
    const maxHeight = Math.max(160, Math.min(FLYOUT_MAX_HEIGHT, viewportHeight - FLYOUT_VIEWPORT_MARGIN * 2));
    const borders = flyout.offsetHeight - flyout.clientHeight;
    const height = Math.min(flyout.scrollHeight + borders, maxHeight);
    const lowestTop = viewportHeight - FLYOUT_VIEWPORT_MARGIN - height;
    const viewportTop = Math.max(FLYOUT_VIEWPORT_MARGIN, Math.min(panelRect.top + preferredTop, lowestTop));
    flyout.style.maxHeight = `${maxHeight}px`;
    flyout.style.top = `${Math.round(viewportTop - panelRect.top)}px`;
  });

  return flyoutRef;
}

/**
 * Aligns a cascading Level-2 model flyout with the currently hovered/selected
 * Level-1 provider row, instead of always pinning it to the top of the panel.
 *
 * Usage: attach `panelRef` to the settings panel and `onRowRef` to every
 * Level-1 provider row button. `activeProvider` is the provider whose row the
 * flyout should line up with; pass "" while no row is active to keep the
 * flyout top-aligned.
 */
export function useProviderFlyoutTop(open: boolean, activeProvider: string) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const rowsRef = useRef(new Map<string, HTMLButtonElement>());
  const [flyoutTop, setFlyoutTop] = useState(0);

  const onRowRef = useCallback((provider: string, el: HTMLButtonElement | null) => {
    if (el) {
      rowsRef.current.set(provider, el);
    } else {
      rowsRef.current.delete(provider);
    }
  }, []);

  const updateFlyoutTop = useCallback(() => {
    if (!open || !activeProvider) {
      setFlyoutTop(0);
      return;
    }
    const row = rowsRef.current.get(activeProvider);
    if (row) {
      if (panelRef.current && panelRef.current.clientHeight > 0) {
        const rowRect = row.getBoundingClientRect();
        const panelRect = panelRef.current.getBoundingClientRect();
        const visualTop = rowRect.top - panelRect.top;
        const maxTop = Math.max(0, panelRef.current.clientHeight - 60);
        const clampedTop = Math.max(0, Math.min(visualTop, maxTop));
        setFlyoutTop(clampedTop);
      } else {
        setFlyoutTop(row.offsetTop);
      }
    }
  }, [open, activeProvider]);

  useEffect(() => {
    updateFlyoutTop();
  }, [updateFlyoutTop]);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    const scrollContainer = panel.querySelector(".vsVoiceLevel1Scroll") || panel;
    scrollContainer.addEventListener("scroll", updateFlyoutTop, { passive: true });
    window.addEventListener("resize", updateFlyoutTop);
    return () => {
      scrollContainer.removeEventListener("scroll", updateFlyoutTop);
      window.removeEventListener("resize", updateFlyoutTop);
    };
  }, [open, updateFlyoutTop]);

  const scrollToRow = useCallback((provider: string) => {
    const row = rowsRef.current.get(provider);
    if (row && typeof row.scrollIntoView === "function") {
      row.scrollIntoView({ block: "nearest" });
    }
  }, []);

  return { panelRef, onRowRef, flyoutTop, scrollToRow };
}
