import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import type { TranscriptionJobResponse, WordTimestamp } from "../../api";
import ErrorNotice from "../ErrorNotice";
import { useI18n } from "../../i18n";
import { asrProviderLabel } from "../../utils/asrProviders";
import TranscriptionSubtitlePlayer, { type SubtitleExportActions } from "./TranscriptionSubtitlePlayer";

type Props = {
  job: TranscriptionJobResponse | null;
  transcript: string;
  words?: WordTimestamp[] | null;
  statusMessage: string;
  memorySaved: boolean;
  isBusy: boolean;
  detailLoading: boolean;
  audioDuration: number;
  audioSourceUrl?: string;
  error: Error | null;
  infoMessage: string;
  language: string;
  onBack: () => void;
  onCopy: () => void;
  onExport: (format: "txt" | "srt" | "vtt" | "json") => void;
  onAudioDurationChange: (dur: number) => void;
  onReservedAction?: (action: string) => void;
  onSaveMemory: () => void;
  memorySaving: boolean;
};

export default function TranscriptionDetailDrawer({
  job,
  transcript,
  words,
  statusMessage,
  memorySaved,
  isBusy,
  detailLoading,
  audioDuration,
  audioSourceUrl,
  error,
  infoMessage,
  language,
  onBack,
  onCopy,
  onExport,
  onAudioDurationChange,
  onSaveMemory,
  memorySaving,
}: Props) {
  const { t } = useI18n();
  const [showExportMenu, setShowExportMenu] = useState(false);
  // Cue-aware export actions registered by the subtitle player (bilingual exports, burn-in video).
  const [subtitleExports, setSubtitleExports] = useState<SubtitleExportActions | null>(null);

  const runExport = (run: () => void) => {
    run();
    setShowExportMenu(false);
  };

  const fileName = job?.file_name || t("转写详情", "Transcription Detail");
  const detailStatusClass =
    job?.status === "completed"
      ? "completed"
      : job?.status === "failed"
      ? "failed"
      : "";

  return (
    <section className="vsTranscribeDetail">
      {/* Header */}
      <div className="vsTranscribeDetailHeader">
        <button
          type="button"
          className="vsTranscribeBackBtn"
          onClick={onBack}
          title={t("返回转写列表", "Back to transcription list")}
          aria-label={t("返回转写列表", "Back to transcription list")}
        >
          <ArrowLeft size={16} strokeWidth={2.2} />
          <span>{t("返回列表", "Back")}</span>
        </button>

        <div className="vsTranscribeDetailInfo">
          <h2 className="vsTranscribeDetailFileName" title={fileName}>{fileName}</h2>
          <div className="vsTranscribeDetailMeta">
            {job?.updated_at
              ? new Date(job.updated_at).toLocaleString(
                  language === "en-US" ? "en-US" : "zh-CN"
                )
              : ""}
            {job?.mode && (
              <span style={{ marginLeft: 8, opacity: 0.7 }}>
                ({job.mode === "sync" ? t("同步", "Sync") : t("异步", "Async")})
              </span>
            )}
            {job?.provider && (
              <span style={{ marginLeft: 8, opacity: 0.7 }}>
                · {t("引擎", "Engine")}: {asrProviderLabel(job.provider, language)}
              </span>
            )}
            {statusMessage && (
              <span className="vsTranscribeDetailStatus">{statusMessage}</span>
            )}
            {memorySaved && (
              <span className="vsTranscribeBadgeSuccess">
                {t("已入记忆", "Saved to memory")}
              </span>
            )}
          </div>
        </div>
        <div className="vsTranscribeDetailActions">
          <button
            onClick={onSaveMemory}
            disabled={!transcript || memorySaving || memorySaved}
            className="vsBtnSecondary"
            title={t("把这段转写存入长期记忆", "Save this transcript to long-term memory")}
            style={{ height: 34, fontSize: 13, padding: "0 14px" }}
          >
            {memorySaved
              ? t("✓ 已入记忆", "✓ In memory")
              : memorySaving
              ? t("存入中…", "Saving…")
              : t("🧠 存入记忆", "🧠 Save to memory")}
          </button>
          <button
            onClick={onCopy}
            disabled={!transcript}
            className="vsBtnSecondary"
            style={{ height: 34, fontSize: 13, padding: "0 14px" }}
          >
            {t("复制", "Copy")}
          </button>
          <div style={{ position: "relative" }}>
            <button
              className="vsBtnSecondary"
              disabled={!transcript}
              onClick={() => setShowExportMenu((v) => !v)}
              style={{ height: 34, fontSize: 13, padding: "0 14px" }}
            >
              {t("导出", "Export")} ▾
            </button>
            {showExportMenu && transcript && (
              <>
                <div
                  style={{ position: "fixed", inset: 0, zIndex: 99 }}
                  onClick={() => setShowExportMenu(false)}
                />
                <div className="vsExportDropdownMenu">
                  <button
                    className="vsExportDropdownItem"
                    onClick={() => runExport(() => onExport("txt"))}
                  >
                    <span>📃</span>
                    <span>{t("导出 TXT 文本", "Export TXT")}</span>
                  </button>
                  <button
                    className="vsExportDropdownItem"
                    onClick={() => runExport(() => onExport("json"))}
                  >
                    <span>📦</span>
                    <span>{t("导出 JSON 数据", "Export JSON Data")}</span>
                  </button>
                  <div className="vsMenuDivider" />
                  <button
                    className="vsExportDropdownItem"
                    onClick={() => runExport(() => onExport("srt"))}
                  >
                    <span>📄</span>
                    <span>{t("导出 SRT 字幕", "Export SRT Subtitle")}</span>
                  </button>
                  <button
                    className="vsExportDropdownItem"
                    onClick={() => runExport(() => onExport("vtt"))}
                  >
                    <span>📑</span>
                    <span>{t("导出 VTT 字幕", "Export VTT Subtitle")}</span>
                  </button>
                  {subtitleExports && (
                    <>
                      <div className="vsMenuDivider" />
                      <button
                        className="vsExportDropdownItem"
                        onClick={() => runExport(() => subtitleExports.exportSubtitleFile("bilingual_srt"))}
                      >
                        <span>📝</span>
                        <span>{t("导出双语字幕 (SRT)", "Export Bilingual SRT")}</span>
                      </button>
                      <button
                        className="vsExportDropdownItem"
                        onClick={() => runExport(() => subtitleExports.exportSubtitleFile("target_srt"))}
                      >
                        <span>🌐</span>
                        <span>{t("导出译文字幕 (SRT)", "Export Translated SRT")}</span>
                      </button>
                      <button
                        className="vsExportDropdownItem"
                        onClick={() => runExport(() => subtitleExports.exportSubtitleFile("bilingual_vtt"))}
                      >
                        <span>🗂️</span>
                        <span>{t("导出双语 WebVTT", "Export Bilingual VTT")}</span>
                      </button>
                      {subtitleExports.hasVideo && (
                        <>
                          <div className="vsMenuDivider" />
                          <button
                            className="vsExportDropdownItem vsExportDropdownHighlight"
                            disabled={subtitleExports.burning}
                            onClick={() => runExport(() => subtitleExports.burnBilingualVideo())}
                          >
                            <span>🎬</span>
                            <span>
                              {subtitleExports.burning
                                ? t("正在压制双语视频…", "Burning bilingual video…")
                                : t("压制并导出双语视频 (MP4)", "Burn-in Bilingual Video (MP4)")}
                            </span>
                          </button>
                        </>
                      )}
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Status Banner - only when busy or failed */}
      {statusMessage && (isBusy || job?.status === "failed") && (
        <div className={`vsTranscribeStatusBanner ${detailStatusClass}`}>
          <div
            className="vsTranscribeStatusDot"
            style={{
              background: isBusy
                ? "var(--brand)"
                : "var(--danger, #ef4444)",
              animation: isBusy ? "pulsingDot 2s infinite" : "none",
            }}
          />
          <span className="vsTranscribeStatusText">{statusMessage}</span>
        </div>
      )}

      {/* Transcript + synced subtitle player */}
      {detailLoading ? (
        <div className="vsTranscribeDetailContent custom-scrollbar">
          <div className="vsTranscribeDetailTranscript loading">
            <div
              className="spinner"
              style={{
                width: 40,
                height: 40,
                border: "4px solid var(--line)",
                borderTopColor: "var(--brand)",
                borderRadius: "50%",
              }}
            />
            <p style={{ fontSize: 14, fontWeight: 600 }}>
              {t("加载中…", "Loading...")}
            </p>
          </div>
        </div>
      ) : transcript ? (
        <TranscriptionSubtitlePlayer
          jobId={job?.job_id}
          transcript={transcript}
          words={words || []}
          audioSourceUrl={audioSourceUrl}
          audioDuration={audioDuration}
          fileName={job?.file_name}
          onAudioDurationChange={onAudioDurationChange}
          onRegisterExportActions={setSubtitleExports}
        />
      ) : isBusy ? (
        <div className="vsTranscribeDetailContent custom-scrollbar">
          <div className="vsTranscribeDetailTranscript loading">
            <div
              className="spinner"
              style={{
                width: 40,
                height: 40,
                border: "4px solid var(--line)",
                borderTopColor: "var(--brand)",
                borderRadius: "50%",
              }}
            />
            <p style={{ fontSize: 14, fontWeight: 600 }}>
              {t("转写处理中，请稍候...", "Transcribing audio, please wait...")}
            </p>
          </div>
        </div>
      ) : (
        <div className="vsTranscribeDetailContent custom-scrollbar">
          <div className="vsTranscribeDetailTranscript loading">
            <p style={{ fontSize: 14 }}>
              {t("暂无转写内容", "No transcript content available")}
            </p>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ padding: "0 24px 12px" }}>
          <ErrorNotice message={error.message || String(error)} scope="Transcription" />
        </div>
      )}

      {/* Info Message */}
      {infoMessage && (
        <div
          style={{
            margin: "0 24px 12px",
            fontSize: 12,
            color: "#b45309",
            background: "#fef3c7",
            padding: "8px 12px",
            borderRadius: 8,
            border: "1px solid #fde68a",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span>💡</span>
          <span style={{ flex: 1 }}>{infoMessage}</span>
        </div>
      )}
    </section>
  );
}
