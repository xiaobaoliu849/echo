import { useEffect, useState } from "react";
import {
  AUTH_REJECTED_EVENT,
  changeAuthPassword,
  clearAuthRuntime,
  clearHostedMemory,
  fetchHostedHistory,
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
  fillDays,
  formatDate,
  formatElapsed,
  formatTime,
  minutes,
  modelLabel,
  useSubmit,
} from "../hostedFormat";
import { applyHostedPrefs } from "../hostedPrefs";
import { createInlineTranslator } from "../i18n";
import { formatErrorMessage } from "../utils/errorFormatting";
import { DailyChart, GrantList, LotList, Modal, StatTile } from "./HostedUi";

/**
 * Settings for a hosted user: everything they can change about their own
 * account, and nothing about the operator's server (keys, providers).
 */

export type SettingsTab = "account" | "learning" | "memory" | "general" | "security";

const HISTORY_DAYS = 30;
const CALLS_SHOWN = 10;
const LOW_BALANCE_SECONDS = 10 * 60;

function useT() {
  return createInlineTranslator(getHostedLanguage());
}

export default function HostedSettings({ initialTab = "account", onClose }: { initialTab?: SettingsTab; onClose: () => void }) {
  const t = useT();
  const [tab, setTab] = useState<SettingsTab>(initialTab);
  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "account", label: t("账户与时长", "Account & minutes") },
    { id: "learning", label: t("学习偏好", "Learning") },
    { id: "memory", label: t("AI 记忆", "AI memory") },
    { id: "general", label: t("通用", "General") },
    { id: "security", label: t("账号安全", "Security") },
  ];
  return (
    <Modal title={t("设置", "Settings")} onClose={onClose} wide>
      <div className="hostedSettings">
        <nav className="hostedSettingsNav" aria-label={t("设置分类", "Settings sections")}>
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-current={tab === item.id ? "page" : undefined}
              className={tab === item.id ? "is-active" : ""}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="hostedSettingsBody">
          {tab === "account" ? <AccountTab /> : null}
          {tab === "learning" ? <LearningTab /> : null}
          {tab === "memory" ? <MemorySection /> : null}
          {tab === "general" ? <GeneralTab /> : null}
          {tab === "security" ? <SecurityTab /> : null}
        </div>
      </div>
    </Modal>
  );
}

// ── account & minutes ────────────────────────────────────────────────────

