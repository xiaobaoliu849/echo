import { useState, useMemo, useEffect } from "react";
import { ArrowLeft, RefreshCw, Search, Sparkles } from "lucide-react";
import ErrorNotice from "../components/ErrorNotice";
import { VoiceCard } from "../components/VoiceCard";
import type { VoiceDesignController, VoiceProviderId } from "../hooks/useVoiceManagement";
import { useI18n } from "../i18n";
import type { ErrorRuntimeContext } from "../types/ui";
import "./VoiceStudio.css";

type Props = {
  design: VoiceDesignController;
  errorRuntimeContext: ErrorRuntimeContext;
  voiceProvider?: VoiceProviderId;
  onVoiceProviderChange?: (provider: VoiceProviderId) => void;
  onDetailModeChange?: (isDetail: boolean) => void;
};

export default function VoiceDesignPage({ design, errorRuntimeContext, voiceProvider = "qwen", onVoiceProviderChange, onDetailModeChange }: Props) {
  const { t } = useI18n();
  const [viewMode, setViewMode] = useState<"library" | "workspace">("library");

  useEffect(() => {
    onDetailModeChange?.(viewMode === "workspace");
  }, [viewMode, onDetailModeChange]);
  const [searchQuery, setSearchQuery] = useState("");
  const [hasAttemptedSubmit, setHasAttemptedSubmit] = useState(false);

  const handleNewDesign = () => {
    setHasAttemptedSubmit(false);
    setViewMode("workspace");
  };

  const handleBackToLibrary = () => {
    setViewMode("library");
  };

  const filteredVoices = useMemo(() => {
    if (!searchQuery.trim()) return design.designVoices;
    const q = searchQuery.toLowerCase();
    return design.designVoices.filter(
      (v) => v.voice.toLowerCase().includes(q)
    );
  }, [design.designVoices, searchQuery]);

  if (viewMode === "workspace") {
    return (
      <form
        className="vsVoiceStudioWorkspace"
        onSubmit={async (e) => {
          setHasAttemptedSubmit(true);
          await design.onSubmit(e);
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
              {t("创造专属音色", "Create Custom Voice")}
            </h2>
          </div>

          <button
            type="submit"
            className="vsVoiceStudioSubmit"
            disabled={design.designBusy}
          >
            {design.designBusy ? (
              <>
                <span className="spinner-mini"></span>
                {t("处理中…", "Designing...")}
              </>
            ) : (
              t("✨ 开始创造", "✨ Create Voice")
            )}
          </button>
        </div>

        {/* Content Area */}
        <div className="vsVoiceStudioBody custom-scrollbar">
          <div className="vsVoiceStudioFormInner">

            {/* Status / Errors (Top of form) */}
            {hasAttemptedSubmit && design.designError && (
              <ErrorNotice
                message={design.designError}
                scope="voice_design"
                context={{
                  ...errorRuntimeContext,
                  preferred_name: design.designName,
                  language: design.designLanguage
                }}
              />
            )}
            {design.designInfo ? <p className="vsSettingsNotice ok" style={{ margin: 0 }}>{design.designInfo}</p> : null}

            {/* Design feedback & preview player inline */}
            {design.designPreviewAudio && (
              <div className="vsVoiceStudioPreview">
                <p className="vsVoiceStudioPreviewTitle">
                  {t(`✨ 音色设计成功！这是新音色《${design.designName}》的试听：`, `✨ Voice design succeeded. Preview for "${design.designName}":`)}
                </p>
                <audio controls controlsList="nodownload" src={design.designPreviewAudio} className="vsAudioElement" style={{ width: "100%", height: "36px" }} />
              </div>
            )}

            <div className="vsVoiceStudioFormCard">
              <p className="vsVoiceStudioIntro">
                {t("通过自然语言描述，创造独一无二的专属音色。", "Create a unique custom voice from a natural-language description.")}
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
                </select>
              </label>

              <div className="vsFormRow">
                <label className="vsField">
                  <span className="vsFieldLabel">{t("音色名称", "Voice name")}</span>
                  <input
                    className="vsInput"
                    value={design.designName}
                    onChange={(e) => design.onNameChange(e.target.value)}
                    placeholder={t("例如：voice_design_demo", "For example: voice_design_demo")}
                    required
                  />
                </label>
                <label className="vsField">
                  <span className="vsFieldLabel">{t("预设语种", "Preset language")}</span>
                  <input
                    className="vsInput"
                    value={design.designLanguage}
                    onChange={(e) => design.onLanguageChange(e.target.value)}
                    placeholder="zh / en"
                    required
                  />
                </label>
              </div>

              <label className="vsField">
                <span className="vsFieldLabel">{t("风格提示词 (Prompt)", "Style prompt")}</span>
                <textarea
                  className="vsTextarea"
                  rows={5}
                  value={design.designPrompt}
                  onChange={(e) => design.onPromptChange(e.target.value)}
                  placeholder={t("在此详细描述音色的年龄、语气、场景和说话风格... 如：一个活泼可爱的中国南方小女孩的声音，带有童音，语速偏快。", "Describe the voice in detail here: age, tone, use case, and speaking style... For example: a lively young southern Chinese girl with a childlike tone and brisk pacing.")}
                  required
                />
              </label>

              <label className="vsField">
                <span className="vsFieldLabel">{t("试听检验文本 (Preview Text)", "Preview text")}</span>
                <textarea
                  className="vsTextarea"
                  rows={3}
                  value={design.designPreviewText}
                  onChange={(e) => design.onPreviewTextChange(e.target.value)}
                  placeholder={t("输入一段用于新音色试听的示例文本", "Enter a sample script to preview the new voice")}
                  required
                />
              </label>
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
            placeholder={t("搜索设计的音色…", "Search designed voices...")}
          />
        </div>

        <div className="vsVoiceStudioActions">
          <button
            onClick={() => void design.onRefresh()}
            className="vsBtnGhost vsVoiceStudioRefreshBtn"
            style={{ fontSize: 12, padding: "6px 12px" }}
            title={t("刷新", "Refresh")}
            disabled={design.designListBusy}
          >
            <RefreshCw size={13} aria-hidden="true" />
            {design.designListBusy ? t("刷新中...", "Refreshing...") : t("刷新", "Refresh")}
          </button>
          <button
            onClick={handleNewDesign}
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
            <Sparkles size={15} aria-hidden="true" />
            {t("设计新音色", "Design New Voice")}
          </button>
        </div>
      </div>

      {/* Card Grid */}
      <div className="vsVoiceStudioGridWrap custom-scrollbar">
        {design.designListBusy && design.designVoices.length === 0 ? (
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
              <Sparkles size={34} strokeWidth={1.6} aria-hidden="true" />
            </div>
            <h3 className="vsVoiceStudioEmptyTitle">
              {searchQuery
                ? t("没有匹配的音色", "No matching voices")
                : t("暂无设计的音色", "No designed voices yet")}
            </h3>
            <p className="vsVoiceStudioEmptyDesc">
              {searchQuery
                ? t("尝试调整搜索条件。", "Try adjusting your search criteria.")
                : t("点击右上角的「设计新音色」开始通过自然语言创造专属声音。", "Click 'Design New Voice' in the top right to create a custom voice using natural language.")}
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
                    void design.onDeleteVoice(item.voice);
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
