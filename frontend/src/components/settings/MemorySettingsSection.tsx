import EvermindBadge from "../EvermindBadge";
import type { UseSettingsResult } from "../../hooks/useSettings";
import SecretInput from "./SecretInput";
import { useI18n } from "../../i18n";

type Props = {
  settings: UseSettingsResult;
};

export default function MemorySettingsSection({ settings }: Props) {
  const { t } = useI18n();

  return (
    <div className="vsSettingsCard vsMemorySection">
      <div className="vsMemoryHero">
        <EvermindBadge variant="light" className="vsMemoryHeroBadge" />
        <div className="vsMemoryHeroCopy">
          <strong>{t("Echo × EverMind", "Echo × EverMind")}</strong>
          <p>
            {t(
              "把品牌放在记忆中心最合适，因为这里是用户真正配置、理解并启用 EverMem 的地方；侧边栏则保留一个运行时状态入口。",
              "The memory center is the right home for the brand because this is where users actually configure, understand, and enable EverMem; the sidebar keeps a smaller runtime status touchpoint.",
            )}
          </p>
        </div>
      </div>
      <div className="vsCardSection">
        <label className="vsToggleLabel">
          <div className="vsToggleInfo">
            <span className="vsToggleTitle">{t("启用长期记忆支持", "Enable Long-Term Memory")}</span>
            <span className="vsToggleDesc">{t("激活与 EverMemOS 的连接通讯。", "Enable the connection to EverMemOS.")}</span>
          </div>
          <input
            type="checkbox"
            className="vsSwitch"
            checked={settings.evermemEnabled}
            onChange={(e) => settings.onEvermemEnabledChange(e.target.checked)}
          />
        </label>
        {settings.evermemEnabled && (
          <label className="vsToggleLabel warning-tint">
            <div className="vsToggleInfo">
              <span className="vsToggleTitle">{t("启用「临时会话」模式", "Enable Temporary Session Mode")}</span>
              <span className="vsToggleDesc">{t("开启后，应用本次运行期间将不检索云端记忆，也不写入任何新记忆记录。", "When enabled, this app run will not read from cloud memory or write new memory records.")}</span>
            </div>
            <input
              type="checkbox"
              className="vsSwitch"
              checked={settings.evermemTempSession}
              onChange={(e) => settings.onEvermemTempSessionChange(e.target.checked)}
            />
          </label>
        )}
      </div>

      {settings.evermemEnabled && (
        <>
          <div className="vsCardSection border-top">
            <div className="vsFormRow">
              <label className="vsField">
                <span className="vsFieldLabel">API URL</span>
                <input
                  className="vsInput"
                  value={settings.evermemApiUrl}
                  onChange={(e) => settings.onEvermemApiUrlChange(e.target.value)}
                  placeholder="https://api.evermind.ai"
                />
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">API Key</span>
                <SecretInput
                  value={settings.evermemApiKey}
                  onChange={settings.onEvermemApiKeyChange}
                  placeholder={t("EverMemOS 访问密钥", "EverMemOS access key")}
                  section="memory_settings"
                  secretKey="api_key"
                />
              </label>
            </div>
            <label className="vsField">
              <span className="vsFieldLabel">{t("Scope ID (留空为默认)", "Scope ID (leave empty for default)")}</span>
              <input
                className="vsInput"
                value={settings.evermemScopeId}
                onChange={(e) => settings.onEvermemScopeIdChange(e.target.value)}
                placeholder={t("指定云端分区作用域", "Specify the cloud memory scope")}
              />
            </label>
          </div>

          <div className="vsCardSection border-top vsMemoryScenes">
            <h3 className="vsCardSubTitle">{t("场景生效控制", "Scene Controls")}</h3>
            <p className="vsFieldHint" style={{ marginBottom: 12 }}>{t("请根据需要勾选以下场景，授权 AI 主动参与学习。", "Enable the scenes where the AI is allowed to learn proactively.")}</p>

            <div className="vsCheckGrid">
              <label className="vsCheckItem">
                <input
                  type="checkbox"
                  checked={settings.evermemRememberChat}
                  onChange={(e) => settings.onEvermemRememberChatChange(e.target.checked)}
                />
                <span>{t("AI 对话助手", "AI Chat Assistant")}</span>
              </label>
              <label className="vsCheckItem">
                <input
                  type="checkbox"
                  checked={settings.evermemRememberVoiceChat}
                  onChange={(e) => settings.onEvermemRememberVoiceChatChange(e.target.checked)}
                />
                <span>{t("实时语音对话", "Realtime Voice Chat")}</span>
              </label>
              <label className="vsCheckItem">
                <input
                  type="checkbox"
                  checked={settings.evermemRememberRecordings}
                  onChange={(e) => settings.onEvermemRememberRecordingsChange(e.target.checked)}
                />
                <span>{t("录音提炼分析任务", "Recording analysis tasks")}</span>
              </label>
              <label className="vsCheckItem">
                <input
                  type="checkbox"
                  checked={settings.evermemStoreTranscript}
                  onChange={(e) => settings.onEvermemStoreTranscriptChange(e.target.checked)}
                />
                <span>{t("全量转写归档存储", "Archive full transcripts")}</span>
              </label>
              <label className="vsCheckItem">
                <input
                  type="checkbox"
                  checked={settings.evermemRememberPodcast}
                  onChange={(e) => settings.onEvermemRememberPodcastChange(e.target.checked)}
                />
                <span>{t("双人播客台本生成", "Two-speaker podcast scripts")}</span>
              </label>
              <label className="vsCheckItem">
                <input
                  type="checkbox"
                  checked={settings.evermemRememberTts}
                  onChange={(e) => settings.onEvermemRememberTtsChange(e.target.checked)}
                />
                <span>{t("纯文本朗读", "Plain text narration")}</span>
              </label>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
