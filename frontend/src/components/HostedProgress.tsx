import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, Clock, Flame, Trophy } from "lucide-react";
import { type HostedDailyUsage, type HostedHistory } from "../api";
import { getHostedLanguage } from "../hosted";
import { fillDays, hostedErrorMessage, minutes, practiceLevel, practiceStreaks } from "../hostedFormat";
import { PROGRESS_DAYS, PROGRESS_KEY, loadProgressHistory, useCachedResource } from "../hostedCache";
import { createInlineTranslator } from "../i18n";

/**
 * Practice footprint for a hosted user: streaks, totals and a calendar
 * heatmap built from the account's own call history (per account, unlike the
 * self-hosted VoiceTrajectoryHeatmap, which reads this machine's sessions).
 */

// 26 whole weeks ending with the current one, starting on a Monday.
const DAYS = PROGRESS_DAYS;

const t = createInlineTranslator(getHostedLanguage());

type Cell = HostedDailyUsage & { future: boolean };

function talkTime(seconds: number): { value: string; unit: string } {
  if (seconds >= 100 * 60) {
    return { value: (Math.trunc((seconds / 3600) * 10) / 10).toFixed(1), unit: t("小时", "h") };
  }
  return { value: minutes(seconds), unit: t("分钟", "min") };
}

function dayLabel(day: string): string {
  const [, month, date] = day.split("-").map(Number);
  return t(`${month}月${date}日`, `${month}/${date}`);
}

export default function HostedProgress() {
  const { data, error: loadError } = useCachedResource(PROGRESS_KEY, loadProgressHistory);
  const history: HostedHistory | null = data ?? null;
  const error = loadError && !history ? hostedErrorMessage(loadError, t("加载失败", "Could not load")) : "";
  const [active, setActive] = useState<Cell | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { weeks, daily } = useMemo(() => {
    // Pad to Monday-aligned weeks: the last column ends on this week's Sunday.
    const today = new Date();
    const mondayOffset = (today.getDay() + 6) % 7;
    const pastDays = DAYS - 7 + mondayOffset + 1;
    const filled = fillDays(history?.daily ?? [], pastDays);
    const cells: Cell[] = filled.map((d) => ({ ...d, future: false }));
    for (let i = 1; i < 7 - mondayOffset; i += 1) {
      const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      cells.push({ day: key, wall_seconds: 0, billed_seconds: 0, users: 0, future: true });
    }
    const columns: Cell[][] = [];
    for (let i = 0; i < cells.length; i += 7) {
      columns.push(cells.slice(i, i + 7));
    }
    return { weeks: columns, daily: filled };
  }, [history]);

  useEffect(() => {
    // Newest week on the right: start scrolled there on narrow screens.
    const el = scrollRef.current;
    if (el) {
      el.scrollLeft = el.scrollWidth;
    }
  }, [weeks]);

  if (error && !history) {
    return <p className="hostedAdminError" role="alert">{error}</p>;
  }

  const { current, longest } = practiceStreaks(daily);
  const total = daily.reduce((sum, d) => sum + d.wall_seconds, 0);
  const activeDays = daily.filter((d) => d.wall_seconds > 0).length;
  const best = daily.reduce<HostedDailyUsage | null>((top, d) => (d.wall_seconds > (top?.wall_seconds ?? 0) ? d : top), null);
  const time = talkTime(total);
  const loading = history === null;
  const show = (value: string) => (loading ? "…" : value);

  return (
    <div className="hostedProgress">
      <div className="hostedProgressStats">
        <div className="hostedProgressStat is-streak">
          <span className="hostedProgressStatLabel"><Flame size={15} aria-hidden="true" />{t("当前连续", "Current streak")}</span>
          <span className="hostedProgressStatValue">{show(String(current))}<small>{t("天", " days")}</small></span>
        </div>
        <div className="hostedProgressStat">
          <span className="hostedProgressStatLabel"><Trophy size={15} aria-hidden="true" />{t("最长连续", "Longest streak")}</span>
          <span className="hostedProgressStatValue">{show(String(longest))}<small>{t("天", " days")}</small></span>
        </div>
        <div className="hostedProgressStat">
          <span className="hostedProgressStatLabel"><Clock size={15} aria-hidden="true" />{t("累计练习", "Total practice")}</span>
          <span className="hostedProgressStatValue">{show(time.value)}<small>{time.unit}</small></span>
        </div>
        <div className="hostedProgressStat">
          <span className="hostedProgressStatLabel"><CalendarDays size={15} aria-hidden="true" />{t("练习天数", "Days practised")}</span>
          <span className="hostedProgressStatValue">{show(String(activeDays))}<small>{t("天", " days")}</small></span>
        </div>
      </div>

      <section className="hostedProgressCard" aria-label={t("近半年练习日历", "Practice calendar, last six months")}>
        <div className="hostedProgressReadout" aria-live="polite">
          {active ? (
            <>
              <strong>{dayLabel(active.day)}</strong>{" "}
              {active.wall_seconds > 0
                ? t(`练了 ${minutes(active.wall_seconds)} 分钟`, `${minutes(active.wall_seconds)} min of practice`)
                : t("没有练习", "No practice")}
            </>
          ) : (
            <span className="hostedAdminMuted">
              {best
                ? t(`近半年 · 单日最多 ${minutes(best.wall_seconds)} 分钟（${dayLabel(best.day)}）`, `Last 6 months · best day ${minutes(best.wall_seconds)} min (${dayLabel(best.day)})`)
                : loading
                  ? t("加载中…", "Loading…")
                  : t("近半年还没有练习，打个电话开始吧。", "No practice in the last six months yet. Start a call!")}
            </span>
          )}
        </div>
        <div className="hostedHeatmapScroll" ref={scrollRef}>
          <div className="hostedHeatmap" onMouseLeave={() => setActive(null)}>
            <div className="hostedHeatmapDays" aria-hidden="true">
              <span />
              <span>{t("一", "Mon")}</span>
              <span />
              <span>{t("三", "Wed")}</span>
              <span />
              <span>{t("五", "Fri")}</span>
              <span />
              <span>{t("日", "Sun")}</span>
            </div>
            {weeks.map((week) => {
              const first = week.find((d) => d.day.endsWith("-01"));
              return (
                <div key={week[0].day} className="hostedHeatmapWeek">
                  <span className="hostedHeatmapMonth" aria-hidden="true">
                    {first ? t(`${Number(first.day.slice(5, 7))}月`, new Date(`${first.day}T00:00`).toLocaleString("en", { month: "short" })) : ""}
                  </span>
                  {week.map((cell) =>
                    cell.future ? (
                      <span key={cell.day} className="hostedHeatmapCell is-future" />
                    ) : (
                      <span
                        key={cell.day}
                        className={`hostedHeatmapCell level-${practiceLevel(cell.wall_seconds)}`}
                        tabIndex={0}
                        aria-label={`${dayLabel(cell.day)} ${minutes(cell.wall_seconds)} ${t("分钟", "min")}`}
                        onMouseEnter={() => setActive(cell)}
                        onFocus={() => setActive(cell)}
                        onBlur={() => setActive(null)}
                      />
                    ),
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <div className="hostedHeatmapLegend" aria-hidden="true">
          <span>{t("少", "Less")}</span>
          {[0, 1, 2, 3, 4].map((level) => <span key={level} className={`hostedHeatmapCell level-${level}`} />)}
          <span>{t("多", "More")}</span>
        </div>
      </section>
    </div>
  );
}
