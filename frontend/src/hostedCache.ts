import { useCallback, useEffect, useState } from "react";
import { fetchHostedHistory, getAuthRuntimeConfig } from "./api";

/**
 * Stale-while-revalidate cache for the hosted settings page.
 *
 * Every settings tab used to fetch on mount, so each tab switch waited a full
 * round trip to the hosted server (and, for memory, on to EverOS). Results
 * are now kept per account for the page's lifetime: a tab shows the last
 * value at once and refreshes in the background. Concurrent requests for the
 * same key share one promise, so opening the page can prefetch every tab.
 *
 * A local write (putCached) bumps the entry's generation; a fetch that
 * started before it is still shared but its result is discarded, so a slow
 * revalidation can never undo a toggle, a save or an erase.
 */

type Entry = { value?: unknown; has: boolean; at: number; gen: number; pending?: Promise<unknown> };

const entries = new Map<string, Entry>();
// A value younger than this is not refetched when a tab opens again.
const FRESH_MS = 15_000;

function scopedKey(key: string): string {
  return `${getAuthRuntimeConfig().apiToken}\u0000${key}`;
}

function entryFor(id: string): Entry {
  let entry = entries.get(id);
  if (!entry) {
    entry = { has: false, at: 0, gen: 0 };
    entries.set(id, entry);
  }
  return entry;
}

export function loadCached<T>(key: string, fetcher: () => Promise<T>, force = false): Promise<T> {
  const entry = entryFor(scopedKey(key));
  if (entry.pending) {
    return entry.pending as Promise<T>;
  }
  if (!force && entry.has && Date.now() - entry.at < FRESH_MS) {
    return Promise.resolve(entry.value as T);
  }
  const gen = entry.gen;
  const pending: Promise<T> = fetcher().then(
    (value) => {
      if (entry.pending === pending) {
        entry.pending = undefined;
      }
      if (entry.gen !== gen) {
        return entry.value as T; // overtaken by a local write
      }
      entry.value = value;
      entry.has = true;
      entry.at = Date.now();
      return value;
    },
    (err) => {
      if (entry.pending === pending) {
        entry.pending = undefined; // the last good value stays
      }
      throw err;
    },
  );
  entry.pending = pending;
  return pending;
}

export function peekCached<T>(key: string): T | undefined {
  return entries.get(scopedKey(key))?.value as T | undefined;
}

/** Record a value from a local change (a saved preference, a toggle, an erase). */
export function putCached<T>(key: string, value: T): void {
  const entry = entryFor(scopedKey(key));
  entry.value = value;
  entry.has = true;
  entry.at = Date.now();
  entry.gen += 1;
}

/** The cached value at once (if any), refreshed in the background. */
export function useCachedResource<T>(key: string, fetcher: () => Promise<T>) {
  const [data, setDataState] = useState<T | undefined>(() => peekCached<T>(key));
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setDataState(peekCached<T>(key));
    loadCached(key, fetcher)
      .then(() => {
        if (!cancelled) {
          // Read back from the cache: a local write may have won meanwhile.
          setDataState(peekCached<T>(key));
          setError(null);
        }
      })
      .catch((err) => !cancelled && setError(err));
    return () => {
      cancelled = true;
    };
    // The fetcher is identified by its key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const setData = useCallback(
    (value: T) => {
      putCached(key, value);
      setDataState(value);
    },
    [key],
  );
  return { data, error, setData };
}

/** The practice heatmap's history: 26 whole weeks (the Account tab filters it to 30 days). */
export const PROGRESS_DAYS = 26 * 7;
export const PROGRESS_KEY = `history:${PROGRESS_DAYS}`;
export const loadProgressHistory = () => fetchHostedHistory(PROGRESS_DAYS);

/** Preferences are also saved outside settings (onboarding, the call popover). */
export const PREFS_KEY = "prefs";
