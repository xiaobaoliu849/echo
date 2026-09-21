import { useCallback, useEffect, useRef, useState } from "react";
import {
  listTranscriptionJobs,
  renameTranscriptionJob,
  retryTranscriptionJob,
  deleteTranscriptionJob,
  batchDeleteTranscriptionJobs,
  ApiRequestError,
  type TranscriptionJobResponse
} from "../api";

const STORAGE_KEY = "vs_transcription_history";
const MAX_HISTORY = 100;

export type TranscriptionHistoryFilter = "all" | "completed" | "running" | "failed";

export type HistoryItem = Pick<
  TranscriptionJobResponse,
  | "job_id"
  | "file_name"
  | "status"
  | "updated_at"
  | "remote_job_id"
  | "has_transcript"
  | "memory_saved"
  | "source_url"
  | "error"
  | "mode"
  | "progress"
  | "duration_seconds"
  | "origin"
  | "transcript_preview"
> & {
  timestamp: number;
};

function isStoredHistoryItem(value: unknown): value is HistoryItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  if (!["job_id", "file_name", "mode", "status"].every(key => typeof item[key] === "string")) return false;
  if (!item.job_id || typeof item.timestamp !== "number" || !Number.isFinite(item.timestamp)) return false;
  const textFields = ["updated_at", "remote_job_id", "source_url", "error", "progress", "origin", "transcript_preview"];
  return textFields.every(key => item[key] == null || typeof item[key] === "string")
    && ["has_transcript", "memory_saved"].every(key => item[key] === undefined || typeof item[key] === "boolean")
    && (item.duration_seconds == null || (typeof item.duration_seconds === "number" && Number.isFinite(item.duration_seconds)));
}

function safeLoadStoredHistory(): HistoryItem[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      return [];
    }
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed.filter(isStoredHistoryItem).slice(0, MAX_HISTORY) : [];
  } catch (err) {
    console.warn("Failed to load transcription history:", err);
    return [];
  }
}

function safeSaveHistory(history: HistoryItem[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
  } catch (err) {
    console.warn("Failed to save transcription history:", err);
  }
}

function mapJobToHistoryItem(job: TranscriptionJobResponse): HistoryItem {
  return {
    job_id: job.job_id,
    file_name: job.file_name,
    status: job.status,
    updated_at: job.updated_at,
    remote_job_id: job.remote_job_id,
    has_transcript: Boolean(job.has_transcript),
    memory_saved: Boolean(job.memory_saved),
    source_url: job.source_url,
    error: job.error,
    mode: job.mode,
    progress: job.progress,
    duration_seconds: job.duration_seconds ?? null,
    origin: job.origin ?? null,
    transcript_preview: job.transcript_preview ?? null,
    timestamp: Date.now(),
  };
}

function mergeHistory(
  incomingJobs: TranscriptionJobResponse[],
  existingHistory: HistoryItem[],
): HistoryItem[] {
  const merged = new Map<string, HistoryItem>();
  for (const item of existingHistory) {
    merged.set(item.job_id, item);
  }
  for (const job of incomingJobs) {
    merged.set(job.job_id, mapJobToHistoryItem(job));
  }
  return [...merged.values()]
    .sort((left, right) => {
      const rightTime = Date.parse(right.updated_at || "") || right.timestamp || 0;
      const leftTime = Date.parse(left.updated_at || "") || left.timestamp || 0;
      return rightTime - leftTime;
    })
    .slice(0, MAX_HISTORY);
}

export function useTranscriptionHistory() {
  const [history, setHistory] = useState<HistoryItem[]>(safeLoadStoredHistory);
  const [historyBusy, setHistoryBusy] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [activeFilter, setActiveFilter] = useState<TranscriptionHistoryFilter>("all");
  const revision = useRef(0);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      revision.current += 1;
    };
  }, []);

  useEffect(() => { safeSaveHistory(history); }, [history]);

  // A local mutation makes all earlier list snapshots obsolete.
  const updateHistory = useCallback((update: (previous: HistoryItem[]) => HistoryItem[]) => {
    if (!mounted.current) return;
    revision.current += 1;
    setHistoryBusy(false);
    setHistory(update);
  }, []);

  const refreshHistory = useCallback(async () => {
    const requestRevision = ++revision.current;
    setHistoryBusy(true);
    setHistoryError("");
    try {
      const statuses = activeFilter === "all" ? undefined : [activeFilter];
      const response = await listTranscriptionJobs({ statuses, limit: MAX_HISTORY });
      if (revision.current !== requestRevision) return;
      setHistory((prev) => {
        // Only the unfiltered listing may prune: a status-filtered response is
        // partial by design and would wipe every non-matching local entry.
        return mergeHistory(response.jobs, activeFilter === "all" ? [] : prev);
      });
    } catch (err) {
      if (revision.current !== requestRevision) return;
      const message = err instanceof Error ? err.message : "Failed to refresh transcription history.";
      setHistoryError(message);
    } finally {
      if (revision.current === requestRevision) setHistoryBusy(false);
    }
  }, [activeFilter]);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

  const addOrUpdateJob = useCallback((job: TranscriptionJobResponse) => {
    updateHistory((prev) => mergeHistory([job], prev));
  }, [updateHistory]);

  /** The backend confirmed a cached history entry no longer exists server-side.
   * Flip the local entry to failed so it stops masquerading as an active
   * "排队中" task the user can never open. */
  const markMissingJob = useCallback((jobId: string) => {
    updateHistory((prev) => {
      const target = prev.find((item) => item.job_id === jobId);
      if (!target) return prev;
      const next = prev.map((item) =>
        item.job_id === jobId
          ? {
              ...item,
              status: "failed" as const,
              error:
                "转写记录已失效，服务器上不存在该任务。 (This transcription record no longer exists on the server.)",
            }
          : item
      );
      return next;
    });
  }, [updateHistory]);

  const retryJob = async (jobId: string) => {
    const retried = await retryTranscriptionJob(jobId);
    addOrUpdateJob(retried);
    return retried;
  };

  const renameJob = async (jobId: string, fileName: string) => {
    const renamed = await renameTranscriptionJob(jobId, fileName);
    addOrUpdateJob(renamed);
    return renamed;
  };

  const clearHistory = () => {
    updateHistory(() => []);
  };

  const removeJob = async (jobId: string) => {
    try {
      await deleteTranscriptionJob(jobId);
    } catch (err) {
      // A missing record is already deleted; other failures must remain visible.
      if (!(err instanceof ApiRequestError && err.status === 404)) throw err;
    }
    updateHistory((prev) => prev.filter(item => item.job_id !== jobId));
  };

  const removeJobs = async (jobIds: string[]) => {
    if (jobIds.length === 0) return { deleted: [], failed: [] };
    const result = await batchDeleteTranscriptionJobs(jobIds);
    const idSet = new Set(result.deleted);
    updateHistory((prev) => prev.filter(item => !idSet.has(item.job_id)));
    return result;
  };

  return {
    history,
    historyBusy,
    historyError,
    activeFilter,
    setActiveFilter,
    refreshHistory,
    addOrUpdateJob,
    markMissingJob,
    retryJob,
    renameJob,
    clearHistory,
    removeJob,
    removeJobs,
  };
}
