import { type ComponentType, lazy, type LazyExoticComponent } from "react";

export function lazyWithRetry<T extends ComponentType<any>>(
  componentImport: () => Promise<{ default: T }>
): LazyExoticComponent<T> {
  return lazy(async () => {
    const sessionKey = "vs_chunk_retry_pending";
    try {
      const component = await componentImport();
      try {
        sessionStorage.removeItem(sessionKey);
      } catch {
        // Ignore storage access errors in sandboxed environments
      }
      return component;
    } catch (error) {
      let hasRetried = false;
      try {
        hasRetried = Boolean(sessionStorage.getItem(sessionKey));
      } catch {
        // Ignore storage access errors
      }

      if (!hasRetried) {
        try {
          sessionStorage.setItem(sessionKey, "1");
        } catch {
          // Ignore
        }
        window.location.reload();
        return new Promise<{ default: T }>(() => {});
      }

      try {
        sessionStorage.removeItem(sessionKey);
      } catch {
        // Ignore
      }
      throw error;
    }
  });
}
