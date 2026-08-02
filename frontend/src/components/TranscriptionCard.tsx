import React, { useMemo } from "react";
import type { HistoryItem } from "../hooks/useTranscriptionHistory";
import { useI18n } from "../i18n";

type Props = {
  item: HistoryItem;
  isActive?: boolean;
  onClick: () => void;
  onDelete: (e: React.MouseEvent) => void;
  onRetry?: (e: React.MouseEvent) => void;
  /** Manage mode: card click toggles selection instead of opening detail. */
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: (e: React.MouseEvent) => void;
};

/* Deterministic gradient palette based on filename hash */
const COVER_GRADIENTS = [
  ["#7c3aed", "#a78bfa", "#c4b5fd"], // violet
  ["#6366f1", "#818cf8", "#a5b4fc"], // indigo
  ["#3b82f6", "#60a5fa", "#93c5fd"], // blue
  ["#0891b2", "#22d3ee", "#67e8f9"], // cyan
  ["#059669", "#34d399", "#6ee7b7"], // emerald
  ["#d97706", "#fbbf24", "#fcd34d"], // amber
  ["#e11d48", "#fb7185", "#fda4af"], // rose
  ["#9333ea", "#c084fc", "#d8b4fe"], // purple
  ["#0d9488", "#2dd4bf", "#5eead4"], // teal
  ["#ea580c", "#fb923c", "#fdba74"], // orange
];

function hashStr(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function getFileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot < 0) return "";
  return name.slice(dot + 1).toUpperCase();
}

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

/* SVG wave bars for the card cover */
function WaveBars({ color }: { color: string }) {
  const bars = 24;
  return (
    <svg className="vsTranscribeCardWave" viewBox={`0 0 ${bars * 6} 48`} preserveAspectRatio="none">
      {Array.from({ length: bars }, (_, i) => {
        const h = 8 + Math.sin(i * 0.7) * 14 + Math.cos(i * 1.3) * 8;
        return (
          <rect
            key={i}
            x={i * 6}
            y={24 - h / 2}
            width={4}
            height={h}
            rx={2}
            fill={color}
          />
        );
      })}
    </svg>
  );
}

export const TranscriptionCard: React.FC<Props> = ({
  item,
  isActive,
  onClick,
  onDelete,
  onRetry,
  selectable,
  selected,
  onToggleSelect,
}) => {
  const { t } = useI18n();
  const fileName = item.file_name || t("未知文件", "Unknown file");
  const ext = getFileExtension(fileName);
  const hash = useMemo(() => hashStr(fileName), [fileName]);
  const palette = COVER_GRADIENTS[hash % COVER_GRADIENTS.length];

  const statusClass =
    item.status === "completed"
      ? ""
      : item.status === "failed"
      ? "failed"
      : item.status === "submitted"
      ? "submitted"
      : "running";

  const handleActivate = (e: React.MouseEvent) => {
    if (selectable && onToggleSelect) {
      onToggleSelect(e);
    } else {
      onClick();
    }
  };

  return (
    <div
      className={`vsTranscribeCard ${statusClass} ${isActive ? "active" : ""} ${
        selectable ? "selectable" : ""
      } ${selected ? "selected" : ""}`}
      onClick={handleActivate}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (selectable && onToggleSelect) {
            onToggleSelect(e as unknown as React.MouseEvent);
          } else {
            onClick();
          }
        }
      }}
    >
      {/* Selection checkbox (manage mode) */}
      {selectable && (
        <button
          type="button"
          className={`vsTranscribeCardCheckbox ${selected ? "checked" : ""}`}
          aria-label={selected ? t("取消选择", "Deselect") : t("选择", "Select")}
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelect?.(e);
          }}
        >
          {selected ? "✓" : ""}
        </button>
      )}

      {/* Cover */}
      <div className="vsTranscribeCardCover">
        <div
          className="vsTranscribeCardCoverBg"
          style={{
            background: `linear-gradient(135deg, ${palette[0]}, ${palette[1]} 60%, ${palette[2]})`,
          }}
        />
        <WaveBars color="rgba(255,255,255,0.6)" />
        <button
          className="vsTranscribeCardPlayBtn"
          onClick={(e) => {
            e.stopPropagation();
            onClick();
          }}
          aria-label={t("查看详情", "View details")}
        >
          ▶
        </button>
        {ext && <span className="vsTranscribeCardFormatBadge">{ext}</span>}
        <span className={`vsTranscribeCardStatusDot ${statusClass}`} />
      </div>

      {/* Meta */}
      <div className="vsTranscribeCardMeta">
        <div className="vsTranscribeCardMetaTop">
          <span className="vsTranscribeCardTime">
            {formatRelativeTime(item.updated_at, t)}
          </span>
        </div>
        <h4 className="vsTranscribeCardTitle" title={fileName}>
          {fileName}
        </h4>
        <p className="vsTranscribeCardPreview">
          {item.status === "completed" && item.has_transcript
            ? t("点击查看转写内容", "Click to view transcript")
            : item.status === "failed"
            ? item.error || t("转写失败", "Transcription failed")
            : item.status === "completed"
            ? t("已完成", "Completed")
            : t("处理中…", "Processing...")}
        </p>
      </div>

      {/* Footer */}
      <div className="vsTranscribeCardFooter">
        {item.memory_saved ? (
          <span className="vsTranscribeCardMemoryBadge">
            {t("已入记忆", "In Memory")}
          </span>
        ) : (
          <span />
        )}
        {!selectable && (
          <div className="vsTranscribeCardActions">
            {item.status === "failed" && onRetry && (
              <button
                className="vsTranscribeCardRetryBtn"
                onClick={onRetry}
                title={t("重试转写", "Retry transcription")}
              >
                {t("重试", "Retry")}
              </button>
            )}
            <button
              className="vsTranscribeCardDeleteBtn"
              onClick={onDelete}
              title={t("删除记录", "Delete record")}
            >
              {t("删除", "Delete")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
