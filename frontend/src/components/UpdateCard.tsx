import { Download, RefreshCw } from "lucide-react";
import { useAppUpdater } from "../hooks/useAppUpdater";
import { useI18n } from "../i18n";

export default function UpdateCard() {
  const updater = useAppUpdater();
  const { t } = useI18n();
  if (!updater.isElectron) return null;
  const { phase, updateInfo, progress } = updater;
  const canCheck = ["idle", "up-to-date", "error"].includes(phase);
  const error = updater.connectionError || updater.errorMessage;
  return (
    <section className="vsSettingsCard vsUpdateCard" aria-label={t("应用更新", "Application updates")}>
      <div className="vsCardSection">
        <h3 className="vsCardSubTitle">{t("应用更新", "Application updates")}</h3>
        <p>{t("当前版本", "Installed version")}: {updater.appVersion || "—"}</p>
        {updateInfo && <p>{t("新版本", "New version")}: {updateInfo.version}</p>}
        <div role="status" aria-live="polite">
          {phase === "idle" && t("启动后自动检查，每 6 小时再次检查。下载和安装由你决定。", "Checks automatically after launch and every 6 hours. You choose when to download and install.")}
          {phase === "unsupported" && t("应用内更新适用于已安装的 Windows 版本。开发模式不检查更新。", "In-app updates are available in installed Windows builds. Development builds do not check for updates.")}
          {phase === "checking" && t("正在检查更新…", "Checking for updates…")}
          {phase === "up-to-date" && t("当前已是最新版本。", "You are on the latest version.")}
          {phase === "available" && t("新版本已发布，可以下载。", "A new release is available to download.")}
          {phase === "downloading" && t("正在下载并验证更新…", "Downloading and verifying the update…")}
          {phase === "ready" && t("更新已下载。请先保存工作并结束通话、录音及生成任务，再重启安装。也可以稍后返回安装。", "The update is downloaded. Save your work and finish calls, recordings and generation tasks before restarting. You can return later to install.")}
          {phase === "installing" && t("正在启动安装程序…", "Starting the installer…")}
        </div>
        {phase === "downloading" && <div className="vsUpdateProgress">
          <progress aria-label={t("下载进度", "Download progress")} max={100} value={progress?.percent} />
          {progress && <span>{progress.percent.toFixed(1)}% · {(progress.transferred / 1048576).toFixed(1)} / {(progress.total / 1048576).toFixed(1)} MB</span>}
        </div>}
        {error && <div className="vsSettingsNotice warning" role="alert">
          <p>{t("更新未完成。请检查网络后重试；当前版本仍可使用。", "The update could not be completed. Check your connection and retry; your current version remains usable.")}</p>
          <details><summary>{t("错误详情", "Error details")}</summary><p>{error}</p></details>
        </div>}
        {updateInfo?.releaseNotes && <details className="vsUpdateNotes" open>
          <summary>{t("更新内容", "Release notes")}</summary>
          <div>{updateInfo.releaseNotes}</div>
        </details>}
        {updater.lastChecked && <p className="vsFieldHint">{t("上次检查", "Last checked")}: {new Date(updater.lastChecked).toLocaleString()}</p>}
        <div className="vsSystemActions">
          {canCheck && <button className="vsBtnGhost" type="button" onClick={() => void updater.checkForUpdates()}>
            <RefreshCw size={16} aria-hidden="true" /> {t("检查更新", "Check for updates")}
          </button>}
          {phase === "available" && <button className="vsBtnPrimary" type="button" onClick={() => void updater.downloadUpdate()}>
            <Download size={16} aria-hidden="true" /> {t("下载更新", "Download update")}
          </button>}
          {phase === "ready" && <button className="vsBtnPrimary" type="button" onClick={() => void updater.installNow()}>
            {t("重启并安装", "Restart and install")}
          </button>}
        </div>
      </div>
    </section>
  );
}
