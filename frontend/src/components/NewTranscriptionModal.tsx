import React, { useState } from "react";
import { AudioDropZone } from "./AudioDropZone";
import ErrorNotice from "./ErrorNotice";
import RealtimeTranscriptionPanel from "./transcription/RealtimeTranscriptionPanel";
import { useI18n } from "../i18n";
import type { TranscriptionJobResponse } from "../api";

type Props = {
  open: boolean;
  onClose: () => void;
  onLocalTranscribe: (file: File, provider?: string) => void;
  onRemoteSubmit: (url: string) => void;
  onRealtimeComplete: (job: TranscriptionJobResponse) => void;
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
    onRemoteSubmit(url);
  }

  return (
    <div
      className="vsTranscribeModalOverlay"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isBusy) onClose();
      }}
    >
      <div className="vsTranscribeModal" onClick={(e) => e.stopPropagation()}>
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
            onClick={() => setInputMode("realtime")}
            style={{ flex: 1, justifyContent: "center" }}
          >
            {t("实时转写", "Realtime")}
          </button>
        </div>

        {/* Content */}
        {inputMode === "realtime" ? (
          <RealtimeTranscriptionPanel onComplete={onRealtimeComplete} />
        ) : inputMode === "local" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            <AudioDropZone
              onFileDrop={handleFileDrop}
              selectedFile={selectedFile}
              isProcessing={isBusy}
              inputLabel={t("选择转写音频", "Choose transcription audio")}
              readyText={t(
                "已选中，可开始同步转写",
                "Selected. Ready for synchronous transcription"
              )}
              subText={t(
                "支持 MP3, WAV, M4A, FLAC, AAC, OGG 格式 (最大 25MB)",
                "Supports MP3, WAV, M4A, FLAC, AAC, OGG formats (max 25MB)"
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
                <option value="auto">{t("自动选择 (优先精确时间戳)", "Auto (prefer precise timestamps)")}</option>
                <option value="deepgram">Deepgram (Nova-3)</option>
                <option value="openai">OpenAI Whisper</option>
                <option value="assemblyai">AssemblyAI</option>
                <option value="dashscope">Qwen-Audio 3.0 ASR Flash ({t("阿里云", "Alibaba Cloud")})</option>
                <option value="xiaomi">{t("小米 MiMo", "Xiaomi MiMo")}</option>
                <option value="qwen-legacy">Qwen3 ASR Flash ({t("旧版", "Legacy")})</option>
              </select>
              <span
                style={{
                  fontSize: "12px",
                  color: "var(--muted)",
                  lineHeight: "1.4",
                }}
              >
                {t(
                  "Deepgram、OpenAI Whisper、AssemblyAI 和 Qwen-Audio 3.0 ASR Flash 支持精确单词级时间戳，适合生成字幕。Qwen-Audio 还支持热词定制与多语种混合识别。",
                  "Deepgram, OpenAI Whisper, AssemblyAI, and Qwen-Audio 3.0 ASR Flash support precise word-level timestamps, ideal for subtitle generation. Qwen-Audio also supports instant hotwords and mixed-language recognition."
                )}
              </span>
            </div>
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
              {isSyncBusy ? (
                <>
                  <span className="spinner-mini" /> {t("转写中…", "Transcribing...")}
                </>
              ) : (
                t("开始同步转写", "Start sync transcription")
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
