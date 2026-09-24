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

const GOOGLE_VOICE_CONSENT_STATEMENT =
  "I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model.";

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
  const [consentMode, setConsentMode] = useState<"upload" | "record">("record");
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
    return clone.cloneVoices.filter((v) =>
      `${v.voice} ${v.name || ""} ${v.provider || ""}`.toLowerCase().includes(q)
    );
  }, [clone.cloneVoices, searchQuery]);

  const acceptedFormats =
    clone.cloneAcceptedFormats.length > 0
      ? clone.cloneAcceptedFormats.join(", ")
      : "mp3, wav, flac, m4a, ogg, webm";
  const sampleLocked = voiceProvider === "gemini" && !clone.cloneConsentFile;

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
            disabled={!clone.cloneCanSubmit}
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
                {voiceProvider === "gemini"
                  ? t(
                      "按顺序完成两步：先录制授权声明，再录制自然语音样板。",
                      "Complete these steps in order: record your consent statement first, then your natural speech sample."
                    )
                  : t(
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

              {voiceProvider === "gemini" && (
                <div className="vsField">
                  <span className="vsFieldLabel">{t("第 1 步：授权声明录音（必填）", "Step 1: Consent recording (required)")}</span>
                  <span className="vsFieldHint">
                    {t(
                      "先由本人完整朗读以下声明。完成后，再用相同麦克风录制自然语音样板。",
                      "First, read the full statement below yourself. Then record a natural speech sample with the same microphone."
                    )}
                  </span>
                  <blockquote className="vsVoiceStudioReminder vsVoiceConsentStatement">
                    <span>{GOOGLE_VOICE_CONSENT_STATEMENT}</span>
                    <button
                      type="button"
                      className="vsBtnGhost"
                      onClick={() => navigator.clipboard?.writeText(GOOGLE_VOICE_CONSENT_STATEMENT)}
                    >
                      {t("复制", "Copy")}
                    </button>
                  </blockquote>
                  <div className="vsCloneSourceSelector">
                    <button type="button" className={`vsCloneSourceTab ${consentMode === "record" ? "active" : ""}`} onClick={() => setConsentMode("record")}>{t("录制授权", "Record consent")}</button>
                    <button type="button" className={`vsCloneSourceTab ${consentMode === "upload" ? "active" : ""}`} onClick={() => setConsentMode("upload")}>{t("上传授权录音", "Upload consent audio")}</button>
                  </div>
                  {consentMode === "record" ? (
                    <VoiceRecorder
                      consentPrompt
                      currentFile={clone.cloneConsentFile}
                      onRecordingComplete={clone.onConsentFileChange}
                      onDiscard={() => clone.onConsentFileChange(null)}
                      disabled={clone.cloneBusy}
                    />
                  ) : (
                    <div className="vsVoiceStudioUploadWrap">
                      <input
                        type="file"
                        accept="audio/*"
                        aria-label={t("选择授权录音", "Choose consent audio")}
                        onChange={(e) => clone.onConsentFileChange(e.target.files?.[0] || null)}
                      />
                      {clone.cloneConsentFile && (
                        <AudioPreviewPlayer
                          file={clone.cloneConsentFile}
                          title={clone.cloneConsentFile.name}
                          onRemove={() => clone.onConsentFileChange(null)}
                        />
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Source Mode Switcher: Upload vs Record */}
              <div className="vsField">
                <span className="vsFieldLabel">
                  {voiceProvider === "gemini"
                    ? t("第 2 步：录制或上传自然语音样板", "Step 2: Record or upload a natural speech sample")
                    : t("🎙️ 声音样板录入方式", "🎙️ Voice Sample Input Method")}
                </span>
                {sampleLocked && (
                  <span className="vsFieldHint">
                    {t("请先完成第 1 步，再录制或上传语音样板。", "Complete Step 1 before recording or uploading the voice sample.")}
                  </span>
                )}
                <div className="vsCloneSourceSelector">
                  <button
                    type="button"
                    className={`vsCloneSourceTab ${sourceMode === "upload" ? "active" : ""}`}
                    onClick={() => setSourceMode("upload")}
                    disabled={sampleLocked}
                  >
                    <UploadCloud size={16} />
                    <span>{t("上传音频文件", "Upload Audio File")}</span>
                  </button>
                  <button
                    type="button"
                    className={`vsCloneSourceTab ${sourceMode === "record" ? "active" : ""}`}
                    onClick={() => setSourceMode("record")}
                    disabled={sampleLocked}
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
                      aria-disabled={sampleLocked}
                      onDragOver={(e) => {
                        e.preventDefault();
                        if (sampleLocked) return;
                        setIsDragging(true);
                      }}
                      onDragLeave={(e) => {
                        e.preventDefault();
                        setIsDragging(false);
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        setIsDragging(false);
                        if (sampleLocked) return;
                        const file = e.dataTransfer.files?.[0];
                        if (file) {
                          clone.onAudioFileChange(file);
                        }
                      }}
                      onClick={() => {
                        if (!sampleLocked) fileInputRef.current?.click();
                      }}
                    >
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="audio/*"
                        aria-label={t("选择音频文件", "Choose an audio file")}
                        disabled={sampleLocked}
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
                        aria-label={t("选择音频文件", "Choose an audio file")}
                        style={{ display: "none" }}
                        disabled={sampleLocked}
                        onChange={(e) => clone.onAudioFileChange(e.target.files?.[0] || null)}
                      />
                      <AudioPreviewPlayer
                        file={clone.cloneAudioFile}
                        title={clone.cloneAudioFile.name}
                        onReplace={() => {
                          if (!sampleLocked) fileInputRef.current?.click();
                        }}
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
                    disabled={clone.cloneBusy || sampleLocked}
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
        {clone.cloneError && <ErrorNotice message={clone.cloneError} scope="voice_clone" />}
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
                key={`${item.provider || "unknown"}:${item.voice}`}
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
                    void clone.onDeleteVoice(item.voice, item.provider as VoiceProviderId | undefined);
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
