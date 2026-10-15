import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import echoIcon from "../assets/echo-icon.png";
import {
  createHostedAccount,
  fetchHostedAdminOverview,
  fetchHostedAdminUserDetail,
  grantHostedMinutes,
  resetHostedPassword,
  setHostedAccountActive,
  type HostedAdminOverview,
  type HostedAdminUser,
  type HostedAdminUserDetail,
  type HostedDailyUsage,
} from "../api";
import { HOSTED_MODEL_LABELS } from "../hosted";
import { formatErrorMessage } from "../utils/errorFormatting";

/**
 * Operator console for a hosted server: accounts, top-ups and usage.
 * Reached at #/admin by an admin account; everything it calls is
 * admin-gated on the server, so the page itself guards nothing.
 */

const PERIODS = [7, 30, 90] as const;
const LOW_BALANCE_SECONDS = 10 * 60;

type Dialog =
  | { kind: "create" }
  | { kind: "grant"; user: HostedAdminUser }
  | { kind: "password"; user: HostedAdminUser }
  | { kind: "detail"; user: HostedAdminUser };

function minutes(seconds: number): string {
  const value = seconds / 60;
  return value >= 100 || Number.isInteger(value) ? String(Math.round(value)) : value.toFixed(1);
}

function formatTime(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) {
    return "—";
  }
  const date = new Date(epochSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  return `${m}:${String(seconds % 60).padStart(2, "0")}`;
}

function modelLabel(model: string): string {
  return HOSTED_MODEL_LABELS[model] || model || "—";
}

function generatePassword(): string {
  const digits = new Uint32Array(6);
  crypto.getRandomValues(digits);
  return Array.from(digits, (n) => String(n % 10)).join("");
}

/** One entry per calendar day in the period, so quiet days show as gaps. */
function fillDays(daily: HostedDailyUsage[], days: number): HostedDailyUsage[] {
  const byDay = new Map(daily.map((row) => [row.day, row]));
  const out: HostedDailyUsage[] = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i -= 1) {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    out.push(byDay.get(key) || { day: key, wall_seconds: 0, billed_seconds: 0, users: 0 });
  }
  return out;
}

