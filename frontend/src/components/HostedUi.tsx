import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { HostedDailyUsage, HostedGrantRecord, HostedLot } from "../api";
import { getHostedLanguage } from "../hosted";
import { formatDate, formatTime, minutes } from "../hostedFormat";
import { createInlineTranslator } from "../i18n";

// Follows the account's interface language (fixed per page load).
const t = createInlineTranslator(getHostedLanguage());

// Building blocks shared by the hosted settings panel and admin console.

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
    return <p className="hostedAdminMuted">{t("这段时间还没有通话。", "No calls in this period.")}</p>;
  }
  return (
    <figure className="hostedAdminChart">
      <div className="hostedAdminChartReadout" aria-live="polite">
        {active ? (
          <>
            <strong>{active.day.slice(5)}</strong>{" "}
            {t(
              `${minutes(active.wall_seconds)} 分钟 · ${active.users} 人 · 扣费 ${minutes(active.billed_seconds)} 分钟`,
              `${minutes(active.wall_seconds)} min · ${active.users} people · billed ${minutes(active.billed_seconds)} min`,
            )}
          </>
        ) : (
          <span className="hostedAdminMuted">
            {t(`峰值 ${minutes(peak)} 分钟/天 · 指向柱子看当天明细`, `Peak ${minutes(peak)} min/day · point at a bar for details`)}
          </span>
        )}
      </div>
      <div className="hostedAdminBars" role="list" onMouseLeave={() => setHover(null)}>
        {daily.map((d, index) => (
          <div
            key={d.day}
            role="listitem"
            tabIndex={0}
            className={hover === index ? "hostedAdminBarSlot is-hover" : "hostedAdminBarSlot"}
            aria-label={t(`${d.day} ${minutes(d.wall_seconds)} 分钟，${d.users} 人`, `${d.day} ${minutes(d.wall_seconds)} min, ${d.users} people`)}
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
          <button type="button" className="hostedAdminClose" onClick={onClose} aria-label={t("关闭", "Close")}>×</button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

const EXPIRY_WARNING_SECONDS = 7 * 86400;

/** Unused minutes per top-up with their expiry, soonest first. */
export function LotList({ lots }: { lots: HostedLot[] }) {
  if (lots.length === 0) {
    return <p className="hostedAdminMuted">{t("没有可用分钟。", "No minutes available.")}</p>;
  }
  const soon = Date.now() / 1000 + EXPIRY_WARNING_SECONDS;
  return (
    <ul className="hostedLotList">
      {lots.map((lot, index) => (
        <li key={`${lot.created_at}-${index}`} className={lot.expires_at !== null && lot.expires_at <= soon ? "is-soon" : ""}>
          <strong className="hostedAdminNum">{minutes(lot.remaining_seconds)} 分钟</strong>
          <span>{lot.expires_at === null ? t("长期有效", "No expiry") : t(`${formatDate(lot.expires_at)} 到期`, `Expires ${formatDate(lot.expires_at)}`)}</span>
          <span className="hostedAdminMuted">
            {t(`${formatTime(lot.created_at)} 充值 ${minutes(lot.granted_seconds)} 分钟`, `${formatTime(lot.created_at)} topped up ${minutes(lot.granted_seconds)} min`)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Top-ups, deductions and expiries, newest first. */
export function GrantList({ grants }: { grants: HostedGrantRecord[] }) {
  return (
    <ul className="hostedAdminGrants">
      {grants.map((grant, index) => (
        <li key={`${grant.created_at}-${index}`}>
          <span className="hostedAdminMuted">{formatTime(grant.created_at)}</span>
          <span className={grant.delta_seconds < 0 ? "hostedAdminLow" : ""}>
            {grant.delta_seconds > 0 ? "+" : ""}{minutes(grant.delta_seconds)} {t("分钟", "min")}
          </span>
          <span>{grant.kind === "expire" ? t("到期作废", "Expired unused") : grant.note || "—"}</span>
        </li>
      ))}
    </ul>
  );
}
