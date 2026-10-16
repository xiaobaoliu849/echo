import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  Brain,
  Flame,
  GraduationCap,
  Languages,
  MessagesSquare,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import echoIcon from "../assets/echo-icon.png";
import {
  AUTH_REJECTED_EVENT,
  changeAuthPassword,
  clearAuthRuntime,
  clearHostedMemory,
  fetchHostedMemory,
  fetchHostedPrefs,
  fetchHostedRenewal,
  saveHostedPrefs,
  setHostedMemoryEnabled,
  type HostedHistory,
  type HostedMemory,
  type HostedPrefs,
  type HostedRenewal,
} from "../api";
import { getHostedLanguage } from "../hosted";
import EvermindBadge from "./EvermindBadge";
import {
  USER_PACKAGES,
  formatDate,
  formatElapsed,
  formatTime,
  memoryEpochSeconds,
  memoryFacts,
  memoryLabel,
  minutes,
  modelLabel,
  useSubmit,
  hostedErrorMessage,
} from "../hostedFormat";
import { PREFS_KEY, PROGRESS_KEY, loadCached, loadProgressHistory, useCachedResource } from "../hostedCache";
import { applyHostedPrefs } from "../hostedPrefs";
import { createInlineTranslator } from "../i18n";
import HostedProgress from "./HostedProgress";
import UpdateCard from "./UpdateCard";
import { GrantList, LotList } from "./HostedUi";

/**
 * Settings for a hosted user: everything they can change about their own
 * account, and nothing about the operator's server (keys, providers).
 */

export type SettingsTab = "progress" | "account" | "learning" | "memory" | "general" | "security";

const HISTORY_DAYS = 30;
const CALLS_SHOWN = 10;
const LOW_BALANCE_SECONDS = 10 * 60;
const EPISODES_SHOWN = 6;

// The server sends at most this many episodes (hosted_memory.overview).
const EPISODE_PAGE = 30;

// Cache keys (scoped per account by hostedCache).
const RENEWAL_KEY = "renewal";
const MEMORY_KEY = "memory";

/**
 * Start the cheap tabs' requests at once, so switching tabs rarely waits.
 * Memory is left out: it costs two EverOS round trips abroad, so it loads
 * only when its tab is pointed at or opened.
 */
function prefetchSettings() {
  const loads: [string, () => Promise<unknown>][] = [
    [PROGRESS_KEY, loadProgressHistory],
    [RENEWAL_KEY, fetchHostedRenewal],
    [PREFS_KEY, fetchHostedPrefs],
  ];
  for (const [key, load] of loads) {
    loadCached(key, load).catch(() => undefined); // each tab shows its own error
  }
}

function prefetchTab(id: SettingsTab) {
  if (id === "memory") {
    loadCached(MEMORY_KEY, fetchHostedMemory).catch(() => undefined);
  }
}

function useT() {
  return createInlineTranslator(getHostedLanguage());
}

type TabInfo = { id: SettingsTab; icon: LucideIcon; label: string; hint: string; title: string; lead: string };

