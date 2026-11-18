import { useState } from "react";
import { Globe, Cpu, Brain, Mic, Monitor, AudioLines, ArrowLeft, Flame, Check } from "lucide-react";
import VoiceTrajectoryHeatmap from "../components/VoiceTrajectoryHeatmap";
import ErrorNotice from "../components/ErrorNotice";
import type { UseSettingsResult } from "../hooks/useSettings";
import { useI18n } from "../i18n";
import type { ErrorRuntimeContext } from "../types/ui";
import ProviderSettingsSection from "../components/settings/ProviderSettingsSection";
import TranscriptionSettingsSection from "../components/settings/TranscriptionSettingsSection";
import MemorySettingsSection from "../components/settings/MemorySettingsSection";
import DesktopSettingsSection from "../components/settings/DesktopSettingsSection";
import LocalVoiceSettingsSection from "../components/settings/LocalVoiceSettingsSection";

type Props = {
  onSignIn?: () => void;
  settings: UseSettingsResult;
  errorRuntimeContext?: ErrorRuntimeContext;
  onClose?: () => void;
  initialCategory?: "provider" | "desktop" | "trajectory";
};

type SettingCategory = "general" | "trajectory" | "provider" | "transcription" | "memory" | "desktop" | "local-voice";

export default function SettingsPage({ settings, errorRuntimeContext, onClose, onSignIn, initialCategory = "provider" }: Props) {
  const { t } = useI18n();
  const [activeCategory, setActiveCategory] = useState<SettingCategory>(initialCategory);

  const locked = !settings.settingsData && /AUTH_ADMIN_|AUTH_TOKEN_/.test(settings.settingsError);
  const unavailable = ["provider", "memory", "transcription"].includes(activeCategory) && !settings.settingsData;
  const isProviderWorkspace = activeCategory === "provider" && !unavailable;
  const showFooter = activeCategory !== "trajectory" && activeCategory !== "local-voice";

  const [infoOrigin, setInfoOrigin] = useState<{
    info: string;
    category: SettingCategory;
    provider: string;
  }>(() => ({
    info: settings.settingsInfo,
    category: initialCategory,
    provider: settings.settingsProvider,
  }));

  if (settings.settingsInfo !== infoOrigin.info) {
    setInfoOrigin({
      info: settings.settingsInfo,
      category: activeCategory,
      provider: settings.settingsProvider,
    });
  }

  const visibleSettingsInfo =
    settings.settingsInfo &&
    infoOrigin.category === activeCategory &&
    (activeCategory !== "provider" || infoOrigin.provider === settings.settingsProvider)
      ? settings.settingsInfo
      : "";

  const footerNode = showFooter ? (
    <footer className="vsSettingsFormFooter">
      <div className="vsSettingsFooterStatus" aria-live="polite">
        {settings.settingsSaving ? (
          <span className="status-saving">
            <span className="spinner-mini" /> {t("正在保存配置...", "Saving settings...")}
          </span>
        ) : visibleSettingsInfo ? (
          <span className="status-saved ok">
            <Check size={14} aria-hidden="true" />
            <span>{visibleSettingsInfo}</span>
          </span>
        ) : (
          <span className="status-ready">
            <span className={`vsFooterReadyDot ${settings.settingsData ? "ready" : ""}`} aria-hidden="true" />
            <span>{settings.settingsData ? t("参数配置就绪", "Settings ready") : t("等待加载设置", "Awaiting settings")}</span>
          </span>
        )}
      </div>
      <div className="vsSettingsFooterActions">
        <button
          type="submit"
          className="vsBtnPrimary vsFooterSaveBtn"
          disabled={!settings.settingsData || settings.settingsSaving || settings.settingsBusy}
        >
          {settings.settingsSaving ? t("保存中...", "Saving...") : t("保存", "Save")}
        </button>
      </div>
    </footer>
  ) : null;

  return (
    <div className="vsSettingsLayout">
      {/* ── Left Navigation Sidebar ── */}
      <nav className="vsSettingsNav custom-scrollbar" aria-label={t("设置导航", "Settings navigation")}>
        {onClose && (
          <div className="vsSettingsNavHeader">
            <button
              type="button"
              className="vsSettingsBackBtn"
              onClick={onClose}
              title={t("返回工作区", "Back to Workspace")}
              aria-label={t("返回工作区", "Back to Workspace")}
            >
              <span className="vsSettingsBackIcon" aria-hidden="true">
                <ArrowLeft size={13} />
              </span>
              <span className="vsSettingsBackLabel">{t("返回工作区", "Back to Workspace")}</span>
            </button>
          </div>
        )}

        <div className="vsSettingsNavSection">
          <div className="vsSettingsNavSectionTitle">{t("基础设置", "Basic Settings")}</div>
          <ul className="vsSettingsNavList">
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "general" ? "active" : ""}`}
                onClick={() => setActiveCategory("general")}
              >
                <span className="vsSettingsNavIcon"><Globe size={15} /></span>
                <span className="vsSettingsNavItemTitle">{t("通用", "General")}</span>
              </button>
            </li>
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "trajectory" ? "active" : ""}`}
                onClick={() => setActiveCategory("trajectory")}
              >
                <span className="vsSettingsNavIcon"><Flame size={15} className="vsNavFlameIcon" /></span>
                <span className="vsSettingsNavItemTitle">{t("语音足迹", "Voice Trajectory")}</span>
              </button>
            </li>
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "provider" ? "active" : ""}`}
                onClick={() => setActiveCategory("provider")}
              >
                <span className="vsSettingsNavIcon"><Cpu size={15} /></span>
                <span className="vsSettingsNavItemTitle">{t("提供商", "Providers")}</span>
              </button>
            </li>
          </ul>
        </div>

        <div className="vsSettingsNavSection">
          <div className="vsSettingsNavSectionTitle">{t("Agent 能力", "Agent Capabilities")}</div>
          <ul className="vsSettingsNavList">
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "memory" ? "active" : ""}`}
                onClick={() => setActiveCategory("memory")}
              >
                <span className="vsSettingsNavIcon"><Brain size={15} /></span>
                <span className="vsSettingsNavItemTitle">{t("记忆", "Memory")}</span>
              </button>
            </li>
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "transcription" ? "active" : ""}`}
                onClick={() => setActiveCategory("transcription")}
              >
                <span className="vsSettingsNavIcon"><Mic size={15} /></span>
                <span className="vsSettingsNavItemTitle">{t("转写", "Transcription")}</span>
              </button>
            </li>
          </ul>
        </div>

        <div className="vsSettingsNavSection">
          <div className="vsSettingsNavSectionTitle">{t("系统与环境", "System & Runtime")}</div>
          <ul className="vsSettingsNavList">
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "local-voice" ? "active" : ""}`}
                onClick={() => setActiveCategory("local-voice")}
              >
                <span className="vsSettingsNavIcon"><AudioLines size={15} /></span>
                <span className="vsSettingsNavItemTitle">{t("本地语音", "Local Voice")}</span>
              </button>
            </li>
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "desktop" ? "active" : ""}`}
                onClick={() => setActiveCategory("desktop")}
              >
                <span className="vsSettingsNavIcon"><Monitor size={15} /></span>
                <span className="vsSettingsNavItemTitle">{t("系统", "System")}</span>
              </button>
            </li>
          </ul>
        </div>
      </nav>

      {/* ── Right Content Area ── */}
      <section className={`vsSettingsContent ${activeCategory === "provider" ? "provider-tab" : ""}`}>
        <form className="vsSettingsForm" onSubmit={settings.onSubmit}>
          {isProviderWorkspace ? (
            <>
              <ErrorNotice
                message={settings.settingsError}
                scope="settings"
                context={{
                  ...errorRuntimeContext,
                  provider: settings.settingsProvider,
                  default_model: settings.settingsDefaultModel
                }}
              />
              <fieldset className="vsSettingsFieldset" disabled={settings.settingsSaving}>
                <ProviderSettingsSection settings={settings} footer={footerNode} />
              </fieldset>
            </>
          ) : (
            <>
              <div className="vsSettingsScrollPane custom-scrollbar">
                <div className="vsSettingsPageInner">
                  {activeCategory !== "provider" && (
                    <header className="vsSettingsHeader">
                      <div className="vsSettingsHeadInfo">
                        <h1 className="vsSettingsTitle">
                          {activeCategory === "general" && t("通用偏好", "General Preferences")}
                          {activeCategory === "trajectory" && t("语音学习足迹与打卡", "Voice Practice Trajectory & Streaks")}
                          {activeCategory === "memory" && t("EverMem 长期记忆中心", "EverMem Memory Center")}
                          {activeCategory === "transcription" && t("文件转写与上传配置", "Transcription & Upload Settings")}
                          {activeCategory === "desktop" && t("系统与运行时状态", "System & Runtime Status")}
                          {activeCategory === "local-voice" && t("本地语音模型（免 API Key）", "Local Voice Models (No API Key)")}
                        </h1>
                      </div>
                    </header>
                  )}

                  <ErrorNotice
                    message={unavailable && locked ? "" : settings.settingsError}
                    scope="settings"
                    context={{
                      ...errorRuntimeContext,
                      provider: settings.settingsProvider,
                      default_model: settings.settingsDefaultModel
                    }}
                  />

                  {activeCategory === "general" && (
                    <div className="vsSettingsCard">
                      <div className="vsCardSection">
                        <h3 className="vsCardSubTitle">{t("界面与语言", "Interface and Language")}</h3>
                        <div className="vsFormRow">
                          <label className="vsField">
                            <span className="vsFieldLabel">{t("界面语言", "Display Language")}</span>
                            <select
                              className="vsSelect"
                              value={settings.displayLanguage}
                              onChange={(e) => settings.onDisplayLanguageChange(e.target.value)}
                              disabled={settings.settingsBusy || settings.settingsSaving}
                            >
                              <option value="zh-CN">{t("中文", "Chinese")}</option>
                              <option value="en-US">English</option>
                            </select>
                            <span className="vsFieldHint">{t("切换后当前前端界面会立即刷新文案；保存后会写入全局配置。", "Switching updates the current frontend labels immediately; saving persists it to global config.")}</span>
                          </label>
                        </div>
                      </div>

                      {settings.settingsConfigPath ? (
                        <div className="vsCardSection border-top">
                          <h3 className="vsCardSubTitle">{t("配置与同步", "Config and Sync")}</h3>
                          <div className="vsSystemPath">
                            <span className="vsFieldLabel">{t("当前配置文件", "Current config file")}</span>
                            <code className="vsCodeBlock">{settings.settingsConfigPath}</code>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  )}

                  {activeCategory === "trajectory" && (
                    <div className="vsSettingsCard vsTrajectoryCardShell">
                      <VoiceTrajectoryHeatmap />
                    </div>
                  )}

                  {/* Locked while saving: the save response re-syncs every field, which
                      would silently discard anything typed during the request. */}
                  <fieldset className="vsSettingsFieldset" disabled={settings.settingsSaving}>
                    {unavailable ? (
                      <section className="vsProviderUnavailable" aria-live="polite">
                        <Cpu size={28} aria-hidden="true" />
                        <h2>{settings.settingsBusy ? t("正在读取设置", "Loading settings") : locked ? t("需要管理员权限", "Administrator access required") : t("无法读取设置", "Settings unavailable")}</h2>
                        {locked && <p>{t("请使用管理员账号登录，以查看和管理已保存的 API Key。", "Sign in with an administrator account to manage your saved API keys.")}</p>}
                        {!settings.settingsBusy && <div>
                          {locked && onSignIn && <button type="button" className="vsBtnPrimary" onClick={onSignIn}>{t("管理员登录", "Admin sign-in")}</button>}
                          <button type="button" className="vsBtnSecondary" onClick={() => void settings.onReload()}>{t("重新加载", "Retry")}</button>
                        </div>}
                      </section>
                    ) : null}
                    {!unavailable && activeCategory === "memory" && <MemorySettingsSection settings={settings} />}
                    {!unavailable && activeCategory === "transcription" && <TranscriptionSettingsSection settings={settings} />}
                    {activeCategory === "desktop" && <DesktopSettingsSection settings={settings} />}
                  </fieldset>
                  {activeCategory === "local-voice" && <LocalVoiceSettingsSection />}
                </div>
              </div>
              {footerNode}
            </>
          )}
        </form>
      </section>
    </div>
  );
}
