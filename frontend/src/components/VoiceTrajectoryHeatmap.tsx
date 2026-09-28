import { useEffect, useMemo, useState } from "react";
import { Flame, Trophy, Clock, MessageSquare, Calendar, RefreshCw, X } from "lucide-react";
import { fetchVoiceAgentTrajectory, type VoiceAgentTrajectoryResponse, type VoiceAgentTrajectoryDay } from "../api";
import { useI18n } from "../i18n";

type Props = {
  onClose?: () => void;
  className?: string;
  initialDays?: number;
};

function formatDuration(seconds: number, isZh: boolean): string {
  if (seconds <= 0) return isZh ? "0 分钟" : "0m";
  if (seconds < 60) return isZh ? `${seconds} 秒` : `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) {
    return isZh ? `${mins} 分钟` : `${mins}m`;
  }
  const hours = Math.floor(mins / 60);
  const remMin = mins % 60;
  return isZh ? `${hours} 小时 ${remMin > 0 ? remMin + " 分钟" : ""}` : `${hours}h ${remMin > 0 ? remMin + "m" : ""}`;
}

function formatDate(dateStr: string, isZh: boolean): string {
  try {
    const [y, m, d] = dateStr.split("-").map(Number);
    const date = new Date(y, m - 1, d);
    if (isNaN(date.getTime())) return dateStr;
    if (isZh) {
      return `${date.getMonth() + 1}月${date.getDate()}日`;
    }
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric", weekday: "short" });
  } catch {
    return dateStr;
  }
}

export default function VoiceTrajectoryHeatmap({ onClose, className = "", initialDays = 180 }: Props) {
  const { language } = useI18n();
  const isZh = language.toLowerCase().startsWith("zh");

  const [daysRange, setDaysRange] = useState<number>(initialDays);
  const [data, setData] = useState<VoiceAgentTrajectoryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [hoveredCell, setHoveredCell] = useState<{
    date: string;
    info?: VoiceAgentTrajectoryDay;
    x: number;
    y: number;
  } | null>(null);

  const loadData = async (range: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchVoiceAgentTrajectory(range);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load trajectory");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(daysRange);
  }, [daysRange]);

  // Construct weeks and days matrix
  const weeks = useMemo(() => {
    const today = new Date();
    const result: Array<{
      days: Array<{
        dateStr: string;
        dateObj: Date;
        level: number;
        info?: VoiceAgentTrajectoryDay;
        isFuture: boolean;
      }>;
    }> = [];

    // Calculate start date
    const totalDays = daysRange;
    const start = new Date(today);
    start.setDate(today.getDate() - totalDays);

    // Align start to preceding Monday (0=Sun, 1=Mon, ..., 6=Sat)
    const dayOfWeek = start.getDay();
    const diffToMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
    start.setDate(start.getDate() - diffToMonday);

    const curr = new Date(start);
    let currentWeek: Array<{
      dateStr: string;
      dateObj: Date;
      level: number;
      info?: VoiceAgentTrajectoryDay;
      isFuture: boolean;
    }> = [];

    while (curr <= today || currentWeek.length > 0) {
      const y = curr.getFullYear();
      const m = String(curr.getMonth() + 1).padStart(2, "0");
      const d = String(curr.getDate()).padStart(2, "0");
      const dateStr = `${y}-${m}-${d}`;
      const isFuture = curr > today;

      const info = data?.daily_activity?.[dateStr];
      const level = isFuture ? 0 : info ? info.level : 0;

      currentWeek.push({
        dateStr,
        dateObj: new Date(curr),
        level,
        info,
        isFuture,
      });

      if (currentWeek.length === 7) {
        result.push({ days: currentWeek });
        currentWeek = [];
        if (curr > today) break;
      }

      curr.setDate(curr.getDate() + 1);
    }

    if (currentWeek.length > 0) {
      result.push({ days: currentWeek });
    }

    return result;
  }, [daysRange, data]);

  const currentStreak = data?.current_streak ?? 0;
  const longestStreak = data?.longest_streak ?? 0;
  const totalSeconds = data?.total_seconds ?? 0;
  const totalTurns = data?.total_turns ?? 0;
  const activeDays = data?.active_days ?? 0;

  return (
    <div className={`trajectory-card ${className}`}>
      {/* Header */}
      <div className="trajectory-header">
        <div className="trajectory-title-group">
          <span className="trajectory-icon-badge">
            <Flame size={18} />
          </span>
          <div>
            <h3 className="trajectory-title">
              {isZh ? "语音练习足迹" : "Voice Practice Trajectory"}
            </h3>
            <p className="trajectory-subtitle">
              {isZh
                ? "每日语音对话时长与连续打卡记录"
                : "Daily spoken duration & conversation streak"}
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div className="trajectory-range-tabs">
            <button
              type="button"
              className={`trajectory-range-btn ${daysRange === 90 ? "active" : ""}`}
              onClick={() => setDaysRange(90)}
            >
              {isZh ? "近3个月" : "3 Months"}
            </button>
            <button
              type="button"
              className={`trajectory-range-btn ${daysRange === 180 ? "active" : ""}`}
              onClick={() => setDaysRange(180)}
            >
              {isZh ? "近6个月" : "6 Months"}
            </button>
            <button
              type="button"
              className={`trajectory-range-btn ${daysRange === 365 ? "active" : ""}`}
              onClick={() => setDaysRange(365)}
            >
              {isZh ? "1年" : "1 Year"}
            </button>
          </div>

          <button
            type="button"
            className="trajectory-range-btn"
            style={{ padding: "5px" }}
            title={isZh ? "刷新数据" : "Refresh"}
            onClick={() => loadData(daysRange)}
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>

          {onClose && (
            <button
              type="button"
              className="trajectory-range-btn"
              style={{ padding: "5px" }}
              onClick={onClose}
              aria-label="Close"
            >
              <X size={15} />
            </button>
          )}
        </div>
      </div>

      {error && (
        <div style={{ color: "var(--danger, #ef4444)", fontSize: "0.8rem", padding: "4px 0" }}>
          {error}
        </div>
      )}

      {/* Stats Summary Row */}
      <div className="trajectory-stats-row">
        <div className="trajectory-stat-box">
          <div className="trajectory-stat-label">
            <Flame size={14} style={{ color: "#ef4444" }} />
            <span>{isZh ? "当前连续打卡" : "Current Streak"}</span>
          </div>
          <div className="trajectory-stat-value">
            {currentStreak} <span style={{ fontSize: "0.75rem", fontWeight: "normal" }}>{isZh ? "天" : "days"}</span>
          </div>
        </div>

        <div className="trajectory-stat-box">
          <div className="trajectory-stat-label">
            <Trophy size={14} style={{ color: "#eab308" }} />
            <span>{isZh ? "最长连续天数" : "Longest Streak"}</span>
          </div>
          <div className="trajectory-stat-value">
            {longestStreak} <span style={{ fontSize: "0.75rem", fontWeight: "normal" }}>{isZh ? "天" : "days"}</span>
          </div>
        </div>

        <div className="trajectory-stat-box">
          <div className="trajectory-stat-label">
            <Clock size={14} style={{ color: "#3b82f6" }} />
            <span>{isZh ? "累计对话时长" : "Total Spoken Time"}</span>
          </div>
          <div className="trajectory-stat-value">
            {formatDuration(totalSeconds, isZh)}
          </div>
        </div>

        <div className="trajectory-stat-box">
          <div className="trajectory-stat-label">
            <MessageSquare size={14} style={{ color: "#10b981" }} />
            <span>{isZh ? "累计对话轮次" : "Total Spoken Turns"}</span>
          </div>
          <div className="trajectory-stat-value">
            {totalTurns} <span style={{ fontSize: "0.75rem", fontWeight: "normal" }}>{isZh ? "轮" : "turns"}</span>
          </div>
        </div>

        <div className="trajectory-stat-box">
          <div className="trajectory-stat-label">
            <Calendar size={14} style={{ color: "#8b5cf6" }} />
            <span>{isZh ? "活跃天数" : "Active Days"}</span>
          </div>
          <div className="trajectory-stat-value">
            {activeDays} <span style={{ fontSize: "0.75rem", fontWeight: "normal" }}>{isZh ? "天" : "days"}</span>
          </div>
        </div>
      </div>

      {/* Heatmap Grid */}
      <div className="trajectory-grid-wrapper">
        <div className="trajectory-grid">
          {/* Day of Week Labels */}
          <div className="trajectory-day-labels">
            <span>{isZh ? "一" : "Mon"}</span>
            <span>{isZh ? "三" : "Wed"}</span>
            <span>{isZh ? "五" : "Fri"}</span>
            <span>{isZh ? "日" : "Sun"}</span>
          </div>

          {/* Week Columns */}
          {weeks.map((week, wIdx) => (
            <div key={`week-${wIdx}`} className="trajectory-week-col">
              {week.days.map((day) => {
                if (day.isFuture) {
                  return (
                    <div
                      key={day.dateStr}
                      className="trajectory-square"
                      style={{ opacity: 0.2, cursor: "default" }}
                    />
                  );
                }
                return (
                  <div
                    key={day.dateStr}
                    className={`trajectory-square trajectory-level-${day.level}`}
                    onMouseEnter={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      setHoveredCell({
                        date: day.dateStr,
                        info: day.info,
                        x: rect.left + rect.width / 2,
                        y: rect.top,
                      });
                    }}
                    onMouseLeave={() => setHoveredCell(null)}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Hover Tooltip Portal */}
      {hoveredCell && (
        <div
          className="trajectory-tooltip"
          style={{
            position: "fixed",
            left: `${hoveredCell.x}px`,
            top: `${hoveredCell.y}px`,
          }}
        >
          <div style={{ fontWeight: 600 }}>{formatDate(hoveredCell.date, isZh)}</div>
          {hoveredCell.info && hoveredCell.info.duration_seconds > 0 ? (
            <div>
              {formatDuration(hoveredCell.info.duration_seconds, isZh)} ·{" "}
              {hoveredCell.info.turn_count} {isZh ? "轮对话" : "turns"} ({hoveredCell.info.session_count} {isZh ? "次会话" : "sessions"})
            </div>
          ) : (
            <div style={{ opacity: 0.8 }}>{isZh ? "无语音练习记录" : "No practice recorded"}</div>
          )}
        </div>
      )}

      {/* Footer / Legend */}
      <div className="trajectory-footer">
        <div>
          {data?.peak_day && data.peak_day.duration_seconds > 0 && (
            <span>
              {isZh ? "最高单日纪录：" : "Personal Best Day: "}
              <strong>{formatDate(data.peak_day.date, isZh)}</strong> (
              {formatDuration(data.peak_day.duration_seconds, isZh)})
            </span>
          )}
        </div>

        <div className="trajectory-legend">
          <span>{isZh ? "少" : "Less"}</span>
          <div className="trajectory-legend-box trajectory-level-0" />
          <div className="trajectory-legend-box trajectory-level-1" />
          <div className="trajectory-legend-box trajectory-level-2" />
          <div className="trajectory-legend-box trajectory-level-3" />
          <div className="trajectory-legend-box trajectory-level-4" />
          <span>{isZh ? "多" : "More"}</span>
        </div>
      </div>
    </div>
  );
}
