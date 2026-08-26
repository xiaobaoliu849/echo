import ErrorNotice from "../components/ErrorNotice";
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

export default function TtsPage({ tts, errorRuntimeContext }: Props) {
  const { t } = useI18n();
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

  return (
    <section className="vsTtsWorkspace vsTtsSingleColumn">
      <form className="vsTtsLayout" onSubmit={tts.onSubmit} style={{ display: "flex", flexDirection: "column", height: "100%", margin: 0 }}>
        {/* ── Top Pane: Header & Mode Selection ── */}
        <header className="vsTtsPrimaryHeader" style={{ padding: "12px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div className="vsModeTabs" style={{ display: "flex", gap: 8 }}>
            <button type="button" className={tts.ttsMode === "text" ? "vsBtnPrimary" : "vsBtnSecondary"} onClick={() => tts.onTtsModeChange("text")} style={{ height: "32px", fontSize: "12px", padding: "0 12px" }}>
              {t("文本转语音", "Text to speech")}
            </button>
            <button type="button" className={tts.ttsMode === "dialogue" ? "vsBtnPrimary" : "vsBtnSecondary"} onClick={() => tts.onTtsModeChange("dialogue")} style={{ height: "32px", fontSize: "12px", padding: "0 12px" }}>
              {t("对话转语音", "Dialogue to speech")}
            </button>
            <button type="button" className={tts.ttsMode === "pdf" ? "vsBtnPrimary" : "vsBtnSecondary"} onClick={() => tts.onTtsModeChange("pdf")} style={{ height: "32px", fontSize: "12px", padding: "0 12px" }}>
              {t("PDF 转语音", "PDF to speech")}
            </button>
          </div>
          <div className="vsTtsPrimaryStats" style={{ margin: 0 }}>
            <span>{t(`${activeLength} 字`, `${activeLength} chars`)}</span>
          </div>
        </header>

        {/* ── Config Horizontal Toolbar ── */}
        {tts.ttsMode === "dialogue" ? (
          <div className="vsTtsToolbar vsTtsDialogueToolbar" style={{ display: "flex", flexDirection: "column", alignItems: "stretch", gap: "12px", padding: "16px 24px" }}>
            {/* Person A Row */}
            <div style={{ display: "grid", gridTemplateColumns: "85px 220px minmax(260px, 1fr)", alignItems: "center", gap: "16px" }}>
              <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "700", color: "var(--brand)", whiteSpace: "nowrap" }}>
                {t("角色 A (A)", "Speaker A")}:
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%" }}>
                <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155", whiteSpace: "nowrap" }}>{t("服务商", "Engine")}:</span>
                <select
                  className="vsSelect"
                  value={tts.ttsEngine}
                  onChange={(e) => tts.onEngineChange(e.target.value as typeof tts.ttsEngine)}
                  style={{ width: "100%", height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
                >
                  {tts.engineOptions.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%" }}>
                <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155", whiteSpace: "nowrap" }}>{t("音色", "Voice")}:</span>
                <select
                  className="vsSelect"
                  value={tts.voice}
                  onChange={(e) => tts.onVoiceChange(e.target.value)}
                  disabled={tts.loadingVoices || tts.voiceOptions.length === 0}
                  style={{ flex: 1, height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
                >
                  <option value="" disabled>{t("-- 请选择音色 A --", "-- Select voice A --")}</option>
                  {tts.voiceOptions.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                {tts.loadingVoices && <span style={{ fontSize: "12px", color: "var(--brand)", whiteSpace: "nowrap" }}>{t("加载中…", "Loading...")}</span>}
              </div>
            </div>

            {/* Person B Row */}
            <div style={{ display: "grid", gridTemplateColumns: "85px 220px minmax(260px, 1fr)", alignItems: "center", gap: "16px" }}>
              <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "700", color: "var(--brand)", whiteSpace: "nowrap" }}>
                {t("角色 B (B)", "Speaker B")}:
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%" }}>
                <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155", whiteSpace: "nowrap" }}>{t("服务商", "Engine")}:</span>
                <select
                  className="vsSelect"
                  value={tts.ttsEngineB}
                  onChange={(e) => tts.onEngineBChange?.(e.target.value as typeof tts.ttsEngine)}
                  style={{ width: "100%", height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
                >
                  {tts.engineOptions.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%" }}>
                <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155", whiteSpace: "nowrap" }}>{t("音色", "Voice")}:</span>
                <select
                  className="vsSelect"
                  value={tts.voiceB}
                  onChange={(e) => tts.onVoiceBChange?.(e.target.value)}
                  disabled={tts.loadingVoicesB || tts.voiceOptionsB.length === 0}
                  style={{ flex: 1, height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
                >
                  <option value="" disabled>{t("-- 请选择音色 B --", "-- Select voice B --")}</option>
                  {tts.voiceOptionsB.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                {tts.loadingVoicesB && <span style={{ fontSize: "12px", color: "var(--brand)", whiteSpace: "nowrap" }}>{t("加载中…", "Loading...")}</span>}
              </div>
            </div>

            {/* Global Settings Row */}
            <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap", marginTop: "4px", borderTop: "1px dashed var(--line)", paddingTop: "12px" }}>
              <div className="vsTtsToolbarField" style={{ margin: 0 }}>
                <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155" }}>{t("全局语速", "Rate")}:</span>
                <input
                  type="text"
                  className="vsInput"
                  value={tts.rate}
                  onChange={(e) => tts.onRateChange(e.target.value)}
                  placeholder="+0%"
                  style={{ width: "90px", height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
                />
                <button
                  type="button"
                  className="vsBtnGhost"
                  onClick={() => tts.onRateChange("+0%")}
                  style={{ fontSize: "12px", padding: "4px 8px" }}
                >
                  Reset
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="vsTtsToolbar">
            <div className="vsTtsToolbarField">
              <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155" }}>{t("TTS 引擎", "Engine")}:</span>
              <select
                className="vsSelect"
                value={tts.ttsEngine}
                onChange={(e) => tts.onEngineChange(e.target.value as typeof tts.ttsEngine)}
                style={{ width: "160px", height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
              >
                {tts.engineOptions.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>

            {tts.ttsModelOptions && tts.ttsModelOptions.length > 0 && (
              <div className="vsTtsToolbarField">
                <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155" }}>{t("模型版本", "Model")}:</span>
                <select
                  className="vsSelect"
                  value={tts.ttsModel || ""}
                  onChange={(e) => tts.onModelChange?.(e.target.value)}
                  style={{ width: "190px", height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
                >
                  {tts.ttsModelOptions.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="vsTtsToolbarField" style={{ flex: "1 1 280px", maxWidth: "480px" }}>
              <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155" }}>{t("首选音色", "Voice")}:</span>
              <select
                className="vsSelect"
                value={tts.voice}
                onChange={(e) => tts.onVoiceChange(e.target.value)}
                disabled={tts.loadingVoices || tts.voiceOptions.length === 0}
                style={{ flex: 1, minWidth: 0, height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
              >
                <option value="" disabled>{t("-- 请选择音色 --", "-- Select a voice --")}</option>
                {tts.voiceOptions.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
              {tts.loadingVoices && <span style={{ fontSize: "12px", color: "var(--brand)" }}>{t("加载中…", "Loading...")}</span>}
            </div>

            <div className="vsTtsToolbarField">
              <span className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: "600", color: "#334155" }}>{t("全局语速", "Rate")}:</span>
              <input
                type="text"
                className="vsInput"
                value={tts.rate}
                onChange={(e) => tts.onRateChange(e.target.value)}
                placeholder="+0%"
                style={{ width: "90px", height: "34px", padding: "4px 8px", fontSize: "13px", borderRadius: "6px" }}
              />
              <button
                type="button"
                className="vsBtnGhost"
                onClick={() => tts.onRateChange("+0%")}
                style={{ fontSize: "12px", padding: "4px 8px" }}
              >
                Reset
              </button>
            </div>
          </div>
        )}

        {errorNotice}

        {/* ── Middle Pane: Full-Width Editor Area ── */}
        <div className="vsTtsEditorWrap">
          <div className="vsTtsEditorCard">
            {tts.ttsMode === "text" ? (
              <textarea
                className="vsTtsEditor custom-scrollbar"
                value={tts.text}
                onChange={(e) => tts.onTextChange(e.target.value)}
                placeholder={t("输入要合成朗读的正文内容、旁白或单人对白结构…", "Enter narration, body text, or a single-speaker script to synthesize...")}
              />
            ) : null}
            {tts.ttsMode === "dialogue" ? (
              <textarea
                className="vsTtsEditor custom-scrollbar"
                value={tts.dialogueText}
                onChange={(e) => tts.onDialogueTextChange(e.target.value)}
                placeholder={t("A: 你好，欢迎来到今天的节目。\nB: 今天我们来聊聊 Echo 的语音工作流。", "A: Hello, welcome to today's show.\nB: Today we're talking about Echo's speech workflow.")}
              />
            ) : null}
            {tts.ttsMode === "pdf" ? (
              <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "16px", gap: 12 }}>
                <div className="vsPdfUploadRow" style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: "var(--bg-secondary)", borderRadius: "8px", border: "1px solid var(--line)", opacity: (tts.extractingPdf || tts.polishingPdf) ? 0.6 : 1 }}>
                  <span style={{ fontSize: "13px", fontWeight: "600", color: "var(--text)", whiteSpace: "nowrap", flexShrink: 0 }}>📁 {t("选择 PDF 文件", "Select PDF File")}:</span>
                  <input
                    type="file"
                    key={tts.pdfFile ? tts.pdfFile.name : "empty"}
                    accept="application/pdf"
                    onChange={(e) => tts.onPdfFileChange(e.target.files?.[0] || null)}
                    disabled={tts.extractingPdf || tts.polishingPdf}
                    style={{ fontSize: "13px", color: "var(--text)", flex: 1, minWidth: 0, cursor: (tts.extractingPdf || tts.polishingPdf) ? "not-allowed" : "pointer" }}
                  />
                  {tts.pdfText.trim() && (
                    <button
                      type="button"
                      className="vsBtnSecondary"
                      onClick={tts.onPolishPdfText}
                      disabled={tts.extractingPdf || tts.polishingPdf}
                      style={{ height: "28px", fontSize: "12px", padding: "0 10px", borderRadius: "6px", display: "flex", alignItems: "center", gap: "4px", whiteSpace: "nowrap" }}
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
                  disabled={tts.extractingPdf || tts.polishingPdf}
                  placeholder={
                    tts.extractingPdf
                      ? t("正在从 PDF 提取文本中，请稍候...", "Extracting text from PDF, please wait...")
                      : tts.polishingPdf
                      ? t("正在使用 AI 优化文本（移除噪声、转换数学公式），请稍候...", "AI is optimizing text (removing noise, translating math formulas), please wait...")
                      : t("这里放 PDF 提取后的可朗读正文。", "Paste the readable body text extracted from the PDF here.")
                  }
                  style={{ flex: 1, resize: "none", border: "none", outline: "none", padding: "8px 0 0 0", opacity: (tts.extractingPdf || tts.polishingPdf) ? 0.6 : 1 }}
                />
              </div>
            ) : null}
          </div>
        </div>

        {/* ── Bottom Pane: Playback & Action Footer ── */}
        <div className="vsTtsEditorFooter" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 24px", gap: 20 }}>
          <button
            type="button"
            className="vsBtnSecondary"
            onClick={() => {
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
            }}
            disabled={!tts.activeSourceText || tts.extractingPdf || tts.polishingPdf}
            style={{ height: "40px" }}
          >
            {t("清空舞台", "Clear workspace")}
          </button>

          {/* Synthesis Player Row */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", minWidth: 0, gap: "8px" }}>
            {tts.audioUrl && (
              <div style={{ display: "flex", alignItems: "center", gap: "12px", width: "100%", maxWidth: "480px" }}>
                <audio controls src={tts.audioUrl} className="vsAudioElement" style={{ flex: 1, height: "36px" }} />
                <button
                  type="button"
                  className="vsBtnSecondary"
                  onClick={handleDownload}
                  style={{ height: "36px", fontSize: "12px", padding: "0 14px", whiteSpace: "nowrap" }}
                >
                  {t("导出音频", "Export Audio")}
                </button>
              </div>
            )}

            {tts.ttsInfo && (
              <p className="vsSettingsNotice ok" style={{ margin: 0, padding: "8px 16px", fontSize: "13px", borderRadius: "8px" }}>{tts.ttsInfo}</p>
            )}

            {!tts.audioUrl && !tts.ttsInfo && (
              <div style={{ color: "var(--muted)", fontSize: "13px", display: "flex", alignItems: "center", gap: "6px" }}>
                <span>🎧</span>
                <span>{t("完成输入后，点击右下角“生成音频”开始试听", "Enter text and click Generate Audio to listen")}</span>
              </div>
            )}
          </div>

          <button
            type="submit"
            className="vsBtnPrimary"
            disabled={tts.generating || tts.extractingPdf || tts.polishingPdf || !tts.activeSourceText.trim()}
            style={{ height: "40px", minWidth: "120px" }}
          >
            {tts.generating ? (
              <>
                <span className="spinner-mini"></span>
                {t("生成中…", "Generating...")}
              </>
            ) : (
              t("生成音频", "Generate audio")
            )}
          </button>
        </div>
      </form>
    </section>
  );
}
