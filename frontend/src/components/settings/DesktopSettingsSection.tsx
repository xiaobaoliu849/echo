import { useAppUpdater } from "../../hooks/useAppUpdater";
import type { UseSettingsResult } from "../../hooks/useSettings";
import { useI18n } from "../../i18n";

type Props = {
  settings: UseSettingsResult;
};

// ── helpers ────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── component ──────────────────────────────────────────────────────────────

export default function DesktopSettingsSection({ settings }: Props) {
  const { t } = useI18n();
  const updater = useAppUpdater();

  const desktopSection = settings.desktopSection || {
    backendPhase: "",
    backendStatus: "",
    backendAuthMode: "",
    backendVersion: "",
    preflight: { available: false, ok: false, failed_count: 0, failed_checks: [], timestamp: "" },
    latestError: { available: false, recovery_hints: [], error_type: "", message: "", timestamp: "" },
    diagnosticsDir: "",
  };

  const preflight = desktopSection.preflight || { available: false, ok: false, failed_count: 0, failed_checks: [] };
  const latestError = desktopSection.latestError || { available: false, recovery_hints: [] };

  return (
    <>
      {/* ── Auto-Update Card (Electron only) ── */}
      {updater.isElectron && (
        <div className="vsSettingsCard">
          <div className="vsCardSection">
            <h3 className="vsCardSubTitle">{t("应用更新", "Application Update")}</h3>

            {/* Current version */}
            <div className="vsFormRow">
              <label className="vsField">
                <span className="vsFieldLabel">{t("当前版本", "Current Version")}</span>
                <input
                  className="vsInput"
                  value={updater.appVersion || t("读取中...", "Loading...")}
                  readOnly
                />
              </label>
              {updater.updateInfo?.version && (
                <label className="vsField">
                  <span className="vsFieldLabel">{t("可用新版本", "Available Version")}</span>
                  <input
                    className="vsInput"
                    value={`v${updater.updateInfo.version}`}
                    readOnly
                    style={{ color: "var(--accent, #6ee7b7)" }}
                  />
                </label>
              )}
            </div>

            {/* Status messages */}
            {updater.phase === "checking" && (
              <div className="vsSettingsNotice">
                <span className="spinner-mini" style={{ marginRight: 6 }} />
                {t("正在检查更新...", "Checking for updates...")}
              </div>
            )}
            {updater.phase === "up-to-date" && (
              <div className="vsSettingsNotice ok">
                ✓ {t("当前已是最新版本", "You are on the latest version")}
              </div>
            )}
            {updater.phase === "available" && (
              <div className="vsSettingsNotice ok">
                🎉 {t(
                  `发现新版本 v${updater.updateInfo?.version ?? ""}，点击下方按钮开始下载。`,
                  `New version v${updater.updateInfo?.version ?? ""} is available. Click below to download.`
                )}
              </div>
            )}
            {updater.phase === "downloading" && updater.progress && (
              <div className="vsSettingsNotice" style={{ padding: "10px 14px" }}>
                <div style={{ marginBottom: 6, fontSize: 13 }}>
                  {t("正在下载更新", "Downloading update")}
                  {" — "}
                  {updater.progress.percent.toFixed(1)}%
                  {" ("}
                  {formatBytes(updater.progress.transferred)}
                  {" / "}
                  {formatBytes(updater.progress.total)}
                  {")"}
                </div>
                <div
                  style={{
                    height: 6,
                    borderRadius: 3,
                    background: "var(--border, rgba(255,255,255,0.1))",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${updater.progress.percent}%`,
                      background: "var(--accent, #6ee7b7)",
                      transition: "width 0.3s ease",
                      borderRadius: 3,
                    }}
                  />
                </div>
              </div>
            )}
            {updater.phase === "ready" && (
              <div className="vsSettingsNotice ok">
                ✅ {t("下载完成，点击下方按钮重启安装。", "Download complete. Click below to restart and install.")}
              </div>
            )}
            {updater.phase === "error" && updater.errorMessage && (
              <div className="vsSettingsNotice warning">
                ⚠️ {updater.errorMessage}
              </div>
            )}

            {/* Action buttons */}
            <div className="vsSystemActions" style={{ marginTop: 12 }}>
              {(updater.phase === "idle" ||
                updater.phase === "up-to-date" ||
                updater.phase === "error") && (
                <button
                  type="button"
                  className="vsBtnGhost"
                  onClick={() => void updater.checkForUpdates()}
                >
                  {t("检查更新", "Check for Updates")}
                </button>
              )}
              {updater.phase === "available" && (
                <button
                  type="button"
                  className="vsBtnPrimary"
                  onClick={() => void updater.downloadUpdate()}
                >
                  {t("立即下载", "Download Now")}
                </button>
              )}
              {updater.phase === "ready" && (
                <button
                  type="button"
                  className="vsBtnPrimary"
                  onClick={updater.installNow}
                >
                  {t("重启并安装", "Restart & Install")}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="vsSettingsCard vsDesktopSection">
        <div className="vsCardSection">
          <h3 className="vsCardSubTitle">{t("诊断与底层信息", "Diagnostics & Runtime Details")}</h3>
          <div className="vsFormRow">
            <label className="vsField">
              <span className="vsFieldLabel">{t("后端阶段", "Backend Phase")}</span>
              <input
                className="vsInput"
                value={desktopSection.backendPhase || t("未上报", "Unknown")}
                readOnly
              />
            </label>
            <label className="vsField">
              <span className="vsFieldLabel">{t("运行状态", "Backend Status")}</span>
              <input
                className="vsInput"
                value={desktopSection.backendStatus || t("未知", "Unknown")}
                readOnly
              />
            </label>
          </div>
          <div className="vsFormRow">
            <label className="vsField">
              <span className="vsFieldLabel">{t("鉴权模式", "Auth Mode")}</span>
              <input
                className="vsInput"
                value={desktopSection.backendAuthMode || t("未启用", "Disabled")}
                readOnly
              />
            </label>
            <label className="vsField">
              <span className="vsFieldLabel">{t("版本号", "Version")}</span>
              <input
                className="vsInput"
                value={desktopSection.backendVersion || t("未上报", "Unknown")}
                readOnly
              />
            </label>
          </div>
          <div className="vsSettingsNotice">
            {t(
              "当前桌面壳已具备单实例、原生菜单和窗口状态保存。托盘、全局快捷键、置顶等原生能力先保存配置，后续再接壳层。",
              "The desktop shell already supports single-instance mode, native menus, and window state persistence. Tray, global shortcuts, and always-on-top are stored now and can be wired into the shell later."
            )}
          </div>
          <div className="vsSystemActions">
            <button type="button" className="vsBtnGhost" onClick={settings.onToggleRuntimeOpen}>
              {settings.backendRuntimeOpen
                ? t("隐藏系统运行时日志", "Hide runtime log")
                : t("显示系统运行时日志", "Show runtime log")}
            </button>
            <button
              type="button"
              className="vsBtnGhost"
              onClick={() => void settings.onCopyBackendRuntime()}
            >
              {settings.runtimeCopyStatus === "ok"
                ? t("已复制到剪贴板！", "Copied to clipboard!")
                : t("复制运行时信息", "Copy runtime info")}
            </button>
          </div>
          {settings.runtimeCopyStatus === "fail" && (
            <p className="vsSettingsNotice warning">{t("复制失败，请尝试选取下方文本后手动复制。", "Copy failed. Try selecting the text below and copying it manually.")}</p>
          )}
          {settings.backendRuntimeOpen && (
            <pre className="runtimeDetails">{settings.backendRuntimeRaw}</pre>
          )}

          {settings.settingsConfigPath && (
            <div className="vsSystemPath">
              <span className="vsFieldLabel">{t("全局配置文件宿主路径:", "Config File Path:")}</span>
              <code className="vsCodeBlock">{settings.settingsConfigPath}</code>
            </div>
          )}

          <div className="vsCardSection border-top">
            <h3 className="vsCardSubTitle">{t("最近一次桌面预检", "Latest Desktop Preflight")}</h3>
            <div className={`vsSettingsNotice ${preflight.ok === false ? "warning" : "ok"}`}>
              {!preflight.available && t("尚未生成桌面预检结果。可在桌面菜单中运行预检。", "No desktop preflight result has been generated yet. Run the preflight from the desktop menu.")}
              {preflight.available && preflight.ok === true &&
                t(
                  `桌面预检通过。时间：${preflight.timestamp || "未知"}。`,
                  `Desktop preflight passed. Time: ${preflight.timestamp || "Unknown"}.`
                )}
              {preflight.available && preflight.ok === false &&
                t(
                  `桌面预检存在 ${preflight.failed_count} 个问题。时间：${preflight.timestamp || "未知"}。`,
                  `Desktop preflight found ${preflight.failed_count} issues. Time: ${preflight.timestamp || "Unknown"}.`
                )}
            </div>

            {(preflight.failed_checks || []).length ? (
              <div className="vsSystemPath">
                <span className="vsFieldLabel">{t("失败项摘要", "Failed Checks")}</span>
                <code className="vsCodeBlock">
                  {(preflight.failed_checks || [])
                    .map((item) => `${item.name}: ${item.detail}`)
                    .join("\n")}
                </code>
              </div>
            ) : null}

            {latestError.available ? (
              <div className="vsSystemPath">
                <span className="vsFieldLabel">{t("最近一次启动错误", "Latest Launch Error")}</span>
                <code className="vsCodeBlock">
                  {`${latestError.error_type || "Error"}\n${latestError.message || t("未知错误", "Unknown error")}\n${latestError.timestamp || ""}`.trim()}
                </code>
              </div>
            ) : null}

            {latestError.available &&
            (latestError.recovery_hints || []).length ? (
              <div className="vsSettingsNotice warning">
                <strong>{t("恢复建议", "Recovery Suggestions")}</strong>
                <ul style={{ margin: "8px 0 0 18px" }}>
                  {(latestError.recovery_hints || []).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {desktopSection.diagnosticsDir ? (
              <div className="vsSystemPath">
                <span className="vsFieldLabel">{t("诊断目录", "Diagnostics Directory")}</span>
                <code className="vsCodeBlock">{desktopSection.diagnosticsDir}</code>
              </div>
            ) : null}
          </div>
        </div>

        <div className="vsCardSection border-top">
          <h3 className="vsCardSubTitle">{t("桌面偏好", "Desktop Preferences")}</h3>
          <label className="vsToggleLabel">
            <div className="vsToggleInfo">
              <span className="vsToggleTitle">{t("记住窗口位置", "Remember Window Position")}</span>
              <span className="vsToggleDesc">{t("将桌面窗口位置和尺寸写入配置，用于下次启动恢复。", "Save the desktop window position and size for the next launch.")}</span>
            </div>
            <input
              type="checkbox"
              className="vsSwitch"
              checked={settings.desktopRememberWindowPosition || false}
              onChange={(e) => settings.onDesktopRememberWindowPositionChange(e.target.checked)}
            />
          </label>

          <label className="vsToggleLabel">
            <div className="vsToggleInfo">
              <span className="vsToggleTitle">{t("窗口始终置顶", "Always On Top")}</span>
              <span className="vsToggleDesc">{t("保存桌面置顶偏好，待原生壳层接线后可直接生效。", "Save the always-on-top preference for the native desktop shell.")}</span>
            </div>
            <input
              type="checkbox"
              className="vsSwitch"
              checked={settings.desktopAlwaysOnTop || false}
              onChange={(e) => settings.onDesktopAlwaysOnTopChange(e.target.checked)}
            />
          </label>

          <label className="vsToggleLabel">
            <div className="vsToggleInfo">
              <span className="vsToggleTitle">{t("显示托盘图标", "Show Tray Icon")}</span>
              <span className="vsToggleDesc">{t("保留桌面托盘偏好，后续桌面壳补齐托盘能力时直接复用。", "Persist the tray preference so the native shell can reuse it later.")}</span>
            </div>
            <input
              type="checkbox"
              className="vsSwitch"
              checked={settings.desktopShowTrayIcon || false}
              onChange={(e) => settings.onDesktopShowTrayIconChange(e.target.checked)}
            />
          </label>

          <label className="vsField" style={{ marginTop: 20 }}>
            <span className="vsFieldLabel">{t("唤醒快捷键", "Wake Shortcut")}</span>
            <input
              className="vsInput"
              value={settings.desktopWakeShortcut || ""}
              onChange={(e) => settings.onDesktopWakeShortcutChange(e.target.value)}
              placeholder={t("例如：Alt+Shift+S", "For example: Alt+Shift+S")}
            />
            <span className="vsFieldHint">{t("当前先保存到全局配置，供后续原生全局快捷键接线使用。", "Saved into the global config for future native global shortcut support.")}</span>
          </label>
        </div>
      </div>

      <div className="vsSettingsCard">
        <div className="vsCardSection">
          <h3 className="vsCardSubTitle">{t("开源推荐：VibeVoice TTS", "Open Source Pick: VibeVoice TTS")}</h3>
          <p className="vsFieldHint" style={{ marginTop: 4 }}>
            {t(
              "微软 2025 年开源的 VibeVoice（MIT 协议）支持几秒参考音频即可克隆声音，最长 90 分钟连续合成，可精确控制时间轴与情感。适合本地部署、无 API 成本的场景。",
              "Microsoft's open-source VibeVoice (MIT, 2025) clones voices from a few seconds of reference audio, synthesizes up to 90 minutes of continuous speech with precise timeline and emotion control. Great for on-prem, zero-API-cost deployments."
            )}
          </p>
          <ul style={{ margin: "12px 0 12px 20px", padding: 0, color: "var(--text)", fontSize: "13px", lineHeight: 1.7 }}>
            <li>{t("声音克隆：仅需 3–10 秒参考音频", "Voice cloning: 3–10s reference audio")}</li>
            <li>{t("长音频：支持 90 分钟连续合成", "Long-form: up to 90-minute continuous synthesis")}</li>
            <li>{t("多说话人：同一段文本可切换音色", "Multi-speaker: switch timbres within one text")}</li>
          </ul>
        </div>
      </div>
    </>
  );
}
