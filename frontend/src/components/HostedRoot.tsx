import { useEffect, useState, type FormEvent } from "react";
import App from "../App";
import HostedAdmin from "./HostedAdmin";
import HostedOnboarding from "./HostedOnboarding";
import echoIcon from "../assets/echo-icon.png";
import {
  AUTH_REJECTED_EVENT,
  clearAuthRuntime,
  fetchHostedInfo,
  fetchHostedPrefs,
  getAuthRuntimeConfig,
  loginAuthUser,
  registerHostedAccount,
  type HostedPrefs,
} from "../api";
import { createInlineTranslator } from "../i18n";
import { formatErrorMessage } from "../utils/errorFormatting";
import { HOSTED_ADMIN_HASH, getHostedLanguage, setHostedLanguage } from "../hosted";
import { applyHostedPrefs } from "../hostedPrefs";
import "../styles/hosted.css";

type Phase = "login" | "loading" | "onboarding" | "ready";

/**
 * Entry for the hosted (paid) build. Nothing behind the login screen mounts
 * until the user has a session, so the app never fires API calls the
 * server would reject. After login the account's preferences are applied to
 * this device, and a first-time user is walked through onboarding.
 */
export default function HostedRoot() {
  const [phase, setPhase] = useState<Phase>(() => (getAuthRuntimeConfig().apiToken ? "loading" : "login"));
  const [prefs, setPrefs] = useState<HostedPrefs | null>(null);
  const [hash, setHash] = useState(() => window.location.hash);

  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const onRejected = () => {
      clearAuthRuntime();
      setPhase("login");
    };
    window.addEventListener(AUTH_REJECTED_EVENT, onRejected);
    return () => window.removeEventListener(AUTH_REJECTED_EVENT, onRejected);
  }, []);

  useEffect(() => {
    if (phase !== "loading") {
      return;
    }
    let cancelled = false;
    fetchHostedPrefs()
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        if (applyHostedPrefs(loaded)) {
          window.location.reload(); // re-render everything in the account's language
          return;
        }
        setPrefs(loaded);
        setPhase(loaded.onboarded ? "ready" : "onboarding");
      })
      .catch(() => {
        // Preferences are a convenience: never lock the user out over them.
        if (!cancelled) {
          setPhase("ready");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [phase]);

  if (phase === "login") {
    return <HostedLogin onLoggedIn={() => setPhase("loading")} />;
  }
  if (phase === "loading") {
    return <main className="hostedLogin" aria-busy="true" />;
  }
  // The operator console never waits behind the learner onboarding.
  const adminConsole = hash === HOSTED_ADMIN_HASH && getAuthRuntimeConfig().isAdmin;
  if (phase === "onboarding" && prefs && !adminConsole) {
    return <HostedOnboarding prefs={prefs} onDone={() => setPhase("ready")} />;
  }
  if (adminConsole) {
    return (
      <HostedAdmin
        onExit={() => {
          window.location.hash = "";
        }}
        onLogout={() => {
          clearAuthRuntime();
          setPhase("login");
        }}
      />
    );
  }
  return <App />;
}

function HostedLogin({ onLoggedIn }: { onLoggedIn: () => void }) {
  const language = getHostedLanguage();
  const t = createInlineTranslator(language);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [registrationOpen, setRegistrationOpen] = useState(false);
  const [trialMinutes, setTrialMinutes] = useState(30);
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [learner, setLearner] = useState<"child" | "adult">("child");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchHostedInfo()
      .then((info) => {
        setRegistrationOpen(Boolean(info.registration_open));
        setTrialMinutes(info.trial_minutes || 30);
      })
      .catch(() => undefined);
  }, []);

  const switchLanguage = () => {
    setHostedLanguage(language === "en-US" ? "zh-CN" : "en-US");
    window.location.reload();
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!account.trim() || !password) {
      setError(t("请输入账号和密码", "Enter your account and password"));
      return;
    }
    if (mode === "register") {
      if (!inviteCode.trim()) {
        setError(t("请输入小区邀请码", "Enter the community invite code"));
        return;
      }
      if (password.length < 6) {
        setError(t("密码至少 6 位", "Password needs at least 6 characters"));
        return;
      }
      if (password !== confirm) {
        setError(t("两次输入的密码不一样", "The two passwords do not match"));
        return;
      }
    }
    setBusy(true);
    try {
      if (mode === "register") {
        await registerHostedAccount({ invite_code: inviteCode.trim(), account: account.trim(), password, learner });
      } else {
        await loginAuthUser(account.trim(), password);
      }
      onLoggedIn();
    } catch (err) {
      const message = formatErrorMessage(err, mode === "register" ? t("注册失败", "Sign-up failed") : t("登录失败", "Login failed"));
      setError(
        mode === "login" && /incorrect|401/i.test(message)
          ? t("账号或密码不对，请再试一次", "Wrong account or password, please try again")
          : message,
      );
    } finally {
      setBusy(false);
    }
  }

  const registering = mode === "register";
  return (
    <main className="hostedLogin">
      <button type="button" className="hostedLangSwitch" onClick={switchLanguage}>
        {language === "en-US" ? "中文" : "English"}
      </button>
      <form className="hostedLoginCard" onSubmit={submit}>
        <img src={echoIcon} alt="" className="hostedLoginIcon" />
        <h1>{t("Echo 英语口语陪练", "Echo English Speaking Coach")}</h1>
        <p className="hostedLoginLead">{t("AI 外教 24 小时在线，随时开口练", "An AI tutor ready to talk any time")}</p>
        {registrationOpen ? (
          <div className="hostedLoginTabs" role="tablist">
            <button type="button" role="tab" aria-selected={!registering} className={registering ? "" : "is-active"} onClick={() => { setMode("login"); setError(""); }}>
              {t("登录", "Log in")}
            </button>
            <button type="button" role="tab" aria-selected={registering} className={registering ? "is-active" : ""} onClick={() => { setMode("register"); setError(""); }}>
              {t(`注册 · 送 ${trialMinutes} 分钟`, `Sign up · ${trialMinutes} free min`)}
            </button>
          </div>
        ) : null}
        {registering ? (
          <label>
            <span>{t("小区邀请码（小区群里有）", "Community invite code (posted in the group chat)")}</span>
            <input value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} autoComplete="off" autoCapitalize="characters" />
          </label>
        ) : null}
        <label>
          <span>{registering ? t("账号（门牌号或昵称，登录用）", "Account (door number or nickname)") : t("账号", "Account")}</span>
          <input
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            autoComplete="username"
            placeholder={t("例如 1203", "e.g. 1203")}
            autoFocus
          />
        </label>
        <label>
          <span>{registering ? t("密码（至少 6 位）", "Password (6+ characters)") : t("密码", "Password")}</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={registering ? "new-password" : "current-password"}
          />
        </label>
        {registering ? (
          <>
            <label>
              <span>{t("再输一次密码", "Repeat the password")}</span>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
            </label>
            <div className="hostedLearnerPick" role="radiogroup" aria-label={t("谁在学", "Who is learning")}>
              <span>{t("谁在学？", "Who is learning?")}</span>
              <div>
                <button type="button" role="radio" aria-checked={learner === "child"} className={learner === "child" ? "is-active" : ""} onClick={() => setLearner("child")}>
                  {t("孩子", "A child")}
                </button>
                <button type="button" role="radio" aria-checked={learner === "adult"} className={learner === "adult" ? "is-active" : ""} onClick={() => setLearner("adult")}>
                  {t("大人", "An adult")}
                </button>
              </div>
            </div>
          </>
        ) : null}
        {error ? <p className="hostedLoginError" role="alert">{error}</p> : null}
        <button type="submit" className="hostedLoginSubmit" disabled={busy}>
          {busy
            ? registering ? t("注册中…", "Signing up…") : t("登录中…", "Logging in…")
            : registering ? t(`注册并领取 ${trialMinutes} 分钟`, `Sign up and get ${trialMinutes} minutes`) : t("登录", "Log in")}
        </button>
        {registrationOpen ? null : (
          <p className="hostedLoginHint">{t("没有账号？请联系管理员开通", "No account yet? Ask the organiser to create one")}</p>
        )}
      </form>
    </main>
  );
}
