import { useState } from "react";
import { Globe, Cpu, Brain, Mic, Monitor, AudioLines, ArrowLeft, Flame, Check, Save } from "lucide-react";
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

const settingsNavigation = [
  {
    label: ["基础设置", "Basic Settings"],
    items: [
      { id: "general", label: ["通用", "General"], icon: Globe },
      { id: "trajectory", label: ["语音足迹", "Voice Trajectory"], icon: Flame },
      { id: "provider", label: ["提供商", "Providers"], icon: Cpu },
    ],
  },
  {
    label: ["Agent 能力", "Agent Capabilities"],
    items: [
      { id: "memory", label: ["记忆", "Memory"], icon: Brain },
      { id: "transcription", label: ["转写", "Transcription"], icon: Mic },
    ],
  },
  {
    label: ["系统与环境", "System & Runtime"],
    items: [
      { id: "local-voice", label: ["本地语音", "Local Voice"], icon: AudioLines },
      { id: "desktop", label: ["系统", "System"], icon: Monitor },
    ],
  },
] as const;

export default function SettingsPage({ settings, errorRuntimeContext, onClose, onSignIn, initialCategory = "provider" }: Props) {
  const { t } = useI18n();
  const [activeCategory, setActiveCategory] = useState<SettingCategory>(initialCategory);

  const locked = !settings.settingsData && /AUTH_ADMIN_|AUTH_TOKEN_/.test(settings.settingsError);
  const unavailable = ["provider", "memory", "transcription"].includes(activeCategory) && !settings.settingsData;

  return (
    <div className="vsSettingsLayout">
      <nav className="vsSettingsNav" aria-label={t("设置", "Settings")}>
        <div className="vsSettingsNavHeader">
          {onClose && (
            <button
              type="button"
              className="vsSettingsBackBtn"
              onClick={onClose}
              title={t("返回工作区", "Back to Workspace")}
              aria-label={t("返回工作区", "Back to Workspace")}
            >
              <ArrowLeft size={16} aria-hidden="true" />
              <span>{t("返回工作区", "Back to Workspace")}</span>
            </button>
          )}
          <p className="vsSettingsNavTitle">{t("设置", "Settings")}</p>
        </div>
        {settingsNavigation.map(({ label, items }) => (
          <div className="vsSettingsNavSection" key={label[1]}>
            <div className="vsSettingsNavSectionTitle">{t(label[0], label[1])}</div>
            <ul className="vsSettingsNavList">
              {items.map(({ id, label: itemLabel, icon: Icon }) => {
                const title = t(itemLabel[0], itemLabel[1]);
                return (
                  <li key={id}>
                    <button
                      type="button"
                      className="vsSettingsNavItem"
                      aria-current={activeCategory === id ? "page" : undefined}
                      title={title}
                      aria-label={title}
                      onClick={() => setActiveCategory(id)}
                    >
                      <Icon size={17} aria-hidden="true" />
                      <span>{title}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* ── Right Content Area ── */}
      <section className={`vsSettingsContent custom-scrollbar ${activeCategory === "provider" ? "provider-tab" : ""}`}>
        <form className="vsSettingsForm" onSubmit={settings.onSubmit}>
          <header className="vsSettingsHeader">
            <div className="vsSettingsHeadInfo">
              <h1 className="vsSettingsTitle">
                {activeCategory === "general" && t("通用偏好", "General Preferences")}
                {activeCategory === "trajectory" && t("语音学习足迹与打卡", "Voice Practice Trajectory & Streaks")}
                {activeCategory === "provider" && t("AI 供应商参数", "AI Provider Settings")}
                {activeCategory === "memory" && t("EverMem 长期记忆中心", "EverMem Memory Center")}
                {activeCategory === "transcription" && t("文件转写与上传配置", "Transcription & Upload Settings")}
                {activeCategory === "desktop" && t("系统与运行时状态", "System & Runtime Status")}
                {activeCategory === "local-voice" && t("本地语音模型（免 API Key）", "Local Voice Models (No API Key)")}
              </h1>
            </div>
          </header>

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

              <div className="vsCardSection border-top">
                <h3 className="vsCardSubTitle">{t("配置与同步", "Config and Sync")}</h3>
                {settings.settingsConfigPath ? (
                  <div className="vsSystemPath">
                    <span className="vsFieldLabel">{t("当前配置文件", "Current config file")}</span>
                    <code className="vsCodeBlock">{settings.settingsConfigPath}</code>
                  </div>
                ) : null}
              </div>
            </div>
          )}

          {activeCategory === "trajectory" && (
            <div className="vsSettingsCard" style={{ padding: "0", background: "transparent", border: "none", boxShadow: "none" }}>
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
                  <button type="button" onClick={() => void settings.onReload()}>{t("重新加载", "Retry")}</button>
                </div>}
              </section>
            ) : activeCategory === "provider" && <ProviderSettingsSection settings={settings} />}
            {!unavailable && activeCategory === "memory" && <MemorySettingsSection settings={settings} />}
            {!unavailable && activeCategory === "transcription" && <TranscriptionSettingsSection settings={settings} />}
            {activeCategory === "desktop" && <DesktopSettingsSection settings={settings} />}
          </fieldset>
          {activeCategory === "local-voice" && <LocalVoiceSettingsSection />}

          {(activeCategory !== "trajectory" || settings.settingsSaving || settings.settingsInfo) && <footer className="vsSettingsFormFooter">
            <div className="vsSettingsFooterStatus" role="status">
              {settings.settingsSaving ? (
                <span className="status-saving">
                  <span className="spinner-mini" aria-hidden="true" /> {t("正在保存配置...", "Saving settings...")}
                </span>
              ) : settings.settingsInfo ? (
                <span className="status-saved"><Check size={15} aria-hidden="true" />{settings.settingsInfo}</span>
              ) : null}
            </div>
            {activeCategory !== "trajectory" && (
              <div className="vsSettingsFooterActions">
                <button
                  type="submit"
                  className="vsBtnPrimary vsFooterSaveBtn"
                  disabled={!settings.settingsData || settings.settingsSaving || settings.settingsBusy}
                >
                  <Save size={16} aria-hidden="true" />
                  {settings.settingsSaving ? t("保存中...", "Saving...") : t("保存", "Save")}
                </button>
              </div>
            )}
          </footer>}
        </form>
      </section>
    </div>
  );
}
