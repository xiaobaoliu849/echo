import { useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE_URL,
  fetchTranscriptionJob,
  getTranscriptionJobWords,
  transcribeAudio,
  createTranscriptionJob,
  createTranscriptionJobFromUrl,
  saveTranscriptionJobMemory,
  type TranscriptionJobResponse,
  type WordTimestamp,
} from "../api";
import TranscriptionDetailDrawer from "../components/transcription/TranscriptionDetailDrawer";
import TranscriptionTable from "../components/transcription/TranscriptionTable";
import { useTranscriptionHistory, type HistoryItem } from "../hooks/useTranscriptionHistory";
import { useI18n } from "../i18n";
import { generateSrt, generateVtt } from "../utils/subtitleGenerator";
import { exportTextFile } from "../utils/desktopFileSave";

type ViewMode = "library" | "detail";

type Props = {
  onSendToChat?: (text: string) => void;
};

function isPollingStatus(status?: string): boolean {
  return status === "submitted" || status === "running" || status === "queued";
}

/** The backend hands back a root-relative `/api/transcription/jobs/{id}/audio`
 * whenever the source file still exists locally. That resolves against the SPA
 * origin, which is only the API origin in packaged/desktop mode — under
 * `npm run dev` the app is on :5173 with no proxy, so the player would request
 * the audio from Vite and get an HTML 404 back. Absolute URLs (remote sources)
 * are passed through untouched.
 *
 * Applied where the URL is consumed, not where the job is built: history is
 * persisted to localStorage, and storing an absolute URL there would pin saved
 * jobs to whichever origin happened to be in use when they were transcribed. */
function resolveSourceUrl(url?: string | null): string | undefined {
  if (!url) return undefined;
  return /^https?:\/\//i.test(url) ? url : `${API_BASE_URL}${url}`;
}

/** Local uploads above this size skip the blocking sync request and run as a
 * background chunked job instead (the backend splits long audio / extracts
 * video audio tracks with ffmpeg, then transcribes chunk by chunk). */
const LOCAL_ASYNC_THRESHOLD_BYTES = 25 * 1024 * 1024;

function getJobStatusMessage(
  job: TranscriptionJobResponse,
  t: (zh: string, en: string) => string
): string {
  switch (job.status) {
    case "submitted":
      return t("任务已提交，排队中…", "Job submitted, queued...");
    case "queued":
      return t("任务排队中…", "Job queued...");
    case "running":
      // Local chunked jobs report fine-grained progress ("第 3/12 段…").
      return job.progress || t("正在转写中…", "Transcribing...");
    case "completed":
      return t("转写完成。", "Transcription completed.");
    case "failed":
      return job.error
        ? t(`转写失败: ${job.error}`, `Transcription failed: ${job.error}`)
        : t("转写过程遇到错误。", "Transcription encountered an error.");
    default:
      return "";
  }
}

