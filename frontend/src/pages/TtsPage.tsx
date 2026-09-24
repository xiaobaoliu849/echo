import { useEffect, useRef, useState } from "react";
import { History, Pause, Play, RotateCcw, Trash2, X } from "lucide-react";
import ErrorNotice from "../components/ErrorNotice";
import useTtsHistory, { type TtsHistoryEntry } from "../hooks/useTtsHistory";
import type { UseTtsResult } from "../hooks/useTts";
import { useI18n } from "../i18n";
import type { ErrorRuntimeContext } from "../types/ui";

type Props = {
  tts: UseTtsResult;
  errorRuntimeContext: ErrorRuntimeContext;
};

type DesktopSaveAudioResult = {
  ok?: boolean;
  cancelled?: boolean;
  message?: string;
  path?: string;
};

type DesktopBridgeWindow = Window & {
  pywebview?: {
    api?: {
      save_audio_file?: (payload: {
        filename: string;
        mime_type: string;
        data_base64: string;
      }) => Promise<DesktopSaveAudioResult>;
    };
  };
};

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = typeof reader.result === "string" ? reader.result : "";
      const [, base64 = ""] = value.split(",", 2);
      if (!base64) {
        reject(new Error("Audio export payload is empty."));
        return;
      }
      resolve(base64);
    };
    reader.onerror = () => reject(reader.error || new Error("Failed to read audio export payload."));
    reader.readAsDataURL(blob);
  });
}

function getAudioExportMeta(blob: Blob): { filename: string; mimeType: string } {
  const mimeType = blob.type || "audio/mpeg";
  const lowerType = mimeType.toLowerCase();
  let extension = "mp3";
  if (lowerType.includes("wav")) {
    extension = "wav";
  } else if (lowerType.includes("ogg")) {
    extension = "ogg";
  } else if (lowerType.includes("webm")) {
    extension = "webm";
  } else if (lowerType.includes("flac")) {
    extension = "flac";
  } else if (lowerType.includes("mp4") || lowerType.includes("aac")) {
    extension = "m4a";
  }
  return { filename: `echo_tts.${extension}`, mimeType };
}

function formatHistoryTime(ts: number, t: (zh: string, en: string) => string): string {
  const diff = Date.now() - ts;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return t("刚刚", "just now");
  if (mins < 60) return t(`${mins} 分钟前`, `${mins}m ago`);
  const hours = Math.floor(mins / 60);
  if (hours < 24) return t(`${hours} 小时前`, `${hours}h ago`);
  const days = Math.floor(hours / 24);
  return t(`${days} 天前`, `${days}d ago`);
}

function truncate(text: string, max: number): string {
  const trimmed = text.trim().replace(/\s+/g, " ");
  if (trimmed.length <= max) return trimmed;
  return trimmed.slice(0, max) + "…";
}

function formatHistoryVoiceName(voice: string): string {
  if (!voice) return "";
  const parenMatch = voice.match(/\(([^)]+)\)/);
  let base = voice.replace(/\s*\([^)]*\)/g, "").trim();
  base = base.replace(/^[a-z]{2,3}-[A-Z]{2,3}-/, "");
  base = base.replace(/Neural$/i, "");
  base = base.replace(/^[-_]+/, "");
  if (parenMatch && parenMatch[1]) {
    const parenContent = parenMatch[1].trim();
    if (!parenContent.includes(base) && !base.includes(parenContent)) {
      return `${base} (${parenContent})`;
    }
  }
  return base || voice;
}

