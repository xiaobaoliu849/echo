import { useCallback, useEffect, useRef, useState } from "react";

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

  useEffect(() => {
    if (!open || !activeProvider) {
      setFlyoutTop(0);
      return;
    }
    const row = rowsRef.current.get(activeProvider);
    if (row) {
      // offsetTop is relative to the panel (the row's positioned ancestor),
      // matching the flyout's own absolute positioning context.
      setFlyoutTop(row.offsetTop);
    }
  }, [open, activeProvider]);

  return { panelRef, onRowRef, flyoutTop };
}
