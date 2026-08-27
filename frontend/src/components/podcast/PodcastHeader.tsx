import { ArrowLeft } from "lucide-react";
import type { UseAudioOverviewResult } from "../../hooks/useAudioOverview";
import { useI18n } from "../../i18n";

type Props = {
  audioOverview: UseAudioOverviewResult;
  onBackToLibrary?: () => void;
  onSaveScript?: () => void;
  onExportScript?: () => void;
  hasScript?: boolean;
};

export default function PodcastHeader({
  audioOverview,
  onBackToLibrary,
  onSaveScript,
  onExportScript,
  hasScript = false
}: Props) {
  const { t } = useI18n();
  const isWorkspaceView = Boolean(onBackToLibrary);

  const titleText = isWorkspaceView
    ? audioOverview.audioOverviewPodcastId
      ? t(
          `播客 #${audioOverview.audioOverviewPodcastId}: ${audioOverview.audioOverviewTopic || "未命名"}`,
          `Podcast #${audioOverview.audioOverviewPodcastId}: ${audioOverview.audioOverviewTopic || "Unnamed"}`
        )
      : t("新建播客草稿", "New Podcast Draft")
    : t("播客工作台", "Podcast Studio");

  const subtitleText = isWorkspaceView
    ? t("播客工作台 · 从主题到剧本与合成", "Podcast Studio · Topic to script and voice synthesis")
    : t("从一个主题开始，逐步生成脚本并合成双人播客。", "Start from one topic, generate a script, then synthesize a two-host podcast.");

  return (
    <div className={`vsPodcastHeader ${isWorkspaceView ? "is-workspace" : ""}`}>
      <div className="vsPodcastHeaderMain">
        {onBackToLibrary && (
          <button
            type="button"
            className="vsTranscribeBackBtn"
            onClick={onBackToLibrary}
            title={t("返回列表", "Back to list")}
            aria-label={t("返回列表", "Back to list")}
          >
            <ArrowLeft size={18} strokeWidth={2.2} />
          </button>
        )}
        <div className="vsPodcastHeaderCopy">
          <h2>{titleText}</h2>
          <p>{subtitleText}</p>
        </div>
      </div>

      <div className="vsPodcastHeaderActions">
        {onSaveScript && (
          <button
            type="button"
            onClick={onSaveScript}
            disabled={audioOverview.audioOverviewSaving || audioOverview.audioOverviewBusy}
            className="vsBtnSecondary vsBtnSmall"
          >
            {audioOverview.audioOverviewSaving ? t("保存中...", "Saving...") : t("保存草稿", "Save Draft")}
          </button>
        )}
        {onExportScript && (
          <button
            type="button"
            onClick={onExportScript}
            disabled={!hasScript}
            className="vsBtnSecondary vsBtnSmall"
          >
            {t("导出 TXT", "Export TXT")}
          </button>
        )}
        <span className="vsPodcastStatusChip">{audioOverview.currentAudioOverviewLabel}</span>
        {audioOverview.audioAgentRunId !== null ? (
          <span className="vsPodcastStatusChip">
            {t(
              `Agent Run #${audioOverview.audioAgentRunId} · ${audioOverview.audioAgentStatus || "queued"}`,
              `Agent Run #${audioOverview.audioAgentRunId} · ${audioOverview.audioAgentStatus || "queued"}`
            )}
          </span>
        ) : null}
        <span
          className={`vsPodcastStatusChip ${audioOverview.audioOverviewMemoryConfigured ? "is-memory" : "is-muted"}`}
        >
          {audioOverview.audioOverviewMemoryConfigured
            ? t("长期记忆已接入", "Long-term memory connected")
            : t("长期记忆未接入", "Long-term memory not connected")}
        </span>
        <button
          type="button"
          className="ghost vsPodcastMiniBtn"
          onClick={audioOverview.onNewDraft}
          disabled={
            audioOverview.audioOverviewBusy ||
            audioOverview.audioOverviewSaving ||
            audioOverview.audioOverviewSynthBusy
          }
        >
          {t("新建草稿", "New draft")}
        </button>
        <div className="vsPodcastMenuWrap">
          <button
            type="button"
            className="ghost vsPodcastMenuTrigger"
            aria-label={t("更多操作", "More actions")}
            aria-expanded={audioOverview.audioOverviewMenuOpen}
            onClick={audioOverview.onToggleMenu}
          >
            ⋯
          </button>
          {audioOverview.audioOverviewMenuOpen ? (
            <div className="vsPodcastMenu">
              <button
                type="button"
                className="vsPodcastMenuItem danger"
                onClick={() => void audioOverview.onDeleteCurrent()}
                disabled={audioOverview.audioOverviewPodcastId === null}
              >
                {t("删除当前", "Delete current")}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