function AccountTab() {
  const t = useT();
  const [history, setHistory] = useState<HostedHistory | null>(null);
  const [renewal, setRenewal] = useState<HostedRenewal | null>(null);
  const [error, setError] = useState("");
  const [showAllCalls, setShowAllCalls] = useState(false);
  const [renewOpen, setRenewOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchHostedHistory(HISTORY_DAYS), fetchHostedRenewal()])
      .then(([nextHistory, nextRenewal]) => {
        if (!cancelled) {
          setHistory(nextHistory);
          setRenewal(nextRenewal);
          // Running low: show how to top up without an extra click.
          if (nextHistory.remaining_seconds < LOW_BALANCE_SECONDS) {
            setRenewOpen(true);
          }
        }
      })
      .catch((err) => !cancelled && setError(formatErrorMessage(err, t("加载失败", "Could not load"))));
    return () => {
      cancelled = true;
    };
  }, [t]);

  const remaining = history?.remaining_seconds ?? null;
  const used = (history?.daily ?? []).reduce((sum, d) => sum + d.wall_seconds, 0);
  const calls = history?.calls ?? [];
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
        <h3>{t(`近 ${HISTORY_DAYS} 天`, `Last ${HISTORY_DAYS} days`)}</h3>
        <div className="hostedAdminDetailStats">
          <StatTile
            label={t("通话次数", "Calls")}
            value={String(calls.length)}
            unit={t("次", "")}
            hint={t("同一模型间隔 90 秒内算一次", "Pauses under 90 s count as one call")}
          />
          <StatTile label={t("通话时长", "Talk time")} value={minutes(used)} unit={t("分钟", "min")} hint={t("实际通话时长", "Actual minutes talked")} />
        </div>
        {history ? <DailyChart daily={fillDays(history.daily, HISTORY_DAYS)} /> : null}
      </section>

      <section className="hostedPanelSection">
        <h3>{t("通话记录", "Call history")}</h3>
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
  const [prefs, setPrefs] = useState<HostedPrefs | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchHostedPrefs()
      .then((value) => !cancelled && setPrefs(value))
      .catch((err) => !cancelled && setError(formatErrorMessage(err, "")));
    return () => {
      cancelled = true;
    };
  }, []);
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
      setError(formatErrorMessage(err, ""));
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
      <p className="hostedAdminMuted">{t("这些设置决定 AI 外教怎么和你聊，保存在账号上，换电脑也不会丢。", "These shape how the AI tutor talks with you. They are saved on your account.")}</p>
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
      const message = formatErrorMessage(err, t("修改失败", "Could not change it"));
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
  const [memory, setMemory] = useState<HostedMemory | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchHostedMemory()
      .then((value) => !cancelled && setMemory(value))
      .catch((err) => !cancelled && setError(formatErrorMessage(err, t("读取记忆失败", "Could not load memories"))));
    return () => {
      cancelled = true;
    };
  }, [t]);

  if (error && !memory) {
    return <p className="hostedAdminError" role="alert">{error}</p>;
  }
  if (!memory) {
    return <p className="hostedAdminMuted">{t("加载中…", "Loading…")}</p>;
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

  const toggle = async () => {
    setBusy(true);
    setError("");
    try {
      const next = await setHostedMemoryEnabled(memory.opted_out);
      setMemory({ ...memory, ...next });
    } catch (err) {
      setError(formatErrorMessage(err, t("操作失败", "Something went wrong")));
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
      setMemory({ ...memory, profile: [], episodes: [] });
      setMessage(t("已清除。之后的通话会重新开始记。", "Erased. Future calls start a fresh memory."));
    } catch (err) {
      setError(formatErrorMessage(err, t("清除失败", "Could not erase")));
    } finally {
      setBusy(false);
    }
  };

  const profile = memory.profile ?? [];
  const episodes = memory.episodes ?? [];
  return (
    <div className="hostedMemory">
      {header}
      <div className="hostedMemoryHead">
        <span className="hostedAdminMuted">{t("有效期至", "Valid until")} {formatDate(memory.memory_until ?? 0)}</span>
        <label className="hostedAdminCheck">
          <input type="checkbox" checked={!memory.opted_out} disabled={busy} onChange={() => void toggle()} />
          <span>{t("通话时让 AI 记住我", "Let the AI remember me in calls")}</span>
        </label>
      </div>
      {memory.opted_out ? (
        <p className="hostedAdminMuted">{t("已关闭：通话时 AI 不会读取也不会记录你的内容。", "Off: calls neither read nor record anything about you.")}</p>
      ) : null}
      {memory.error ? <p className="hostedAdminMuted">{memory.error}</p> : null}
      {memory.error ? null : profile.length === 0 && episodes.length === 0 ? (
        <p className="hostedAdminMuted">{t("AI 还没有记住关于你的内容，多聊几次就会有了。", "Nothing remembered yet; it builds up as you talk.")}</p>
      ) : (
        <>
          {profile.length > 0 ? (
            <ul className="hostedMemoryList">
              {profile.map((line, index) => <li key={`p-${index}`}>{line}</li>)}
            </ul>
          ) : null}
          {episodes.length > 0 ? (
            <ul className="hostedMemoryList is-episodes">
              {episodes.map((item, index) => <li key={item.id || `e-${index}`}>{item.text}</li>)}
            </ul>
          ) : null}
        </>
      )}
      {error ? <p className="hostedAdminError" role="alert">{error}</p> : null}
      {message ? <p className="hostedAdminNotice" role="status">{message}</p> : null}
      <div>
        <button type="button" className="hostedAdminGhost" disabled={busy} onClick={() => void clearAll()}>
          {t("清除我的全部记忆", "Erase all my memories")}
        </button>
      </div>
    </div>
  );
}
