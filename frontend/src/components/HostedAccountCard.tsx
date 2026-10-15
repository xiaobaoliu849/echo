import { useEffect, useState } from "react";
import HostedAccountPanel from "./HostedAccountPanel";
import {
  AUTH_REJECTED_EVENT,
  clearAuthRuntime,
  fetchHostedBalance,
  getAuthRuntimeConfig,
  type HostedExpiringSoon,
} from "../api";
import { formatTime, minutes as formatMinutes } from "../hostedFormat";
import { HOSTED_ADMIN_HASH, HOSTED_BALANCE_EVENT, formatRemainingMinutes, type HostedBalanceDetail } from "../hosted";

/** Account card in the sidebar footer: who is logged in and minutes left. */
export default function HostedAccountCard() {
  const [account, setAccount] = useState("");
  const [remaining, setRemaining] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
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
      <button
        type="button"
        className="hostedAccountOpen"
        onClick={() => setPanelOpen(true)}
        title={`剩余 ${minutes} 分钟 · 我的账户`}
      >
        <span className="hostedAccountText">
          <span className="hostedAccountName">{account || "…"} · 我的账户</span>
          <span className="hostedAccountMinutes">
            剩余 <strong>{minutes}</strong> 分钟
          </span>
          {expiring ? (
            <span
              className="hostedAccountExpiring"
              title={`${formatMinutes(expiring.seconds)} 分钟将于 ${formatTime(expiring.expires_at)} 到期`}
            >
              {formatTime(expiring.expires_at).slice(0, 5)} 到期 {formatMinutes(expiring.seconds)} 分
            </span>
          ) : null}
        </span>
        <strong className="hostedAccountMinutesCompact">{minutes}</strong>
      </button>
      {panelOpen ? <HostedAccountPanel onClose={() => setPanelOpen(false)} /> : null}
      {getAuthRuntimeConfig().isAdmin ? (
        <a className="hostedAccountLogout" href={HOSTED_ADMIN_HASH}>管理</a>
      ) : null}
      <button type="button" className="hostedAccountLogout" onClick={logout}>退出</button>
    </div>
  );
}