/** Full-window settings page: icon nav on the left, one titled section on the right. */
export default function HostedSettings({ initialTab = "account", onClose }: { initialTab?: SettingsTab; onClose: () => void }) {
  const t = useT();
  const [tab, setTab] = useState<SettingsTab>(initialTab);
  const mainRef = useRef<HTMLElement>(null);
  const tabs: TabInfo[] = [
    {
      id: "progress",
      icon: Flame,
      label: t("练习足迹", "Practice"),
      hint: t("打卡与练习时长", "Streaks and minutes"),
      title: t("你的练习足迹", "Your practice"),
      lead: t("每天开口说一点，进步看得见。", "A little every day adds up. Here is how far you have come."),
    },
    {
      id: "account",
      icon: Wallet,
      label: t("账户与时长", "Account & minutes"),
      hint: t("余额、续费与记录", "Balance, top-ups, history"),
      title: t("账户与时长", "Account & minutes"),
      lead: t("剩余分钟、有效期，以及每一次通话和充值。", "Minutes left, when they expire, and every call and top-up."),
    },
    {
      id: "learning",
      icon: GraduationCap,
      label: t("学习偏好", "Learning"),
      hint: t("水平、教练、母语", "Level, coach, language"),
      title: t("让外教更懂你", "Tune your tutor"),
      lead: t("这些设置决定 AI 外教怎么和你聊，保存在账号上，换电脑也不会丢。", "These shape how the AI tutor talks with you. They are saved on your account."),
    },
    {
      id: "memory",
      icon: Brain,
      label: t("AI 记忆", "AI memory"),
      hint: t("外教记得的你", "What the tutor remembers"),
      title: t("AI 记忆", "AI memory"),
      lead: t("外教会记住你的名字、水平和聊过的话题，下次接着聊。", "The tutor remembers your name, level and past topics, and picks up where you left off."),
    },
    {
      id: "general",
      icon: Languages,
      label: t("通用", "General"),
      hint: t("界面语言、版本更新", "Language, updates"),
      title: t("通用", "General"),
      lead: t("界面语言，以及应用的版本与更新。", "Display language, and app version and updates."),
    },
    {
      id: "security",
      icon: ShieldCheck,
      label: t("账号安全", "Security"),
      hint: t("密码与退出登录", "Password, log out"),
      title: t("账号安全", "Security"),
      lead: t("修改密码，或在这台电脑上退出登录。", "Change your password, or log out on this computer."),
    },
  ];
  const current = tabs.find((item) => item.id === tab) ?? tabs[0];

  useEffect(prefetchSettings, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const select = (id: SettingsTab) => {
    setTab(id);
    mainRef.current?.scrollTo({ top: 0 });
  };

  // Portalled so a transformed or clipped ancestor (the sidebar) cannot trap it.
  return createPortal(
    <div className="hostedAdminOverlay hostedSettingsPage" role="dialog" aria-modal="true" aria-label={t("设置", "Settings")}>
      <header className="hostedSettingsTopbar">
        <img src={echoIcon} alt="" className="hostedSettingsTopbarIcon" />
        <strong>Echo</strong>
        <span className="hostedSettingsTopbarTitle">{t("设置", "Settings")}</span>
        <button type="button" className="hostedSettingsBack" onClick={onClose} title={t("返回 (Esc)", "Back (Esc)")}>
          <ArrowLeft size={16} aria-hidden="true" />
          {t("返回对话", "Back to chat")}
        </button>
      </header>
      <div className="hostedSettings">
        <nav className="hostedSettingsNav" aria-label={t("设置分类", "Settings sections")}>
          {tabs.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                aria-current={tab === item.id ? "page" : undefined}
                className={tab === item.id ? "is-active" : ""}
                onClick={() => select(item.id)}
                onPointerEnter={() => prefetchTab(item.id)}
                onFocus={() => prefetchTab(item.id)}
              >
                <span className="hostedSettingsNavIcon"><Icon size={18} aria-hidden="true" /></span>
                <span className="hostedSettingsNavText">
                  <strong>{item.label}</strong>
                  <small>{item.hint}</small>
                </span>
              </button>
            );
          })}
        </nav>
        <main className="hostedSettingsMain" ref={mainRef}>
          <div className="hostedSettingsBody">
            <div className="hostedSettingsHero">
              <h1>{current.title}</h1>
              <p>{current.lead}</p>
            </div>
            {tab === "progress" ? <HostedProgress /> : null}
            {tab === "account" ? <AccountTab /> : null}
            {tab === "learning" ? <LearningTab /> : null}
            {tab === "memory" ? <MemorySection /> : null}
            {tab === "general" ? <GeneralTab /> : null}
            {tab === "security" ? <SecurityTab /> : null}
          </div>
        </main>
      </div>
    </div>,
    document.body,
  );
}