export default function HostedAdmin({ onExit, onLogout }: { onExit: () => void; onLogout: () => void }) {
  const [days, setDays] = useState<number>(30);
  const [overview, setOverview] = useState<HostedAdminOverview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setOverview(await fetchHostedAdminOverview(days));
      setError("");
    } catch (err) {
      setError(formatErrorMessage(err, "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void refresh();
    // Keeps the live-call list honest without a manual refresh.
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!notice) {
      return;
    }
    const timer = window.setTimeout(() => setNotice(""), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const users = useMemo(() => {
    const list = overview?.users ?? [];
    const needle = query.trim().toLowerCase();
    return needle ? list.filter((u) => u.account.toLowerCase().includes(needle)) : list;
  }, [overview, query]);

  const totals = useMemo(() => {
    const list = overview?.users ?? [];
    const customers = list.filter((u) => !u.is_admin);
    return {
      active: customers.filter((u) => u.is_active).length,
      customers: customers.length,
      used: (overview?.daily ?? []).reduce((sum, d) => sum + d.wall_seconds, 0),
      outstanding: customers.reduce((sum, u) => sum + u.remaining_seconds, 0),
    };
  }, [overview]);

  const done = (message: string) => {
    setDialog(null);
    setNotice(message);
    void refresh();
  };

  const toggleActive = async (user: HostedAdminUser) => {
    const next = !user.is_active;
    if (!next && !window.confirm(`停用 ${user.account}？对方会立即被登出，通话中会断开。`)) {
      return;
    }
    try {
      await setHostedAccountActive(user.account, next);
      done(`${user.account} 已${next ? "启用" : "停用"}`);
    } catch (err) {
      setError(formatErrorMessage(err, "操作失败"));
    }
  };

  return (
    <div className="hostedAdmin">
      <header className="hostedAdminHeader">
        <div className="hostedAdminBrand">
          <img src={echoIcon} alt="" />
          <h1>Echo 管理后台</h1>
        </div>
        <div className="hostedAdminHeaderActions">
          <div className="hostedAdminSegmented" role="group" aria-label="统计周期">
            {PERIODS.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={days === value}
                className={days === value ? "is-active" : ""}
                onClick={() => setDays(value)}
              >
                近 {value} 天
              </button>
            ))}
          </div>
          <button type="button" className="hostedAdminGhost" onClick={() => void refresh()} disabled={loading}>
            {loading ? "刷新中…" : "刷新"}
          </button>
          <button type="button" className="hostedAdminGhost" onClick={onExit}>返回练习</button>
          <button type="button" className="hostedAdminGhost" onClick={onLogout}>退出</button>
        </div>
      </header>

      <main className="hostedAdminMain">
        {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
        {notice ? <p className="hostedAdminNotice" role="status">{notice}</p> : null}

        <section className="hostedAdminStats" aria-label="概览">
          <StatTile label="正常用户" value={String(totals.active)} hint={`共 ${totals.customers} 个账号`} />
          <StatTile label="正在通话" value={String(overview?.live.length ?? 0)} hint="每 30 秒刷新" />
          <StatTile label={`近 ${days} 天通话`} value={minutes(totals.used)} unit="分钟" hint="实际通话时长" />
          <StatTile label="用户未用余额" value={minutes(totals.outstanding)} unit="分钟" hint="已售未用" />
        </section>

        {overview && overview.live.length > 0 ? (
          <section className="hostedAdminCard">
            <h2>正在通话</h2>
            <ul className="hostedAdminLive">
              {overview.live.map((call) => (
                <li key={`${call.account}-${call.mode}-${call.elapsed_seconds}`}>
                  <span className="hostedAdminLiveDot" aria-hidden="true" />
                  <strong>{call.account}</strong>
                  <span>{modelLabel(call.model)}</span>
                  <span className="hostedAdminMuted">{call.mode === "direct" ? "直连" : "中转"}</span>
                  <span className="hostedAdminNum">{formatElapsed(call.elapsed_seconds)}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="hostedAdminCard">
          <h2>每日通话分钟</h2>
          <DailyChart daily={fillDays(overview?.daily ?? [], days)} />
        </section>

        <section className="hostedAdminCard">
          <div className="hostedAdminCardHead">
            <h2>账号</h2>
            <input
              type="search"
              className="hostedAdminSearch"
              placeholder="搜索账号"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="搜索账号"
            />
            <button type="button" className="hostedAdminPrimary" onClick={() => setDialog({ kind: "create" })}>
              新建账号
            </button>
          </div>
          <div className="hostedAdminTableWrap">
            <table className="hostedAdminTable">
              <thead>
                <tr>
                  <th>账号</th>
                  <th>状态</th>
                  <th className="hostedAdminNum">剩余(分)</th>
                  <th className="hostedAdminNum">近{days}天用(分)</th>
                  <th>最近使用</th>
                  <th aria-label="操作" />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.account} className={user.is_active ? "" : "is-disabled"}>
                    <td data-label="账号">
                      <button type="button" className="hostedAdminLink" onClick={() => setDialog({ kind: "detail", user })}>
                        {user.account}
                      </button>
                    </td>
                    <td data-label="状态">
                      <StatusBadge user={user} />
                    </td>
                    <td data-label="剩余(分)" className="hostedAdminNum">
                      <span className={!user.is_admin && user.remaining_seconds < LOW_BALANCE_SECONDS ? "hostedAdminLow" : ""}>
                        {minutes(user.remaining_seconds)}
                      </span>
                    </td>
                    <td data-label={`近${days}天用(分)`} className="hostedAdminNum">{minutes(user.used_seconds)}</td>
                    <td data-label="最近使用">{formatTime(user.last_used_at)}</td>
                    <td className="hostedAdminRowActions">
                      <button type="button" onClick={() => setDialog({ kind: "grant", user })}>加时长</button>
                      <button type="button" onClick={() => setDialog({ kind: "password", user })}>重置密码</button>
                      {user.is_admin ? null : (
                        <button type="button" onClick={() => void toggleActive(user)}>
                          {user.is_active ? "停用" : "启用"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {overview && users.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="hostedAdminEmpty">{query ? "没有匹配的账号" : "还没有账号"}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <section className="hostedAdminCard">
          <h2>按模型（近 {days} 天）</h2>
          {overview && overview.by_model.length > 0 ? (
            <table className="hostedAdminTable hostedAdminTableCompact">
              <thead>
                <tr>
                  <th>模型</th>
                  <th>服务商</th>
                  <th className="hostedAdminNum">通话分钟</th>
                </tr>
              </thead>
              <tbody>
                {overview.by_model.map((row) => (
                  <tr key={`${row.provider}/${row.model}`}>
                    <td data-label="模型">{modelLabel(row.model)}</td>
                    <td data-label="服务商">{row.provider}</td>
                    <td data-label="通话分钟" className="hostedAdminNum">{minutes(row.wall_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="hostedAdminMuted">这段时间还没有通话。</p>
          )}
        </section>
      </main>

      {dialog?.kind === "create" ? (
        <CreateDialog onClose={() => setDialog(null)} onDone={done} />
      ) : null}
      {dialog?.kind === "grant" ? (
        <GrantDialog user={dialog.user} onClose={() => setDialog(null)} onDone={done} />
      ) : null}
      {dialog?.kind === "password" ? (
        <PasswordDialog user={dialog.user} onClose={() => setDialog(null)} onDone={done} />
      ) : null}
      {dialog?.kind === "detail" ? (
        <DetailDialog
          user={dialog.user}
          days={days}
          onClose={() => setDialog(null)}
          onGrant={() => setDialog({ kind: "grant", user: dialog.user })}
        />
      ) : null}
    </div>
  );
}

function StatTile({ label, value, unit, hint }: { label: string; value: string; unit?: string; hint: string }) {
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

function StatusBadge({ user }: { user: HostedAdminUser }) {
  if (user.is_admin) {
    return <span className="hostedAdminBadge is-admin">管理员</span>;
  }
  return user.is_active ? (
    <span className="hostedAdminBadge is-ok">● 正常</span>
  ) : (
    <span className="hostedAdminBadge is-off">⏸ 停用</span>
  );
}

function DailyChart({ daily }: { daily: HostedDailyUsage[] }) {
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

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="hostedAdminOverlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="hostedAdminModal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="hostedAdminModalHead">
          <h2>{title}</h2>
          <button type="button" className="hostedAdminClose" onClick={onClose} aria-label="关闭">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function useSubmit(action: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(formatErrorMessage(err, "操作失败"));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, setError, submit };
}

function PasswordField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label>
      <span>密码（至少 6 位）</span>
      <div className="hostedAdminInline">
        <input value={value} onChange={(e) => onChange(e.target.value)} autoComplete="new-password" required minLength={6} />
        <button type="button" className="hostedAdminGhost" onClick={() => onChange(generatePassword())}>随机</button>
      </div>
    </label>
  );
}

function CreateDialog({ onClose, onDone }: { onClose: () => void; onDone: (message: string) => void }) {
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState(generatePassword);
  const [mins, setMins] = useState("60");
  const [note, setNote] = useState("");
  const [created, setCreated] = useState<{ account: string; password: string } | null>(null);
  const { busy, error, submit } = useSubmit(async () => {
    const result = await createHostedAccount({
      account: account.trim(),
      password,
      minutes: Math.max(0, Math.round(Number(mins) || 0)),
      note: note.trim(),
    });
    setCreated({ account: result.account, password });
  });

  if (created) {
    const text = `Echo 英语口语陪练\n账号：${created.account}\n密码：${created.password}`;
    return (
      <Modal title="账号已开通" onClose={() => onDone(`已开通 ${created.account}`)}>
        <p className="hostedAdminMuted">把下面的内容发给用户（密码只显示这一次）：</p>
        <pre className="hostedAdminCredentials">{text}</pre>
        <div className="hostedAdminModalActions">
          <button type="button" className="hostedAdminGhost" onClick={() => void navigator.clipboard?.writeText(text)}>复制</button>
          <button type="button" className="hostedAdminPrimary" onClick={() => onDone(`已开通 ${created.account}`)}>完成</button>
        </div>
      </Modal>
    );
  }
  return (
    <Modal title="新建账号" onClose={onClose}>
      <form className="hostedAdminForm" onSubmit={submit}>
        <label>
          <span>账号（如门牌号 1203，用户用它登录）</span>
          <input value={account} onChange={(e) => setAccount(e.target.value)} required maxLength={120} autoFocus />
        </label>
        <PasswordField value={password} onChange={setPassword} />
        <label>
          <span>赠送 / 首充分钟</span>
          <input type="number" min={0} max={100000} value={mins} onChange={(e) => setMins(e.target.value)} />
        </label>
        <label>
          <span>备注（可选）</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="例如 试用 / 微信转账 ¥49" />
        </label>
        {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
        <div className="hostedAdminModalActions">
          <button type="button" className="hostedAdminGhost" onClick={onClose}>取消</button>
          <button type="submit" className="hostedAdminPrimary" disabled={busy}>{busy ? "开通中…" : "开通"}</button>
        </div>
      </form>
    </Modal>
  );
}

const GRANT_PRESETS = [60, 300, 600, 1200];

function GrantDialog({
  user,
  onClose,
  onDone,
}: {
  user: HostedAdminUser;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [mins, setMins] = useState("300");
  const [note, setNote] = useState("");
  const amount = Math.round(Number(mins) || 0);
  const { busy, error, setError, submit } = useSubmit(async () => {
    if (amount === 0) {
      setError("请输入分钟数");
      return;
    }
    if (amount < 0 && !window.confirm(`从 ${user.account} 扣减 ${-amount} 分钟？`)) {
      return;
    }
    const result = await grantHostedMinutes(user.account, amount, note.trim());
    onDone(`${user.account} ${amount > 0 ? "已加" : "已扣"} ${Math.abs(amount)} 分钟，现剩 ${minutes(result.remaining_seconds)} 分钟`);
  });
  return (
    <Modal title={`给 ${user.account} 加时长`} onClose={onClose}>
      <form className="hostedAdminForm" onSubmit={submit}>
        <p className="hostedAdminMuted">当前剩余 {minutes(user.remaining_seconds)} 分钟。负数表示扣减（纠错用）。</p>
        <div className="hostedAdminChips">
          {GRANT_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={amount === preset ? "is-active" : ""}
              onClick={() => setMins(String(preset))}
            >
              +{preset}
            </button>
          ))}
        </div>
        <label>
          <span>分钟数</span>
          <input type="number" min={-100000} max={100000} value={mins} onChange={(e) => setMins(e.target.value)} autoFocus />
        </label>
        <label>
          <span>备注</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="例如 10月 微信转账 ¥49" />
        </label>
        {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
        <div className="hostedAdminModalActions">
          <button type="button" className="hostedAdminGhost" onClick={onClose}>取消</button>
          <button type="submit" className="hostedAdminPrimary" disabled={busy}>
            {busy ? "提交中…" : amount < 0 ? `扣减 ${-amount} 分钟` : `加 ${amount} 分钟`}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function PasswordDialog({
  user,
  onClose,
  onDone,
}: {
  user: HostedAdminUser;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [password, setPassword] = useState(generatePassword);
  const [saved, setSaved] = useState(false);
  const { busy, error, submit } = useSubmit(async () => {
    await resetHostedPassword(user.account, password);
    setSaved(true);
  });
  if (saved) {
    const text = `Echo 账号：${user.account}\n新密码：${password}`;
    return (
      <Modal title="密码已重置" onClose={() => onDone(`${user.account} 密码已重置`)}>
        <p className="hostedAdminMuted">
          {user.is_admin ? "你自己的登录也已失效，关闭后需要用新密码重新登录。" : "对方已登录的设备需要用新密码重新登录。"}
        </p>
        <pre className="hostedAdminCredentials">{text}</pre>
        <div className="hostedAdminModalActions">
          <button type="button" className="hostedAdminGhost" onClick={() => void navigator.clipboard?.writeText(text)}>复制</button>
          <button type="button" className="hostedAdminPrimary" onClick={() => onDone(`${user.account} 密码已重置`)}>完成</button>
        </div>
      </Modal>
    );
  }
  return (
    <Modal title={`重置 ${user.account} 的密码`} onClose={onClose}>
      <form className="hostedAdminForm" onSubmit={submit}>
        <PasswordField value={password} onChange={setPassword} />
        {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
        <div className="hostedAdminModalActions">
          <button type="button" className="hostedAdminGhost" onClick={onClose}>取消</button>
          <button type="submit" className="hostedAdminPrimary" disabled={busy}>{busy ? "提交中…" : "重置"}</button>
        </div>
      </form>
    </Modal>
  );
}

function DetailDialog({
  user,
  days,
  onClose,
  onGrant,
}: {
  user: HostedAdminUser;
  days: number;
  onClose: () => void;
  onGrant: () => void;
}) {
  const [detail, setDetail] = useState<HostedAdminUserDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    fetchHostedAdminUserDetail(user.account, days)
      .then((value) => !cancelled && setDetail(value))
      .catch((err) => !cancelled && setError(formatErrorMessage(err, "加载失败")));
    return () => {
      cancelled = true;
    };
  }, [user.account, days]);
  const used = (detail?.daily ?? []).reduce((sum, d) => sum + d.wall_seconds, 0);
  return (
    <Modal title={`账号 ${user.account}`} onClose={onClose}>
      {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
      <div className="hostedAdminDetailStats">
        <StatTile label="剩余" value={minutes(detail?.remaining_seconds ?? user.remaining_seconds)} unit="分钟" hint={user.is_active ? "正常" : "已停用"} />
        <StatTile label={`近 ${days} 天通话`} value={minutes(used)} unit="分钟" hint={`最近 ${formatTime(user.last_used_at)}`} />
      </div>
      <h3>每日通话</h3>
      {detail ? <DailyChart daily={fillDays(detail.daily, days)} /> : <p className="hostedAdminMuted">加载中…</p>}
      <h3>充值记录</h3>
      {detail && detail.grants.length > 0 ? (
        <ul className="hostedAdminGrants">
          {detail.grants.map((grant, index) => (
            <li key={`${grant.created_at}-${index}`}>
              <span className="hostedAdminMuted">{formatTime(grant.created_at)}</span>
              <span className={grant.delta_seconds < 0 ? "hostedAdminLow" : ""}>
                {grant.delta_seconds > 0 ? "+" : ""}{minutes(grant.delta_seconds)} 分钟
              </span>
              <span>{grant.note || "—"}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="hostedAdminMuted">{detail ? "还没有充值记录。" : ""}</p>
      )}
      <div className="hostedAdminModalActions">
        <button type="button" className="hostedAdminGhost" onClick={onClose}>关闭</button>
        <button type="button" className="hostedAdminPrimary" onClick={onGrant}>加时长</button>
      </div>
    </Modal>
  );
}
