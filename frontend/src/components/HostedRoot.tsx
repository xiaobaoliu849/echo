import { useEffect, useState, type FormEvent } from "react";
import App from "../App";
import HostedAdmin from "./HostedAdmin";
import echoIcon from "../assets/echo-icon.png";
import { AUTH_REJECTED_EVENT, clearAuthRuntime, getAuthRuntimeConfig, loginAuthUser } from "../api";
import { formatErrorMessage } from "../utils/errorFormatting";
import { HOSTED_ADMIN_HASH } from "../hosted";
import "../styles/hosted.css";

/**
 * Entry for the hosted (paid) build. Nothing behind the login screen mounts
 * until the user has a session, so the app never fires API calls the
 * server would reject.
 */
export default function HostedRoot() {
  const [loggedIn, setLoggedIn] = useState(() => Boolean(getAuthRuntimeConfig().apiToken));
  const [hash, setHash] = useState(() => window.location.hash);

  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const onRejected = () => {
      clearAuthRuntime();
      setLoggedIn(false);
    };
    window.addEventListener(AUTH_REJECTED_EVENT, onRejected);
    return () => window.removeEventListener(AUTH_REJECTED_EVENT, onRejected);
  }, []);

  if (!loggedIn) {
    return <HostedLogin onLoggedIn={() => setLoggedIn(true)} />;
  }
  if (hash === HOSTED_ADMIN_HASH && getAuthRuntimeConfig().isAdmin) {
    return (
      <HostedAdmin
        onExit={() => {
          window.location.hash = "";
        }}
        onLogout={() => {
          clearAuthRuntime();
          setLoggedIn(false);
        }}
      />
    );
  }
  return <App />;
}

function HostedLogin({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!account.trim() || !password) {
      setError("请输入账号和密码");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await loginAuthUser(account.trim(), password);
      onLoggedIn();
    } catch (err) {
      const message = formatErrorMessage(err, "登录失败");
      setError(/incorrect|401/i.test(message) ? "账号或密码不对，请再试一次" : message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="hostedLogin">
      <form className="hostedLoginCard" onSubmit={submit}>
        <img src={echoIcon} alt="" className="hostedLoginIcon" />
        <h1>Echo 英语口语陪练</h1>
        <p className="hostedLoginLead">AI 外教 24 小时在线，随时开口练</p>
        <label>
          <span>账号</span>
          <input
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            autoComplete="username"
            placeholder="例如 1203"
            autoFocus
          />
        </label>
        <label>
          <span>密码</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        {error ? <p className="hostedLoginError" role="alert">{error}</p> : null}
        <button type="submit" disabled={busy}>{busy ? "登录中…" : "登录"}</button>
        <p className="hostedLoginHint">没有账号？请联系管理员开通</p>
      </form>
    </main>
  );
}
