import { useState } from "react";
import { Download, X } from "lucide-react";
import { useAppUpdater } from "../hooks/useAppUpdater";
import { useI18n } from "../i18n";

const DISMISSED_VERSION_KEY = "echo_dismissed_update_version";

export default function AppUpdateNotice({ onOpenUpdates, hidden = false }: {
  onOpenUpdates: () => void;
  hidden?: boolean;
}) {
  const updater = useAppUpdater();
  const { t } = useI18n();
  const [dismissedVersion, setDismissedVersion] = useState(() => {
    try { return localStorage.getItem(DISMISSED_VERSION_KEY); } catch { return null; }
  });
  const version = updater.updateInfo?.version;
  if (!updater.isElectron || hidden || !version || version === dismissedVersion ||
      !["available", "ready"].includes(updater.phase)) return null;
  const dismiss = () => {
    setDismissedVersion(version);
    try { localStorage.setItem(DISMISSED_VERSION_KEY, version); } catch { /* Session dismissal still works. */ }
  };
  return <aside className="vsUpdateNotice" role="status" aria-label={t("更新提醒", "Update notification")}>
    <Download size={18} aria-hidden="true" />
    <div>
      <p>{updater.phase === "ready" ? t("更新已准备就绪", "Update ready") : t("发现新版本", "Update available")} · {version}</p>
      <button type="button" className="vsBtnGhost" onClick={onOpenUpdates}>
        {t("在设置中查看", "View in Settings")}
      </button>
    </div>
    <button type="button" className="vsBtnGhost" aria-label={t("暂不提醒此版本", "Dismiss this version")}
      onClick={dismiss}><X size={16} aria-hidden="true" /></button>
  </aside>;
}
