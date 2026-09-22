import type { MouseEvent } from "react";
import { Headphones, FileText, ArrowUpRight, Trash2 } from "lucide-react";
import type { AudioOverviewPodcast } from "../../api";
import { useI18n } from "../../i18n";

type Props = {
  item: AudioOverviewPodcast;
  isActive?: boolean;
  onClick: () => void;
  onDelete: (event: MouseEvent) => void;
};

function formatRelativeTime(dateStr: string | null | undefined, t: (zh: string, en: string) => string): string {
  if (!dateStr) return t("未知时间", "Unknown");
  const date = new Date(dateStr);
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return t("刚刚", "Just now");
  if (diffMin < 60) return t(`${diffMin} 分钟前`, `${diffMin}m ago`);
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return t(`${diffHr} 小时前`, `${diffHr}h ago`);
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return t(`${diffDay} 天前`, `${diffDay}d ago`);
  const diffMon = Math.floor(diffDay / 30);
  if (diffMon < 12) return t(`${diffMon} 个月前`, `${diffMon}mo ago`);
  return t(`${Math.floor(diffMon / 12)} 年前`, `${Math.floor(diffMon / 12)}y ago`);
}

export function PodcastCard({ item, isActive, onClick, onDelete }: Props) {
  const { t } = useI18n();
  const topic = item.topic || t("未命名播客", "Untitled podcast");
  const completed = Boolean(item.audio_path);
  const hasScript = Boolean(item.script_lines?.length);
  return (
    <article className={`podcastEpisodeCard${isActive ? " is-active" : ""}`}>
      <button type="button" className="podcastEpisodeOpen" onClick={onClick}>
        <span className="podcastEpisodeTop">
          <span className="podcastLibraryMark">
            {completed ? <Headphones size={22} aria-hidden="true" /> : <FileText size={22} aria-hidden="true" />}
          </span>
          <span className="podcastEpisodeState">{completed ? t("可收听", "Ready to play") : hasScript ? t("脚本就绪", "Script ready") : t("草稿", "Draft")}</span>
        </span>
        <h3>{topic}</h3>
        <span className="podcastEpisodeLink">{t("打开播客", "Open podcast")} <ArrowUpRight size={14} aria-hidden="true" /></span>
      </button>
      <div className="podcastEpisodeFooter">
        <span>{formatRelativeTime(item.updated_at, t)}</span>
        <button type="button" onClick={onDelete} aria-label={t(`删除播客：${topic}`, `Delete podcast: ${topic}`)} title={t("删除播客", "Delete podcast")}>
          <Trash2 size={15} aria-hidden="true" />
        </button>
      </div>
    </article>
  );
}
