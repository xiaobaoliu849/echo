import type { HistoryItem } from "../../hooks/useTranscriptionHistory";
import { TranscriptionCard } from "../TranscriptionCard";
import ErrorNotice from "../ErrorNotice";
import { useI18n } from "../../i18n";

type FilterType = "all" | "completed" | "running" | "failed";

type Props = {
  history: HistoryItem[];
  filteredHistory: HistoryItem[];
  activeFilter: FilterType;
  searchQuery: string;
  historyBusy: boolean;
  activeJobId?: string;
  error: Error | null;
  onSearchChange: (q: string) => void;
  onFilterChange: (f: FilterType) => void;
  onRefresh: () => void;
  onCardClick: (item: HistoryItem) => void;
  onDeleteJob: (jobId: string) => void;
  onRetryJob: (jobId: string) => void;
  onRenameJob?: (jobId: string, fileName: string) => Promise<void> | void;
  /** Manage (batch) mode */
  manageMode: boolean;
  selectedIds: Set<string>;
  batchDeleting: boolean;
  onToggleManageMode: () => void;
  onToggleSelect: (jobId: string) => void;
  onSelectAllVisible: () => void;
  onClearSelection: () => void;
  onBatchDelete: () => void;
};

type HistoryGroup = {
  key: string;
  label: string;
  items: HistoryItem[];
};

function entryTimeMs(item: HistoryItem): number {
  return Date.parse(item.updated_at || "") || item.timestamp || 0;
}

/** Bucket records into scannable recency groups (今天 / 昨天 / 7 天内 / …).
 * The input is already sorted newest-first, so groups come out in order. */
function groupHistoryByDate(
  items: HistoryItem[],
  t: (zh: string, en: string) => string
): HistoryGroup[] {
  const buckets: { key: string; label: string; maxAgeMs: number }[] = [
    { key: "today", label: t("今天", "Today"), maxAgeMs: 1 * 24 * 3600_000 },
    { key: "yesterday", label: t("昨天", "Yesterday"), maxAgeMs: 2 * 24 * 3600_000 },
    { key: "week", label: t("7 天内", "Last 7 days"), maxAgeMs: 7 * 24 * 3600_000 },
    { key: "month", label: t("30 天内", "Last 30 days"), maxAgeMs: 30 * 24 * 3600_000 },
    { key: "earlier", label: t("更早", "Earlier"), maxAgeMs: Number.POSITIVE_INFINITY },
  ];
  const now = Date.now();
  const groups = new Map<string, HistoryGroup>();
  for (const item of items) {
    const age = Math.max(0, now - entryTimeMs(item));
    const bucket = buckets.find((b) => age < b.maxAgeMs) ?? buckets[buckets.length - 1];
    let group = groups.get(bucket.key);
    if (!group) {
      group = { key: bucket.key, label: bucket.label, items: [] };
      groups.set(bucket.key, group);
    }
    group.items.push(item);
  }
  return buckets.map((b) => groups.get(b.key)).filter((g): g is HistoryGroup => Boolean(g));
}

