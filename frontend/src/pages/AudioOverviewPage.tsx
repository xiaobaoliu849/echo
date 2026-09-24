import { Headphones, Plus, RefreshCw, Search, ArrowRight } from "lucide-react";
import "./PodcastLibrary.css";
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

  const libraryBusy = libraryTab === "podcasts" ? audioOverview.audioOverviewListBusy : audioOverview.agentRunHistoryBusy;
  const hasScript = audioOverview.audioOverviewScriptLines.length > 0;

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
  }, [hasScript, audioOverview.audioOverviewPodcastId]);

  // ── Handlers ──
  const handleNewPodcast = () => {
    setStageOverride(null);
    audioOverview.onNewDraft();
    setViewMode("workspace");
  };

  const handleOpenPodcast = (id: number) => {
    setStageOverride(null);
    void audioOverview.onLoadPodcast(id);
    setViewMode("workspace");
  };

  const handleBackToLibrary = () => {
    setViewMode("library");
  };

  // ── Filtered History ──
  const filteredPodcasts = useMemo(() => {
    if (!searchQuery.trim()) return audioOverview.audioOverviewPodcasts;
    const q = searchQuery.toLowerCase();
    return audioOverview.audioOverviewPodcasts.filter(
      (p) => p.topic.toLowerCase().includes(q) || String(p.id).includes(q)
    );
  }, [audioOverview.audioOverviewPodcasts, searchQuery]);

  const filteredRuns = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return audioOverview.agentRunHistory.filter((run) =>
      !query || run.topic.toLowerCase().includes(query) || String(run.id).includes(query)
    );
  }, [audioOverview.agentRunHistory, searchQuery]);

  // ═══════════════════════════════════════════════════
  // RENDER: Workspace View (Detail Editor)
  // ═══════════════════════════════════════════════════
  if (viewMode === "workspace") {
    return (
      <section className="vsTranscribeDetail vsPodcastWorkspace">
        <PodcastHeader
          audioOverview={audioOverview}
          onBackToLibrary={handleBackToLibrary}
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
            <details className="vsPodcastDetails" open={audioOverview.audioAgentCanRetry || undefined}>
              <summary>{audioOverview.audioOverviewBusy ? t("正在准备脚本… 查看进度", "Preparing your script… View progress") : t("生成详情", "Generation details")}</summary>
              <AgentProgressPanel
                steps={audioOverview.audioAgentSteps}
                currentStep={audioOverview.audioAgentCurrentStep}
                agentStatus={audioOverview.audioAgentStatus}
                errorMessage={audioOverview.audioAgentErrorMessage}
                canRetry={audioOverview.audioAgentCanRetry}
                onRetry={audioOverview.onRetryAgentRun}
                busy={audioOverview.audioOverviewBusy}
              />
            </details>
          ) : null}

          {/* Creation steps */}
          <nav className="vsPodcastStepperTabs" aria-label={t("播客创作步骤", "Podcast creation steps")}>
            <button
              type="button"
              className={activeStage === 1 ? "vsBtnPrimary vsStepperBtn" : "vsBtnSecondary vsStepperBtn"}
              aria-current={activeStage === 1 ? "step" : undefined}
              onClick={() => setStageOverride(1)}
            >
              1. {t("主题与资料", "Topic & Sources")}
            </button>
            <button
              type="button"
              className={activeStage === 2 ? "vsBtnPrimary vsStepperBtn" : "vsBtnSecondary vsStepperBtn"}
              aria-current={activeStage === 2 ? "step" : undefined}
              disabled={!hasScript}
              onClick={() => setStageOverride(2)}
            >
              2. {t("剧本与配音", "Script & Voice")}
            </button>
          </nav>
        </div>

        {/* Content Area */}
        <div className="vsPodcastContentArea custom-scrollbar">
          <div className="vsPodcastContentInner">

            {/* Stage 1: Topic Prompt Section */}
            <div id="podcast-topic-section" hidden={activeStage !== 1}>
              <PodcastTopicStep audioOverview={audioOverview} />
            </div>

            {/* Stage 2: Script & Voice Synthesis Section */}
            {(hasScript && activeStage === 2) && (
              <div id="podcast-script-section" className="vsPodcastMergedScriptArea">
                {/* Audio Player (if exists) */}
                {audioOverview.audioOverviewAudioUrl && (
                  <div className="vsAudioPlayerCard">
                    <h3 className="vsAudioPlayerTitle">{t("收听播客", "Listen to your podcast")}</h3>
                    <audio controls controlsList="nodownload" src={audioOverview.audioOverviewAudioUrl} className="vsAudioPlayerElement" />
                  </div>
                )}

                {audioOverview.audioAgentSources.length > 0 && (
                  <details className="vsPodcastDetails">
                    <summary>{t("参考来源", "Reference sources")} ({audioOverview.audioAgentSources.length})</summary>
                    <AgentSourcesPanel sources={audioOverview.audioAgentSources} />
                  </details>
                )}
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
    <section className="podcastLibrary custom-scrollbar">
      <div className="podcastLibraryInner">
      <header className="podcastLibraryHeader">
        <div className="podcastLibraryIdentity">
          <span className="podcastLibraryMark"><Headphones size={24} strokeWidth={1.6} aria-hidden="true" /></span>
          <div>
            <h2>{t("Echo 播客", "Echo Podcasts")}</h2>
            <p>{t("让想法成为值得聆听的对话。", "Ideas worth listening to.")}</p>
          </div>
        </div>
        <div className="podcastLibraryActions">
          {(audioOverview.audioOverviewTopic.trim() || hasScript || audioOverview.audioAgentRunId !== null) && (
            <button type="button" className="podcastLibraryButton" onClick={() => setViewMode("workspace")}>
              {t("继续编辑", "Continue editing")} <ArrowRight size={15} aria-hidden="true" />
            </button>
          )}
          <button type="button" className="podcastLibraryButton is-primary" onClick={handleNewPodcast}
            disabled={audioOverview.audioOverviewBusy || audioOverview.audioOverviewSaving || audioOverview.audioOverviewSynthBusy}>
            <Plus size={17} aria-hidden="true" /> {t("新建播客", "New Podcast")}
          </button>
        </div>
      </header>

      <div className="podcastLibraryToolbar">
        <div className="podcastLibraryTabs" role="group" aria-label={t("播客视图", "Podcast views")}>
          <button type="button" aria-pressed={libraryTab === "podcasts"}
            onClick={() => { setLibraryTab("podcasts"); setSearchQuery(""); }}>
            {t("我的播客", "My podcasts")} <span>{audioOverview.audioOverviewPodcasts.length}</span>
          </button>
          <button type="button" aria-pressed={libraryTab === "agent_runs"}
            onClick={() => { setLibraryTab("agent_runs"); setSearchQuery(""); }}>
            {t("生成记录", "Generation history")} <span>{audioOverview.agentRunHistory.length}</span>
          </button>
        </div>
        <div className="podcastLibraryTools">
          <label className="podcastLibrarySearch">
            <Search size={16} aria-hidden="true" />
            <input type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)}
              aria-label={libraryTab === "podcasts" ? t("搜索播客", "Search podcasts") : t("搜索生成记录", "Search generation history")}
              placeholder={t("搜索主题…", "Search topics…")} />
          </label>
          <button type="button" className="podcastLibraryButton is-icon"
            aria-label={t("刷新列表", "Refresh list")} title={t("刷新列表", "Refresh list")} disabled={libraryBusy}
            onClick={() => void (libraryTab === "podcasts" ? audioOverview.onRefreshList() : audioOverview.onLoadAgentRunHistory())}>
            <RefreshCw size={17} aria-hidden="true" />
          </button>
        </div>
      </div>
      <p className="podcastLibraryCaption">
        {libraryTab === "podcasts"
          ? t("你的播客与草稿，随时继续创作。", "Your episodes and drafts, ready when you are.")
          : t("查看创作进度，打开记录继续编辑。", "Follow your progress. Open a session to keep creating.")}
      </p>

      {/* Card Grid / Agent History */}
      {libraryTab === "agent_runs" ? (
        <div className="podcastLibraryContent">
          <AgentRunHistory
            runs={filteredRuns}
            searching={Boolean(searchQuery.trim())}
            busy={audioOverview.agentRunHistoryBusy}
            onOpenRun={(run) => {
              void audioOverview.onOpenAgentRun(run);
              setViewMode("workspace");
            }}
          />
        </div>
      ) : (
      <div className="podcastLibraryContent">
        {audioOverview.audioOverviewListBusy && audioOverview.audioOverviewPodcasts.length === 0 ? (
          <div className="podcastLibraryEmpty">
            <div className="vsTranscribeEmptyIcon">
              <div className="spinner vsLoadingSpinner" />
            </div>
            <p className="vsTranscribeEmptyDesc">
              {t("加载历史记录中…", "Loading podcast history...")}
            </p>
          </div>
        ) : filteredPodcasts.length === 0 ? (
          <div className="podcastLibraryEmpty">
            <span className="podcastLibraryEmptyIcon"><Headphones size={30} strokeWidth={1.4} aria-hidden="true" /></span>
            <h3 className="vsTranscribeEmptyTitle">
              {searchQuery
                ? t("没有匹配的记录", "No matching records")
                : t("暂无播客记录", "No podcasts yet")}
            </h3>
            <p className="vsTranscribeEmptyDesc">
              {searchQuery
                ? t("尝试调整搜索关键词或重置筛选条件。", "Try adjusting your search query.")
                : t("从一个主题开始，创作你的第一期播客。", "Start with a topic and create your first episode.")}
            </p>
          </div>
        ) : (
          <div className="vsTranscribeGrid podcastEpisodeGrid">
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
      </div>
    </section>
  );
}
