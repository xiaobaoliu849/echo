import { useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE_URL,
  ApiRequestError,
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
import RealtimeTranscriptionPanel from "../components/transcription/RealtimeTranscriptionPanel";
import { useTranscriptionHistory, type HistoryItem } from "../hooks/useTranscriptionHistory";
import { useI18n } from "../i18n";
import { AudioDropZone } from "../components/AudioDropZone";
import { generateSrt, generateVtt } from "../utils/subtitleGenerator";
import { exportTextFile } from "../utils/desktopFileSave";

type ViewMode = "library" | "detail";

type Props = {
  onSendToChat?: (text: string) => void;
  initialTab?: PageTab;
  onDetailModeChange?: (isDetail: boolean) => void;
};

function isPollingStatus(status?: string): boolean {
  return status === "submitted" || status === "running" || status === "queued";
}

/** The backend confirms the job record itself is gone (deleted elsewhere,
 * evicted, or lost store) — no amount of retrying can succeed. */
function isJobNotFoundError(err: unknown): boolean {
  return (
    err instanceof ApiRequestError &&
    (err.status === 404 || err.detail?.code === "TRANSCRIPTION_JOB_NOT_FOUND")
  );
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

export type PageTab = "realtime" | "file" | "remote" | "library";

export function TranscriptionPage({ onSendToChat, initialTab = "file", onDetailModeChange }: Props) {
  const { t, language } = useI18n();

  const [viewMode, setViewMode] = useState<ViewMode>("library");

  useEffect(() => {
    onDetailModeChange?.(viewMode === "detail");
  }, [viewMode, onDetailModeChange]);
  const [pageTab, setPageTab] = useState<PageTab>(initialTab);
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
  const [searchQuery, setSearchQuery] = useState("");

  // File upload state in Studio File mode
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileAsrProvider, setFileAsrProvider] = useState<string>("auto");

  // Remote URL state in Studio Remote mode
  const [remoteUrl, setRemoteUrl] = useState("");
  const [asyncModel, setAsyncModel] = useState<string>("qwen-filetrans");

  const {
    history,
    historyBusy,
    activeFilter,
    setActiveFilter,
    refreshHistory,
    addOrUpdateJob,
    markMissingJob,
    removeJob,
    removeJobs,
    retryJob,
    renameJob,
  } = useTranscriptionHistory();

  const [manageMode, setManageMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);

  // Filter history by search term (title, transcript preview, or job id)
  const filteredHistory = useMemo(() => {
    if (!searchQuery.trim()) return history;
    const q = searchQuery.toLowerCase();
    return history.filter(
      (item) =>
        (item.file_name && item.file_name.toLowerCase().includes(q)) ||
        (item.transcript_preview && item.transcript_preview.toLowerCase().includes(q)) ||
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
        if (isJobNotFoundError(e)) {
          // The record is confirmed gone server-side — polling can never
          // succeed. Flip the view to a terminal failed state instead of
          // spinning on "任务排队中…" forever, and mark the history entry.
          setJob((prev) => (prev ? { ...prev, status: "failed", error: e.message } : prev));
          setStatusMessage(
            t(
              "转写失败：服务器上已不存在该任务记录。",
              "Transcription failed: this job no longer exists on the server."
            )
          );
          setError(e);
          markMissingJob(activePollingJobId);
          return;
        }
        setError(e);
        timerId = setTimeout(poll, 4000);
      }
    }

    poll();

    return () => {
      cancelled = true;
      if (timerId !== null) clearTimeout(timerId);
    };
    }, [activePollingJobId, addOrUpdateJob, markMissingJob, t]);

  async function handleLocalTranscription(file: File, provider?: string) {
    setError(null);
    setInfoMessage("");

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
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
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
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        origin: "upload",
        duration_seconds: resp.duration_seconds ?? null,
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
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setError(e);
    } finally {
      setIsSyncBusy(false);
    }
  }

  async function handleRemoteJobStart(url: string, provider?: string) {
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
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setError(e);
    } finally {
      setIsAsyncBusy(false);
    }
  }

  function handleRealtimeComplete(completedJob: TranscriptionJobResponse, jobWords?: WordTimestamp[]) {
    setJob(completedJob);
    setTranscript(completedJob.transcript || "");
    setWords(jobWords || []);
    setMemorySaved(Boolean(completedJob.memory_saved));
    setStatusMessage(getJobStatusMessage(completedJob, t));
    addOrUpdateJob(completedJob);
    setError(null);
    setViewMode("detail");
  }

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
    } catch (err) {
      if (isJobNotFoundError(err)) {
        // The record is gone server-side. Do NOT rebuild it with the stale
        // queued/running history status — that previously spawned an eternal
        // "任务排队中" polling loop for a job that no longer exists.
        const missingJob: TranscriptionJobResponse = {
          job_id: item.job_id,
          remote_job_id: item.remote_job_id,
          mode: "saved",
          status: "failed",
          file_name: item.file_name,
          has_transcript: item.has_transcript,
          memory_saved: item.memory_saved,
          source_url: item.source_url,
          updated_at: item.updated_at,
          error: t(
            "服务器上已不存在该任务记录（可能已被删除）。",
            "This job no longer exists on the server (it may have been deleted)."
          ),
        };
        setJob(missingJob);
        setTranscript("");
        setWords([]);
        setMemorySaved(Boolean(item.memory_saved));
        setStatusMessage(getJobStatusMessage(missingJob, t));
        markMissingJob(item.job_id);
      } else {
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
      }
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
      content = "\uFEFF" + generateSrt(transcript, audioDuration, words);
    } else if (format === "vtt") {
      content = generateVtt(transcript, audioDuration, words);
    }
    if (!content) return;

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

  async function handleRenameJob(jobId: string, fileName: string) {
    setError(null);
    try {
      await renameJob(jobId, fileName);
      showInfo(t("已重命名。", "Renamed."));
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setError(e);
    }
  }

  function toggleManageMode() {
    setManageMode((prev) => {
      const next = !prev;
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
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        width: "100%",
        gap: "14px",
        padding: "16px 24px",
        boxSizing: "border-box",
        overflowY: "auto",
      }}
    >
      {/* Studio Top Level Mode Tabs */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: "1px solid var(--border-color)",
          paddingBottom: "12px",
          flexShrink: 0,
          flexWrap: "wrap",
          gap: "10px",
        }}
      >
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => setPageTab("realtime")}
            style={{
              padding: "8px 16px",
              borderRadius: "10px",
              fontSize: "14px",
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: pageTab === "realtime" ? "var(--brand, #6366f1)" : "var(--bg-subtle, rgba(0,0,0,0.04))",
              color: pageTab === "realtime" ? "#fff" : "var(--text)",
              border: "none",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            <span aria-hidden="true">🎙️</span>
            {t("实时录音", "Realtime Live")}
          </button>
          <button
            type="button"
            onClick={() => setPageTab("file")}
            aria-label={t("新建转写 / 本地音频", "New Transcription / Local Audio")}
            style={{
              padding: "8px 16px",
              borderRadius: "10px",
              fontSize: "14px",
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: pageTab === "file" ? "var(--brand, #6366f1)" : "var(--bg-subtle, rgba(0,0,0,0.04))",
              color: pageTab === "file" ? "#fff" : "var(--text)",
              border: "none",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            <span aria-hidden="true">📁</span>
            {t("本地音频", "Local Audio")}
          </button>
          <button
            type="button"
            onClick={() => setPageTab("remote")}
            style={{
              padding: "8px 16px",
              borderRadius: "10px",
              fontSize: "14px",
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: pageTab === "remote" ? "var(--brand, #6366f1)" : "var(--bg-subtle, rgba(0,0,0,0.04))",
              color: pageTab === "remote" ? "#fff" : "var(--text)",
              border: "none",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            <span aria-hidden="true">🔗</span>
            {t("链式转写", "Link Pipeline")}
          </button>
          <button
            type="button"
            onClick={() => setPageTab("library")}
            style={{
              padding: "8px 16px",
              borderRadius: "10px",
              fontSize: "14px",
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: pageTab === "library" ? "var(--brand, #6366f1)" : "var(--bg-subtle, rgba(0,0,0,0.04))",
              color: pageTab === "library" ? "#fff" : "var(--text)",
              border: "none",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            <span aria-hidden="true">📚</span>
            {t("转写历史库", "Library & History")}
          </button>
        </div>

        {infoMessage && (
          <span style={{ fontSize: "13px", color: "var(--primary, #6366f1)", fontWeight: 500 }}>
            {infoMessage}
          </span>
        )}
      </div>

      {/* Tab Content */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {/* MODE 1: Realtime Live Studio */}
        {pageTab === "realtime" && (
          <RealtimeTranscriptionPanel
            onComplete={handleRealtimeComplete}
            onSwitchToLibrary={() => setPageTab("library")}
          />
        )}

        {/* MODE 2: File & Media Transcription Studio */}
        {pageTab === "file" && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "20px",
              background: "var(--bg-card)",
              border: "1px solid var(--border-color)",
              borderRadius: "16px",
              padding: "28px 32px",
              maxWidth: "860px",
              margin: "0 auto",
              width: "100%",
              boxSizing: "border-box",
            }}
          >
            <div>
              <h2 style={{ margin: "0 0 6px 0", fontSize: "18px", fontWeight: 700, color: "var(--text)" }}>
                {t("本地音视频文件转写", "Local Audio & Video Transcription")}
              </h2>
              <p style={{ margin: 0, fontSize: "13px", color: "var(--muted)", lineHeight: 1.5 }}>
                {t(
                  "支持各类常见音频与视频文件（MP3/WAV/M4A/FLAC/AAC/OGG/MP4/MKV/MOV/AVI 等，视频将自动抽取音轨）。长音频与大文件自动分段后台转写，无 5 分钟上限。",
                  "Supports all audio and video formats. Video files have audio tracks extracted automatically. Large files (>25MB) are chunked in the background with no duration limits."
                )}
              </p>
            </div>

            <AudioDropZone
              onFileDrop={(file) => setSelectedFile(file)}
              selectedFile={selectedFile}
              isProcessing={isBusy}
              inputLabel={t("选择转写音频或视频", "Choose audio or video to transcribe")}
              readyText={t("已选中，可开始转写", "Selected. Ready for transcription")}
              subText={t(
                "点击或拖拽文件至此区域 (MP3, WAV, M4A, FLAC, MP4, MKV, MOV 等)",
                "Click or drag file here (MP3, WAV, M4A, FLAC, MP4, MKV, MOV, etc.)"
              )}
            />

            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <label style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>
                {t("语音识别引擎", "Speech Recognition Engine")}
              </label>
              <select
                value={fileAsrProvider}
                onChange={(e) => setFileAsrProvider(e.target.value)}
                disabled={isBusy}
                className="vsSelect"
                style={{
                  width: "100%",
                  height: "44px",
                  borderRadius: "10px",
                  fontSize: "14px",
                }}
              >
                <option value="auto">{t("自动选择 (推荐)", "Auto (Recommended)")}</option>
                <optgroup label={t("精准字级时间戳引擎", "Word-level Timestamps Engines")}>
                  <option value="google">Google Gemini 3.5 Transcribe</option>
                  <option value="dashscope">Qwen-Audio 3.0 ASR Flash (阿里云)</option>
                  <option value="deepgram">Deepgram Nova-3</option>
                  <option value="openai">OpenAI Whisper</option>
                  <option value="assemblyai">AssemblyAI</option>
                  <option value="doubao">豆包 ASR 2.0 (火山引擎)</option>
                </optgroup>
                <optgroup label={t("纯文本引擎", "Text-only Engines")}>
                  <option value="xiaomi">小米 MiMo</option>
                  <option value="qwen-legacy">Qwen3 ASR Flash (旧版)</option>
                </optgroup>
              </select>
            </div>

            {error && (
              <div style={{ marginTop: "4px" }}>
                <span style={{ fontSize: "13px", color: "var(--danger, #e5484d)", fontWeight: 500 }}>
                  {error.message}
                </span>
              </div>
            )}

            <button
              type="button"
              onClick={() => {
                if (selectedFile) {
                  const provider = fileAsrProvider === "auto" ? undefined : fileAsrProvider;
                  handleLocalTranscription(selectedFile, provider);
                }
              }}
              disabled={isBusy || !selectedFile}
              className="vsBtnPrimary"
              style={{
                width: "100%",
                height: "46px",
                fontSize: "15px",
                borderRadius: "12px",
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                marginTop: "6px",
              }}
            >
              {isSyncBusy ? (
                <>
                  <span className="spinner-mini" /> {t("正在上传并转写…", "Transcribing…")}
                </>
              ) : isAsyncBusy ? (
                <>
                  <span className="spinner-mini" /> {t("正在提交后台分段转写…", "Submitting background task…")}
                </>
              ) : (
                t("开始转写", "Start Transcription")
              )}
            </button>
          </div>
        )}

        {/* MODE 3: Remote Link Pipeline Studio */}
        {pageTab === "remote" && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "20px",
              background: "var(--bg-card)",
              border: "1px solid var(--border-color)",
              borderRadius: "16px",
              padding: "28px 32px",
              maxWidth: "860px",
              margin: "0 auto",
              width: "100%",
              boxSizing: "border-box",
            }}
          >
            <div>
              <h2 style={{ margin: "0 0 6px 0", fontSize: "18px", fontWeight: 700, color: "var(--text)" }}>
                {t("链式与网络音视频转写", "Async Link & Remote Media Pipeline")}
              </h2>
              <p style={{ margin: 0, fontSize: "13px", color: "var(--muted)", lineHeight: 1.5 }}>
                {t(
                  "支持输入在线音视频直链或播客链接，由云端异步转写引擎自动下载并生成带时间戳字幕。",
                  "Enter a direct audio/video URL or podcast link. The cloud async pipeline will download and transcribe it."
                )}
              </p>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <label style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>
                {t("音视频网络链接 (URL)", "Media URL")}
              </label>
              <input
                type="url"
                value={remoteUrl}
                onChange={(e) => setRemoteUrl(e.target.value)}
                placeholder="https://example.com/meeting.wav"
                disabled={isBusy}
                className="vsInput"
                style={{
                  width: "100%",
                  height: "44px",
                  borderRadius: "10px",
                  fontSize: "14px",
                  padding: "0 14px",
                }}
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <label style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>
                {t("异步转写模型", "Async ASR Model")}
              </label>
              <select
                value={asyncModel}
                onChange={(e) => setAsyncModel(e.target.value)}
                disabled={isBusy}
                className="vsSelect"
                style={{
                  width: "100%",
                  height: "44px",
                  borderRadius: "10px",
                  fontSize: "14px",
                }}
              >
                <option value="qwen-filetrans">Qwen FileTrans (DashScope 录音文件识别)</option>
              </select>
            </div>

            {error && (
              <div style={{ marginTop: "4px" }}>
                <span style={{ fontSize: "13px", color: "var(--danger, #e5484d)", fontWeight: 500 }}>
                  {error.message}
                </span>
              </div>
            )}

            <button
              type="button"
              onClick={() => {
                const url = remoteUrl.trim();
                if (url) {
                  handleRemoteJobStart(url, asyncModel);
                }
              }}
              disabled={isBusy || !remoteUrl.trim()}
              className="vsBtnPrimary"
              style={{
                width: "100%",
                height: "46px",
                fontSize: "15px",
                borderRadius: "12px",
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                marginTop: "6px",
              }}
            >
              {isAsyncBusy ? (
                <>
                  <span className="spinner-mini" /> {t("正在提交异步任务…", "Submitting async task…")}
                </>
              ) : (
                t("提交异步任务", "Submit Async Pipeline")
              )}
            </button>
          </div>
        )}

        {/* MODE 4: Transcripts & Document Library */}
        {pageTab === "library" && (
          <TranscriptionTable
            history={history}
            filteredHistory={filteredHistory}
            activeFilter={activeFilter}
            searchQuery={searchQuery}
            historyBusy={historyBusy}
            activeJobId={job?.job_id}
            error={error}
            onSearchChange={setSearchQuery}
            onFilterChange={handleFilterChange}
            onRefresh={refreshHistory}
            onCardClick={handleCardClick}
            onDeleteJob={removeJob}
            onRetryJob={(id) =>
              retryJob(id).catch((err) => {
                // A record that 404s on retry is gone server-side; reflect it
                // in the library instead of silently ignoring the click.
                if (isJobNotFoundError(err)) markMissingJob(id);
              })
            }
            onRenameJob={handleRenameJob}
            manageMode={manageMode}
            selectedIds={selectedIds}
            batchDeleting={batchDeleting}
            onToggleManageMode={toggleManageMode}
            onToggleSelect={toggleSelect}
            onSelectAllVisible={selectAllVisible}
            onClearSelection={clearSelection}
            onBatchDelete={handleBatchDelete}
          />
        )}
      </div>
    </div>
  );
}

export default TranscriptionPage;

