import { ChevronRight, FileAudio, History } from "lucide-react";
import type { AudioAgentRun } from "../../api";
import { useI18n } from "../../i18n";

type Props = {
  runs: AudioAgentRun[];
  busy: boolean;
  searching?: boolean;
  onOpenRun: (run: AudioAgentRun) => void;
};

const STATUS_ZH: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  awaiting_review: "待审核",
  draft_ready: "草稿就绪",
  synthesizing: "合成中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const STATUS_EN: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  awaiting_review: "Awaiting review",
  draft_ready: "Draft ready",
  synthesizing: "Synthesizing",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function formatTime(value: string, language: string): string {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(language, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function AgentRunHistory({ runs, busy, searching = false, onOpenRun }: Props) {
  const { t, language } = useI18n();
  const statusLabels = language === "zh-CN" ? STATUS_ZH : STATUS_EN;

  if (!runs.length) {
    return (
      <div className="podcastLibraryEmpty" role="status">
        <span className="podcastLibraryEmptyIcon"><History size={30} strokeWidth={1.4} aria-hidden="true" /></span>
        <h3>{busy ? t("正在加载…", "Loading…") : searching ? t("没有匹配的记录", "No matching sessions") : t("暂无生成记录", "No sessions yet")}</h3>
        <p>{searching ? t("尝试换一个主题关键词。", "Try another topic keyword.") : t("生成脚本后，可以在这里查看进度并继续创作。", "Once you generate a script, follow its progress here.")}</p>
      </div>
    );
  }

  return (
    <div className="podcastHistory" aria-busy={busy}>
      <div className="podcastHistoryLabels" aria-hidden="true">
        <span>{t("主题", "Topic")}</span>
        <span>{t("创建时间", "Created")}</span>
        <span>{t("状态", "Status")}</span>
        <span />
      </div>
      <ul className="podcastHistoryList">
        {runs.map((run) => (
          <li key={run.id}>
            <button type="button" className="podcastHistoryRow" onClick={() => onOpenRun(run)}>
              <span className="podcastHistorySubject">
                <span className="podcastHistoryIcon"><FileAudio size={20} strokeWidth={1.5} aria-hidden="true" /></span>
                <span className="podcastHistoryCopy">
                  <span className="podcastHistoryTitle">{run.topic || t("未命名播客", "Untitled podcast")}</span>
                  <span className="podcastHistoryMeta">
                    <span>#{run.id}</span><span>{run.provider}</span>
                    <span>{run.language.startsWith("zh") ? t("中文", "Chinese") : run.language.startsWith("en") ? t("英文", "English") : run.language}</span>
                  </span>
                  {run.error_message && <span className="podcastHistoryError">{run.error_message}</span>}
                </span>
              </span>
              <time className="podcastHistoryTime" dateTime={run.created_at}>{formatTime(run.created_at, language)}</time>
              <span className="podcastHistoryStatus" data-status={run.status}>
                <span aria-hidden="true" />{statusLabels[run.status] || run.status}
              </span>
              <ChevronRight className="podcastHistoryChevron" size={16} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
