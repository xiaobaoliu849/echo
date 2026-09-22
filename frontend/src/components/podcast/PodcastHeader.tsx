import { ArrowLeft } from "lucide-react";
import type { UseAudioOverviewResult } from "../../hooks/useAudioOverview";
import { useI18n } from "../../i18n";

type Props = {
  audioOverview: UseAudioOverviewResult;
  onBackToLibrary?: () => void;
};

export default function PodcastHeader({
  audioOverview,
  onBackToLibrary
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
    : t("Echo 播客", "Echo Podcasts");

  const subtitleText = isWorkspaceView
    ? t("Echo 播客 · 主题、脚本、音频", "Echo Podcasts · Topic, script, audio")
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

