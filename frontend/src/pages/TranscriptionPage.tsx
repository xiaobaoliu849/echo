import { useEffect, useMemo, useState } from "react";
import {
  API_BASE_URL,
  fetchTranscriptionJob,
  transcribeAudio,
  createTranscriptionJobFromUrl,
  type TranscriptionJobResponse,
  type WordTimestamp,
} from "../api";
import TranscriptionDetailDrawer from "../components/transcription/TranscriptionDetailDrawer";
import TranscriptionTable from "../components/transcription/TranscriptionTable";
import { useTranscriptionHistory, type HistoryItem } from "../hooks/useTranscriptionHistory";
import { useI18n } from "../i18n";
import { generateSrt, generateVtt } from "../utils/subtitleGenerator";

type ViewMode = "library" | "detail";

type Props = {
  onSendToChat?: (text: string) => void;
};

function isPollingStatus(status?: string): boolean {
  return status === "submitted" || status === "running";
}

function getJobStatusMessage(
  job: TranscriptionJobResponse,
  t: (zh: string, en: string) => string
): string {
  switch (job.status) {
    case "submitted":
      return t("任务已提交，排队中…", "Job submitted, queued...");
    case "running":
      return t("正在使用 Whisper 转写中…", "Transcribing with Whisper...");
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
    retryJob,
  } = useTranscriptionHistory();

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
        source_url: resp.source_url ? (resp.source_url.startsWith("http") ? resp.source_url : `${API_BASE_URL}${resp.source_url}`) : undefined,
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

  async function handleRemoteJobStart(url: string) {
    setModalError(null);
    setError(null);
    setInfoMessage("");
    setIsAsyncBusy(true);

    try {
      const newJob = await createTranscriptionJobFromUrl(url);
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

  function handleRealtimeComplete(job: TranscriptionJobResponse) {
    setJob(job);
    setTranscript(job.transcript || "");
    setWords([]);
    setMemorySaved(Boolean(job.memory_saved));
    setStatusMessage(getJobStatusMessage(job, t));
    addOrUpdateJob(job);
    setError(null);
    setViewMode("detail");
    setShowNewModal(false);
  }

  async function handleCardClick(item: HistoryItem) {
    setDetailLoading(true);
    setViewMode("detail");
    try {
      const fullJob = await fetchTranscriptionJob(item.job_id);
      setJob(fullJob);
      setTranscript(fullJob.transcript || "");
      setWords([]);
      setMemorySaved(Boolean(fullJob.memory_saved));
      setStatusMessage(getJobStatusMessage(fullJob, t));
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
    setError(null);
    setInfoMessage("");
  }

  function handleCopy() {
    if (!transcript) return;
    navigator.clipboard.writeText(transcript).then(() => {
      setInfoMessage(t("文稿已复制到剪贴板", "Transcript copied to clipboard."));
      setTimeout(() => setInfoMessage(""), 3000);
    });
  }

  function handleExport(format: "txt" | "srt" | "vtt" | "json") {
    if (!transcript && words.length === 0) return;
    const baseName = (job?.file_name || "transcript").replace(/\.[^/.]+$/, "");
    let content = "";
    let mimeType = "text/plain";
    let extension = format;

    if (format === "txt") {
      content = transcript;
    } else if (format === "json") {
      content = JSON.stringify({ transcript, words, job }, null, 2);
      mimeType = "application/json";
    } else if (format === "srt") {
      content = generateSrt(transcript, audioDuration, words);
    } else if (format === "vtt") {
      content = generateVtt(transcript, audioDuration, words);
    }

    const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${baseName}.${extension}`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function handleReservedAction(actionId: string) {
    if (actionId === "send_to_chat" && transcript && onSendToChat) {
      onSendToChat(transcript);
    }
  }

  function handleFilterChange(filter: "all" | "completed" | "running" | "failed") {
    setActiveFilter(filter);
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
        audioSourceUrl={job?.source_url ? job.source_url : undefined}
        error={error}
        infoMessage={infoMessage}
        language={language}
        onBack={handleBackToLibrary}
        onCopy={handleCopy}
        onExport={handleExport}
        onAudioDurationChange={setAudioDuration}
        onReservedAction={handleReservedAction}
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
    />
  );
}

export default TranscriptionPage;
