import { useState, useMemo, useEffect } from "react";
import { ArrowLeft, Dna, FileText, RefreshCw, Search } from "lucide-react";
import ErrorNotice from "../components/ErrorNotice";
import { VoiceCard } from "../components/VoiceCard";
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

export default function VoiceClonePage({ clone, errorRuntimeContext, voiceProvider = "qwen", onVoiceProviderChange, onDetailModeChange }: Props) {
  const { t } = useI18n();
  const [viewMode, setViewMode] = useState<"library" | "workspace">("library");

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
    return clone.cloneVoices.filter(
      (v) => v.voice.toLowerCase().includes(q)
    );
  }, [clone.cloneVoices, searchQuery]);

  const acceptedFormats = clone.cloneAcceptedFormats.length > 0
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
            {clone.cloneInfo ? <p className="vsSettingsNotice ok" style={{ margin: 0 }}>{clone.cloneInfo}</p> : null}

            {/* Inline Training Status Indicators */}
            {clone.cloneBusy && (
              <div className="vsVoiceStudioBusy">
                <span className="spinner-mini" style={{ width: "24px", height: "24px" }}></span>
                <div style={{ flex: 1 }}>
                  <div className="vsVoiceStudioBusyTitle">{t("音色克隆处理中", "Voice cloning in progress")}</div>
                  <div className="vsVoiceStudioBusyDesc">{t("正在通过大模型提取声纹特征，请稍候…", "Extracting voiceprint features with the model. Please wait.")}</div>
                </div>
              </div>
            )}

            <div className="vsVoiceStudioFormCard">
              <p className="vsVoiceStudioIntro">
                {t("通过上传音频样板复刻特定人声。", "Recreate a specific voice from an uploaded audio sample.")}
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
                <span className="vsFieldHint">{t("请使用字母、数字或下划线，方便在模型调用时识别。", "Use letters, numbers, or underscores so the model can reference it reliably.")}</span>
              </label>

              <div className="vsVoiceStudioUpload">
                <div className="vsField">
                  <span className="vsFieldLabel">{t("🎙️ 上传音频样板", "🎙️ Upload audio sample")}</span>
                  <input
                    type="file"
                    accept="audio/*"
                    className="vsInput"
                    onChange={(e) => clone.onAudioFileChange(e.target.files?.[0] || null)}
                    required
                  />
                  <span className="vsFieldHint vsVoiceStudioUploadTip">
                    {t(`💡 支持格式：${acceptedFormats}。建议 10-30 秒清晰、无背景噪音的单人语音。`, `💡 Supported: ${acceptedFormats}. Upload a clear 10-30 second single-speaker clip with minimal background noise.`)}
                  </span>
                </div>

                {clone.cloneAudioFile && (
                  <div className="vsVoiceStudioFileChip">
                    <span className="vsVoiceStudioFileChipIcon">
                      <FileText size={18} aria-hidden="true" />
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="vsVoiceStudioFileChipName">
                        {clone.cloneAudioFile.name}
                      </div>
                      <div className="vsVoiceStudioFileChipSize">
                        {(clone.cloneAudioFile.size / 1024 / 1024).toFixed(2)} MB
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className="vsVoiceStudioReminder">
                <p className="vsFieldHint" style={{ margin: 0 }}>
                  <strong>{t("温馨提示：", "Reminder:")}</strong> {t("克隆音色仅供个人研究与创作使用。请确保您拥有该声音样本的使用授权，尊重他人的声音版权与隐私。", "Voice cloning is for personal research and creative work only. Make sure you have permission to use the source voice sample and respect voice rights and privacy.")}
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
              <div className="spinner" style={{ width: 32, height: 32, border: "3px solid var(--line)", borderTopColor: "var(--brand)", borderRadius: "50%" }} />
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
                : t("点击右上角的「克隆新音色」上传音频样板，复刻指定人声。", "Click 'Clone New Voice' in the top right to upload an audio sample and recreate a specific voice.")}
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
                  if (confirm(t(`确定要删除音色 "${item.voice}" 吗？`, `Are you sure you want to delete voice "${item.voice}"?`))) {
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