export function TranscriptionPage({ onSendToChat }: Props) {
  const { t, language } = useI18n();

  const [viewMode, setViewMode] = useState<ViewMode>("library");
  const [job, setJob] = useState<TranscriptionJobResponse | null>(null);
  const [transcript, setTranscript] = useState("");
  const [words, setWords] = useState<WordTimestamp[]>([]);
  const [statusMessage, setStatusMessage] = useState("");
  const [memorySaved, setMemorySaved] = useState(false);
  const [isSyncBusy, setIsSyncBusy] = useState(false);
  const [isAsyncBusy, setIsAsyncBusy] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [audioDuration, setAudioDuration] = useState(0);

  const [error, setError] = useState<Error | null>(null);
  const [infoMessage, setInfoMessage] = useState("");
  const [modalError, setModalError] = useState<Error | null>(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const {
    history,
    historyBusy,
    activeFilter,
    setActiveFilter,
    refreshHistory,
    addOrUpdateJob,
    removeJob,
    removeJobs,
    retryJob,
  } = useTranscriptionHistory();

  const [manageMode, setManageMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);

  // Filter history by search term
  const filteredHistory = useMemo(() => {
    if (!searchQuery.trim()) return history;
    const q = searchQuery.toLowerCase();
    return history.filter(
      (item) =>
        (item.file_name && item.file_name.toLowerCase().includes(q)) ||
        (item.job_id && item.job_id.toLowerCase().includes(q))
    );
  }, [history, searchQuery]);

  const activePollingJobId = isPollingStatus(job?.status) ? job?.job_id : null;

  // Poll active async job status
  useEffect(() => {
    if (!activePollingJobId) return;

    let timerId: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    async function poll() {
      if (cancelled || !activePollingJobId) return;

      try {
        const nextJob = await fetchTranscriptionJob(activePollingJobId);
        if (cancelled) return;

        setJob(nextJob);
        setStatusMessage(getJobStatusMessage(nextJob, t));
        addOrUpdateJob(nextJob);

        if (nextJob.status === "completed") {
          setTranscript(nextJob.transcript || "");
          setMemorySaved(Boolean(nextJob.memory_saved));
          setError(null);
          // Fetch word-level timestamps persisted for the async job so the
          // detail drawer can export precision-aligned SRT/VTT.
          void loadJobWords(nextJob.job_id);
        } else if (nextJob.status === "failed") {
          setError(
            new Error(
              nextJob.error || t("转写失败", "Transcription failed")
            )
          );
        }

        if (isPollingStatus(nextJob.status)) {
          timerId = setTimeout(poll, 2500);
        }
      } catch (err) {
        if (cancelled) return;
        const e = err instanceof Error ? err : new Error(String(err));
        setError(e);
        timerId = setTimeout(poll, 4000);
      }
    }

    poll();

    return () => {
      cancelled = true;
      if (timerId !== null) clearTimeout(timerId);
    };
  }, [activePollingJobId, addOrUpdateJob, t]);

  async function handleLocalTranscription(file: File, provider?: string) {
    setModalError(null);
    setError(null);
    setInfoMessage("");

    // Large files (typically long recordings or video files) would block the
    // sync request for many minutes; route them to the background chunked
    // pipeline and follow progress through job polling instead.
    if (file.size > LOCAL_ASYNC_THRESHOLD_BYTES) {
      setIsAsyncBusy(true);
      try {
        const newJob = await createTranscriptionJob(file, provider);
        setJob(newJob);
        setTranscript("");
        setWords([]);
        setMemorySaved(Boolean(newJob.memory_saved));
        setStatusMessage(getJobStatusMessage(newJob, t));
        addOrUpdateJob(newJob);
        setViewMode("detail");
        setShowNewModal(false);
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        setModalError(e);
        setError(e);
      } finally {
        setIsAsyncBusy(false);
      }
      return;
    }

    setIsSyncBusy(true);

    try {
      const resp = await transcribeAudio(file, provider);
      const localJob: TranscriptionJobResponse = {
        job_id: resp.job_id || `sync_${Date.now()}`,
        mode: (resp as any).mode || "sync",
        status: "completed",
        file_name: file.name,
        transcript: resp.transcript,
        has_transcript: true,
        memory_saved: resp.memory_saved,
        provider: resp.provider ?? null,
        source_url: resp.source_url || (resp.job_id ? `/api/transcription/jobs/${resp.job_id}/audio` : undefined),
        updated_at: new Date().toISOString(),
      };

      setJob(localJob);
      setTranscript(resp.transcript);
      setWords(resp.words || []);
      setMemorySaved(Boolean(resp.memory_saved));
      if (resp.duration_seconds) {
        setAudioDuration(resp.duration_seconds);
      }
      setStatusMessage(getJobStatusMessage(localJob, t));
      addOrUpdateJob(localJob);
      setViewMode("detail");
      setShowNewModal(false);
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setModalError(e);
      setError(e);
    } finally {
      setIsSyncBusy(false);
    }
  }

  async function handleRemoteJobStart(url: string, provider?: string) {
    setModalError(null);
    setError(null);
    setInfoMessage("");
    setIsAsyncBusy(true);

    try {
      const newJob = await createTranscriptionJobFromUrl(url, provider);
      setJob(newJob);
      setTranscript(newJob.transcript || "");
      setWords([]);
      setMemorySaved(Boolean(newJob.memory_saved));
      setStatusMessage(getJobStatusMessage(newJob, t));
      addOrUpdateJob(newJob);
      setViewMode("detail");
      setShowNewModal(false);
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setModalError(e);
      setError(e);
    } finally {
      setIsAsyncBusy(false);
    }
  }

  function handleRealtimeComplete(job: TranscriptionJobResponse, words?: WordTimestamp[]) {
    setJob(job);
    setTranscript(job.transcript || "");
    setWords(words || []);
    setMemorySaved(Boolean(job.memory_saved));
    setStatusMessage(getJobStatusMessage(job, t));
    addOrUpdateJob(job);
    setError(null);
    setViewMode("detail");
    setShowNewModal(false);
  }

  // Load word-level timestamps for a completed job (async local/URL jobs store
  // them separately). 404 / missing words fall back to an empty list so the
  // drawer still exports evenly-split SRT for providers without timestamps.
  async function loadJobWords(jobId?: string | null) {
    if (!jobId) return;
    try {
      const loaded = await getTranscriptionJobWords(jobId);
      setWords(loaded || []);
    } catch {
      setWords([]);
    }
  }

  async function handleCardClick(item: HistoryItem) {
    setDetailLoading(true);
    setViewMode("detail");
    setAudioDuration(0);
    try {
      const fullJob = await fetchTranscriptionJob(item.job_id);
      setJob(fullJob);
      setTranscript(fullJob.transcript || "");
      setWords([]);
      setMemorySaved(Boolean(fullJob.memory_saved));
      setStatusMessage(getJobStatusMessage(fullJob, t));
      if (fullJob.status === "completed") {
        void loadJobWords(fullJob.job_id);
      }
    } catch {
      // Fallback to local history item info if server fetch fails
      const fallbackJob: TranscriptionJobResponse = {
        job_id: item.job_id,
        remote_job_id: item.remote_job_id,
        mode: "saved",
        status: item.status,
        file_name: item.file_name,
        has_transcript: item.has_transcript,
        memory_saved: item.memory_saved,
        source_url: item.source_url,
        updated_at: item.updated_at,
        error: item.error,
      };
      setJob(fallbackJob);
      setTranscript("");
      setWords([]);
      setMemorySaved(Boolean(item.memory_saved));
      setStatusMessage(getJobStatusMessage(fallbackJob, t));
    } finally {
      setDetailLoading(false);
    }
  }

  function handleBackToLibrary() {
    setViewMode("library");
    setJob(null);
    setTranscript("");
    setWords([]);
    setAudioDuration(0);
    setError(null);
    setInfoMessage("");
  }

  const infoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showInfo(message: string) {
    // Replace any pending auto-clear so a quick second action isn't wiped by
    // the first action's timer.
    if (infoTimerRef.current) clearTimeout(infoTimerRef.current);
    setInfoMessage(message);
    infoTimerRef.current = setTimeout(() => setInfoMessage(""), 3000);
  }

  function handleCopy() {
    if (!transcript) return;
    navigator.clipboard.writeText(transcript).then(() => {
      showInfo(t("文稿已复制到剪贴板", "Transcript copied to clipboard."));
    });
  }

  async function handleExport(format: "txt" | "srt" | "vtt" | "json") {
    if (!transcript && words.length === 0) return;
    const baseName = (job?.file_name || "transcript").replace(/\.[^/.]+$/, "");
    let content = "";
    let mimeType = "text/plain";
    const extension = format;

    if (format === "txt") {
      content = transcript;
    } else if (format === "json") {
      content = JSON.stringify({ transcript, words, job }, null, 2);
      mimeType = "application/json";
    } else if (format === "srt") {
      // BOM keeps CJK subtitles readable in legacy Windows players (ANSI default).
      content = "\uFEFF" + generateSrt(transcript, audioDuration, words);
    } else if (format === "vtt") {
      content = generateVtt(transcript, audioDuration, words);
    }
    if (!content) return;

    // Desktop (pywebview) swallows blob-anchor downloads, so this goes through
    // the native save dialog there and falls back to an anchor in browsers.
    const outcome = await exportTextFile(`${baseName}.${extension}`, content, mimeType);
    if (outcome.kind === "saved-desktop") {
      showInfo(
        outcome.path
          ? t(`文件已导出: ${outcome.path}`, `Exported: ${outcome.path}`)
          : t("文件已导出。", "File exported.")
      );
    } else if (outcome.kind === "failed") {
      setError(
        new Error(
          t(`导出失败: ${outcome.message}`, `Export failed: ${outcome.message}`)
        )
      );
    }
  }

  function handleReservedAction(actionId: string) {
    if (actionId === "send_to_chat" && transcript && onSendToChat) {
      onSendToChat(transcript);
    }
  }

  function handleFilterChange(filter: "all" | "completed" | "running" | "failed") {
    setActiveFilter(filter);
  }

  function toggleManageMode() {
    setManageMode((prev) => {
      const next = !prev;
      // Leaving manage mode drops any pending selection.
      if (!next) setSelectedIds(new Set());
      return next;
    });
  }

  function toggleSelect(jobId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  function selectAllVisible() {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const item of filteredHistory) next.add(item.job_id);
      return next;
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  async function handleBatchDelete() {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    const ok = confirm(
      t(
        `确定要删除所选的 ${ids.length} 条记录吗？此操作不可撤销。`,
        `Delete ${ids.length} selected record(s)? This cannot be undone.`
      )
    );
    if (!ok) return;
    setBatchDeleting(true);
    setError(null);
    try {
      const result = await removeJobs(ids);
      setSelectedIds(new Set());
      if (result.failed && result.failed.length > 0) {
        showInfo(
          t(
            `部分记录删除失败（${result.failed.length} 条）`,
            `Some records failed to delete (${result.failed.length}).`
          )
        );
      } else {
        showInfo(
          t(
            `已删除 ${result.deleted.length} 条记录`,
            `Deleted ${result.deleted.length} record(s).`
          )
        );
      }
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setError(e);
    } finally {
      setBatchDeleting(false);
    }
  }

  async function handleSaveMemory() {
    if (!job?.job_id) return;
    setMemorySaving(true);
    setError(null);
    try {
      const updated = await saveTranscriptionJobMemory(job.job_id);
      setJob(updated);
      setMemorySaved(true);
      addOrUpdateJob(updated);
      showInfo(t("已存入长期记忆", "Saved to long-term memory."));
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setError(e);
    } finally {
      setMemorySaving(false);
    }
  }

  const isBusy = isSyncBusy || isAsyncBusy || isPollingStatus(job?.status);

  if (viewMode === "detail") {
    return (
      <TranscriptionDetailDrawer
        job={job}
        transcript={transcript}
        words={words}
        statusMessage={statusMessage}
        memorySaved={memorySaved}
        isBusy={isBusy}
        detailLoading={detailLoading}
        audioDuration={audioDuration}
        audioSourceUrl={resolveSourceUrl(job?.source_url)}
        error={error}
        infoMessage={infoMessage}
        language={language}
        onBack={handleBackToLibrary}
        onCopy={handleCopy}
        onExport={handleExport}
        onAudioDurationChange={setAudioDuration}
        onReservedAction={handleReservedAction}
        onSaveMemory={handleSaveMemory}
        memorySaving={memorySaving}
      />
    );
  }

  return (
    <TranscriptionTable
      history={history}
      filteredHistory={filteredHistory}
      activeFilter={activeFilter}
      searchQuery={searchQuery}
      historyBusy={historyBusy}
      activeJobId={job?.job_id}
      error={error}
      modalError={modalError}
      showNewModal={showNewModal}
      isBusy={isBusy}
      isSyncBusy={isSyncBusy}
      isAsyncBusy={isAsyncBusy}
      onSearchChange={setSearchQuery}
      onFilterChange={handleFilterChange}
      onRefresh={refreshHistory}
      onOpenNewModal={() => {
        setModalError(null);
        setShowNewModal(true);
      }}
      onCloseNewModal={() => setShowNewModal(false)}
      onCardClick={handleCardClick}
      onDeleteJob={removeJob}
      onRetryJob={(id) => retryJob(id).catch(() => {})}
      onLocalTranscribe={handleLocalTranscription}
      onRemoteSubmit={handleRemoteJobStart}
      onRealtimeComplete={handleRealtimeComplete}
      manageMode={manageMode}
      selectedIds={selectedIds}
      batchDeleting={batchDeleting}
      onToggleManageMode={toggleManageMode}
      onToggleSelect={toggleSelect}
      onSelectAllVisible={selectAllVisible}
      onClearSelection={clearSelection}
      onBatchDelete={handleBatchDelete}
    />
  );
}

export default TranscriptionPage;
