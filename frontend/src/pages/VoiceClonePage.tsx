import { useState, useMemo, useEffect } from "react";
import { ArrowLeft } from "lucide-react";
import ErrorNotice from "../components/ErrorNotice";
import { VoiceCard } from "../components/VoiceCard";
import type { VoiceCloneController } from "../hooks/useVoiceManagement";
import { useI18n } from "../i18n";
import type { ErrorRuntimeContext } from "../types/ui";

type Props = {
  clone: VoiceCloneController;
  errorRuntimeContext: ErrorRuntimeContext;
  voiceProvider?: "qwen" | "xiaomi" | "gpt_sovits";
  onVoiceProviderChange?: (provider: "qwen" | "xiaomi" | "gpt_sovits") => void;
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

  if (viewMode === "workspace") {
    return (
      <form 
        className="vsTranscribeDetail" 
        onSubmit={async (e) => {
          setHasAttemptedSubmit(true);
          await clone.onSubmit(e);
        }}
        style={{ display: "flex", flexDirection: "column", height: "100%", margin: 0 }}
      >
        {/* Header (Action Bar) */}
        <div className="vsTranscribeDetailHeader" style={{ borderBottom: "1px solid var(--line)", padding: "16px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <button
              type="button"
              className="vsTranscribeBackBtn"
              onClick={handleBackToLibrary}
              title={t("返回音色库", "Back to library")}
            >
              <ArrowLeft size={16} strokeWidth={2.2} />
              <span className="vsTranscribeBackBtnText">{t("返回", "Back")}</span>
            </button>
            <div className="vsTranscribeDetailInfo">
              <h2 className="vsTranscribeDetailFileName" style={{ fontSize: "16px", margin: 0 }}>
                {t("克隆复刻音色", "Clone Custom Voice")}
              </h2>
            </div>
          </div>

          <button
            type="submit"
            className="vsBtnPrimary"
            disabled={clone.cloneBusy || !clone.cloneAudioFile}
            style={{ height: "36px", minWidth: "120px", fontSize: "14px", borderRadius: "8px", fontWeight: 600 }}
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
        <div className="custom-scrollbar" style={{ flex: 1, overflowY: "auto", padding: "24px 24px 40px", display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div style={{ maxWidth: "800px", width: "100%", display: "flex", flexDirection: "column", gap: "24px" }}>
            
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
              <div style={{ padding: "16px", background: "rgba(107, 76, 246, 0.05)", border: "1px dashed var(--brand)", borderRadius: "12px", display: "flex", alignItems: "center", gap: "12px" }}>
                <span className="spinner-mini" style={{ width: "24px", height: "24px" }}></span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--brand)" }}>{t("音色克隆处理中", "Voice cloning in progress")}</div>
                  <div style={{ fontSize: "12px", color: "var(--muted)", marginTop: "2px" }}>{t("正在通过大模型提取声纹特征，请稍候…", "Extracting voiceprint features with the model. Please wait.")}</div>
                </div>
              </div>
            )}

            <div style={{ background: "var(--panel-strong)", padding: "32px", borderRadius: "16px", border: "1px solid var(--line)", display: "flex", flexDirection: "column", gap: "24px" }}>
              <p style={{ margin: "0 0 8px 0", color: "var(--muted)", fontSize: "14px" }}>
                {t("通过上传音频样板复刻特定人声。", "Recreate a specific voice from an uploaded audio sample.")}
              </p>

              <label className="vsField">
                <span className="vsFieldLabel">{t("引擎供应商", "Engine Provider")}</span>
                <select
                  className="vsInput"
                  value={voiceProvider}
                  onChange={(e) => onVoiceProviderChange?.(e.target.value as "qwen" | "xiaomi" | "gpt_sovits")}
                  style={{ height: "40px", fontSize: "14px" }}
                >
                  <option value="qwen">{t("阿里 DashScope (Qwen)", "Alibaba DashScope (Qwen)")}</option>
                  <option value="xiaomi">{t("小米 MiMo", "Xiaomi MiMo")}</option>
                  <option value="gpt_sovits">{t("GPT-SoVITS (本地 API)", "GPT-SoVITS (Local API)")}</option>
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

              <div className="vsCardSection" style={{ background: "var(--surface)", padding: "24px", borderRadius: "8px", border: "1px dashed var(--brand)", textAlign: "center" }}>
                <div className="vsField">
                  <span className="vsFieldLabel" style={{ fontSize: "15px", marginBottom: "8px" }}>{t("🎙️ 上传音频样板", "🎙️ Upload audio sample")}</span>
                  <input
                    type="file"
                    accept="audio/*"
                    className="vsInput"
                    style={{ display: "block", margin: "0 auto 12px", width: "100%", maxWidth: "300px" }}
                    onChange={(e) => clone.onAudioFileChange(e.target.files?.[0] || null)}
                    required
                  />
                  <span className="vsFieldHint" style={{ marginTop: "12px", color: "var(--brand-dark)" }}>
                    {t("💡 建议：上传 5-30 秒清晰、无背景噪音的单人语音片段，效果最佳。", "💡 Tip: upload a clear 5-30 second single-speaker clip with minimal background noise for best results.")}
                  </span>
                </div>

                {clone.cloneAudioFile && (
                  <div style={{ marginTop: "16px", padding: "12px", background: "#fff", borderRadius: "8px", border: "1px solid var(--line)", display: "flex", alignItems: "center", gap: "10px", textAlign: "left" }}>
                    <span style={{ fontSize: "20px" }}>📄</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: "14px", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {clone.cloneAudioFile.name}
                      </div>
                      <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                        {(clone.cloneAudioFile.size / 1024 / 1024).toFixed(2)} MB
                      </div>
                    </div>
                  </div>
                )}
              </div>
              
              <div style={{ padding: "16px", background: "#f8fafc", borderRadius: "10px", border: "1px solid #e2e8f0" }}>
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
    <section className="vsTranscribeLibrary">
      {/* Toolbar */}
      <div className="vsTranscribeToolbar">
        <div className="vsTranscribeSearchBox">
          <span className="vsTranscribeSearchIcon">🔍</span>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t("搜索克隆的音色…", "Search cloned voices...")}
          />
        </div>

        <div className="vsTranscribeToolbarActions">
          <button
            onClick={() => void clone.onRefresh()}
            className="vsBtnGhost"
            style={{ fontSize: 12, padding: "6px 12px" }}
            title={t("刷新", "Refresh")}
            disabled={clone.cloneListBusy}
          >
            ↻ {clone.cloneListBusy ? t("刷新中...", "Refreshing...") : t("刷新", "Refresh")}
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
            }}
          >
            ✨ {t("克隆新音色", "Clone New Voice")}
          </button>
        </div>
      </div>

      {/* Card Grid */}
      <div className="vsTranscribeGridWrap custom-scrollbar">
        {clone.cloneListBusy && clone.cloneVoices.length === 0 ? (
          <div className="vsTranscribeEmpty">
            <div className="vsTranscribeEmptyIcon">
              <div className="spinner" style={{ width: 32, height: 32, border: "3px solid var(--line)", borderTopColor: "var(--brand)", borderRadius: "50%" }} />
            </div>
            <p className="vsTranscribeEmptyDesc">
              {t("加载音色库中…", "Loading voice library...")}
            </p>
          </div>
        ) : filteredVoices.length === 0 ? (
          <div className="vsTranscribeEmpty">
            <div className="vsTranscribeEmptyIcon">🧬</div>
            <h3 className="vsTranscribeEmptyTitle">
              {searchQuery
                ? t("没有匹配的音色", "No matching voices")
                : t("暂无克隆的音色", "No cloned voices yet")}
            </h3>
            <p className="vsTranscribeEmptyDesc">
              {searchQuery
                ? t("尝试调整搜索条件。", "Try adjusting your search criteria.")
                : t("点击右上角的「克隆新音色」上传音频样板，复刻指定人声。", "Click 'Clone New Voice' in the top right to upload an audio sample and recreate a specific voice.")}
            </p>
          </div>
        ) : (
          <div className="vsTranscribeGrid">
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
