import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from "react";
import echoIcon from "../assets/echo-icon.png";
import {
  ApiRequestError,
  createHostedAccount,
  fetchHostedAdminOverview,
  fetchHostedAdminUserDetail,
  fetchHostedRenewal,
  grantHostedMinutes,
  resetHostedPassword,
  saveHostedRenewal,
  setHostedAccountMemory,
  fetchHostedRegistration,
  saveHostedRegistration,
  setHostedAccountActive,
  type HostedAdminOverview,
  type HostedAdminUser,
  type HostedAdminUserDetail,
} from "../api";
import {
  HOSTED_PACKAGES,
  defaultRenewalText,
  fillDays,
  formatDate,
  formatElapsed,
  formatTime,
  minutes,
  modelLabel,
  packageNote,
  useSubmit,
} from "../hostedFormat";
import { formatErrorMessage } from "../utils/errorFormatting";
import { DailyChart, GrantList, LotList, Modal, StatTile } from "./HostedUi";

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

function memoryLabel(until: number | null): string {
  return until && until * 1000 > Date.now() ? `${formatDate(until).slice(5)} 到期` : "—";
}

function generatePassword(): string {
  const digits = new Uint32Array(6);
  crypto.getRandomValues(digits);
  return Array.from(digits, (n) => String(n % 10)).join("");
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
      if (err instanceof ApiRequestError && err.status === 403) {
        // Logged in, but not as the operator: back to the practice page.
        window.alert("当前登录的不是管理员账号，已返回练习页面。");
        onExit();
        return;
      }
      setError(formatErrorMessage(err, "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [days, onExit]);

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
        {overview && !overview.memory_configured ? (
          <p className="hostedAdminNotice" role="status">
            服务器还没有配置 EverOS 密钥，AI 记忆暂时不能用（开通了也不会生效）。
          </p>
        ) : null}

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
                  <th>来源</th>
                  <th className="hostedAdminNum">剩余(分)</th>
                  <th className="hostedAdminNum">近{days}天用(分)</th>
                  <th>最近使用</th>
                  <th>AI 记忆</th>
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
                    <td data-label="来源" className="hostedAdminMuted">{user.signup === "self" ? "自助注册" : "开户"}</td>
                    <td data-label="剩余(分)" className="hostedAdminNum">
                      <span className={!user.is_admin && user.remaining_seconds < LOW_BALANCE_SECONDS ? "hostedAdminLow" : ""}>
                        {minutes(user.remaining_seconds)}
                      </span>
                    </td>
                    <td data-label={`近${days}天用(分)`} className="hostedAdminNum">{minutes(user.used_seconds)}</td>
                    <td data-label="最近使用">{formatTime(user.last_used_at)}</td>
                    <td data-label="AI 记忆">{memoryLabel(user.memory_until)}</td>
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
                    <td colSpan={8} className="hostedAdminEmpty">{query ? "没有匹配的账号" : "还没有账号"}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <RegistrationSettings onSaved={(message) => setNotice(message)} />

        <RenewalSettings onSaved={() => setNotice("续费信息已保存，用户在「设置 → 账户与时长」里能看到")} />

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

const QR_MAX_EDGE = 640;

/** Downscale an uploaded payment QR so it travels comfortably as JSON. */
function readQrImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, QR_MAX_EDGE / Math.max(image.width, image.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(image.width * scale);
      canvas.height = Math.round(image.height * scale);
      const context = canvas.getContext("2d");
      if (!context) {
        reject(new Error("无法读取图片"));
        return;
      }
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL("image/png"));
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("无法读取图片，请换一张 PNG 或 JPG"));
    };
    image.src = url;
  });
}

/** Easy to read aloud and type on a phone: no 0/O or 1/I. */
function generateInviteCode(): string {
  const alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
  const values = new Uint32Array(6);
  crypto.getRandomValues(values);
  return Array.from(values, (n) => alphabet[n % alphabet.length]).join("");
}

