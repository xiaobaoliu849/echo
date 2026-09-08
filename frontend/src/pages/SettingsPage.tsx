import { useState } from "react";
import { Globe, Cpu, Brain, Mic, Monitor } from "lucide-react";
import ErrorNotice from "../components/ErrorNotice";
import type { UseSettingsResult } from "../hooks/useSettings";
import { useI18n } from "../i18n";
import type { ErrorRuntimeContext } from "../types/ui";
import ProviderSettingsSection from "../components/settings/ProviderSettingsSection";
import TranscriptionSettingsSection from "../components/settings/TranscriptionSettingsSection";
import MemorySettingsSection from "../components/settings/MemorySettingsSection";
import DesktopSettingsSection from "../components/settings/DesktopSettingsSection";

type Props = {
  settings: UseSettingsResult;
  errorRuntimeContext?: ErrorRuntimeContext;
  onClose?: () => void;
};

type SettingCategory = "general" | "provider" | "transcription" | "memory" | "desktop";

export default function SettingsPage({ settings, errorRuntimeContext, onClose }: Props) {
  const { t } = useI18n();
  const [activeCategory, setActiveCategory] = useState<SettingCategory>("provider");

  return (
    <div className="vsSettingsLayout">
      {/* ── Left Navigation ── */}
      <nav className="vsSettingsNav">
        <div className="vsSettingsNavSection">
          <div className="vsSettingsNavSectionTitle">{t("基础设置", "Basic Settings")}</div>
          <ul className="vsSettingsNavList">
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "general" ? "active" : ""}`}
                onClick={() => setActiveCategory("general")}
              >
                <div className="vsSettingsNavIcon">
                  <Globe size={16} />
                </div>
                <div className="vsSettingsNavItemTitle">{t("通用", "General")}</div>
              </button>
            </li>
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "provider" ? "active" : ""}`}
                onClick={() => setActiveCategory("provider")}
              >
                <div className="vsSettingsNavIcon">
                  <Cpu size={16} />
                </div>
                <div className="vsSettingsNavItemTitle">{t("提供商", "Providers")}</div>
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
                <div className="vsSettingsNavIcon">
                  <Brain size={16} />
                </div>
                <div className="vsSettingsNavItemTitle">{t("记忆", "Memory")}</div>
              </button>
            </li>
            <li>
              <button
                type="button"
                className={`vsSettingsNavItem ${activeCategory === "transcription" ? "active" : ""}`}
                onClick={() => setActiveCategory("transcription")}
              >
                <div className="vsSettingsNavIcon">
                  <Mic size={16} />
                </div>
                <div className="vsSettingsNavItemTitle">{t("转写", "Transcription")}</div>
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
                className={`vsSettingsNavItem ${activeCategory === "desktop" ? "active" : ""}`}
                onClick={() => setActiveCategory("desktop")}
              >
                <div className="vsSettingsNavIcon">
                  <Monitor size={16} />
                </div>
                <div className="vsSettingsNavItemTitle">{t("系统", "System")}</div>
              </button>
            </li>
          </ul>
        </div>
      </nav>

      {/* ── Right Content Area ── */}
      <section className={`vsSettingsContent custom-scrollbar ${activeCategory === "provider" ? "provider-tab" : ""}`}>
        <form className="vsSettingsForm" onSubmit={settings.onSubmit}>
          <header className="vsSettingsHeader">
            <div className="vsSettingsHeadInfo">
              <h1 className="vsSettingsTitle">
                {activeCategory === "general" && t("通用偏好", "General Preferences")}
                {activeCategory === "provider" && t("AI 供应商参数", "AI Provider Settings")}
                {activeCategory === "memory" && t("EverMem 长期记忆中心", "EverMem Memory Center")}
                {activeCategory === "transcription" && t("文件转写与上传配置", "Transcription & Upload Settings")}
                {activeCategory === "desktop" && t("系统与运行时状态", "System & Runtime Status")}
              </h1>
            </div>
          </header>

          <ErrorNotice
            message={settings.settingsError}
            scope="settings"
            context={{
              ...errorRuntimeContext,
              provider: settings.settingsProvider,
              default_model: settings.settingsDefaultModel
            }}
          />
          {settings.settingsInfo ? <div className="vsSettingsNotice ok">{settings.settingsInfo}</div> : null}

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

          {activeCategory === "provider" && <ProviderSettingsSection settings={settings} />}
          {activeCategory === "memory" && <MemorySettingsSection settings={settings} />}
          {activeCategory === "transcription" && <TranscriptionSettingsSection settings={settings} />}
          {activeCategory === "desktop" && <DesktopSettingsSection settings={settings} />}

          <footer className="vsSettingsFormFooter">
            <div className="vsSettingsFooterStatus">
              {settings.settingsSaving ? (
                <span className="status-saving">
                  <span className="spinner-mini" /> {t("正在保存配置...", "Saving settings...")}
                </span>
              ) : settings.settingsInfo ? (
                <span className="status-saved ok">✓ {settings.settingsInfo}</span>
              ) : (
                <span className="status-ready">{t("参数配置就绪", "Settings ready")}</span>
              )}
            </div>
            <div className="vsSettingsFooterActions">
              {onClose && (
                <button
                  type="button"
                  className="vsBtnSecondary vsFooterCloseBtn"
                  onClick={onClose}
                  disabled={settings.settingsSaving}
                >
                  {t("关闭", "Close")}
                </button>
              )}
              <button
                type="submit"
                className="vsBtnPrimary vsFooterSaveBtn"
                disabled={settings.settingsSaving || settings.settingsBusy}
              >
                {settings.settingsSaving ? t("保存中...", "Saving...") : t("保存", "Save")}
              </button>
            </div>
          </footer>
        </form>
      </section>
    </div>
  );
}
