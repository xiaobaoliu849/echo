import { useEffect, useState } from "react";
import {
  changeAuthPassword,
  fetchHostedHistory,
  fetchHostedRenewal,
  type HostedHistory,
  type HostedRenewal,
} from "../api";
import { fillDays, formatElapsed, formatTime, minutes, modelLabel, useSubmit } from "../hostedFormat";
import { formatErrorMessage } from "../utils/errorFormatting";
import { DailyChart, GrantList, LotList, Modal, StatTile } from "./HostedUi";

/** "My account" for a hosted user: balance, how to renew, usage, password. */

const HISTORY_DAYS = 30;
const CALLS_SHOWN = 10;
const LOW_BALANCE_SECONDS = 10 * 60;

export default function HostedAccountPanel({ onClose }: { onClose: () => void }) {
  const [history, setHistory] = useState<HostedHistory | null>(null);
  const [renewal, setRenewal] = useState<HostedRenewal | null>(null);
  const [error, setError] = useState("");
  const [showAllCalls, setShowAllCalls] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchHostedHistory(HISTORY_DAYS), fetchHostedRenewal()])
      .then(([nextHistory, nextRenewal]) => {
        if (!cancelled) {
          setHistory(nextHistory);
          setRenewal(nextRenewal);
        }
      })
      .catch((err) => !cancelled && setError(formatErrorMessage(err, "加载失败")));
    return () => {
      cancelled = true;
    };
  }, []);

  const remaining = history?.remaining_seconds ?? null;
  const used = (history?.daily ?? []).reduce((sum, d) => sum + d.wall_seconds, 0);
  const calls = history?.calls ?? [];
  const shownCalls = showAllCalls ? calls : calls.slice(0, CALLS_SHOWN);

  return (
    <Modal title="我的账户" onClose={onClose} wide>
      {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}

      <div className="hostedPanelBalance">
        <span className="hostedAdminMuted">账号 {history?.account ?? "…"}</span>
        <span className={remaining !== null && remaining < LOW_BALANCE_SECONDS ? "hostedPanelMinutes is-low" : "hostedPanelMinutes"}>
          剩余 <strong>{remaining === null ? "…" : Math.floor(remaining / 60)}</strong> 分钟
        </span>
      </div>

      <section className="hostedPanelSection">
        <h3>有效期</h3>
        <p className="hostedAdminMuted hostedPanelHint">每次充值的分钟各自计算有效期，通话时先扣最早到期的。</p>
        {history ? <LotList lots={history.lots} /> : <p className="hostedAdminMuted">加载中…</p>}
      </section>

      <section className="hostedPanelSection">
        <h3>续费</h3>
        <RenewalBlock renewal={renewal} />
      </section>

      <section className="hostedPanelSection">
        <h3>近 {HISTORY_DAYS} 天</h3>
        <div className="hostedAdminDetailStats">
          <StatTile label="通话次数" value={String(calls.length)} unit="次" hint="同一模型间隔 90 秒内算一次" />
          <StatTile label="通话时长" value={minutes(used)} unit="分钟" hint="实际通话时长" />
        </div>
        {history ? <DailyChart daily={fillDays(history.daily, HISTORY_DAYS)} /> : null}
      </section>

      <section className="hostedPanelSection">
        <h3>通话记录</h3>
        {calls.length === 0 ? (
          <p className="hostedAdminMuted">{history ? "还没有通话。" : "加载中…"}</p>
        ) : (
          <ul className="hostedPanelList">
            {shownCalls.map((call) => (
              <li key={`${call.started_at}-${call.model}`}>
                <span className="hostedAdminMuted">{formatTime(call.started_at)}</span>
                <span>{modelLabel(call.model)}</span>
                <span className="hostedAdminNum">{formatElapsed(call.wall_seconds)}</span>
                <span className="hostedAdminNum hostedAdminMuted">
                  {call.billed_seconds === call.wall_seconds ? "" : `扣 ${minutes(call.billed_seconds)} 分`}
                </span>
              </li>
            ))}
          </ul>
        )}
        {calls.length > CALLS_SHOWN && !showAllCalls ? (
          <button type="button" className="hostedAdminGhost hostedPanelMore" onClick={() => setShowAllCalls(true)}>
            显示全部 {calls.length} 次
          </button>
        ) : null}
      </section>

      <section className="hostedPanelSection">
        <h3>充值记录</h3>
        {history && history.grants.length > 0 ? (
          <GrantList grants={history.grants} />
        ) : (
          <p className="hostedAdminMuted">{history ? "还没有充值记录。" : ""}</p>
        )}
      </section>

      <section className="hostedPanelSection">
        <h3>修改密码</h3>
        <ChangePasswordForm />
      </section>
    </Modal>
  );
}

function RenewalBlock({ renewal }: { renewal: HostedRenewal | null }) {
  if (!renewal) {
    return <p className="hostedAdminMuted">加载中…</p>;
  }
  if (!renewal.text && !renewal.qr) {
    return <p className="hostedAdminMuted">续费请联系管理员。</p>;
  }
  return (
    <div className="hostedPanelRenewal">
      {renewal.qr ? <img src={renewal.qr} alt="付款二维码" className="hostedPanelQr" /> : null}
      {renewal.text ? <p className="hostedPanelRenewalText">{renewal.text}</p> : null}
    </div>
  );
}

function ChangePasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);
  const { busy, error, setError, submit } = useSubmit(async () => {
    if (next.length < 6) {
      setError("新密码至少 6 位");
      return;
    }
    if (next !== confirm) {
      setError("两次输入的新密码不一样");
      return;
    }
    try {
      await changeAuthPassword(current, next);
    } catch (err) {
      const message = formatErrorMessage(err, "修改失败");
      throw new Error(/incorrect|current/i.test(message) ? "当前密码不对" : message, { cause: err });
    }
    setDone(true);
    setCurrent("");
    setNext("");
    setConfirm("");
  });
  return (
    <form className="hostedAdminForm" onSubmit={submit}>
      <label>
        <span>当前密码</span>
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
      </label>
      <label>
        <span>新密码（至少 6 位）</span>
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
      </label>
      <label>
        <span>再输一次新密码</span>
        <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
      </label>
      {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
      {done ? <p className="hostedAdminNotice" role="status">密码已修改。其他设备需要用新密码重新登录。</p> : null}
      <div className="hostedAdminModalActions">
        <button type="submit" className="hostedAdminPrimary" disabled={busy}>{busy ? "提交中…" : "修改密码"}</button>
      </div>
    </form>
  );
}
