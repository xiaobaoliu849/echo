import { useEffect, useState } from "react";
import { AUTH_REJECTED_EVENT, clearAuthRuntime, fetchHostedBalance } from "../api";
import { HOSTED_BALANCE_EVENT, formatRemainingMinutes, type HostedBalanceDetail } from "../hosted";

/** Account card in the sidebar footer: who is logged in and minutes left. */
export default function HostedAccountCard() {
  const [account, setAccount] = useState("");
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      fetchHostedBalance()
        .then((me) => {
          if (!cancelled) {
            setAccount(me.account);
            setRemaining(me.remaining_seconds);
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
    <div className={low ? "hostedAccountCard is-low" : "hostedAccountCard"} role="status" title={`剩余 ${minutes} 分钟`}>
      <div className="hostedAccountText">
        <span className="hostedAccountName">{account || "…"}</span>
        <span className="hostedAccountMinutes">
          剩余 <strong>{minutes}</strong> 分钟
        </span>
      </div>
      <strong className="hostedAccountMinutesCompact">{minutes}</strong>
      <button type="button" className="hostedAccountLogout" onClick={logout}>退出</button>
    </div>
  );
}
