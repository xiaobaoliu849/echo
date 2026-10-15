import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { HostedDailyUsage } from "../api";
import { minutes } from "../hostedFormat";

// Building blocks shared by the hosted "My account" panel and admin console.

export function StatTile({ label, value, unit, hint }: { label: string; value: string; unit?: string; hint: string }) {
  return (
    <div className="hostedAdminStat">
      <span className="hostedAdminStatLabel">{label}</span>
      <span className="hostedAdminStatValue">
        {value}
        {unit ? <small>{unit}</small> : null}
      </span>
      <span className="hostedAdminStatHint">{hint}</span>
    </div>
  );
}

export function DailyChart({ daily }: { daily: HostedDailyUsage[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const peak = Math.max(60, ...daily.map((d) => d.wall_seconds));
  const total = daily.reduce((sum, d) => sum + d.wall_seconds, 0);
  const active = hover === null ? null : daily[hover];
  if (total === 0) {
    return <p className="hostedAdminMuted">这段时间还没有通话。</p>;
  }
  return (
    <figure className="hostedAdminChart">
      <div className="hostedAdminChartReadout" aria-live="polite">
        {active ? (
          <>
            <strong>{active.day.slice(5)}</strong> {minutes(active.wall_seconds)} 分钟 · {active.users} 人 · 扣费 {minutes(active.billed_seconds)} 分钟
          </>
        ) : (
          <span className="hostedAdminMuted">峰值 {minutes(peak)} 分钟/天 · 指向柱子看当天明细</span>
        )}
      </div>
      <div className="hostedAdminBars" role="list" onMouseLeave={() => setHover(null)}>
        {daily.map((d, index) => (
          <div
            key={d.day}
            role="listitem"
            tabIndex={0}
            className={hover === index ? "hostedAdminBarSlot is-hover" : "hostedAdminBarSlot"}
            aria-label={`${d.day} ${minutes(d.wall_seconds)} 分钟，${d.users} 人`}
            onMouseEnter={() => setHover(index)}
            onFocus={() => setHover(index)}
            onBlur={() => setHover(null)}
          >
            <span
              className="hostedAdminBar"
              style={{ height: d.wall_seconds ? `max(2px, ${(d.wall_seconds / peak) * 100}%)` : 0 }}
            />
          </div>
        ))}
      </div>
      <figcaption className="hostedAdminChartAxis">
        <span>{daily[0]?.day.slice(5)}</span>
        <span>{daily[daily.length - 1]?.day.slice(5)}</span>
      </figcaption>
    </figure>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Portalled so a transformed or clipped ancestor (the sidebar) cannot trap it.
  return createPortal(
    <div className="hostedAdminOverlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={wide ? "hostedAdminModal is-wide" : "hostedAdminModal"} role="dialog" aria-modal="true" aria-label={title}>
        <div className="hostedAdminModalHead">
          <h2>{title}</h2>
          <button type="button" className="hostedAdminClose" onClick={onClose} aria-label="关闭">×</button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