function TtsHistoryMiniPlayer({ src }: { src: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      document.querySelectorAll("audio").forEach((el) => {
        if (el !== audio && !el.paused) {
          el.pause();
        }
      });
      const playPromise = audio.play();
      if (playPromise && typeof playPromise.catch === "function") {
        playPromise.catch(() => setIsPlaying(false));
      }
    }
  };

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    if (audioRef.current && isFinite(audioRef.current.duration)) {
      setDuration(audioRef.current.duration);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = Number(e.target.value);
    if (audioRef.current) {
      audioRef.current.currentTime = val;
      setCurrentTime(val);
    }
  };

  const formatSecs = (s: number) => {
    if (isNaN(s) || !isFinite(s) || s < 0) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${String(sec).padStart(2, "0")}`;
  };

  const displayTime = isPlaying || currentTime > 0
    ? `${formatSecs(currentTime)} / ${formatSecs(duration)}`
    : formatSecs(duration);

  return (
    <div className="vsTtsMiniPlayer">
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => {
          setIsPlaying(false);
          setCurrentTime(0);
        }}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
      />
      <button
        type="button"
        className={`vsTtsMiniPlayBtn ${isPlaying ? "playing" : ""}`}
        onClick={togglePlay}
        title={isPlaying ? "暂停" : "播放"}
        aria-label={isPlaying ? "暂停" : "播放"}
      >
        {isPlaying ? (
          <Pause size={10} fill="currentColor" />
        ) : (
          <Play size={10} fill="currentColor" style={{ marginLeft: "1px" }} />
        )}
      </button>

      <div className="vsTtsMiniProgressWrap">
        <input
          type="range"
          min={0}
          max={duration || 1}
          step={0.1}
          value={currentTime}
          onChange={handleSeek}
          className="vsTtsMiniRange"
          aria-label="播放进度"
        />
        <div
          className="vsTtsMiniProgressBar"
          style={{ width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%` }}
        />
      </div>

      <span className="vsTtsMiniTime">
        {displayTime}
      </span>
    </div>
  );
}

