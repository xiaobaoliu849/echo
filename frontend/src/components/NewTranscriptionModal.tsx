import React, { useState } from "react";
import { AudioDropZone } from "./AudioDropZone";
import ErrorNotice from "./ErrorNotice";
import RealtimeTranscriptionPanel from "./transcription/RealtimeTranscriptionPanel";
import { useI18n } from "../i18n";
import type { TranscriptionJobResponse, WordTimestamp } from "../api";
import { ASR_ENGINES, ASYNC_ASR_MODELS } from "../utils/asrProviders";

type Props = {
  open: boolean;
  onClose: () => void;
  onLocalTranscribe: (file: File, provider?: string) => void;
  onRemoteSubmit: (url: string, provider?: string) => void;
  onRealtimeComplete: (job: TranscriptionJobResponse, words?: WordTimestamp[]) => void;
  onSwitchToRealtimeStudio?: () => void;
  isBusy: boolean;
  isSyncBusy: boolean;
  isAsyncBusy: boolean;
  error: Error | null;
};

export const NewTranscriptionModal: React.FC<Props> = ({
  open,
  onClose,
  onLocalTranscribe,
  onRemoteSubmit,
  onRealtimeComplete,
  onSwitchToRealtimeStudio,
  isBusy,
  isSyncBusy,
  isAsyncBusy,
  error,
}) => {
  const { t } = useI18n();
  const [inputMode, setInputMode] = useState<"local" | "remote" | "realtime">("local");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [remoteUrl, setRemoteUrl] = useState("");
  const [asrProvider, setAsrProvider] = useState<string>("auto");
  const [asyncModel, setAsyncModel] = useState<string>("qwen-filetrans");

  if (!open) return null;

  function handleFileDrop(file: File) {
    setSelectedFile(file);
  }

  function handleSubmitLocal() {
    if (!selectedFile) return;
    const provider = asrProvider === "auto" ? undefined : asrProvider;
    onLocalTranscribe(selectedFile, provider);
  }

  function handleSubmitRemote() {
    const url = remoteUrl.trim();
    if (!url) return;
    onRemoteSubmit(url, asyncModel);
  }

  return (
    <div
      className="vsTranscribeModalOverlay"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isBusy) onClose();
      }}
    >
      <div
        className="vsTranscribeModal"
        style={inputMode === "realtime" ? { maxWidth: "780px" } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="vsTranscribeModalHeader">
          <h2 className="vsTranscribeModalTitle">
            {t("新建转写", "New Transcription")}
          </h2>
          <button
            className="vsTranscribeModalClose"
            onClick={onClose}
            disabled={isBusy}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Mode Tabs */}
        <div
          className="vsTranscribeFilterTabs"
          style={{ alignSelf: "stretch" }}
        >
          <button
            type="button"
            className={`vsTranscribeFilterTab ${inputMode === "local" ? "active" : ""}`}
            onClick={() => setInputMode("local")}
            style={{ flex: 1, justifyContent: "center" }}
          >
            {t("本地音频", "Local Audio")}
          </button>
          <button
            type="button"
            className={`vsTranscribeFilterTab ${inputMode === "remote" ? "active" : ""}`}
            onClick={() => setInputMode("remote")}
            style={{ flex: 1, justifyContent: "center" }}
          >
            {t("链式转写", "Async Pipeline")}
          </button>
          <button
            type="button"
            className={`vsTranscribeFilterTab ${inputMode === "realtime" ? "active" : ""}`}
            onClick={() => {
              if (onSwitchToRealtimeStudio) {
                onSwitchToRealtimeStudio();
              } else {
                setInputMode("realtime");
              }
            }}
            style={{ flex: 1, justifyContent: "center" }}
          >
            {t("🎙️ 实时录音转写", "🎙️ Realtime Studio")}
          </button>
        </div>

        {/* Content */}
        {inputMode === "realtime" ? (
          <RealtimeTranscriptionPanel onComplete={onRealtimeComplete} onSwitchToLibrary={onClose} />
        ) : inputMode === "local" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            <AudioDropZone
              onFileDrop={handleFileDrop}
              selectedFile={selectedFile}
              isProcessing={isBusy}
              inputLabel={t("选择转写音频或视频", "Choose audio or video to transcribe")}
              readyText={t(
                "已选中，可开始转写",
                "Selected. Ready for transcription"
              )}
              subText={t(
                "支持音频（MP3/WAV/M4A/FLAC/AAC/OGG）与视频（MP4/MKV/MOV/AVI 等，自动提取音轨）。长音频与大文件自动分段后台转写，无 5 分钟限制。",
                "Supports audio (MP3/WAV/M4A/FLAC/AAC/OGG) and video (MP4/MKV/MOV/AVI etc., audio track extracted automatically). Long or large files are chunked and transcribed in the background — no 5-minute limit."
              )}
            />
            <div className="vsField" style={{ gap: "8px" }}>
              <label
                className="vsFieldLabel"
                style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}
              >
                {t("语音识别引擎", "Speech Recognition Engine")}
              </label>
              <select
                value={asrProvider}
                onChange={(e) => setAsrProvider(e.target.value)}
                disabled={isBusy}
                className="vsSelect"
                style={{
                  width: "100%",
                  height: "44px",
                  borderRadius: "10px",
                  fontSize: "14px",
                }}
              >
                <option value="auto">{t("自动选择", "Auto")}</option>
                <optgroup label={t("推荐 · 支持精确字幕", "Recommended · precise subtitles")}>
                  {ASR_ENGINES.filter((e) => e.group === "timestamps").map((e) => (
                    <option key={e.id} value={e.id}>
                      {t(e.zh, e.en)}
                    </option>
                  ))}
                </optgroup>
                <optgroup label={t("仅文本转写", "Text-only transcription")}>
                  {ASR_ENGINES.filter((e) => e.group === "text-only").map((e) => (
                    <option key={e.id} value={e.id}>
                      {t(e.zh, e.en)}
                    </option>
                  ))}
                </optgroup>
              </select>
              <span
                style={{
                  fontSize: "12px",
                  color: "var(--muted)",
                  lineHeight: "1.4",
                }}
              >
                {(() => {
                  const engine = ASR_ENGINES.find((e) => e.id === asrProvider);
                  return engine ? t(engine.noteZh, engine.noteEn) : "";
                })()}
              </span>
            </div>
            {selectedFile && selectedFile.size > 25 * 1024 * 1024 && (
              <span
                style={{
                  fontSize: "12px",
                  color: "var(--muted)",
                  lineHeight: "1.4",
                }}
              >
                {t(
                  "该文件较大，将自动转入后台分段转写，可在转写记录中查看进度。",
                  "This file is large; it will run as a background chunked job. Track progress in the transcription list."
                )}
              </span>
            )}
            <button
              onClick={handleSubmitLocal}
              disabled={!selectedFile || isBusy}
              className="vsBtnPrimary"
              style={{
                width: "100%",
                height: "44px",
                fontSize: "14px",
                borderRadius: "10px",
                fontWeight: 600,
              }}
            >
              {isSyncBusy || isAsyncBusy ? (
                <>
                  <span className="spinner-mini" /> {t("转写中…", "Transcribing...")}
                </>
              ) : (
                t("开始转写", "Start transcription")
              )}
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            <div className="vsField" style={{ gap: "8px" }}>
              <label
                className="vsFieldLabel"
                style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}
              >
                {t("音频 URL 地址", "Audio URL Address")}
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
                }}
              />
              <span
                style={{
                  fontSize: "12px",
                  color: "var(--muted)",
                  lineHeight: "1.4",
                }}
              >
                {t(
                  "支持直接可下载的公网 http/https/oss 格式音频。大文件推荐走此通道。",
                  "Supports publicly accessible and downloadable http/https/oss links. Best for larger files."
                )}
              </span>
            </div>

            <div className="vsField" style={{ gap: "8px" }}>
              <label
                className="vsFieldLabel"
                style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}
              >
                {t("转写模型", "Transcription Model")}
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
                {ASYNC_ASR_MODELS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {t(m.zh, m.en)}
                  </option>
                ))}
              </select>
              <span
                style={{
                  fontSize: "12px",
                  color: "var(--muted)",
                  lineHeight: "1.4",
                }}
              >
                {t(
                  "链式转写使用阿里云离线文件转写，可在下方模型间选择。",
                  "Async pipeline uses Alibaba offline file transcription; pick a model below."
                )}
              </span>
            </div>

            <button
              onClick={handleSubmitRemote}
              disabled={!remoteUrl.trim() || isBusy}
              className="vsBtnPrimary"
              style={{
                width: "100%",
                height: "44px",
                fontSize: "14px",
                borderRadius: "10px",
                fontWeight: 600,
              }}
            >
              {isAsyncBusy ? (
                <>
                  <span className="spinner-mini" /> {t("任务处理中…", "Processing job...")}
                </>
              ) : (
                t("提交异步任务", "Submit async job")
              )}
            </button>
          </div>
        )}

        {error && (
          <ErrorNotice
            message={error.message || String(error)}
            scope="Transcription"
          />
        )}
      </div>
    </div>
  );
};