/** Self-service sign-up: the invite code neighbours type to create an account. */
function RegistrationSettings({ onSaved }: { onSaved: (message: string) => void }) {
  const [enabled, setEnabled] = useState(false);
  const [code, setCode] = useState("");
  const [loaded, setLoaded] = useState(false);
  const { busy, error, submit } = useSubmit(async () => {
    const next = await saveHostedRegistration({ enabled, code: code.trim().toUpperCase() });
    setCode(next.code);
    onSaved(next.enabled ? `已开放注册，邀请码 ${next.code}（发到小区群即可）` : "已关闭自助注册");
  });

  useEffect(() => {
    fetchHostedRegistration()
      .then((value) => {
        setEnabled(value.enabled);
        setCode(value.code);
      })
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, []);

  return (
    <section className="hostedAdminCard">
      <h2>新用户注册</h2>
      <p className="hostedAdminMuted">
        开放后，邻居在登录页填邀请码就能自己注册，并自动获得新人体验 30 分钟（30 天有效）。邀请码只发在小区群里；
        如果外传了，换一个新的即可，已注册的账号不受影响。
      </p>
      <form className="hostedAdminForm hostedAdminRenewal" onSubmit={submit}>
        <label className="hostedAdminCheck">
          <input type="checkbox" checked={enabled} disabled={!loaded} onChange={(e) => setEnabled(e.target.checked)} />
          <span>开放自助注册</span>
        </label>
        <div className="hostedAdminInline">
          <label>
            <span>邀请码（4–32 位）</span>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              maxLength={32}
              disabled={!loaded}
              placeholder="例如 7KQ2MX"
            />
          </label>
          <button type="button" className="hostedAdminGhost hostedAdminAlignEnd" onClick={() => setCode(generateInviteCode())} disabled={!loaded}>
            随机生成
          </button>
        </div>
        {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
        <div className="hostedAdminModalActions">
          <button type="submit" className="hostedAdminPrimary" disabled={busy || !loaded}>{busy ? "保存中…" : "保存"}</button>
        </div>
      </form>
    </section>
  );
}

function RenewalSettings({ onSaved }: { onSaved: () => void }) {
  const [text, setText] = useState("");
  const [qr, setQr] = useState("");
  const [loaded, setLoaded] = useState(false);
  const { busy, error, setError, submit } = useSubmit(async () => {
    await saveHostedRenewal({ text: text.trim(), qr });
    onSaved();
  });

  useEffect(() => {
    fetchHostedRenewal()
      .then((value) => {
        setText(value.text);
        setQr(value.qr);
      })
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, []);

  const pickQr = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    try {
      setQr(await readQrImage(file));
      setError("");
    } catch (err) {
      setError(formatErrorMessage(err, "无法读取图片"));
    }
  };

  return (
    <section className="hostedAdminCard">
      <h2>续费信息</h2>
      <p className="hostedAdminMuted">显示在每个用户的「设置 → 账户与时长」里。充值备注也会显示给用户本人。</p>
      <form className="hostedAdminForm hostedAdminRenewal" onSubmit={submit}>
        <label>
          <span>说明（价格、微信号、转账后怎么通知你…）</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={1000}
            rows={8}
            disabled={!loaded}
            placeholder={defaultRenewalText()}
          />
        </label>
        <div>
          <button type="button" className="hostedAdminGhost" onClick={() => setText(defaultRenewalText())} disabled={!loaded}>
            填入标准价目
          </button>
        </div>
        <div className="hostedAdminQrRow">
          {qr ? <img src={qr} alt="收款码预览" className="hostedPanelQr" /> : <span className="hostedAdminQrEmpty">未设置收款码</span>}
          <div className="hostedAdminQrActions">
            <label className="hostedAdminGhost hostedAdminFileButton">
              {qr ? "更换收款码" : "上传收款码"}
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => void pickQr(e)} />
            </label>
            {qr ? (
              <button type="button" className="hostedAdminGhost" onClick={() => setQr("")}>移除</button>
            ) : null}
          </div>
        </div>
        {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
        <div className="hostedAdminModalActions">
          <button type="submit" className="hostedAdminPrimary" disabled={busy || !loaded}>{busy ? "保存中…" : "保存"}</button>
        </div>
      </form>
    </section>
  );
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

const VALIDITY_CHOICES = [30, 90];

type PackageState = { id: string; mins: string; validDays: number; note: string; memoryDays: number };

function packageState(id: string): PackageState {
  const pkg = HOSTED_PACKAGES.find((item) => item.id === id) ?? HOSTED_PACKAGES[0];
  return { id: pkg.id, mins: String(pkg.minutes), validDays: pkg.validDays, note: packageNote(pkg), memoryDays: pkg.memoryDays };
}

/** Package presets plus the minutes / validity / note they fill in. */
function PackageFields({
  value,
  onChange,
  allowNegative = false,
}: {
  value: PackageState;
  onChange: (next: PackageState) => void;
  allowNegative?: boolean;
}) {
  // Two presets can share minutes and validity (monthly card, first month), so match by id too.
  const active = HOSTED_PACKAGES.find(
    (pkg) => pkg.id === value.id && String(pkg.minutes) === value.mins && pkg.validDays === value.validDays,
  );
  return (
    <>
      <div className="hostedAdminPackages" role="group" aria-label="套餐">
        {HOSTED_PACKAGES.map((pkg) => (
          <button
            key={pkg.id}
            type="button"
            className={active?.id === pkg.id ? "is-active" : ""}
            onClick={() => onChange(packageState(pkg.id))}
          >
            <strong>{pkg.name}</strong>
            <span>{pkg.minutes} 分钟 · {pkg.validDays} 天</span>
            <span>{pkg.price > 0 ? `¥${pkg.price}` : "免费"}{pkg.memoryDays ? " · 含 AI 记忆" : ""}</span>
            {pkg.firstTimeOnly ? <span className="hostedAdminPackageNote">新用户限一次</span> : null}
          </button>
        ))}
      </div>
      <div className="hostedAdminInline">
        <label>
          <span>分钟数{allowNegative ? "（负数=扣减）" : ""}</span>
          <input
            type="number"
            min={allowNegative ? -100000 : 0}
            max={100000}
            value={value.mins}
            onChange={(e) => onChange({ ...value, mins: e.target.value })}
          />
        </label>
        <label>
          <span>有效期</span>
          <select value={value.validDays} onChange={(e) => onChange({ ...value, validDays: Number(e.target.value) })}>
            {VALIDITY_CHOICES.map((days) => (
              <option key={days} value={days}>{days} 天</option>
            ))}
          </select>
        </label>
      </div>
      <label className="hostedAdminCheck">
        <input
          type="checkbox"
          checked={value.memoryDays > 0}
          onChange={(e) => onChange({ ...value, memoryDays: e.target.checked ? 30 : 0 })}
        />
        <span>同时开通 AI 记忆 30 天（月卡自带）</span>
      </label>
      <label>
        <span>备注（用户能看到）</span>
        <input
          value={value.note}
          onChange={(e) => onChange({ ...value, note: e.target.value })}
          maxLength={200}
          placeholder="例如 月卡 ¥99"
        />
      </label>
    </>
  );
}

function CreateDialog({ onClose, onDone }: { onClose: () => void; onDone: (message: string) => void }) {
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState(generatePassword);
  const [pkg, setPkg] = useState<PackageState>(() => packageState("trial"));
  const [created, setCreated] = useState<{ account: string; password: string } | null>(null);
  const { busy, error, submit } = useSubmit(async () => {
    const result = await createHostedAccount({
      account: account.trim(),
      password,
      minutes: Math.max(0, Math.round(Number(pkg.mins) || 0)),
      note: pkg.note.trim(),
      valid_days: pkg.validDays,
      memory_days: pkg.memoryDays,
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
        <PackageFields value={pkg} onChange={setPkg} />
        {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
        <div className="hostedAdminModalActions">
          <button type="button" className="hostedAdminGhost" onClick={onClose}>取消</button>
          <button type="submit" className="hostedAdminPrimary" disabled={busy}>{busy ? "开通中…" : "开通"}</button>
        </div>
      </form>
    </Modal>
  );
}

function GrantDialog({
  user,
  onClose,
  onDone,
}: {
  user: HostedAdminUser;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [pkg, setPkg] = useState<PackageState>(() => packageState("monthly"));
  const amount = Math.round(Number(pkg.mins) || 0);
  const { busy, error, setError, submit } = useSubmit(async () => {
    if (amount === 0) {
      setError("请输入分钟数");
      return;
    }
    if (amount < 0 && !window.confirm(`从 ${user.account} 扣减 ${-amount} 分钟？`)) {
      return;
    }
    const result = await grantHostedMinutes(user.account, amount, pkg.note.trim(), pkg.validDays, pkg.memoryDays);
    onDone(`${user.account} ${amount > 0 ? "已加" : "已扣"} ${Math.abs(amount)} 分钟，现剩 ${minutes(result.remaining_seconds)} 分钟`);
  });
  return (
    <Modal title={`给 ${user.account} 加时长`} onClose={onClose}>
      <form className="hostedAdminForm" onSubmit={submit}>
        <p className="hostedAdminMuted">当前剩余 {minutes(user.remaining_seconds)} 分钟。选套餐即可，通话时先扣最早到期的分钟。</p>
        <PackageFields value={pkg} onChange={setPkg} allowNegative />
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
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let cancelled = false;
    fetchHostedAdminUserDetail(user.account, days)
      .then((value) => !cancelled && setDetail(value))
      .catch((err) => !cancelled && setError(formatErrorMessage(err, "加载失败")));
    return () => {
      cancelled = true;
    };
  }, [user.account, days, reload]);
  const changeMemory = async (memoryDays: number) => {
    if (memoryDays === 0 && !window.confirm(`取消 ${user.account} 的 AI 记忆？已记住的内容会保留，续上后还能用。`)) {
      return;
    }
    setMemoryBusy(true);
    try {
      await setHostedAccountMemory(user.account, memoryDays);
      setReload((n) => n + 1);
    } catch (err) {
      setError(formatErrorMessage(err, "操作失败"));
    } finally {
      setMemoryBusy(false);
    }
  };
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
      <h3>可用分钟（有效期）</h3>
      {detail ? <LotList lots={detail.lots} /> : null}
      <h3>AI 记忆</h3>
      {detail ? (
        <div className="hostedAdminMemoryRow">
          <span>
            {detail.memory.member ? `${formatDate(detail.memory.memory_until ?? 0)} 到期` : "未开通"}
            {detail.memory.opted_out ? "（用户自己关闭了）" : ""}
          </span>
          <button type="button" className="hostedAdminGhost" disabled={memoryBusy} onClick={() => void changeMemory(30)}>
            {detail.memory.member ? "续 30 天" : "开通 30 天"}
          </button>
          {detail.memory.member ? (
            <button type="button" className="hostedAdminGhost" disabled={memoryBusy} onClick={() => void changeMemory(0)}>
              取消
            </button>
          ) : null}
        </div>
      ) : null}
      <h3>充值记录</h3>
      {detail && detail.grants.length > 0 ? (
        <GrantList grants={detail.grants} />
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
