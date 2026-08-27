import { useCallback, useEffect, useState } from "react";
import {
  listTranscriptionJobs,
  retryTranscriptionJob,
  deleteTranscriptionJob,
  batchDeleteTranscriptionJobs,
  type TranscriptionJobResponse
} from "../api";

const STORAGE_KEY = "vs_transcription_history";
const MAX_HISTORY = 50;

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
> & {
  timestamp: number;
};

function safeLoadStoredHistory(): HistoryItem[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      return [];
    }
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed : [];
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
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyBusy, setHistoryBusy] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [activeFilter, setActiveFilter] = useState<TranscriptionHistoryFilter>("all");

  useEffect(() => {
    const storedHistory = safeLoadStoredHistory();
    setHistory(storedHistory);
  }, []);

  async function refreshHistory(filter: TranscriptionHistoryFilter = activeFilter) {
    setHistoryBusy(true);
    setHistoryError("");
    try {
      const statuses = filter === "all" ? undefined : [filter];
      const response = await listTranscriptionJobs({ statuses, limit: MAX_HISTORY });
      setHistory((prev) => {
        const next = mergeHistory(response.jobs, prev);
        safeSaveHistory(next);
        return next;
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to refresh transcription history.";
      setHistoryError(message);
    } finally {
      setHistoryBusy(false);
    }
  }

  useEffect(() => {
    void refreshHistory(activeFilter);
  }, [activeFilter]);

  const addOrUpdateJob = useCallback((job: TranscriptionJobResponse) => {
    setHistory((prev) => {
      const next = mergeHistory([job], prev);
      safeSaveHistory(next);
      return next;
    });
  }, []);

  /** The backend confirmed a cached history entry no longer exists server-side.
   * Flip the local entry to failed so it stops masquerading as an active
   * "排队中" task the user can never open. */
  const markMissingJob = useCallback((jobId: string) => {
    setHistory((prev) => {
      const target = prev.find((item) => item.job_id === jobId);
      if (!target) return prev;
      const next = prev.map((item) =>
        item.job_id === jobId
          ? {
              ...item,
              status: "failed",
              error:
                "转写记录已失效，服务器上不存在该任务。 (This transcription record no longer exists on the server.)",
              timestamp: Date.now(),
            }
          : item
      );
      safeSaveHistory(next);
      return next;
    });
  }, []);

  const retryJob = async (jobId: string) => {
    const retried = await retryTranscriptionJob(jobId);
    addOrUpdateJob(retried);
    return retried;
  };

  const clearHistory = () => {
    setHistory([]);
    safeSaveHistory([]);
  };
  
  const removeJob = async (jobId: string) => {
    // Remove from server first
    try {
      await deleteTranscriptionJob(jobId);
    } catch {
      // If server delete fails (e.g. already gone), still remove locally
    }
    setHistory((prev) => {
      const next = prev.filter(item => item.job_id !== jobId);
      safeSaveHistory(next);
      return next;
    });
  };

  const removeJobs = async (jobIds: string[]) => {
    if (jobIds.length === 0) return { deleted: [], failed: [] };
    let result: { deleted: string[]; failed: string[] } = { deleted: jobIds, failed: [] };
    try {
      result = await batchDeleteTranscriptionJobs(jobIds);
    } catch {
      // If the batch call fails (e.g. stale ids), still clear them locally,
      // matching removeJob's tolerant behaviour.
    }
    const idSet = new Set(jobIds);
    setHistory((prev) => {
      const next = prev.filter(item => !idSet.has(item.job_id));
      safeSaveHistory(next);
      return next;
    });
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
    clearHistory,
    removeJob,
    removeJobs,
  };
}
