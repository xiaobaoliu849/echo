import { useState, useEffect, useMemo } from "react";
import type { UseAudioOverviewResult } from "../hooks/useAudioOverview";
import PodcastScriptEditor from "../components/podcast/PodcastScriptEditor";
import PodcastSynthBar from "../components/podcast/PodcastSynthBar";
import PodcastTopicStep from "../components/podcast/PodcastTopicStep";
import PodcastHeader from "../components/podcast/PodcastHeader";
import { PodcastCard } from "../components/podcast/PodcastCard";
import AgentProgressPanel from "../components/podcast/AgentProgressPanel";
import AgentSourcesPanel from "../components/podcast/AgentSourcesPanel";
import AgentRunHistory from "../components/podcast/AgentRunHistory";
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
  const [libraryTab, setLibraryTab] = useState<"podcasts" | "agent_runs">("podcasts");

  useEffect(() => {
    if (libraryTab === "agent_runs" && audioOverview.agentRunHistory.length === 0 && !audioOverview.agentRunHistoryBusy) {
      void audioOverview.onLoadAgentRunHistory();
    }
  }, [libraryTab]);

  const hasScript = audioOverview.audioOverviewScriptLines.length > 0;
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
    // Assuming onLoadPodcast exists, although type might not expose it. 
    // We cast as any just in case it's not strongly typed in UseAudioOverviewResult.
    const hook = audioOverview as any;
    if (hook.onLoadPodcast) {
      hook.onLoadPodcast(id);
    }
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
        <PodcastHeader
          audioOverview={headerAudioOverview}
          onBackToLibrary={handleBackToLibrary}
          onSaveScript={audioOverview.onSaveScript}
          onExportScript={audioOverview.onExportScript}
          hasScript={hasScript}
        />

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
          
          {audioOverview.audioAgentRunId !== null ? (
            <AgentProgressPanel
              steps={audioOverview.audioAgentSteps}
              currentStep={audioOverview.audioAgentCurrentStep}
              agentStatus={audioOverview.audioAgentStatus}
              errorMessage={audioOverview.audioAgentErrorMessage}
              canRetry={audioOverview.audioAgentCanRetry}
              onRetry={audioOverview.onRetryAgentRun}
              busy={audioOverview.audioOverviewBusy}
            />
          ) : null}

          {/* Stepper Anchors */}
          <div className="vsPodcastStepperTabs">
            <button
              type="button"
              className={activeStage === 1 ? "vsBtnPrimary vsStepperBtn" : "vsBtnSecondary vsStepperBtn"}
              onClick={() => {
                setStageOverride(1);
                document.getElementById("podcast-topic-section")?.scrollIntoView?.({ behavior: "smooth" });
              }}
            >
              1. {t("主题与资料", "Topic & Sources")}
            </button>
            <button
              type="button"
              className={activeStage === 2 ? "vsBtnPrimary vsStepperBtn" : "vsBtnSecondary vsStepperBtn"}
              onClick={() => {
                setStageOverride(2);
                document.getElementById("podcast-script-section")?.scrollIntoView?.({ behavior: "smooth" });
              }}
            >
              2. {t("剧本与配音", "Script & Voice")}
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div className="vsPodcastContentArea custom-scrollbar">
          <div className="vsPodcastContentInner">
            
            {/* Stage 1: Topic Prompt Section */}
            <div id="podcast-topic-section">
              <PodcastTopicStep audioOverview={audioOverview} />
            </div>

            {/* Stage 2: Script & Voice Synthesis Section */}
            {(hasScript || activeStage === 2 || audioOverview.audioOverviewBusy) && (
              <div id="podcast-script-section" className="vsPodcastMergedScriptArea">
                {/* Audio Player (if exists) */}
                {audioOverview.audioOverviewAudioUrl && (
                  <div className="vsAudioPlayerCard">
                    <h3 className="vsAudioPlayerTitle">{t("合成结果", "Synthesis Result")}</h3>
                    <audio controls src={audioOverview.audioOverviewAudioUrl} className="vsAudioPlayerElement" />
                  </div>
                )}
                
                <AgentSourcesPanel sources={audioOverview.audioAgentSources} />
                <PodcastScriptEditor audioOverview={audioOverview} />
                <PodcastSynthBar audioOverview={audioOverview} />
              </div>
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
      {/* Studio Header & Toolbar */}
      <div className="vsPodcastStudioToolbar">
        <div className="vsStudioSegmentGroup">
          <button
            type="button"
            className={`vsStudioSegmentBtn ${libraryTab === "podcasts" ? "is-active" : ""}`}
            onClick={() => setLibraryTab("podcasts")}
          >
            🎙️ {t("播客记录", "Podcasts")}
          </button>
          <button
            type="button"
            className={`vsStudioSegmentBtn ${libraryTab === "agent_runs" ? "is-active" : ""}`}
            onClick={() => setLibraryTab("agent_runs")}
          >
            ⚡ {t("Agent 运行记录", "Agent Runs")}
          </button>
        </div>

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
            type="button"
            onClick={() => void audioOverview.onRefreshList()}
            className="vsBtnGhost vsBtnSmall"
            title={t("刷新列表", "Refresh list")}
            disabled={audioOverview.audioOverviewListBusy}
          >
            ↻ {audioOverview.audioOverviewListBusy ? t("刷新中...", "Refreshing...") : t("刷新", "Refresh")}
          </button>
          <button
            type="button"
            onClick={handleNewPodcast}
            className="vsBtnPrimary vsBtnNewPodcast"
          >
            ✨ {t("新建播客", "New Podcast")}
          </button>
        </div>
      </div>

      {/* Card Grid / Agent History */}
      {libraryTab === "agent_runs" ? (
        <div className="vsTranscribeGridWrap custom-scrollbar">
          <AgentRunHistory
            runs={audioOverview.agentRunHistory}
            busy={audioOverview.agentRunHistoryBusy}
            onRefresh={() => { void audioOverview.onLoadAgentRunHistory(); }}
            onOpenRun={(run) => {
              void audioOverview.onOpenAgentRun(run);
              setViewMode("workspace");
            }}
          />
        </div>
      ) : (
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
          <div className="vsTranscribeEmptyCard">
            <div className="vsTranscribeEmptyIcon">🎙️</div>
            <h3 className="vsTranscribeEmptyTitle">
              {searchQuery
                ? t("没有匹配的记录", "No matching records")
                : t("暂无播客记录", "No podcasts yet")}
            </h3>
            <p className="vsTranscribeEmptyDesc">
              {searchQuery
                ? t("尝试调整搜索关键词或重置筛选条件。", "Try adjusting your search query.")
                : t("点击右上角「新建播客」开启你的第一个 AI 播客创作体验。", "Click 'New Podcast' at top right to start creating.")}
            </p>
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
      )}

      {/* Global Error */}
      {audioOverview.audioOverviewError && (
        <div className="vsPodcastGlobalError">
          <ErrorNotice message={audioOverview.audioOverviewError} scope="audio_overview" />
        </div>
      )}
    </section>
  );
}
