import { useEffect, useState } from "react";
import HostedSettings, { type SettingsTab } from "./HostedSettings";
import {
  AUTH_REJECTED_EVENT,
  clearAuthRuntime,
  fetchHostedBalance,
  getAuthRuntimeConfig,
  type HostedExpiringSoon,
} from "../api";
import { formatTime, minutes as formatMinutes } from "../hostedFormat";
import { HOSTED_ADMIN_HASH, HOSTED_BALANCE_EVENT, formatRemainingMinutes, getHostedLanguage, type HostedBalanceDetail } from "../hosted";
import { createInlineTranslator } from "../i18n";

/** Account card in the sidebar footer: who is logged in and minutes left. */
export default function HostedAccountCard() {
  const t = createInlineTranslator(getHostedLanguage());
  const [account, setAccount] = useState("");
  const [remaining, setRemaining] = useState<number | null>(null);
  const [settingsTab, setSettingsTab] = useState<SettingsTab | null>(null);
  const [expiring, setExpiring] = useState<HostedExpiringSoon>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      fetchHostedBalance()
        .then((me) => {
          if (!cancelled) {
            setAccount(me.account);
            setRemaining(me.remaining_seconds);
            setExpiring(me.expiring_soon ?? null);
          }
        })
        .catch(() => undefined);
    };
    refresh();
    // Calls push live balances; this catches top-ups made between calls.
    const timer = window.setInterval(refresh, 60_000);
    const onBalance = (event: Event) => {
      setRemaining((event as CustomEvent<HostedBalanceDetail>).detail.remainingSeconds);
    };
    window.addEventListener(HOSTED_BALANCE_EVENT, onBalance);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener(HOSTED_BALANCE_EVENT, onBalance);
    };
  }, []);

  const logout = () => {
    // HostedRoot listens for this and returns to the login screen.
    clearAuthRuntime();
    window.dispatchEvent(new Event(AUTH_REJECTED_EVENT));
  };
  const low = remaining !== null && remaining <= 300;
  const minutes = remaining === null ? "…" : formatRemainingMinutes(remaining);
  return (
    <div className={low ? "hostedAccountCard is-low" : "hostedAccountCard"} role="status">
      {/* Top: who and how much (opens Settings); bottom: actions on their own row. */}
      <button
        type="button"
        className="hostedAccountOpen"
        onClick={() => setSettingsTab("account")}
        title={t(`剩余 ${minutes} 分钟 · 设置`, `${minutes} minutes left · Settings`)}
      >
        <span className="hostedAccountText">
          <span className="hostedAccountName">{account || "…"}</span>
          <span className="hostedAccountMinutes">
            {t("剩余", "")} <strong>{minutes}</strong> {t("分钟", "min left")}
          </span>
          {expiring ? (
            <span
              className="hostedAccountExpiring"
              title={t(`${formatMinutes(expiring.seconds)} 分钟将于 ${formatTime(expiring.expires_at)} 到期`, `${formatMinutes(expiring.seconds)} min expire ${formatTime(expiring.expires_at)}`)}
            >
              {t(`${formatMinutes(expiring.seconds)} 分钟 ${formatTime(expiring.expires_at).slice(0, 5)} 到期`, `${formatMinutes(expiring.seconds)} min expire ${formatTime(expiring.expires_at).slice(0, 5)}`)}
            </span>
          ) : null}
        </span>
        <strong className="hostedAccountMinutesCompact">{minutes}</strong>
      </button>
      <div className="hostedAccountActions">
        <button type="button" onClick={() => setSettingsTab("account")}>{t("设置", "Settings")}</button>
        {getAuthRuntimeConfig().isAdmin ? <a href={HOSTED_ADMIN_HASH}>{t("管理", "Admin")}</a> : null}
        <button type="button" onClick={logout}>{t("退出", "Log out")}</button>
      </div>
      {settingsTab ? <HostedSettings initialTab={settingsTab} onClose={() => setSettingsTab(null)} /> : null}
    </div>
  );
}
