import { useState, useMemo, useEffect, useRef } from "react";
import { ArrowLeft, Dna, RefreshCw, Search, UploadCloud, Mic } from "lucide-react";
import ErrorNotice from "../components/ErrorNotice";
import { VoiceCard } from "../components/VoiceCard";
import { AudioPreviewPlayer } from "../components/voice/AudioPreviewPlayer";
import { VoiceRecorder } from "../components/voice/VoiceRecorder";
import type { VoiceCloneController, VoiceProviderId } from "../hooks/useVoiceManagement";
import { useI18n } from "../i18n";
import type { ErrorRuntimeContext } from "../types/ui";
import "./VoiceStudio.css";

type Props = {
  clone: VoiceCloneController;
  errorRuntimeContext: ErrorRuntimeContext;
  voiceProvider?: VoiceProviderId;
  onVoiceProviderChange?: (provider: VoiceProviderId) => void;
  onDetailModeChange?: (isDetail: boolean) => void;
};

export default function VoiceClonePage({
  clone,
  errorRuntimeContext,
  voiceProvider = "qwen",
  onVoiceProviderChange,
  onDetailModeChange,
}: Props) {
  const { t } = useI18n();
  const [viewMode, setViewMode] = useState<"library" | "workspace">("library");
  const [sourceMode, setSourceMode] = useState<"upload" | "record">("upload");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    onDetailModeChange?.(viewMode === "workspace");
  }, [viewMode, onDetailModeChange]);

  const [searchQuery, setSearchQuery] = useState("");
  const [hasAttemptedSubmit, setHasAttemptedSubmit] = useState(false);

  const handleNewClone = () => {
    setHasAttemptedSubmit(false);
    setViewMode("workspace");
  };

  const handleBackToLibrary = () => {
    setViewMode("library");
  };

  const filteredVoices = useMemo(() => {
    if (!searchQuery.trim()) return clone.cloneVoices;
    const q = searchQuery.toLowerCase();
    return clone.cloneVoices.filter((v) => v.voice.toLowerCase().includes(q));
  }, [clone.cloneVoices, searchQuery]);

  const acceptedFormats =
    clone.cloneAcceptedFormats.length > 0
      ? clone.cloneAcceptedFormats.join(", ")
      : "mp3, wav, flac, m4a, ogg, webm";

  if (viewMode === "workspace") {
    return (
      <form
        className="vsVoiceStudioWorkspace"
        onSubmit={async (e) => {
          setHasAttemptedSubmit(true);
          await clone.onSubmit(e);
        }}
      >
        {/* Header (Action Bar) */}
        <div className="vsVoiceStudioHeader">
          <div className="vsVoiceStudioHeaderLeft">
            <button
              type="button"
              className="vsVoiceStudioBack"
              onClick={handleBackToLibrary}
              title={t("返回音色库", "Back to library")}
            >
              <ArrowLeft size={16} strokeWidth={2.2} />
              <span>{t("返回", "Back")}</span>
            </button>
            <h2 className="vsVoiceStudioTitle">
              {t("克隆复刻音色", "Clone Custom Voice")}
            </h2>
          </div>

          <button
            type="submit"
            className="vsVoiceStudioSubmit"
            disabled={clone.cloneBusy || !clone.cloneAudioFile}
          >
            {clone.cloneBusy ? (
              <>
                <span className="spinner-mini"></span>
                {t("处理中…", "Training...")}
              </>
            ) : (
              t("🧬 开始克隆", "🧬 Clone Voice")
            )}
          </button>
        </div>

        {/* Content Area */}
        <div className="vsVoiceStudioBody custom-scrollbar">
          <div className="vsVoiceStudioFormInner">
            {/* Status / Errors (Top of form) */}
            {hasAttemptedSubmit && clone.cloneError && (
              <ErrorNotice
                message={clone.cloneError}
                scope="voice_clone"
                context={{ ...errorRuntimeContext, preferred_name: clone.cloneName }}
              />
            )}
            {clone.cloneInfo ? (
              <p className="vsSettingsNotice ok" style={{ margin: 0 }}>
                {clone.cloneInfo}
              </p>
            ) : null}

            {/* Inline Training Status Indicators */}
            {clone.cloneBusy && (
              <div className="vsVoiceStudioBusy">
                <span
                  className="spinner-mini"
                  style={{ width: "24px", height: "24px" }}
                ></span>
                <div style={{ flex: 1 }}>
                  <div className="vsVoiceStudioBusyTitle">
                    {t("音色克隆处理中", "Voice cloning in progress")}
                  </div>
                  <div className="vsVoiceStudioBusyDesc">
                    {t(
                      "正在通过大模型提取声纹特征，请稍候…",
                      "Extracting voiceprint features with the model. Please wait."
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className="vsVoiceStudioFormCard">
              <p className="vsVoiceStudioIntro">
                {t(
                  "通过上传音频样板复刻特定人声，或直接使用麦克风录制自己的声音进行克隆。",
                  "Recreate a specific voice by uploading an audio sample or recording yourself directly with the microphone."
                )}
              </p>

              <label className="vsField">
                <span className="vsFieldLabel">{t("引擎供应商", "Engine Provider")}</span>
                <select
                  className="vsInput"
                  value={voiceProvider}
                  onChange={(e) => onVoiceProviderChange?.(e.target.value as VoiceProviderId)}
                  style={{ height: "40px", fontSize: "14px" }}
                >
                  <option value="qwen">{t("阿里 DashScope (Qwen)", "Alibaba DashScope (Qwen)")}</option>
                  <option value="gemini">{t("Google Gemini (Gemini 3.8)", "Google Gemini (Gemini 3.8)")}</option>
                  <option value="xiaomi">{t("小米 MiMo", "Xiaomi MiMo")}</option>
                  <option value="gpt_sovits">{t("GPT-SoVITS (本地 API)", "GPT-SoVITS (Local API)")}</option>
                  <option value="elevenlabs">{t("ElevenLabs 克隆", "ElevenLabs Clone")}</option>
                </select>
              </label>

              {voiceProvider === "gemini" && (
                <div
                  className="vsVoiceStudioReminder"
                  style={{
                    backgroundColor: "rgba(59, 130, 246, 0.08)",
                    borderColor: "rgba(59, 130, 246, 0.3)",
                    borderWidth: 1,
                    borderStyle: "solid",
                    borderRadius: 8,
                    padding: 12,
                    marginBottom: 16,
                  }}
                >
                  <p style={{ margin: "0 0 6px 0", fontSize: 13, fontWeight: 600, color: "var(--brand, #3b82f6)" }}>
                    {t("Google Gemini 声音复刻口述授权要求", "Google Gemini Voice Consent Requirement")}
                  </p>
                  <p className="vsFieldHint" style={{ margin: 0, fontSize: 12 }}>
                    {t(
                      "Google API 强制要求声音复刻音频中必须包含原说话人清楚朗读的授权声明，否则将返回校验失败：",
                      "Google API strictly requires the voice sample to include the speaker reciting this verbal consent statement, otherwise verification will fail:"
                    )}
                  </p>
                  <blockquote
                    style={{
                      margin: "8px 0 0 0",
                      padding: "8px 10px",
                      background: "rgba(0, 0, 0, 0.04)",
                      borderRadius: 6,
                      fontSize: 12,
                      fontStyle: "italic",
                      userSelect: "all",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    <span>“I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model.”</span>
                    <button
                      type="button"
                      className="vsBtnGhost"
                      style={{ fontSize: 11, padding: "3px 8px", height: "auto", whiteSpace: "nowrap" }}
                      onClick={() => {
                        navigator.clipboard?.writeText(
                          "I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model."
                        );
                      }}
                    >
                      {t("复制", "Copy")}
                    </button>
                  </blockquote>
                  <p className="vsFieldHint" style={{ margin: "8px 0 0 0", fontSize: 11, color: "var(--brand, #3b82f6)" }}>
                    {t(
                      "⚡ 系统已集成自动转码：无论麦克风录制 (WebM) 还是本地上传任何音频，后端均会自动规范化为 Google 必需的 24kHz 16-bit PCM WAV 标准流。",
                      "⚡ Automatic Transcoding: Whether recording via microphone (WebM) or uploading any audio format, the backend automatically normalizes the stream to Google's required 24kHz 16-bit PCM WAV standard."
                    )}
                  </p>
                </div>
              )}

              <label className="vsField">
                <span className="vsFieldLabel">{t("新音色命名", "New voice name")}</span>
                <input
                  className="vsInput"
                  value={clone.cloneName}
                  onChange={(e) => clone.onNameChange(e.target.value)}
                  placeholder={t("例如：my_cloned_voice_v1", "For example: my_cloned_voice_v1")}
                  required
                />
                <span className="vsFieldHint">
                  {t(
                    "请使用字母、数字或下划线，方便在模型调用时识别。",
                    "Use letters, numbers, or underscores so the model can reference it reliably."
                  )}
                </span>
              </label>

              {/* Source Mode Switcher: Upload vs Record */}
              <div className="vsField">
                <span className="vsFieldLabel">
                  {t("🎙️ 声音样板录入方式", "🎙️ Voice Sample Input Method")}
                </span>
                <div className="vsCloneSourceSelector">
                  <button
                    type="button"
                    className={`vsCloneSourceTab ${sourceMode === "upload" ? "active" : ""}`}
                    onClick={() => setSourceMode("upload")}
                  >
                    <UploadCloud size={16} />
                    <span>{t("上传音频文件", "Upload Audio File")}</span>
                  </button>
                  <button
                    type="button"
                    className={`vsCloneSourceTab ${sourceMode === "record" ? "active" : ""}`}
                    onClick={() => setSourceMode("record")}
                  >
                    <Mic size={16} />
                    <span>{t("麦克风现场录制", "Record From Microphone")}</span>
                  </button>
                </div>
              </div>

              {/* Upload Mode */}
              {sourceMode === "upload" && (
                <div className="vsVoiceStudioUploadWrap">
                  {!clone.cloneAudioFile ? (
                    <div
                      className={`vsModernDropZone ${isDragging ? "dragging" : ""}`}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setIsDragging(true);
                      }}
                      onDragLeave={(e) => {
                        e.preventDefault();
                        setIsDragging(false);
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        setIsDragging(false);
                        const file = e.dataTransfer.files?.[0];
                        if (file) {
                          clone.onAudioFileChange(file);
                        }
                      }}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="audio/*"
                        aria-label={t("选择音频文件", "Choose an audio file")}
                        onChange={(e) => clone.onAudioFileChange(e.target.files?.[0] || null)}
                      />
                      <div className="vsModernDropZoneIcon">
                        <UploadCloud size={26} strokeWidth={2} />
                      </div>
                      <div className="vsModernDropZoneTitle">
                        {t("点击或拖拽音频文件到此处上传", "Click or drag audio file here to upload")}
                      </div>
                      <div className="vsModernDropZoneSub">
                        {t(
                          `支持格式：${acceptedFormats}。建议 10-30 秒清晰、无背景噪音的单人语音。`,
                          `Supported: ${acceptedFormats}. 10-30s clean single-speaker clip recommended.`
                        )}
                      </div>
                      <div className="vsModernDropZoneBadges">
                        {clone.cloneAcceptedFormats.map((fmt) => (
                          <span key={fmt} className="vsModernDropZoneBadge">
                            {fmt.toUpperCase()}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="audio/*"
                        style={{ display: "none" }}
                        onChange={(e) => clone.onAudioFileChange(e.target.files?.[0] || null)}
                      />
                      <AudioPreviewPlayer
                        file={clone.cloneAudioFile}
                        title={clone.cloneAudioFile.name}
                        onReplace={() => fileInputRef.current?.click()}
                        onRemove={() => clone.onAudioFileChange(null)}
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Record Mode */}
              {sourceMode === "record" && (
                <div className="vsVoiceStudioRecordWrap">
                  <VoiceRecorder
                    onRecordingComplete={(file) => clone.onAudioFileChange(file)}
                    onDiscard={() => clone.onAudioFileChange(null)}
                    currentFile={clone.cloneAudioFile}
                    disabled={clone.cloneBusy}
                  />
                </div>
              )}

              <div className="vsVoiceStudioReminder">
                <p className="vsFieldHint" style={{ margin: 0 }}>
                  <strong>{t("温馨提示：", "Reminder:")}</strong>{" "}
                  {t(
                    "克隆音色仅供个人研究与创作使用。请确保您拥有该声音样本的使用授权，尊重他人的声音版权与隐私。",
                    "Voice cloning is for personal research and creative work only. Make sure you have permission to use the source voice sample and respect voice rights and privacy."
                  )}
                </p>
              </div>
            </div>
          </div>
        </div>
      </form>
    );
  }

  return (
    <section className="vsVoiceStudioLibrary">
      {/* Toolbar */}
      <div className="vsVoiceStudioToolbar">
        <div className="vsVoiceStudioSearch">
          <Search className="vsVoiceStudioSearchIcon" size={15} aria-hidden="true" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t("搜索克隆的音色…", "Search cloned voices...")}
          />
        </div>

        <div className="vsVoiceStudioActions">
          <button
            onClick={() => void clone.onRefresh()}
            className="vsBtnGhost vsVoiceStudioRefreshBtn"
            style={{ fontSize: 12, padding: "6px 12px" }}
            title={t("刷新", "Refresh")}
            disabled={clone.cloneListBusy}
          >
            <RefreshCw size={13} aria-hidden="true" />
            {clone.cloneListBusy ? t("刷新中...", "Refreshing...") : t("刷新", "Refresh")}
          </button>
          <button
            onClick={handleNewClone}
            className="vsBtnPrimary"
            style={{
              height: 36,
              fontSize: 13,
              padding: "0 18px",
              borderRadius: 10,
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Dna size={15} aria-hidden="true" />
            {t("克隆新音色", "Clone New Voice")}
          </button>
        </div>
      </div>

      {/* Card Grid */}
      <div className="vsVoiceStudioGridWrap custom-scrollbar">
        {clone.cloneListBusy && clone.cloneVoices.length === 0 ? (
          <div className="vsVoiceStudioEmpty">
            <div className="vsVoiceStudioEmptyIcon">
              <div
                className="spinner"
                style={{
                  width: 32,
                  height: 32,
                  border: "3px solid var(--line)",
                  borderTopColor: "var(--brand)",
                  borderRadius: "50%",
                }}
              />
            </div>
            <p className="vsVoiceStudioEmptyDesc">
              {t("加载音色库中…", "Loading voice library...")}
            </p>
          </div>
        ) : filteredVoices.length === 0 ? (
          <div className="vsVoiceStudioEmpty">
            <div className="vsVoiceStudioEmptyIcon">
              <Dna size={34} strokeWidth={1.6} aria-hidden="true" />
            </div>
            <h3 className="vsVoiceStudioEmptyTitle">
              {searchQuery
                ? t("没有匹配的音色", "No matching voices")
                : t("暂无克隆的音色", "No cloned voices yet")}
            </h3>
            <p className="vsVoiceStudioEmptyDesc">
              {searchQuery
                ? t("尝试调整搜索条件。", "Try adjusting your search criteria.")
                : t(
                    "点击右上角的「克隆新音色」录制或上传音频样板，复刻指定人声。",
                    "Click 'Clone New Voice' in the top right to record or upload an audio sample and recreate a specific voice."
                  )}
            </p>
          </div>
        ) : (
          <div className="vsVoiceStudioGrid">
            {filteredVoices.map((item) => (
              <VoiceCard
                key={item.voice}
                item={item}
                onDelete={(e) => {
                  e.stopPropagation();
                  if (
                    confirm(
                      t(
                        `确定要删除音色 "${item.voice}" 吗？`,
                        `Are you sure you want to delete voice "${item.voice}"?`
                      )
                    )
                  ) {
                    void clone.onDeleteVoice(item.voice);
                  }
                }}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
