import React, { useMemo, useState } from "react";
import type { HistoryItem } from "../hooks/useTranscriptionHistory";
import { useI18n } from "../i18n";

type Props = {
  item: HistoryItem;
  isActive?: boolean;
  onClick: () => void;
  onDelete: (e: React.MouseEvent) => void;
  onRetry?: (e: React.MouseEvent) => void;
  onRename?: (jobId: string, fileName: string) => void;
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

function getTitleStem(name: string): string {
  const dot = name.lastIndexOf(".");
  // Keep dots that are part of the name itself (e.g. "v1.2 会议").
  if (dot <= 0 || dot < name.length - 6) return name;
  return name.slice(0, dot);
}

/** Server-side storage names leaked by old records — the original name is
 * unrecoverable, so present them as untitled instead of a raw uuid. */
const SYNTHETIC_NAME_PATTERN = /^upload_[0-9a-f]{6,}\.\w+$|^sync_upload$|^realtime_mic$/i;

function isSyntheticName(name: string): boolean {
  return SYNTHETIC_NAME_PATTERN.test(name.trim());
}

function formatRelativeTime(
  dateStr: string | null | undefined,
  t: (zh: string, en: string) => string
): string {
  if (!dateStr) return t("未知时间", "Unknown");
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return t("未知时间", "Unknown");
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

function formatDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return "";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/* Small SVG wave bars for the card thumbnail */
function WaveBars({ color, bars }: { color: string; bars: number }) {
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
  onRename,
  selectable,
  selected,
  onToggleSelect,
}) => {
  const { t } = useI18n();
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");

  const rawName = item.file_name || "";
  const untitled = t("未命名录音", "Untitled recording");
  const displayName = !rawName || isSyntheticName(rawName) ? untitled : getTitleStem(rawName);
  const ext = useMemo(() => getFileExtension(rawName || ""), [rawName]);
  const hash = useMemo(() => hashStr(rawName || item.job_id), [rawName, item.job_id]);
  const palette = COVER_GRADIENTS[hash % COVER_GRADIENTS.length];

  const isActiveJob =
    item.status === "running" ||
    item.status === "submitted" ||
    item.status === "queued" ||
    item.status === "uploaded";
  const isFailed = item.status === "failed";
  const isCompleted = item.status === "completed";
  const statusClass = isCompleted ? "" : isFailed ? "failed" : item.status === "submitted" ? "submitted" : "running";

  const statusLabel = isCompleted
    ? t("已完成", "Completed")
    : isFailed
    ? t("转写失败", "Failed")
    : item.status === "submitted" || item.status === "queued"
    ? t("排队中", "Queued")
    : t("转写中", "Transcribing");

  const originInfo = (() => {
    if (item.origin === "realtime") return { icon: "🎙️", label: t("实时录音", "Realtime") };
    if (item.origin === "url") return { icon: "🔗", label: t("链接转写", "Link") };
    if (item.origin === "upload") return { icon: "📁", label: t("本地文件", "Local file") };
    return null;
  })();

  const durationText = formatDuration(item.duration_seconds);

  const previewText = (() => {
    if (isFailed) return item.error || t("转写失败", "Transcription failed");
    if (isActiveJob) return item.progress || t("正在转写中…", "Transcribing...");
    if (isCompleted) {
      if (item.transcript_preview) return item.transcript_preview;
      if (item.has_transcript) return t("点击查看转写内容", "Click to view transcript");
      return t("暂无转写内容", "No transcript content");
    }
    return t("处理中…", "Processing...");
  })();

  const startRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setRenameValue(rawName && !isSyntheticName(rawName) ? rawName : displayName);
    setIsRenaming(true);
  };

  const commitRename = () => {
    setIsRenaming(false);
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== rawName && onRename) {
      onRename(item.job_id, trimmed);
    }
  };

  const handleActivate = (e: React.MouseEvent) => {
    if (selectable && onToggleSelect) {
      onToggleSelect(e);
    } else {
      onClick();
    }
  };

  return (
    <div
      className={`vsTranscribeCard vsTranscribeCardCompact ${statusClass} ${isActive ? "active" : ""} ${
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

      {/* Head: thumbnail + title + meta */}
      <div className="vsTranscribeCardMain">
        <div
          className="vsTranscribeCardThumb"
          style={{
            background: `linear-gradient(135deg, ${palette[0]}, ${palette[1]} 60%, ${palette[2]})`,
          }}
          aria-hidden="true"
        >
          <WaveBars color="rgba(255,255,255,0.55)" bars={8} />
          {ext && <span className="vsTranscribeCardFormatBadge">{ext}</span>}
          <span className={`vsTranscribeCardStatusDot ${statusClass}`} />
        </div>

        <div className="vsTranscribeCardHead">
          {isRenaming ? (
            <input
              className="vsTranscribeCardRenameInput"
              value={renameValue}
              autoFocus
              onFocus={(e) => e.currentTarget.select()}
              onChange={(e) => setRenameValue(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === "Enter") commitRename();
                if (e.key === "Escape") setIsRenaming(false);
              }}
              onBlur={commitRename}
              aria-label={t("重命名转写记录", "Rename transcription")}
            />
          ) : (
            <div className="vsTranscribeCardTitleRow">
              <h4 className="vsTranscribeCardTitle" title={rawName || displayName}>
                {displayName}
              </h4>
              {item.memory_saved && (
                <span className="vsTranscribeCardMemoryBadge">{t("已入记忆", "In Memory")}</span>
              )}
            </div>
          )}
          <div className="vsTranscribeCardSub">
            <span className="vsTranscribeCardTime">{formatRelativeTime(item.updated_at, t)}</span>
            {originInfo && (
              <>
                <span className="vsTranscribeCardSubSep">·</span>
                <span className="vsTranscribeCardOrigin">
                  {originInfo.icon} {originInfo.label}
                </span>
              </>
            )}
            {durationText && (
              <>
                <span className="vsTranscribeCardSubSep">·</span>
                <span className="vsTranscribeCardDuration" title={t("音频时长", "Audio duration")}>
                  {durationText}
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Preview: transcript head / progress / error */}
      <p className={`vsTranscribeCardPreview ${isFailed ? "error" : ""}`} title={previewText}>
        {previewText}
      </p>

      {/* Footer: status chip + hover actions */}
      <div className="vsTranscribeCardFooter">
        <span className={`vsTranscribeCardStatusChip ${statusClass}`}>
          <span className="vsTranscribeCardStatusChipDot" />
          {statusLabel}
        </span>
        {!selectable && (
          <div className="vsTranscribeCardActions">
            {isFailed && onRetry && (
              <button
                className="vsTranscribeCardRetryBtn"
                onClick={onRetry}
                title={t("重试转写", "Retry transcription")}
              >
                {t("重试", "Retry")}
              </button>
            )}
            {onRename && (
              <button
                className="vsTranscribeCardRenameBtn"
                onClick={startRename}
                title={t("重命名", "Rename")}
              >
                {t("重命名", "Rename")}
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