export default function TranscriptionTable({
  filteredHistory,
  activeFilter,
  searchQuery,
  historyBusy,
  history,
  activeJobId,
  error,
  onSearchChange,
  onFilterChange,
  onRefresh,
  onCardClick,
  onDeleteJob,
  onRetryJob,
  onRenameJob,
  manageMode,
  selectedIds,
  batchDeleting,
  onToggleManageMode,
  onToggleSelect,
  onSelectAllVisible,
  onClearSelection,
  onBatchDelete,
}: Props) {
  const { t } = useI18n();

  const filters = [
    { key: "all" as const, label: t("全部", "All") },
    { key: "completed" as const, label: t("已完成", "Completed") },
    { key: "running" as const, label: t("进行中", "In Progress") },
    { key: "failed" as const, label: t("失败", "Failed") },
  ];

  const allVisibleSelected =
    filteredHistory.length > 0 &&
    filteredHistory.every((item) => selectedIds.has(item.job_id));

  const groups = groupHistoryByDate(filteredHistory, t);

  const renderCard = (item: HistoryItem) => (
    <TranscriptionCard
      key={item.job_id}
      item={item}
      isActive={activeJobId === item.job_id}
      onClick={() => onCardClick(item)}
      onDelete={(e) => {
        e.stopPropagation();
        if (
          confirm(
            t(
              "确定要删除这条记录吗？",
              "Are you sure you want to delete this record?"
            )
          )
        ) {
          onDeleteJob(item.job_id);
        }
      }}
      onRetry={item.status === "failed" ? (e) => {
        e.stopPropagation();
        onRetryJob(item.job_id);
      } : undefined}
      onRename={
        onRenameJob
          ? (jobId, fileName) => {
              Promise.resolve(onRenameJob(jobId, fileName)).catch(() => {
                /* Errors surface through the shared error notice in the page. */
              });
            }
          : undefined
      }
      selectable={manageMode}
      selected={selectedIds.has(item.job_id)}
      onToggleSelect={(e) => {
        e.stopPropagation();
        onToggleSelect(item.job_id);
      }}
    />
  );

  return (
    <section className="vsTranscribeLibrary">
      {/* Toolbar */}
      <div className="vsTranscribeToolbar">
        {/* Search */}
        <div className="vsTranscribeSearchBox">
          <span className="vsTranscribeSearchIcon">🔍</span>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t("搜索标题或转写内容…", "Search titles or transcripts...")}
          />
        </div>

        {/* Filter Tabs */}
        <div className="vsTranscribeFilterTabs">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              className={`vsTranscribeFilterTab ${activeFilter === f.key ? "active" : ""}`}
              onClick={() => onFilterChange(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Actions */}
        <div className="vsTranscribeToolbarActions">
          <button
            onClick={onToggleManageMode}
            className={`vsBtnGhost ${manageMode ? "active" : ""}`}
            style={{ fontSize: 12, padding: "6px 12px" }}
            title={t("批量管理", "Batch manage")}
          >
            {manageMode ? t("✓ 完成", "✓ Done") : t("☰ 管理", "☰ Manage")}
          </button>
          <button
            onClick={onRefresh}
            className="vsBtnGhost"
            style={{ fontSize: 12, padding: "6px 12px" }}
            title={t("刷新", "Refresh")}
          >
            ↻ {t("刷新", "Refresh")}
          </button>
        </div>
      </div>

      {/* Batch action bar (manage mode) */}
      {manageMode && (
        <div className="vsTranscribeBatchBar">
          <button
            type="button"
            className="vsTranscribeBatchSelectAll"
            onClick={allVisibleSelected ? onClearSelection : onSelectAllVisible}
          >
            <span className={`vsTranscribeCardCheckbox inline ${allVisibleSelected ? "checked" : ""}`}>
              {allVisibleSelected ? "✓" : ""}
            </span>
            {allVisibleSelected
              ? t("取消全选", "Deselect all")
              : t("全选当前列表", "Select all visible")}
          </button>
          <span className="vsTranscribeBatchCount">
            {t(`已选 ${selectedIds.size} 项`, `${selectedIds.size} selected`)}
          </span>
          <div className="vsTranscribeBatchActions">
            <button
              type="button"
              className="vsBtnDanger"
              disabled={selectedIds.size === 0 || batchDeleting}
              onClick={onBatchDelete}
            >
              {batchDeleting
                ? t("删除中…", "Deleting…")
                : t(`删除所选 (${selectedIds.size})`, `Delete selected (${selectedIds.size})`)}
            </button>
            <button
              type="button"
              className="vsBtnGhost"
              onClick={onToggleManageMode}
              style={{ fontSize: 12, padding: "6px 12px" }}
            >
              {t("取消", "Cancel")}
            </button>
          </div>
        </div>
      )}

      {/* Card Grid */}
      <div className="vsTranscribeGridWrap custom-scrollbar">
        {historyBusy && history.length === 0 ? (
          <div className="vsTranscribeEmpty">
            <div className="vsTranscribeEmptyIcon">
              <div
                className="spinner"
                style={{
                  width: 32,
                  height: 32,
                  border: "3px solid var(--line)",
                  borderTopColor: "var(--brand)",
                  borderRadius: "50%",
                }}
              />
            </div>
            <p className="vsTranscribeEmptyDesc">
              {t("加载历史记录中…", "Loading transcription history...")}
            </p>
          </div>
        ) : filteredHistory.length === 0 ? (
          <div className="vsTranscribeEmpty">
            <div className="vsTranscribeEmptyIcon">🎙️</div>
            <h3 className="vsTranscribeEmptyTitle">
              {searchQuery || activeFilter !== "all"
                ? t("没有匹配的记录", "No matching records")
                : t("暂无转写记录", "No transcriptions yet")}
            </h3>
            <p className="vsTranscribeEmptyDesc">
              {searchQuery || activeFilter !== "all"
                ? t(
                    "尝试调整搜索条件或筛选条件。",
                    "Try adjusting your search or filter criteria."
                  )
                : t(
                    "暂无转写记录。您可以切换至上方「本地音频」或「实时录音」随时开始转写。",
                    "No transcriptions yet. Switch to 'Local Audio' or 'Realtime Live' above to start transcribing."
                  )}
            </p>
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.key} className="vsTranscribeGroup">
              <div className="vsTranscribeGroupLabel">{group.label}</div>
              <div className="vsTranscribeGrid">{group.items.map(renderCard)}</div>
            </div>
          ))
        )}
      </div>

      {/* Error Notices */}
      {error && (
        <div style={{ margin: "0 24px 16px 24px" }}>
          <ErrorNotice message={error.message} scope="transcription" />
        </div>
      )}
    </section>
  );
}