// ── account & minutes ────────────────────────────────────────────────────

function AccountTab() {
  const t = useT();
  // One 26-week request serves both this tab and Practice; cut it to 30 days here.
  const historyResource = useCachedResource<HostedHistory>(PROGRESS_KEY, loadProgressHistory);
  const renewalResource = useCachedResource<HostedRenewal>(RENEWAL_KEY, fetchHostedRenewal);
  const history = historyResource.data ?? null;
  const renewal = renewalResource.data ?? null;
  const loadError = (!history && historyResource.error) || (!renewal && renewalResource.error);
  const error = loadError ? hostedErrorMessage(loadError, t("加载失败", "Could not load")) : "";
  const [showAllCalls, setShowAllCalls] = useState(false);
  const [renewOpen, setRenewOpen] = useState(false);
  const lowBalance = history !== null && history.remaining_seconds < LOW_BALANCE_SECONDS;

  useEffect(() => {
    // Running low: show how to top up without an extra click.
    if (lowBalance) {
      setRenewOpen(true);
    }
  }, [lowBalance]);

  const remaining = history?.remaining_seconds ?? null;
  const since = recentSince(HISTORY_DAYS);
  const used = (history?.daily ?? []).filter((d) => d.day >= since.day).reduce((sum, d) => sum + d.wall_seconds, 0);
  const calls = (history?.calls ?? []).filter((call) => call.started_at >= since.epoch);
  const shownCalls = showAllCalls ? calls : calls.slice(0, CALLS_SHOWN);

  return (
    <>
      {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
      <div className="hostedPanelBalance">
        <div>
          <span className="hostedAdminMuted">{t("账号", "Account")} {history?.account ?? "…"}</span>
          <span className={remaining !== null && remaining < LOW_BALANCE_SECONDS ? "hostedPanelMinutes is-low" : "hostedPanelMinutes"}>
            {t("剩余", "")} <strong>{remaining === null ? "…" : Math.floor(remaining / 60)}</strong> {t("分钟", "minutes left")}
          </span>
        </div>
        <button type="button" className="hostedAdminPrimary" aria-expanded={renewOpen} onClick={() => setRenewOpen((v) => !v)}>
          {renewOpen ? t("收起", "Hide") : t("续费", "Top up")}
        </button>
      </div>
      {renewOpen ? <RenewalBlock renewal={renewal} /> : null}

      <section className="hostedPanelSection">
        <h3>{t("有效期", "Validity")}</h3>
        <p className="hostedAdminMuted hostedPanelHint">
          {t("每次充值的分钟各自计算有效期，通话时先扣最早到期的。", "Each top-up has its own expiry; calls use the soonest-expiring minutes first.")}
        </p>
        {history ? <LotList lots={history.lots} /> : <p className="hostedAdminMuted">{t("加载中…", "Loading…")}</p>}
      </section>

      <section className="hostedPanelSection">
        <h3>{t(`通话记录 · 近 ${HISTORY_DAYS} 天`, `Calls · last ${HISTORY_DAYS} days`)}</h3>
        <p className="hostedAdminMuted hostedPanelHint">
          {t(
            `共 ${calls.length} 次，${minutes(used)} 分钟。同一模型间隔 90 秒内算一次。`,
            `${calls.length} calls, ${minutes(used)} min. Pauses under 90 s count as one call.`,
          )}
        </p>
        {calls.length === 0 ? (
          <p className="hostedAdminMuted">{history ? t("还没有通话。", "No calls yet.") : t("加载中…", "Loading…")}</p>
        ) : (
          <ul className="hostedPanelList">
            {shownCalls.map((call) => (
              <li key={`${call.started_at}-${call.model}`}>
                <span className="hostedAdminMuted">{formatTime(call.started_at)}</span>
                <span>{modelLabel(call.model)}</span>
                <span className="hostedAdminNum">{formatElapsed(call.wall_seconds)}</span>
                <span className="hostedAdminNum hostedAdminMuted">
                  {call.billed_seconds === call.wall_seconds
                    ? ""
                    : t(`扣 ${minutes(call.billed_seconds)} 分`, `−${minutes(call.billed_seconds)} min`)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {calls.length > CALLS_SHOWN && !showAllCalls ? (
          <button type="button" className="hostedAdminGhost hostedPanelMore" onClick={() => setShowAllCalls(true)}>
            {t(`显示全部 ${calls.length} 次`, `Show all ${calls.length}`)}
          </button>
        ) : null}
      </section>

      <section className="hostedPanelSection">
        <h3>{t("充值记录", "Top-up history")}</h3>
        {history && history.grants.length > 0 ? (
          <GrantList grants={history.grants} />
        ) : (
          <p className="hostedAdminMuted">{history ? t("还没有充值记录。", "No top-ups yet.") : ""}</p>
        )}
      </section>
    </>
  );
}

/** The start of the last ``days`` local days (today included), as a day key and epoch seconds. */
function recentSince(days: number): { day: string; epoch: number } {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (days - 1));
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    day: `${start.getFullYear()}-${pad(start.getMonth() + 1)}-${pad(start.getDate())}`,
    epoch: Math.floor(start.getTime() / 1000),
  };
}

/** What can be bought (the shared price list) and how to pay (the operator's QR and note). */
function RenewalBlock({ renewal }: { renewal: HostedRenewal | null }) {
  const t = useT();
  return (
    <div className="hostedRenew">
      <div className="hostedRenewPackages">
        {USER_PACKAGES.map((pkg) => (
          <div key={pkg.id} className={pkg.memoryDays ? "hostedRenewPackage is-featured" : "hostedRenewPackage"}>
            <div className="hostedRenewPackageHead">
              <strong>{pkg.name}</strong>
              {pkg.memoryDays ? <span className="hostedPremiumTag">{t("含 AI 记忆", "Incl. AI memory")}</span> : null}
            </div>
            <span className="hostedRenewPrice">
              ¥{pkg.price}
              {pkg.validDays === 30 ? <small>{t(" / 月", " / month")}</small> : null}
            </span>
            {pkg.firstPrice ? (
              <span className="hostedRenewOffer">{t(`新用户首月 ¥${pkg.firstPrice}`, `First month ¥${pkg.firstPrice} for new users`)}</span>
            ) : null}
            <span className="hostedAdminMuted">
              {t(`${pkg.minutes} 分钟 · ${pkg.validDays} 天内有效`, `${pkg.minutes} min · valid ${pkg.validDays} days`)}
            </span>
          </div>
        ))}
      </div>
      {!renewal ? (
        <p className="hostedAdminMuted">{t("加载中…", "Loading…")}</p>
      ) : renewal.text || renewal.qr ? (
        <div className="hostedPanelRenewal">
          {renewal.qr ? <img src={renewal.qr} alt={t("付款二维码", "Payment QR code")} className="hostedPanelQr" /> : null}
          {renewal.text ? <p className="hostedPanelRenewalText">{renewal.text}</p> : null}
        </div>
      ) : (
        <p className="hostedAdminMuted">{t("付款方式请联系管理员。", "Ask the organiser how to pay.")}</p>
      )}
    </div>
  );
}

// ── learning preferences ─────────────────────────────────────────────────

function usePrefs() {
  const resource = useCachedResource<HostedPrefs>(PREFS_KEY, fetchHostedPrefs);
  const prefs = resource.data ?? null;
  const setPrefs = resource.setData;
  const [saveError, setError] = useState("");
  const error = saveError || (!prefs && resource.error ? hostedErrorMessage(resource.error, "") : "");
  const [saved, setSaved] = useState(false);
  const save = async (patch: Partial<HostedPrefs>): Promise<HostedPrefs | null> => {
    if (!prefs) {
      return null;
    }
    setPrefs({ ...prefs, ...patch }); // optimistic
    setError("");
    setSaved(false);
    try {
      const next = await saveHostedPrefs(patch);
      setPrefs(next);
      setSaved(true);
      return next;
    } catch (err) {
      setPrefs(prefs);
      setError(hostedErrorMessage(err, ""));
      return null;
    }
  };
  return { prefs, error, saved, save };
}

function LearningTab() {
  const t = useT();
  const { prefs, error, saved, save } = usePrefs();
  if (!prefs) {
    return error ? <p className="hostedAdminError" role="alert">{error}</p> : <p className="hostedAdminMuted">{t("加载中…", "Loading…")}</p>;
  }
  const update = async (patch: Partial<HostedPrefs>) => {
    const next = await save(patch);
    if (next) {
      applyHostedPrefs(next); // the coach of the next (or current) call follows at once
    }
  };
  const levels: { value: HostedPrefs["level"]; label: string }[] = [
    { value: "beginner", label: t("入门", "Beginner") },
    { value: "intermediate", label: t("中级", "Intermediate") },
    { value: "advanced", label: t("高级", "Advanced") },
    ...(prefs.learner === "adult" ? [{ value: "ielts" as const, label: t("雅思", "IELTS") }] : []),
  ];
  return (
    <div className="hostedSettingsGroup">
      <SettingRow label={t("谁在学", "Who is learning")}>
        <Segmented
          value={prefs.learner}
          options={[
            { value: "child", label: t("孩子", "A child") },
            { value: "adult", label: t("大人", "An adult") },
          ]}
          onChange={(learner) => void update({ learner, ...(learner === "child" && prefs.level === "ielts" ? { level: "beginner" } : {}) })}
        />
      </SettingRow>
      <SettingRow label={t("英语水平", "English level")}>
        <Segmented value={prefs.level} options={levels} onChange={(level) => void update({ level })} />
      </SettingRow>
      <SettingRow
        label={t("口语教练", "Speaking coach")}
        hint={t("开启后，说错时 AI 外教会在对话里顺便帮你改正", "When on, the tutor gently corrects mistakes as you talk")}
      >
        <label className="hostedAdminCheck">
          <input type="checkbox" checked={prefs.coach} onChange={(e) => void update({ coach: e.target.checked })} />
          <span>{prefs.coach ? t("已开启", "On") : t("已关闭", "Off")}</span>
        </label>
      </SettingRow>
      <SettingRow label={t("母语", "Native language")} hint={t("卡住时 AI 外教会用它简单解释", "Used for short explanations when you are stuck")}>
        <select value={prefs.native_language} onChange={(e) => void update({ native_language: e.target.value })}>
          <option value="Chinese">{t("中文", "Chinese")}</option>
          <option value="Cantonese">{t("粤语", "Cantonese")}</option>
          <option value="English">English</option>
        </select>
      </SettingRow>
      {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
      {saved ? <p className="hostedAdminNotice" role="status">{t("已保存。", "Saved.")}</p> : null}
      <p className="hostedAdminMuted">{t("外教的声音和模型在输入框下方的选择器里换。", "Pick the tutor's voice and model with the selector under the input box.")}</p>
    </div>
  );
}

function GeneralTab() {
  const t = useT();
  const { prefs, error, save } = usePrefs();
  if (!prefs) {
    return error ? <p className="hostedAdminError" role="alert">{error}</p> : <p className="hostedAdminMuted">{t("加载中…", "Loading…")}</p>;
  }
  const changeLanguage = async (ui_language: HostedPrefs["ui_language"]) => {
    const next = await save({ ui_language });
    if (next && applyHostedPrefs(next)) {
      window.location.reload(); // re-render every screen in the new language
    }
  };
  return (
    <>
      <div className="hostedSettingsGroup">
        <SettingRow label={t("界面语言", "Display language")} hint={t("切换后页面会自动刷新", "The page reloads to apply it")}>
          <Segmented
            value={prefs.ui_language}
            options={[
              { value: "zh-CN", label: "中文" },
              { value: "en-US", label: "English" },
            ]}
            onChange={(value) => void changeLanguage(value)}
          />
        </SettingRow>
        {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
      </div>
      {/* Installed app only; renders nothing in a browser. */}
      <UpdateCard />
    </>
  );
}

function SecurityTab() {
  const t = useT();
  const logout = () => {
    clearAuthRuntime();
    window.dispatchEvent(new Event(AUTH_REJECTED_EVENT));
  };
  return (
    <div className="hostedSettingsGroup">
      <h3>{t("修改密码", "Change password")}</h3>
      <ChangePasswordForm />
      <h3>{t("退出登录", "Log out")}</h3>
      <p className="hostedAdminMuted">{t("在别人的电脑上用完记得退出。", "Log out when you are done on a shared computer.")}</p>
      <div>
        <button type="button" className="hostedAdminGhost" onClick={logout}>{t("退出登录", "Log out")}</button>
      </div>
    </div>
  );
}

function SettingRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="hostedSettingRow">
      <div className="hostedSettingLabel">
        <strong>{label}</strong>
        {hint ? <span className="hostedAdminMuted">{hint}</span> : null}
      </div>
      <div className="hostedSettingControl">{children}</div>
    </div>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="hostedAdminSegmented" role="radiogroup">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          className={value === option.value ? "is-active" : ""}
          onClick={() => value !== option.value && onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// ── security: password ───────────────────────────────────────────────────

function ChangePasswordForm() {
  const t = useT();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);
  const { busy, error, setError, submit } = useSubmit(async () => {
    if (next.length < 6) {
      setError(t("新密码至少 6 位", "The new password needs at least 6 characters"));
      return;
    }
    if (next !== confirm) {
      setError(t("两次输入的新密码不一样", "The two new passwords do not match"));
      return;
    }
    try {
      await changeAuthPassword(current, next);
    } catch (err) {
      const message = hostedErrorMessage(err, t("修改失败", "Could not change it"));
      throw new Error(/incorrect|current/i.test(message) ? t("当前密码不对", "The current password is wrong") : message, { cause: err });
    }
    setDone(true);
    setCurrent("");
    setNext("");
    setConfirm("");
  });
  return (
    <form className="hostedAdminForm" onSubmit={submit}>
      <label>
        <span>{t("当前密码", "Current password")}</span>
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
      </label>
      <label>
        <span>{t("新密码（至少 6 位）", "New password (6+ characters)")}</span>
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
      </label>
      <label>
        <span>{t("再输一次新密码", "Repeat the new password")}</span>
        <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
      </label>
      {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
      {done ? (
        <p className="hostedAdminNotice" role="status">
          {t("密码已修改。其他设备需要用新密码重新登录。", "Password changed. Other devices need to log in again.")}
        </p>
      ) : null}
      <div className="hostedAdminModalActions">
        <button type="submit" className="hostedAdminPrimary" disabled={busy}>
          {busy ? t("提交中…", "Saving…") : t("修改密码", "Change password")}
        </button>
      </div>
    </form>
  );
}

// ── AI memory ────────────────────────────────────────────────────────────

/** Membership, the user's own on/off switch, what is remembered, and a full wipe. */
function MemorySection() {
  const t = useT();
  const zh = getHostedLanguage() !== "en-US";
  const resource = useCachedResource<HostedMemory>(MEMORY_KEY, fetchHostedMemory);
  const memory = resource.data ?? null;
  const setMemory = resource.setData;
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const locked = busy || refreshing;
  const [showAllEpisodes, setShowAllEpisodes] = useState(false);
  const [message, setMessage] = useState("");
  const [actionError, setError] = useState("");
  const loadError = !memory && resource.error ? hostedErrorMessage(resource.error, t("读取记忆失败", "Could not load memories")) : "";
  const error = actionError || loadError;

  if (loadError) {
    return <p className="hostedAdminError" role="alert">{loadError}</p>;
  }
  if (!memory) {
    return (
      <div className="hostedMemory">
        <p className="hostedAdminMuted">{t("正在读取外教记住的内容…", "Loading what the tutor remembers…")}</p>
      </div>
    );
  }
  const header = (
    <div className="hostedMemoryBrand">
      <EvermindBadge variant="light" compact />
      <span className="hostedPremiumTag">{t("月卡专享", "Monthly card perk")}</span>
    </div>
  );
  if (!memory.configured) {
    return (
      <div className="hostedMemory">
        {header}
        <p className="hostedAdminMuted">{t("AI 记忆暂未开放。", "AI memory is not available yet.")}</p>
      </div>
    );
  }
  if (!memory.member) {
    return (
      <div className="hostedMemory">
        {header}
        <p className="hostedMemoryPitch">
          {t(
            "开通月卡即可使用 AI 记忆：外教会记住你的名字、英语水平和聊过的话题，每次都接着上次聊，越聊越懂你。",
            "AI memory comes with the monthly card: the tutor remembers your name, level and past topics, and picks up where you left off.",
          )}
        </p>
      </div>
    );
  }

  const refresh = async () => {
    setRefreshing(true);
    setError("");
    try {
      setMemory(await loadCached(MEMORY_KEY, fetchHostedMemory, true));
    } catch (err) {
      setError(hostedErrorMessage(err, t("读取记忆失败", "Could not load memories")));
    } finally {
      setRefreshing(false);
    }
  };

  const toggle = async () => {
    setBusy(true);
    setError("");
    try {
      const next = await setHostedMemoryEnabled(memory.opted_out);
      setMemory({ ...memory, ...next });
    } catch (err) {
      setError(hostedErrorMessage(err, t("操作失败", "Something went wrong")));
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    if (!window.confirm(t("清除 AI 记住的关于你的全部内容？清除后无法恢复。", "Erase everything the AI remembers about you? This cannot be undone."))) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await clearHostedMemory();
      setMemory({ ...memory, profile: [], facts: [], episodes: [], error: undefined });
      setMessage(t("已清除。之后的通话会重新开始记。", "Erased. Future calls start a fresh memory."));
    } catch (err) {
      setError(hostedErrorMessage(err, t("清除失败", "Could not erase")));
    } finally {
      setBusy(false);
    }
  };

  const facts = memoryFacts(memory);
  const episodes = (memory.episodes ?? [])
    .map((item) => ({ ...item, seconds: memoryEpochSeconds(item.at) }))
    .sort((a, b) => (b.seconds ?? 0) - (a.seconds ?? 0));
  const shownEpisodes = showAllEpisodes ? episodes : episodes.slice(0, EPISODES_SHOWN);
  const empty = facts.length === 0 && episodes.length === 0;
  const refreshButton = (
    <button type="button" className="hostedAdminGhost hostedMemoryRefresh" disabled={locked} onClick={() => void refresh()}>
      <RefreshCw size={14} aria-hidden="true" className={refreshing ? "is-spinning" : ""} />
      {refreshing ? t("刷新中…", "Refreshing…") : t("刷新", "Refresh")}
    </button>
  );

  return (
    <>
      <div className="hostedMemory">
        {header}
        <div className="hostedMemorySwitch">
          <div className="hostedSettingLabel">
            <strong>{t("通话时让 AI 记住我", "Let the AI remember me in calls")}</strong>
            <span className="hostedAdminMuted">
              {memory.opted_out
                ? t("已关闭：通话时 AI 不会读取也不会记录你的内容。", "Off: calls neither read nor record anything about you.")
                : t(`会员有效期至 ${formatDate(memory.memory_until ?? 0)}`, `Membership valid until ${formatDate(memory.memory_until ?? 0)}`)}
            </span>
          </div>
          <label className="hostedSwitch">
            <input
              type="checkbox"
              role="switch"
              aria-label={t("通话时让 AI 记住我", "Let the AI remember me in calls")}
              checked={!memory.opted_out}
              disabled={locked}
              onChange={() => void toggle()}
            />
            <span aria-hidden="true" />
          </label>
        </div>
        {memory.error || empty ? null : (
          <div className="hostedMemoryStats">
            <span><strong>{facts.length}</strong>{t(" 条关于你", " things about you")}</span>
            <span>
              <strong>{episodes.length >= EPISODE_PAGE ? `${EPISODE_PAGE}+` : episodes.length}</strong>
              {t(" 段聊天回忆", " past conversations")}
            </span>
            {refreshButton}
          </div>
        )}
      </div>

      {memory.error ? (
        <div className="hostedMemory">
          <p className="hostedAdminMuted">{memory.error}</p>
          <div>{refreshButton}</div>
        </div>
      ) : empty ? (
        <div className="hostedMemory hostedMemoryEmpty">
          <Sparkles size={28} aria-hidden="true" />
          <strong>{t("外教还没有记住关于你的内容", "Nothing remembered yet")}</strong>
          <p className="hostedAdminMuted">
            {t(
              "多聊几次，说说你的名字、爱好和最近的事，这里就会慢慢出现外教记住的你。刚结束的通话需要几分钟整理。",
              "Talk a few times about your name, hobbies and your week, and it builds up here. A call that just ended takes a few minutes to sort out.",
            )}
          </p>
          <div>{refreshButton}</div>
        </div>
      ) : (
        <>
          {facts.length > 0 ? (
            <section className="hostedMemory">
              <h3 className="hostedMemoryTitle">
                <Brain size={16} aria-hidden="true" />
                {t("外教眼中的你", "What the tutor knows about you")}
              </h3>
              <ul className="hostedMemoryFacts">
                {facts.map((fact, index) => (
                  <li key={`${fact.label}-${index}`}>
                    {fact.label ? <span>{memoryLabel(fact.label, zh)}</span> : null}
                    <strong>{fact.text}</strong>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {episodes.length > 0 ? (
            <section className="hostedMemory">
              <h3 className="hostedMemoryTitle">
                <MessagesSquare size={16} aria-hidden="true" />
                {t("聊过的事", "Past conversations")}
              </h3>
              <ol className="hostedMemoryTimeline">
                {shownEpisodes.map((item, index) => (
                  <li key={item.id || `e-${index}`}>
                    <time className="hostedAdminMuted">{item.seconds ? formatDate(item.seconds) : ""}</time>
                    <div>
                      {item.title ? <strong>{item.title}</strong> : null}
                      <p>{item.text}</p>
                    </div>
                  </li>
                ))}
              </ol>
              {episodes.length > EPISODES_SHOWN && !showAllEpisodes ? (
                <button type="button" className="hostedAdminGhost hostedPanelMore" onClick={() => setShowAllEpisodes(true)}>
                  {episodes.length >= EPISODE_PAGE
                    ? t(`显示最近 ${episodes.length} 段`, `Show the latest ${episodes.length}`)
                    : t(`显示全部 ${episodes.length} 段`, `Show all ${episodes.length}`)}
                </button>
              ) : null}
            </section>
          ) : null}
        </>
      )}

      <div className="hostedMemory hostedMemoryDanger">
        <div className="hostedSettingLabel">
          <strong>{t("清除我的全部记忆", "Erase all my memories")}</strong>
          <span className="hostedAdminMuted">{t("外教会忘掉关于你的一切，无法恢复。", "The tutor forgets everything about you. This cannot be undone.")}</span>
        </div>
        <button type="button" className="hostedAdminGhost is-danger" disabled={locked} onClick={() => void clearAll()}>
          {t("清除", "Erase")}
        </button>
      </div>
      {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
      {message ? <p className="hostedAdminNotice" role="status">{message}</p> : null}
    </>
  );
}
