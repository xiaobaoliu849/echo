import { useState, useEffect, useMemo } from "react";
import type { UseAudioOverviewResult } from "../hooks/useAudioOverview";
import PodcastScriptEditor from "../components/podcast/PodcastScriptEditor";
import PodcastSynthBar from "../components/podcast/PodcastSynthBar";
import PodcastTopicStep from "../components/podcast/PodcastTopicStep";
import PodcastHeader from "../components/podcast/PodcastHeader";
import { PodcastCard } from "../components/podcast/PodcastCard";
import ErrorNotice from "../components/ErrorNotice";
import { useI18n } from "../i18n";
import type { ErrorRuntimeContext } from "../types/ui";

type Props = {
  audioOverview: UseAudioOverviewResult;
  errorRuntimeContext: ErrorRuntimeContext;
};

export default function AudioOverviewPage({
  audioOverview,
  errorRuntimeContext
}: Props) {
  const { t } = useI18n();
  
  // ── View State ──
  const [viewMode, setViewMode] = useState<"library" | "workspace">("library");
  const [searchQuery, setSearchQuery] = useState("");

  const hasScript = audioOverview.audioOverviewScriptLines.length > 0;
  const isAgentRunning =
    audioOverview.audioAgentRunId !== null &&
    ["queued", "running", "synthesizing"].includes(audioOverview.audioAgentStatus || "queued");
  const headerAudioOverview = {
    ...audioOverview,
    currentAudioOverviewLabel: audioOverview.currentAudioOverviewLabel.replace(/^播客 #/, "当前节目 #")
  };
  
  // Auto-switch to workspace when agent run starts or when we have a podcast active
  useEffect(() => {
    if (audioOverview.audioOverviewPodcastId || audioOverview.audioAgentRunId) {
      setViewMode("workspace");
    }
  }, [audioOverview.audioOverviewPodcastId, audioOverview.audioAgentRunId]);

  // Track manual stepper tab selections.
  const [stageOverride, setStageOverride] = useState<1 | 2 | null>(null);
  const activeStage = stageOverride !== null ? stageOverride : (hasScript ? 2 : 1);

  // Reset manual override whenever the script state changes
  useEffect(() => {
    setStageOverride(null);
  }, [hasScript]);

  // ── Handlers ──
  const handleNewPodcast = () => {
    audioOverview.onNewDraft();
    setViewMode("workspace");
  };

  const handleOpenPodcast = (id: number) => {
    void audioOverview.onLoadPodcast(id);
    setViewMode("workspace");
  };

  const handleBackToLibrary = () => {
    setViewMode("library");
    // Optionally clear active podcast, but let's keep it so user can click back without losing draft.
  };

  // ── Filtered History ──
  const filteredPodcasts = useMemo(() => {
    if (!searchQuery.trim()) return audioOverview.audioOverviewPodcasts;
    const q = searchQuery.toLowerCase();
    return audioOverview.audioOverviewPodcasts.filter(
      (p) => p.topic.toLowerCase().includes(q) || String(p.id).includes(q)
    );
  }, [audioOverview.audioOverviewPodcasts, searchQuery]);

  // ═══════════════════════════════════════════════════
  // RENDER: Workspace View (Detail Editor)
  // ═══════════════════════════════════════════════════
  if (viewMode === "workspace") {
    return (
      <section className="vsTranscribeDetail">
        <PodcastHeader audioOverview={headerAudioOverview} />

        {/* Header */}
        <div className="vsTranscribeDetailHeader">
          <button
            className="vsTranscribeBackBtn"
            onClick={handleBackToLibrary}
            title={t("返回列表", "Back to list")}
          >
            ←
          </button>
          <div className="vsTranscribeDetailInfo">
            <h2 className="vsTranscribeDetailFileName">
              {audioOverview.audioOverviewPodcastId
                ? t(`播客 #${audioOverview.audioOverviewPodcastId}: ${audioOverview.audioOverviewTopic || "未命名"}`, `Podcast #${audioOverview.audioOverviewPodcastId}: ${audioOverview.audioOverviewTopic || "Unnamed"}`)
                : t("新建播客草稿", "New Podcast Draft")}
            </h2>
          </div>
          <div className="vsTranscribeDetailActions">
            <button
              onClick={audioOverview.onSaveScript}
              disabled={audioOverview.audioOverviewSaving || audioOverview.audioOverviewBusy}
              className="vsBtnSecondary vsBtnSmall"
            >
              {audioOverview.audioOverviewSaving ? t("保存中...", "Saving...") : t("保存草稿", "Save Draft")}
            </button>
            <button
              onClick={audioOverview.onExportScript}
              disabled={!hasScript}
              className="vsBtnSecondary vsBtnSmall"
            >
              {t("导出 TXT", "Export TXT")}
            </button>
          </div>
        </div>

        {/* Status / Errors */}
        <div className="vsPodcastStatusArea">
          <ErrorNotice
            message={audioOverview.audioOverviewError}
            scope="audio_overview"
            context={{
              ...errorRuntimeContext,
              provider: audioOverview.audioOverviewProvider,
              model: audioOverview.audioOverviewModel,
              language: audioOverview.audioOverviewLanguage,
              podcast_id: audioOverview.audioOverviewPodcastId,
              merge_strategy: audioOverview.audioOverviewMergeStrategy
            }}
          />
          {audioOverview.audioOverviewInfo ? (
            <p className="vsSettingsNotice ok">
              {audioOverview.audioOverviewInfo}
            </p>
          ) : null}
          
          {isAgentRunning ? (
            <div className="vsAgentRunningBanner">
               <div className="spinner vsAgentSpinner" />
               <span className="vsAgentRunningLabel">
                 {t(`Agent 执行中: 步骤 ${audioOverview.audioAgentCurrentStep || "prepare"}`, `Agent running: step ${audioOverview.audioAgentCurrentStep || "prepare"}`)}
               </span>
            </div>
          ) : null}

          {/* Stepper Tabs */}
          <div className="vsPodcastStepperTabs">
            <button
              type="button"
              className={activeStage === 1 ? "vsBtnPrimary vsStepperBtn" : "vsBtnSecondary vsStepperBtn"}
              onClick={() => setStageOverride(1)}
            >
              1. {t("主题与资料", "Topic & Sources")}
            </button>
            <button
              type="button"
              className={activeStage === 2 ? "vsBtnPrimary vsStepperBtn" : "vsBtnSecondary vsStepperBtn"}
              onClick={() => hasScript && setStageOverride(2)}
              disabled={!hasScript}
            >
              2. {t("剧本与配音", "Script & Voice")}
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div className="vsPodcastContentArea custom-scrollbar">
          <div className="vsPodcastContentInner">
            
            {activeStage === 1 && (
              <PodcastTopicStep audioOverview={audioOverview} />
            )}

            {activeStage === 2 && (
              <>
                {/* Audio Player (if exists) */}
                {audioOverview.audioOverviewAudioUrl && (
                  <div className="vsAudioPlayerCard">
                    <h3 className="vsAudioPlayerTitle">{t("合成结果", "Synthesis Result")}</h3>
                    <audio controls src={audioOverview.audioOverviewAudioUrl} className="vsAudioPlayerElement" />
                  </div>
                )}
                
                <PodcastScriptEditor audioOverview={audioOverview} />
                <PodcastSynthBar audioOverview={audioOverview} />
              </>
            )}

          </div>
        </div>
      </section>
    );
  }

  // ═══════════════════════════════════════════════════
  // RENDER: Library / Grid View
  // ═══════════════════════════════════════════════════
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
            placeholder={t("搜索播客记录…", "Search podcasts...")}
          />
        </div>

        <div className="vsTranscribeToolbarActions">
          <button
            onClick={() => void audioOverview.onRefreshList()}
            className="vsBtnGhost vsBtnSmall"
            title={t("刷新", "Refresh")}
            disabled={audioOverview.audioOverviewListBusy}
          >
            ↻ {audioOverview.audioOverviewListBusy ? t("刷新中...", "Refreshing...") : t("刷新", "Refresh")}
          </button>
          <button
            onClick={handleNewPodcast}
            className="vsBtnPrimary vsBtnNewPodcast"
          >
            ✨ {t("新建播客", "New Podcast")}
          </button>
        </div>
      </div>

      {/* Card Grid */}
      <div className="vsTranscribeGridWrap custom-scrollbar">
        {audioOverview.audioOverviewListBusy && audioOverview.audioOverviewPodcasts.length === 0 ? (
          <div className="vsTranscribeEmpty">
            <div className="vsTranscribeEmptyIcon">
              <div className="spinner vsLoadingSpinner" />
            </div>
            <p className="vsTranscribeEmptyDesc">
              {t("加载历史记录中…", "Loading podcast history...")}
            </p>
          </div>
        ) : filteredPodcasts.length === 0 ? (
          <div className="vsTranscribeEmpty">
            <div className="vsTranscribeEmptyIcon">🎙️</div>
            <h3 className="vsTranscribeEmptyTitle">
              {searchQuery
                ? t("没有匹配的记录", "No matching records")
                : t("暂无播客记录", "No podcasts yet")}
            </h3>
            <p className="vsTranscribeEmptyDesc">
              {searchQuery
                ? t("尝试调整搜索条件。", "Try adjusting your search criteria.")
                : t("点击「新建播客」开始创作你的第一个播客节目。", "Click 'New Podcast' to create your first podcast.")}
            </p>
            {!searchQuery && (
              <button
                onClick={handleNewPodcast}
                className="vsBtnPrimary vsBtnNewPodcast"
              >
                ✨ {t("新建播客", "New Podcast")}
              </button>
            )}
          </div>
        ) : (
          <div className="vsTranscribeGrid">
            {filteredPodcasts.map((item) => (
              <PodcastCard
                key={item.id}
                item={item}
                isActive={audioOverview.audioOverviewPodcastId === item.id}
                onClick={() => handleOpenPodcast(item.id)}
                onDelete={(e) => {
                  e.stopPropagation();
                  if (confirm(t("确定要删除这条播客记录吗？", "Are you sure you want to delete this podcast?"))) {
                    void audioOverview.onDeletePodcastById(item.id);
                  }
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Global Error */}
      {audioOverview.audioOverviewError && (
        <div className="vsPodcastGlobalError">
          <ErrorNotice message={audioOverview.audioOverviewError} scope="audio_overview" />
        </div>
      )}
    </section>
  );
}
