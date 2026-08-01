import type { HistoryItem } from "../../hooks/useTranscriptionHistory";
import { TranscriptionCard } from "../TranscriptionCard";
import ErrorNotice from "../ErrorNotice";
import { NewTranscriptionModal } from "../NewTranscriptionModal";
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
  modalError: Error | null;
  showNewModal: boolean;
  isBusy: boolean;
  isSyncBusy: boolean;
  isAsyncBusy: boolean;
  onSearchChange: (q: string) => void;
  onFilterChange: (f: FilterType) => void;
  onRefresh: () => void;
  onOpenNewModal: () => void;
  onCloseNewModal: () => void;
  onCardClick: (item: HistoryItem) => void;
  onDeleteJob: (jobId: string) => void;
  onRetryJob: (jobId: string) => void;
  onLocalTranscribe: (file: File, provider?: string) => Promise<void>;
  onRemoteSubmit: (url: string) => Promise<void>;
};

export default function TranscriptionTable({
  filteredHistory,
  activeFilter,
  searchQuery,
  historyBusy,
  history,
  activeJobId,
  error,
  modalError,
  showNewModal,
  isBusy,
  isSyncBusy,
  isAsyncBusy,
  onSearchChange,
  onFilterChange,
  onRefresh,
  onOpenNewModal,
  onCloseNewModal,
  onCardClick,
  onDeleteJob,
  onRetryJob,
  onLocalTranscribe,
  onRemoteSubmit,
}: Props) {
  const { t } = useI18n();

  const filters = [
    { key: "all" as const, label: t("全部", "All") },
    { key: "completed" as const, label: t("已完成", "Completed") },
    { key: "running" as const, label: t("进行中", "In Progress") },
    { key: "failed" as const, label: t("失败", "Failed") },
  ];

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
            placeholder={t("搜索转写记录…", "Search transcriptions...")}
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
            onClick={onRefresh}
            className="vsBtnGhost"
            style={{ fontSize: 12, padding: "6px 12px" }}
            title={t("刷新", "Refresh")}
          >
            ↻ {t("刷新", "Refresh")}
          </button>
          <button
            onClick={onOpenNewModal}
            className="vsBtnPrimary"
            style={{
              height: 36,
              fontSize: 13,
              padding: "0 18px",
              borderRadius: 10,
              fontWeight: 600,
            }}
          >
            ✨ {t("新建转写", "New Transcription")}
          </button>
        </div>
      </div>

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
                    "点击「新建转写」上传音频文件或输入远程 URL，开始你的第一次转写。",
                    "Click 'New Transcription' to upload audio or enter a remote URL and start your first transcription."
                  )}
            </p>
            {!searchQuery && activeFilter === "all" && (
              <button
                onClick={onOpenNewModal}
                className="vsBtnPrimary"
                style={{
                  height: 40,
                  fontSize: 14,
                  padding: "0 24px",
                  borderRadius: 10,
                  marginTop: 8,
                }}
              >
                ✨ {t("新建转写", "New Transcription")}
              </button>
            )}
          </div>
        ) : (
          <div className="vsTranscribeGrid">
            {filteredHistory.map((item) => (
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
              />
            ))}
          </div>
        )}
      </div>

      {/* Error Notices */}
      {error && !modalError && (
        <div style={{ margin: "0 24px 16px 24px" }}>
          <ErrorNotice message={error.message} scope="transcription" />
        </div>
      )}

      {/* Modal */}
      {showNewModal && (
        <NewTranscriptionModal
          open={showNewModal}
          error={modalError}
          isBusy={isBusy}
          isSyncBusy={isSyncBusy}
          isAsyncBusy={isAsyncBusy}
          onClose={onCloseNewModal}
          onLocalTranscribe={onLocalTranscribe}
          onRemoteSubmit={onRemoteSubmit}
        />
      )}
    </section>
  );
}
