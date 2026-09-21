import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelLocalVoiceSetup,
  fetchLocalVoiceSetupJob,
  fetchLocalVoiceStatus,
  startLocalVoiceServer,
  startLocalVoiceSetup,
  stopLocalVoiceServer,
} from "../api/client";
import type {
  LocalVoiceProviderStatus,
  LocalVoiceSetupJob,
} from "../api/types";

export type LocalVoicePhase =
  | "not-installed"
  | "installing"
  | "installed"      // runtime + models ready, server stopped
  | "starting"
  | "running"
  | "error";

export type LocalVoiceProviderState = {
  status: LocalVoiceProviderStatus;
  phase: LocalVoicePhase;
  setupJob: LocalVoiceSetupJob | null;
  error: string | null;
};

export type UseLocalVoiceStatusResult = {
  providers: Record<string, LocalVoiceProviderState>;
  loading: boolean;
  /** False until the status endpoint answered once — badges stay hidden. */
  loaded: boolean;
  refresh: () => Promise<void>;
  setup: (provider: string, hfToken?: string) => Promise<void>;
  cancelSetup: (provider: string) => Promise<void>;
  startServer: (provider: string, hfToken?: string) => Promise<void>;
  stopServer: (provider: string) => Promise<void>;
};

type SetupWatcher = {
  cancelled: boolean;
  timer?: ReturnType<typeof setTimeout>;
};

function stopWatcher(watcher: SetupWatcher) {
  watcher.cancelled = true;
  clearTimeout(watcher.timer);
}

export function derivePhase(
  status: LocalVoiceProviderStatus,
  setupJob: LocalVoiceSetupJob | null,
  starting: boolean,
  error: string | null
): LocalVoicePhase {
  if (setupJob?.status === "running") return "installing";
  if (status.server_running) return "running";
  if (starting) return "starting";
  if (error) return "error";
  if (status.installed) return "installed";
  return "not-installed";
}

/**
 * Polls /api/realtime-local/status and drives setup-job polling, following
 * the TranscriptionPage polling pattern (2.5s cadence, cleanup flag).
 */
export function useLocalVoiceStatus(active: boolean): UseLocalVoiceStatusResult {
  const [statuses, setStatuses] = useState<Record<string, LocalVoiceProviderStatus>>({});
  const [setupJobs, setSetupJobs] = useState<Record<string, LocalVoiceSetupJob>>({});
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [starting, setStarting] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const setupWatchers = useRef<Record<string, SetupWatcher>>({});

  const refresh = useCallback(async () => {
    try {
      const resp = await fetchLocalVoiceStatus();
      setStatuses((prev) => {
        const next = { ...prev };
        for (const p of resp.providers) next[p.provider] = p;
        return next;
      });
      setLoaded(true);
    } catch {
      // Status polling is best-effort; a missing endpoint (old backend)
      // just leaves local providers without badges.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (cancelled) return;
      await refresh();
      if (!cancelled) timer = setTimeout(poll, 5000);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active, refresh]);

  const watchSetupJob = useCallback(
    (provider: string, jobId: string, watcher: SetupWatcher) => {
      const tick = async () => {
        if (watcher.cancelled) return;
        let job: LocalVoiceSetupJob;
        try {
          job = await fetchLocalVoiceSetupJob(jobId);
        } catch {
          if (!watcher.cancelled) watcher.timer = setTimeout(tick, 4000);
          return;
        }
        if (watcher.cancelled) return;
        setSetupJobs((prev) => ({ ...prev, [provider]: job }));
        if (job.status === "running") {
          watcher.timer = setTimeout(tick, 2500);
        } else {
          delete setupWatchers.current[provider];
          if (job.status === "error") {
            setErrors((prev) => ({ ...prev, [provider]: job.error || "setup failed" }));
          }
          void refresh();
        }
      };
      void tick();
    },
    [refresh]
  );

  useEffect(() => {
    const watchers = setupWatchers.current;
    return () => {
      Object.values(watchers).forEach(stopWatcher);
    };
  }, []);

  const setup = useCallback(
    async (provider: string, hfToken: string = "") => {
      const previous = setupWatchers.current[provider];
      if (previous) stopWatcher(previous);
      const watcher: SetupWatcher = { cancelled: false };
      setupWatchers.current[provider] = watcher;
      setErrors((prev) => ({ ...prev, [provider]: null }));
      try {
        const job = await startLocalVoiceSetup(provider, hfToken);
        if (watcher.cancelled) return;
        setSetupJobs((prev) => ({ ...prev, [provider]: { ...job, provider } }));
        watchSetupJob(provider, job.job_id, watcher);
      } catch (err) {
        if (watcher.cancelled) return;
        delete setupWatchers.current[provider];
        setErrors((prev) => ({
          ...prev,
          [provider]: err instanceof Error ? err.message : String(err),
        }));
      }
    },
    [watchSetupJob]
  );

  const cancelSetup = useCallback(async (provider: string) => {
    // Read the job id outside the state updater — updaters must stay pure
    // (React StrictMode double-invokes them, which would fire two DELETEs).
    const jobId = setupJobs[provider]?.job_id;
    const watcher = setupWatchers.current[provider];
    if (watcher) {
      stopWatcher(watcher);
      delete setupWatchers.current[provider];
    }
    setSetupJobs((prev) => {
      const next = { ...prev };
      delete next[provider];
      return next;
    });
    if (jobId) {
      try {
        await cancelLocalVoiceSetup(jobId);
      } catch {
        // Job already finished or backend restarted — nothing to cancel.
      }
    }
  }, [setupJobs]);

  const startServer = useCallback(
    async (provider: string, hfToken: string = "") => {
      setErrors((prev) => ({ ...prev, [provider]: null }));
      setStarting((prev) => ({ ...prev, [provider]: true }));
      try {
        await startLocalVoiceServer(provider, hfToken);
      } catch (err) {
        setErrors((prev) => ({
          ...prev,
          [provider]: err instanceof Error ? err.message : String(err),
        }));
      } finally {
        setStarting((prev) => ({ ...prev, [provider]: false }));
        await refresh();
      }
    },
    [refresh]
  );

  const stopServer = useCallback(
    async (provider: string) => {
      try {
        await stopLocalVoiceServer(provider);
      } finally {
        await refresh();
      }
    },
    [refresh]
  );

  const providers: Record<string, LocalVoiceProviderState> = {};
  for (const [key, status] of Object.entries(statuses)) {
    providers[key] = {
      status,
      setupJob: setupJobs[key] ?? null,
      error: errors[key] ?? null,
      phase: derivePhase(status, setupJobs[key] ?? null, !!starting[key], errors[key] ?? null),
    };
  }

  return { providers, loading, loaded, refresh, setup, cancelSetup, startServer, stopServer };
}