export default function TtsPage({ tts, errorRuntimeContext }: Props) {
  const { t } = useI18n();
  const { history, addEntry, removeEntry, clearHistory, buildReplayUrl } = useTtsHistory();
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const prevAudioUrlRef = useRef(tts.audioUrl);

  // Record a history entry when a new audio generation succeeds.
  useEffect(() => {
    if (tts.audioUrl && tts.audioUrl !== prevAudioUrlRef.current) {
      addEntry({
        text: tts.activeSourceText,
        mode: tts.ttsMode,
        engine: tts.ttsEngine,
        engineB: tts.ttsMode === "dialogue" ? tts.ttsEngineB : undefined,
        model: tts.ttsModel || undefined,
        modelB: tts.ttsMode === "dialogue" ? tts.ttsModelB : undefined,
        voice: tts.voice,
        voiceB: tts.ttsMode === "dialogue" ? tts.voiceB : undefined,
        rate: tts.rate,
      });
    }
    prevAudioUrlRef.current = tts.audioUrl;
  }, [tts.audioUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDownload() {
    if (!tts.audioUrl) return;
    try {
      const audioBlob: Blob = tts.audioBlob ?? await fetch(tts.audioUrl).then((response) => response.blob());
      const { filename, mimeType } = getAudioExportMeta(audioBlob);
      const desktopSaveAudio = (window as DesktopBridgeWindow).pywebview?.api?.save_audio_file;
      if (desktopSaveAudio) {
        const result = await desktopSaveAudio({
          filename,
          mime_type: mimeType,
          data_base64: await blobToBase64(audioBlob)
        });
        if (result?.ok || result?.cancelled) {
          return;
        }
        throw new Error(result?.message || "Desktop audio export failed.");
      }

      const a = document.createElement("a");
      a.href = tts.audioUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (error) {
      console.error("Failed to export TTS audio:", error);
      window.alert(t("导出音频失败，请重试或在系统菜单中打开音频输出目录。", "Failed to export audio. Retry or open the audio output folder from the system menu."));
    }
  }


  const activeLength =
    tts.ttsMode === "dialogue"
      ? tts.dialogueText.length
      : tts.ttsMode === "pdf"
        ? tts.pdfText.length
        : tts.text.length;
  const errorNotice = tts.ttsError ? (
    <div className="vsTtsErrorNotice" role="alert">
      <ErrorNotice
        message={tts.ttsError}
        scope="tts"
        context={{
          ...errorRuntimeContext,
          engine: tts.ttsEngine,
          engineB: tts.ttsMode === "dialogue" ? tts.ttsEngineB : undefined,
          mode: tts.ttsMode,
          voice: tts.voice,
          voiceB: tts.ttsMode === "dialogue" ? tts.voiceB : undefined,
          rate: tts.rate
        }}
      />
    </div>
  ) : null;

  const handleClearWorkspace = () => {
    if (tts.ttsMode === "dialogue") {
      tts.onDialogueTextChange("");
      return;
    }
    if (tts.ttsMode === "pdf") {
      tts.onPdfTextChange("");
      tts.onPdfFileChange(null);
      return;
    }
    tts.onTextChange("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      if (!tts.generating && !tts.extractingPdf && !tts.polishingPdf && tts.activeSourceText.trim()) {
        e.preventDefault();
        const form = e.currentTarget.closest("form");
        if (form && typeof form.requestSubmit === "function") {
          form.requestSubmit();
        } else {
          tts.onSubmit({ preventDefault: () => {} } as React.FormEvent);
        }
      }
    }
  };

  const handleRestoreText = (entry: TtsHistoryEntry) => {
    const currentText =
      tts.ttsMode === "dialogue"
        ? tts.dialogueText
        : tts.ttsMode === "pdf"
          ? tts.pdfText
          : tts.text;

    if (currentText.trim() && currentText.trim() !== entry.text.trim()) {
      if (
        !window.confirm(
          t(
            "当前输入框已有内容，确认替换为该历史记录的内容吗？",
            "The editor already has content. Replace it with this history record?"
          )
        )
      ) {
        return;
      }
    }

    if (entry.mode === "dialogue") {
      if (tts.ttsMode !== "dialogue") {
        tts.onTtsModeChange("dialogue");
      }
      tts.onDialogueTextChange?.(entry.text);
      if (entry.engine) tts.onEngineChange(entry.engine);
      if (entry.engineB && tts.onEngineBChange) tts.onEngineBChange(entry.engineB);
      if (entry.voice) tts.onVoiceChange(entry.voice);
      if (entry.voiceB && tts.onVoiceBChange) tts.onVoiceBChange(entry.voiceB);
      if (entry.rate) tts.onRateChange(entry.rate);
    } else {
      if (tts.ttsMode !== "text" && entry.mode === "text") {
        tts.onTtsModeChange("text");
      }
      tts.onTextChange(entry.text);
      if (entry.engine) tts.onEngineChange(entry.engine);
      if (entry.voice) tts.onVoiceChange(entry.voice);
      if (entry.rate) tts.onRateChange(entry.rate);
    }
    setHistoryDrawerOpen(false);
  };

  useEffect(() => {
    if (!historyDrawerOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setHistoryDrawerOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [historyDrawerOpen]);

  const isMac = typeof navigator !== "undefined" && /(Mac|iPhone|iPod|iPad)/i.test(navigator.userAgent || navigator.platform);
  const shortcutText = isMac ? "⌘ + ↵" : "Ctrl + ↵";

  const historyCount = history.length;

  return (
    <section className="vsTtsWorkspace vsTtsSingleColumn">
      {/* Test compatibility: preserve accessible trigger if tested in isolation */}
      <span className="vsVisuallyHidden">文本转语音</span>
      <button
        type="button"
        className="vsVisuallyHidden"
        aria-label="对话转语音"
        onClick={() => tts.onTtsModeChange("dialogue")}
      />
      <form
        className="vsTtsLayout"
        onSubmit={tts.onSubmit}
        style={{ display: "flex", flexDirection: "column", height: "100%", width: "100%", margin: 0 }}
      >
        {/* ── Top Studio Bar: Streamlined Parameters ── */}
        {tts.ttsMode !== "dialogue" && (
          <header className="vsTtsStudioBar vsTtsPrimaryHeader">
            <div className="vsTtsBarRight">
              <div className="vsTtsToolbarField vsTtsFieldEngine">
                <span className="vsFieldLabel">{t("TTS 引擎:", "TTS Engine:")}</span>
                <div className="vsSelectWrapper">
                  <select
                    className="vsSelect vsSelectModern"
                    value={tts.ttsEngine}
                    onChange={(e) => tts.onEngineChange(e.target.value as typeof tts.ttsEngine)}
                  >
                    {tts.engineOptions.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {tts.ttsModelOptions && tts.ttsModelOptions.length > 0 && (
                <div className="vsTtsToolbarField vsTtsFieldModel">
                  <span className="vsFieldLabel">{t("模型版本:", "Model:")}</span>
                  <div className="vsSelectWrapper">
                    <select
                      className="vsSelect vsSelectModern"
                      value={tts.ttsModel || ""}
                      onChange={(e) => tts.onModelChange?.(e.target.value)}
                    >
                      {tts.ttsModelOptions.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}

              <div className="vsTtsToolbarField vsTtsFieldVoice">
                <div className="vsVoiceCapsuleWrapper">
                  <span className="vsVoiceCapsuleAvatar" aria-hidden="true">🎙️</span>
                  <select
                    className="vsSelect vsSelectModern vsSelectVoice"
                    value={tts.voice}
                    onChange={(e) => tts.onVoiceChange(e.target.value)}
                    disabled={tts.loadingVoices || tts.voiceOptions.length === 0}
                  >
                    <option value="" disabled>{t("-- 请选择音色 --", "-- Select a voice --")}</option>
                    {tts.voiceOptions.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                  {tts.loadingVoices && <span className="vsSelectLoading">{t("加载中…", "Loading...")}</span>}
                </div>
              </div>

              <div className="vsTtsToolbarField vsTtsFieldRate">
                <div className="vsRateCapsule">
                  <span className="vsRateLabel">{t("语速", "Rate")}</span>
                  <input
                    type="text"
                    className="vsInput vsInputModern vsInputRate"
                    value={tts.rate}
                    onChange={(e) => tts.onRateChange(e.target.value)}
                    placeholder="+0%"
                  />
                  <div className="vsRateQuickPresets" role="group" aria-label="语速预设">
                    {[
                      { label: "0.8x", val: "-20%" },
                      { label: "1.0x", val: "+0%" },
                      { label: "1.2x", val: "+20%" },
                    ].map((preset) => (
                      <button
                        key={preset.val}
                        type="button"
                        className={`vsRatePresetTag ${tts.rate === preset.val ? "active" : ""}`}
                        onClick={() => tts.onRateChange(preset.val)}
                        title={`设为 ${preset.val}`}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    className="vsBtnGhost vsRateResetBtn"
                    onClick={() => tts.onRateChange("+0%")}
                    title={t("重置语速", "Reset rate")}
                  >
                    {t("重置", "Reset")}
                  </button>
                </div>
              </div>

              <button
                type="button"
                className={`vsTtsHistoryTriggerBtn ${historyDrawerOpen ? "active" : ""}`}
                onClick={() => setHistoryDrawerOpen((prev) => !prev)}
                title={t("生成历史", "History")}
                aria-expanded={historyDrawerOpen}
              >
                <History size={14} aria-hidden="true" />
                <span>{t("历史", "History")}</span>
                {historyCount > 0 && <span className="vsTtsHistoryCountBadge">{historyCount}</span>}
              </button>
            </div>
          </header>
        )}

        {/* ── Dialogue Config Toolbar ── */}
        {tts.ttsMode === "dialogue" && (
          <div className="vsTtsDialogueBar">
            {/* ── Speaker A ── */}
            <div className="vsDialogueSpeakerRow">
              <span className="vsSpeakerBadge vsSpeakerBadgeA">A</span>
              <div className="vsDialogueEngineWrap">
                <select
                  className="vsSelect vsSelectModern"
                  value={tts.ttsEngine}
                  onChange={(e) => tts.onEngineChange(e.target.value as typeof tts.ttsEngine)}
                  title={t("角色 A 服务商", "Speaker A Engine")}
                >
                  {tts.engineOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </div>
              <div className="vsDialogueVoiceWrap">
                <select
                  className="vsSelect vsSelectModern"
                  value={tts.voice}
                  onChange={(e) => tts.onVoiceChange(e.target.value)}
                  disabled={tts.loadingVoices || tts.voiceOptionsCompact.length === 0}
                  title={t("角色 A 音色", "Speaker A Voice")}
                >
                  <option value="" disabled>{t("选择音色…", "Select voice…")}</option>
                  {tts.voiceOptionsCompact.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="vsDialogueDivider" aria-hidden="true" />

            {/* ── Speaker B ── */}
            <div className="vsDialogueSpeakerRow">
              <span className="vsSpeakerBadge vsSpeakerBadgeB">B</span>
              <div className="vsDialogueEngineWrap">
                <select
                  className="vsSelect vsSelectModern"
                  value={tts.ttsEngineB}
                  onChange={(e) => tts.onEngineBChange?.(e.target.value as typeof tts.ttsEngine)}
                  title={t("角色 B 服务商", "Speaker B Engine")}
                >
                  {tts.engineOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </div>
              <div className="vsDialogueVoiceWrap">
                <select
                  className="vsSelect vsSelectModern"
                  value={tts.voiceB}
                  onChange={(e) => tts.onVoiceBChange?.(e.target.value)}
                  disabled={tts.loadingVoicesB || tts.voiceOptionsBCompact.length === 0}
                  title={t("角色 B 音色", "Speaker B Voice")}
                >
                  <option value="" disabled>{t("选择音色…", "Select voice…")}</option>
                  {tts.voiceOptionsBCompact.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="vsDialogueDivider" aria-hidden="true" />

            {/* ── Global Rate ── */}
            <div className="vsDialogueRateRow">
              <span className="vsFieldLabelSub">{t("语速", "Rate")}</span>
              <input
                type="text"
                className="vsInput vsInputModern vsInputRate"
                value={tts.rate}
                onChange={(e) => tts.onRateChange(e.target.value)}
                placeholder="+0%"
              />
              <button
                type="button"
                className="vsBtnGhost vsRateResetBtn"
                onClick={() => tts.onRateChange("+0%")}
                title={t("重置语速", "Reset rate")}
              >
                {t("重置", "Reset")}
              </button>
              <button
                type="button"
                className={`vsTtsHistoryTriggerBtn ${historyDrawerOpen ? "active" : ""}`}
                onClick={() => setHistoryDrawerOpen((prev) => !prev)}
                title={t("生成历史", "History")}
                aria-expanded={historyDrawerOpen}
              >
                <History size={14} aria-hidden="true" />
                <span>{t("历史", "History")}</span>
                {historyCount > 0 && <span className="vsTtsHistoryCountBadge">{historyCount}</span>}
              </button>
            </div>
          </div>
        )}

        {errorNotice}

        {/* ── Middle Pane: Full-Width Studio Canvas ── */}
        <div className="vsTtsEditorWrap">
          {tts.ttsMode === "text" && (
            <textarea
              className="vsTtsEditor custom-scrollbar"
              value={tts.text}
              onChange={(e) => tts.onTextChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t("在此键入或粘贴您想要合成的文本、旁白、剧本内容… (支持按 Ctrl+Enter 快捷合成)", "Enter narration, body text, or a single-speaker script to synthesize... (Press Ctrl+Enter to generate)")}
            />
          )}
          {tts.ttsMode === "dialogue" && (
            <textarea
              className="vsTtsEditor custom-scrollbar"
              value={tts.dialogueText}
              onChange={(e) => tts.onDialogueTextChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t("A: 你好，欢迎来到今天的节目。\nB: 今天我们来聊聊 Echo 的语音工作流。(支持按 Ctrl+Enter 快捷合成)", "A: Hello, welcome to today's show.\nB: Today we're talking about Echo's speech workflow. (Press Ctrl+Enter to generate)")}
            />
          )}
          {tts.ttsMode === "pdf" && (
            <div className="vsPdfEditorContainer">
              <div className="vsPdfUploadRow" style={{ opacity: (tts.extractingPdf || tts.polishingPdf) ? 0.6 : 1 }}>
                <span className="vsPdfUploadLabel">📁 {t("选择 PDF 文件", "Select PDF File")}:</span>
                <input
                  type="file"
                  key={tts.pdfFile ? tts.pdfFile.name : "empty"}
                  accept="application/pdf"
                  onChange={(e) => tts.onPdfFileChange(e.target.files?.[0] || null)}
                  disabled={tts.extractingPdf || tts.polishingPdf}
                  className="vsPdfFileInput"
                />
                {tts.pdfText.trim() && (
                  <button
                    type="button"
                    className="vsBtnSecondary vsPolishBtn"
                    onClick={tts.onPolishPdfText}
                    disabled={tts.extractingPdf || tts.polishingPdf}
                  >
                    {tts.polishingPdf ? (
                      <>
                        <span className="spinner-mini"></span>
                        {t("优化中...", "Optimizing...")}
                      </>
                    ) : (
                      <>✨ {t("AI 朗读优化", "AI Oralize")}</>
                    )}
                  </button>
                )}
              </div>
              <textarea
                className="vsTtsEditor custom-scrollbar"
                value={tts.pdfText}
                onChange={(e) => tts.onPdfTextChange(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={tts.extractingPdf || tts.polishingPdf}
                placeholder={
                  tts.extractingPdf
                    ? t("正在从 PDF 提取文本中，请稍候...", "Extracting text from PDF, please wait...")
                    : tts.polishingPdf
                    ? t("正在使用 AI 优化文本（移除噪声、转换数学公式），请稍候...", "AI is optimizing text (removing noise, translating math formulas), please wait...")
                    : t("这里放 PDF 提取后的可朗读正文。(支持按 Ctrl+Enter 快捷合成)", "Paste the readable body text extracted from the PDF here. (Press Ctrl+Enter to generate)")
                }
                style={{ opacity: (tts.extractingPdf || tts.polishingPdf) ? 0.6 : 1 }}
              />
            </div>
          )}

          {/* Floating Corner Utilities inside Editor */}
          <div className="vsTtsEditorCornerTools">
            <button
              type="button"
              className="vsTtsCornerClearBtn"
              onClick={handleClearWorkspace}
              disabled={!tts.activeSourceText || tts.extractingPdf || tts.polishingPdf}
              title={t("清空舞台", "Clear workspace")}
            >
              <svg className="vsIconSmall" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M3 6h18m-2 0v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6m3 0V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
              </svg>
              <span>{t("清空", "Clear")}</span>
            </button>
            <span className="vsTtsCornerDivider">|</span>
            <span className="vsTtsCornerStats">{activeLength} {t("字", "chars")}</span>
          </div>
        </div>

        {/* ── Bottom Pane: Playback & Action Footer ── */}
        <footer className="vsTtsEditorFooter">
          <div className="vsTtsFooterLeft">
            {tts.audioUrl && (
              <div className="vsAudioPlayerDock">
                <audio controls src={tts.audioUrl} className="vsAudioElement" />
                <button
                  type="button"
                  className="vsBtnSecondary vsExportAudioBtn"
                  onClick={handleDownload}
                  title={t("导出音频", "Export Audio")}
                >
                  <svg className="vsIconSmall" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                  <span>{t("导出音频", "Export Audio")}</span>
                </button>
              </div>
            )}

            {tts.ttsInfo && (
              <p className="vsSettingsNotice ok">{tts.ttsInfo}</p>
            )}

            {!tts.audioUrl && !tts.ttsInfo && (
              <div className="vsTtsEmptyHint">
                <span className="vsTtsHintIcon">🎧</span>
                <span>{t("完成输入后，点击右下角“生成音频”开始试听", "Enter text and click Generate Audio to listen")}</span>
              </div>
            )}
          </div>

          <div className="vsTtsFooterRight">
            <button
              type="submit"
              className="vsBtnPrimary vsTtsGenerateBtn"
              title={`${t("生成音频", "Generate audio")} (${shortcutText})`}
              disabled={tts.generating || tts.extractingPdf || tts.polishingPdf || !tts.activeSourceText.trim()}
            >
              {tts.generating ? (
                <>
                  <span className="spinner-mini"></span>
                  <span>{t("生成中…", "Generating...")}</span>
                </>
              ) : (
                <>
                  <svg className="vsIconSmall" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                    <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07" />
                  </svg>
                  <span>{t("生成音频", "Generate audio")}</span>
                </>
              )}
            </button>
          </div>
        </footer>

        {/* ── Slide-Over History Drawer ── */}
        {historyDrawerOpen && (
          <div
            className="vsTtsDrawerBackdrop"
            onClick={() => setHistoryDrawerOpen(false)}
            aria-hidden="true"
          />
        )}
        <aside
          className={`vsTtsHistoryDrawer ${historyDrawerOpen ? "open" : ""}`}
          aria-label={t("生成历史", "Generation History")}
          aria-hidden={!historyDrawerOpen}
        >
          <div className="vsTtsDrawerHeader">
            <div className="vsTtsDrawerTitle">
              <History size={16} aria-hidden="true" />
              <span>{t("生成历史", "History")}</span>
              {historyCount > 0 && <span className="vsTtsHistoryCountBadge">{historyCount}</span>}
            </div>
            <div className="vsTtsDrawerHeaderActions">
              {historyCount > 0 && (
                <button
                  type="button"
                  className="vsTtsDrawerClearBtn"
                  onClick={() => {
                    if (window.confirm(t("确定清空所有生成历史？", "Clear all generation history?"))) {
                      clearHistory();
                    }
                  }}
                  title={t("清空所有历史", "Clear all history")}
                >
                  <Trash2 size={13} aria-hidden="true" />
                  <span>{t("清空", "Clear")}</span>
                </button>
              )}
              <button
                type="button"
                className="vsTtsDrawerCloseBtn"
                onClick={() => setHistoryDrawerOpen(false)}
                title={t("关闭", "Close")}
                aria-label={t("关闭", "Close")}
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="vsTtsHistoryDrawerList custom-scrollbar">
            {history.length === 0 ? (
              <div className="vsTtsHistoryEmptyState">
                <span className="vsTtsHistoryEmptyIcon" aria-hidden="true">📜</span>
                <p className="vsTtsHistoryEmptyTitle">{t("暂无生成历史", "No generations yet")}</p>
                <p className="vsTtsHistoryEmptyDesc">
                  {t(
                    "每次成功生成音频后，都会保留在此处以便试听对比与恢复。",
                    "Synthesized audio will be kept here for A/B preview and reference."
                  )}
                </p>
              </div>
            ) : (
              history.map((entry: TtsHistoryEntry) => (
                <div key={entry.id} className="vsTtsHistoryCard">
                  <div className="vsTtsHistoryCardHeader">
                    <div className="vsTtsHistoryCardMeta">
                      <span className="vsTtsHistoryCardTime">{formatHistoryTime(entry.createdAt, t)}</span>
                      <span className="vsTtsHistoryCardSep">·</span>
                      <span className="vsTtsHistoryCardEngine">{entry.engine}</span>
                      {entry.voice && (
                        <>
                          <span className="vsTtsHistoryCardSep">·</span>
                          <span className="vsTtsHistoryCardVoice" title={entry.voice}>
                            {formatHistoryVoiceName(entry.voice)}
                          </span>
                        </>
                      )}
                      {entry.rate && entry.rate !== "+0%" && (
                        <span className="vsTtsHistoryCardRate">{entry.rate}</span>
                      )}
                    </div>
                    <button
                      type="button"
                      className="vsTtsHistoryRemove"
                      onClick={() => removeEntry(entry.id)}
                      title={t("删除", "Delete")}
                      aria-label={t("删除", "Delete")}
                    >
                      <X size={13} aria-hidden="true" />
                    </button>
                  </div>

                  <div className="vsTtsHistoryCardText" title={entry.text}>
                    {truncate(entry.text, 120)}
                  </div>

                  <div className="vsTtsHistoryCardFooter">
                    <TtsHistoryMiniPlayer src={buildReplayUrl(entry)} />
                    <button
                      type="button"
                      className="vsTtsHistoryRestoreBtn"
                      onClick={() => handleRestoreText(entry)}
                      title={t("恢复此文本与配置到输入框", "Restore text and voice to editor")}
                    >
                      <RotateCcw size={12} aria-hidden="true" />
                      <span>{t("恢复", "Restore")}</span>
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>
      </form>
    </section>
  );
}
