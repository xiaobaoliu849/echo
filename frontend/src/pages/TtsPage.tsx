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

  return (
    <section className="vsTtsWorkspace vsTtsSingleColumn">
      <form
        className="vsTtsLayout"
        onSubmit={tts.onSubmit}
        style={{ display: "flex", flexDirection: "column", height: "100%", width: "100%", margin: 0 }}
      >
        {/* ── Top Studio Bar: Mode Selector & Streamlined Parameters ── */}
        <header className="vsTtsStudioBar vsTtsPrimaryHeader">
          <div className="vsTtsBarLeft">
            <div className="vsModeTabs" role="tablist" aria-label={t("TTS 模式", "TTS Mode")}>
              <button
                type="button"
                data-mode="text"
                className={`vsModeTabBtn ${tts.ttsMode === "text" ? "active" : ""}`}
                onClick={() => tts.onTtsModeChange("text")}
              >
                {t("文本转语音", "Text to speech")}
              </button>
              <button
                type="button"
                data-mode="dialogue"
                className={`vsModeTabBtn ${tts.ttsMode === "dialogue" ? "active" : ""}`}
                onClick={() => tts.onTtsModeChange("dialogue")}
              >
                {t("对话转语音", "Dialogue to speech")}
              </button>
              <button
                type="button"
                data-mode="pdf"
                className={`vsModeTabBtn ${tts.ttsMode === "pdf" ? "active" : ""}`}
                onClick={() => tts.onTtsModeChange("pdf")}
              >
                {t("PDF 转语音", "PDF to speech")}
              </button>
            </div>
          </div>

          {/* Unified Parameters in Single and PDF mode */}
          {tts.ttsMode !== "dialogue" && (
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
                    Reset
                  </button>
                </div>
              </div>
            </div>
          )}
        </header>

        {/* ── Dialogue Config Toolbar (When in dialogue mode) ── */}
        {tts.ttsMode === "dialogue" && (
          <div className="vsTtsToolbar vsTtsDialogueToolbar">
            <div className="vsDialogueSpeakersGrid">
              {/* Person A Card */}
              <div className="vsSpeakerCard vsSpeakerCardA">
                <div className="vsSpeakerHeader">
                  <span className="vsSpeakerBadge vsSpeakerBadgeA">A</span>
                  <span className="vsSpeakerTitle">{t("角色 A (A)", "Speaker A")}</span>
                </div>
                <div className="vsSpeakerFields">
                  <div className="vsSpeakerField">
                    <span className="vsFieldLabelSub">{t("服务商", "Engine")}:</span>
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
                  <div className="vsSpeakerField vsSpeakerVoiceField">
                    <span className="vsFieldLabelSub">{t("音色", "Voice")}:</span>
                    <div className="vsVoiceCapsuleWrapper">
                      <select
                        className="vsSelect vsSelectModern"
                        value={tts.voice}
                        onChange={(e) => tts.onVoiceChange(e.target.value)}
                        disabled={tts.loadingVoices || tts.voiceOptions.length === 0}
                      >
                        <option value="" disabled>{t("-- 请选择音色 A --", "-- Select voice A --")}</option>
                        {tts.voiceOptions.map((item) => (
                          <option key={item.value} value={item.value}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                      {tts.loadingVoices && <span className="vsSelectLoading">{t("加载中…", "Loading...")}</span>}
                    </div>
                  </div>
                </div>
              </div>

              {/* Person B Card */}
              <div className="vsSpeakerCard vsSpeakerCardB">
                <div className="vsSpeakerHeader">
                  <span className="vsSpeakerBadge vsSpeakerBadgeB">B</span>
                  <span className="vsSpeakerTitle">{t("角色 B (B)", "Speaker B")}</span>
                </div>
                <div className="vsSpeakerFields">
                  <div className="vsSpeakerField">
                    <span className="vsFieldLabelSub">{t("服务商", "Engine")}:</span>
                    <select
                      className="vsSelect vsSelectModern"
                      value={tts.ttsEngineB}
                      onChange={(e) => tts.onEngineBChange?.(e.target.value as typeof tts.ttsEngine)}
                    >
                      {tts.engineOptions.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="vsSpeakerField vsSpeakerVoiceField">
                    <span className="vsFieldLabelSub">{t("音色", "Voice")}:</span>
                    <div className="vsVoiceCapsuleWrapper">
                      <select
                        className="vsSelect vsSelectModern"
                        value={tts.voiceB}
                        onChange={(e) => tts.onVoiceBChange?.(e.target.value)}
                        disabled={tts.loadingVoicesB || tts.voiceOptionsB.length === 0}
                      >
                        <option value="" disabled>{t("-- 请选择音色 B --", "-- Select voice B --")}</option>
                        {tts.voiceOptionsB.map((item) => (
                          <option key={item.value} value={item.value}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                      {tts.loadingVoicesB && <span className="vsSelectLoading">{t("加载中…", "Loading...")}</span>}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Global Settings Row */}
            <div className="vsDialogueGlobalRow">
              <span className="vsFieldLabel">{t("全局语速", "Rate")}:</span>
              <div className="vsRateCapsule">
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
                >
                  Reset
                </button>
              </div>
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
            <span className="vsTtsShortcutHint" title={t("快捷键: Ctrl/Cmd + 回车", "Shortcut: Ctrl/Cmd + Enter")}>⌘/Ctrl + ↵</span>
            <button
              type="submit"
              className="vsBtnPrimary vsTtsGenerateBtn"
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
      </form>
    </section>
  );
}
