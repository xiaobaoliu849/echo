import { useState, useMemo, ReactNode } from "react";
import { Terminal, Brain } from "lucide-react";
import type { UseSettingsResult } from "../../hooks/useSettings";
import { PROVIDER_API_KEY_FIELD } from "../../hooks/useSettings";
import SecretInput from "./SecretInput";
import { useI18n } from "../../i18n";

type Props = {
  settings: UseSettingsResult;
};

const getProviderDisplayNames = (t: (zh: string, en: string) => string): Record<string, string> => ({
  DashScope: t("阿里云 DashScope", "Alibaba DashScope"),
  DeepSeek: t("DeepSeek 深度求索", "DeepSeek"),
  Google: t("Google Gemini", "Google Gemini"),
  Groq: t("Groq 极速 API", "Groq Fast API"),
  OpenRouter: t("OpenRouter 聚合", "OpenRouter Aggregator"),
  SiliconFlow: t("硅基流动 SiliconFlow", "SiliconFlow"),
  Xiaomi: t("小米 mimo", "Xiaomi mimo"),
  OpenAI: t("OpenAI", "OpenAI"),
  ElevenLabs: t("ElevenLabs TTS", "ElevenLabs TTS"),
  Ollama: t("本地 Ollama", "Local Ollama"),
  Deepgram: t("Deepgram ASR", "Deepgram ASR"),
  "GPT-SoVITS": t("本地 GPT-SoVITS API", "Local GPT-SoVITS API"),
  Tavus: t("Tavus 视频分身", "Tavus Video PAL"),
});

const getLobeProviderKey = (name: string): string => {
  let lower = (name || "").toLowerCase();
  if (lower.startsWith("custom_")) {
    lower = lower.substring(7);
  }
  if (lower.includes("dashscope")) return "qwen";
  if (lower.includes("siliconflow")) return "siliconcloud";
  if (lower === "xiaomi") return "xiaomimimo";
  if (lower === "google") return "google";
  if (lower === "openai") return "openai";
  if (lower === "anthropic") return "anthropic";
  if (lower === "deepseek") return "deepseek";
  if (lower === "nvidia") return "nvidia";
  if (lower === "groq") return "groq";
  if (lower === "openrouter") return "openrouter";
  if (lower === "zenmux") return "zenmux";
  if (lower === "ollama") return "ollama";
  if (lower === "deepgram") return "deepgram";
  if (lower === "tavus") return "tavus";
  return lower;
};

const PROVIDER_COLORS: Record<string, string> = {
  qwen: "#6366f1", deepseek: "#4f46e5", google: "#4285f4", openai: "#10a37f",
  groq: "#f55036", openrouter: "#8b5cf6", siliconcloud: "#7c3aed",
  xiaomimimo: "#ff6900", anthropic: "#d4a574", nvidia: "#76b900",
  ollama: "#6b7280", deepgram: "#13ef93", zenmux: "#a855f7", tavus: "#6c5ce7",
};

const LocalProviderIcon = ({ provider, size = 18 }: { provider: string; size?: number }) => (
  <span style={{
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    width: size, height: size, borderRadius: "50%", flexShrink: 0,
    backgroundColor: PROVIDER_COLORS[provider] || "#6b7280", color: "#fff",
    fontSize: size * 0.55, fontWeight: 700, lineHeight: 1,
  }}>
    {(provider || "").charAt(0).toUpperCase()}
  </span>
);

export const renderProviderIcon = (providerName: string): ReactNode => {
  if (!providerName) return null;
  if (providerName.includes("(ACP)")) {
    return <Terminal size={18} />;
  }
  if (providerName === "GPT-SoVITS") {
    return <Brain size={18} />;
  }
  const key = getLobeProviderKey(providerName);
  return <LocalProviderIcon provider={key} size={18} />;
};

export default function ProviderSettingsSection({ settings }: Props) {
  const { t } = useI18n();
  const [modelSearch, setModelSearch] = useState("");
  const [showRawModels, setShowRawModels] = useState(false);
  const [ttsModelSearch, setTtsModelSearch] = useState("");
  const [showRawTtsModels, setShowRawTtsModels] = useState(false);
  const [providerSearch, setProviderSearch] = useState("");

  const [showAddCustomModal, setShowAddCustomModal] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [customApiKey, setCustomApiKey] = useState("");
  const [customUseMaxTokens, setCustomUseMaxTokens] = useState(false);
  const [customHeadersJson, setCustomHeadersJson] = useState("{}");
  const [customModalError, setCustomModalError] = useState("");

  const providerDisplayNames = useMemo(() => {
    const base = getProviderDisplayNames(t);
    const customList = settings.customProviders || [];
    for (const cp of customList) {
      if (cp && cp.id) {
        base[cp.id] = cp.name;
      }
    }
    return base;
  }, [t, settings.customProviders]);

  const providerOptions = settings.providerOptions || [];
  const catalog = settings.providerModelCatalog || {};
  const availableModels = settings.settingsAvailableModels || [];
  const ttsAvailableModels = settings.settingsTtsAvailableModels || [];
  const isTtsSupported =
    ["DashScope", "MiniMax", "Xiaomi", "OpenAI", "ElevenLabs", "Cartesia"].includes(settings.settingsProvider) ||
    ttsAvailableModels.length > 0;

  return (
    <div className="vsProviderSettingsGrid">
      {/* Middle Column: Providers List */}
      <div className="vsProviderListColumn">
        <div className="vsProviderSearchBar">
          <span className="vsProviderSearchIcon">🔍</span>
          <input
            type="text"
            value={providerSearch}
            onChange={(e) => setProviderSearch(e.target.value)}
            placeholder={t("搜索供应商...", "Search providers...")}
          />
        </div>
        <button
          type="button"
          className="vsBtnSecondary vsBtnSmall"
          style={{ margin: "0 12px 12px 12px", display: "flex", justifyContent: "center", alignItems: "center", gap: "4px", padding: "6px 10px", height: "32px", fontSize: "13px" }}
          onClick={() => {
            setCustomName("");
            setCustomBaseUrl("");
            setCustomApiKey("");
            setCustomUseMaxTokens(false);
            setCustomHeadersJson("{}");
            setCustomModalError("");
            setShowAddCustomModal(true);
          }}
        >
          ➕ {t("添加自定义服务商", "Add Custom Provider")}
        </button>
        <div className="vsProviderSelectGroup">
          {providerOptions
            .filter(name => {
              if (!providerSearch.trim()) return true;
              const q = providerSearch.toLowerCase();
              return name.toLowerCase().includes(q) || (providerDisplayNames[name] || "").toLowerCase().includes(q);
            })
            .map((providerName) => {
            const isActive = settings.settingsProvider === providerName;
            const hasKey = !!catalog[providerName]?.defaultModel || 
              (catalog[providerName]?.availableModels && (catalog[providerName]?.availableModels?.length ?? 0) > 0);
            
            return (
              <button
                key={providerName}
                type="button"
                className={`vsProviderSelectorItem ${isActive ? "active" : ""}`}
                onClick={() => settings.onProviderChange(providerName)}
              >
                <div className="vsProviderSelectorMeta">
                  <span className="vsProviderItemIcon">{renderProviderIcon(providerName)}</span>
                  <span className="vsProviderNameText">{providerDisplayNames[providerName] || providerName}</span>
                </div>
                <span className={`vsActiveDot ${hasKey ? "" : "inactive"}`} title={hasKey ? t("已配置", "Configured") : t("未配置", "Not configured")} />
              </button>
            );
          })}
        </div>
      </div>

      {/* Right Column: Config Details */}
      <div className="vsProviderConfigColumn">
        <div className="vsProviderConfigHeader">
          <div className="vsProviderConfigTitleRow" style={{ width: "100%", display: "flex", alignItems: "center" }}>
            <h2 className="vsProviderConfigTitle" style={{ display: "flex", alignItems: "center" }}>
              {providerDisplayNames[settings.settingsProvider] || settings.settingsProvider}
              {settings.isCustomProvider && (
                <span style={{ fontSize: "11px", marginLeft: "8px", padding: "2px 6px", borderRadius: "4px", backgroundColor: "#e0e7ff", color: "#3730a3", fontWeight: "normal" }}>CUSTOM</span>
              )}
            </h2>
            {settings.settingsApiKey
              ? <span className="vsProviderStatusBadge active">{t("活跃", "Active")}</span>
              : <span className="vsProviderStatusBadge">{t("未激活", "Inactive")}</span>}
            {settings.isCustomProvider && (
              <button
                type="button"
                className="vsBtnSecondary vsBtnSmall"
                style={{ marginLeft: "auto", backgroundColor: "#fee2e2", color: "#991b1b", border: "1px solid #fca5a5", padding: "4px 8px" }}
                onClick={() => {
                  if (confirm(t(`确定要删除服务商 "${providerDisplayNames[settings.settingsProvider]}" 吗？`, `Are you sure you want to delete provider "${providerDisplayNames[settings.settingsProvider]}"?`))) {
                    void settings.onDeleteCustomProvider(settings.settingsProvider);
                  }
                }}
              >
                🗑️ {t("删除服务商", "Delete Provider")}
              </button>
            )}
          </div>
        </div>

        <div className="vsProviderConfigFields">
          <label className="vsField">
            <span className="vsFieldLabel">
              {settings.settingsProvider === "Doubao"
                ? t("API Key（火山方舟 · 文字聊天模型）", "API Key (Ark · text chat models)")
                : "API Key"}
            </span>
            <SecretInput
              value={settings.settingsApiKey || ""}
              onChange={settings.onApiKeyChange}
              placeholder={settings.settingsProvider === "Doubao"
                ? t("ark- 开头，仅用于文字聊天；实时语音用下面的 Access Token", "ark- key, text chat only; realtime voice uses the Access Token below")
                : t("输入供应商 API Key", "Enter your API key")}
              section="api_keys"
              secretKey={PROVIDER_API_KEY_FIELD[settings.settingsProvider] || ""}
              customProviderId={settings.isCustomProvider ? settings.settingsProvider : undefined}
            />
          </label>

          {settings.settingsProvider === "Tavus" && (
            <label className="vsField">
              <span className="vsFieldLabel">{t("默认 PAL ID (分身 ID，可选)", "Default PAL ID (Optional)")}</span>
              <input
                className="vsInput"
                value={settings.settingsTavusPalId || ""}
                onChange={(e) => settings.onTavusPalIdChange?.(e.target.value)}
                placeholder={t("留空则在视频分身页面自动列出或手动输入", "Leave empty to list PALs or select in Video PAL page")}
              />
              <span className="vsFieldHint">
                {t(
                  "可选配置。在 platform.tavus.io 创建分身 (PAL)，保存后将作为视频通话的默认分身。",
                  "Optional. Created on platform.tavus.io. When set, used as the default avatar for video calls."
                )}
              </span>
            </label>
          )}

          {settings.settingsProvider !== "Tavus" && (
            <label className="vsField">
              <span className="vsFieldLabel">Base URL ({t("可选", "Optional")})</span>
              <input
                className="vsInput"
                value={settings.settingsApiUrl || ""}
                onChange={(e) => settings.onApiUrlChange(e.target.value)}
                placeholder={t("留空则使用默认地址", "Leave empty to use the default URL")}
              />
              <span className="vsFieldHint">{t("留空则使用该供应商的默认 API 端点", "Leave empty to use the default API endpoint for this provider")}</span>
            </label>
          )}

          {settings.settingsProvider === "Google" && (
            <div className="vsSettingsNotice ok" style={{ marginTop: 8, fontSize: 13, lineHeight: 1.6 }}>
              <div><strong>{t("💡 Google Gemini 双模式已全面支持：", "💡 Google Gemini Dual Mode Supported:")}</strong></div>
              <div style={{ marginTop: 4 }}>• 🟢 <strong>Google AI Studio Key（AIzaSy... 开头）</strong>：{t("用于实时双向语音通话（gemini-3.1-flash-live-preview）、实时同传（gemini-3.5-live-translate-preview），走每日免费配额。", "Used for realtime voice chat (gemini-3.1-flash-live-preview), live translation, with daily free quota.")}</div>
              <div style={{ marginTop: 2 }}>• 🔵 <strong>Google Cloud Vertex AI Key（AQ... 开头）</strong>：{t("用于流式打字聊天与大模型推理（gemini-2.5-flash / gemini-2.5-pro），100% 消耗您的 $340 美元赠金！", "Used for streaming chat & reasoning (gemini-2.5-flash / pro), billing directly to your $340 Google Cloud credits!")}</div>
            </div>
          )}

          {settings.settingsProvider === "DashScope" && (
            <label className="vsField">
              <span className="vsFieldLabel">Qwen Realtime WebSocket URL</span>
              <input
                className="vsInput"
                value={settings.settingsRealtimeApiUrl || ""}
                onChange={(e) => settings.onRealtimeApiUrlChange(e.target.value)}
                placeholder="wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
              />
              <span className="vsFieldHint">
                {t(
                  "Qwen 3.5 Omni Realtime 必须使用百炼业务空间的 WebSocket 地址。",
                  "Qwen 3.5 Omni Realtime requires the WebSocket URL for your Model Studio workspace."
                )}{" "}
                <a
                  href="https://help.aliyun.com/zh/model-studio/realtime"
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("查看官方配置说明", "Open the official setup guide")}
                </a>
              </span>
            </label>
          )}

          {settings.settingsProvider === "Doubao" && (
            <>
              <label className="vsField">
                <span className="vsFieldLabel">{t("API Key / Access Token（豆包语音 · 实时语音必填）", "API Key / Access Token (Doubao Voice · required for Realtime)")}</span>
                <SecretInput
                  value={settings.settingsDoubaoAccessToken || ""}
                  onChange={settings.onDoubaoAccessTokenChange}
                  placeholder={t("新版控制台「API Key 管理」的 API Key", "API Key from the new console's API Key management page")}
                  section="api_keys"
                  secretKey="doubao_access_token"
                />
                <span className="vsFieldHint">
                  {t(
                    "实时语音只需新版控制台「API Key 管理」的 API Key（UUID 格式，无需 APP ID）。TTS 语音合成仍需旧版控制台的 Access Token，与下方 APP ID 配对。与上面的文本聊天 Key 是两套体系。",
                    "Realtime voice only needs an API Key from the new console's API Key management page (UUID format, no APP ID). TTS synthesis still requires a legacy-console Access Token paired with the APP ID below. Separate from the text-chat key above."
                  )}
                </span>
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">{t("豆包语音 APP ID（仅 TTS 语音合成需要）", "Doubao Voice APP ID (only needed for TTS)")}</span>
                <SecretInput
                  value={settings.settingsDoubaoAppId || ""}
                  onChange={settings.onDoubaoAppIdChange}
                  placeholder={t("火山引擎「豆包语音」控制台概览页的 APP ID", "APP ID from the Volcengine Doubao Voice console overview page")}
                  section="api_keys"
                  secretKey="doubao_app_id"
                />
                <span className="vsFieldHint">
                  {t(
                    "实时语音无需填写此项。仅 TTS 语音合成需要：与旧版控制台的 Access Token 成对使用（概览页可查）。",
                    "Not needed for realtime voice. Only TTS synthesis needs it, paired with a legacy-console Access Token (see the console overview page)."
                  )}{" "}
                  <a
                    href="https://console.volcengine.com/speech/new/setting/apikeys"
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("打开新版控制台 API Key 管理", "Open new-console API Key management")}
                  </a>
                </span>
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">{t("融合信息搜索 API Key（可选，开启联网）", "Web Search API Key (optional, enables online search)")}</span>
                <SecretInput
                  value={settings.settingsDoubaoWebsearchKey || ""}
                  onChange={settings.onDoubaoWebsearchKeyChange}
                  placeholder={t("火山引擎「融合信息搜索」服务的 API Key", "API Key of the Volcengine fused web search service")}
                  section="api_keys"
                  secretKey="doubao_websearch_api_key"
                />
                <span className="vsFieldHint">
                  {t(
                    "不填则模型无法联网，天气/新闻等实时问题会凭空编造；填写后自动开启内置联网搜索。",
                    "Without it the model cannot go online and will fabricate answers for weather/news; once filled, built-in web search is enabled automatically."
                  )}
                </span>
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">{t("实时语音 WebSocket URL（可选）", "Realtime WebSocket URL (optional)")}</span>
                <input
                  className="vsInput"
                  value={settings.settingsRealtimeApiUrl || ""}
                  onChange={(e) => settings.onRealtimeApiUrlChange(e.target.value)}
                  placeholder="wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
                />
                <span className="vsFieldHint">
                  {t("留空则使用豆包端到端实时语音-全双工版本官方地址。", "Leave empty to use the official Doubao full-duplex realtime dialogue endpoint.")}
                </span>
              </label>
            </>
          )}

          {settings.isCustomProvider && (
            <>
              <label className="vsField">
                <span className="vsFieldLabel">{t("使用 max_completion_tokens", "Use max_completion_tokens")}</span>
                <div style={{ display: "flex", alignItems: "center", marginTop: "6px" }}>
                  <input
                    type="checkbox"
                    checked={settings.settingsProviderUseMaxCompletionTokens || false}
                    onChange={(e) => settings.onUseMaxCompletionTokensChange(e.target.checked)}
                    style={{ width: "16px", height: "16px", cursor: "pointer" }}
                  />
                  <span style={{ marginLeft: "8px", fontSize: "12px", color: "#666" }}>
                    {t("针对 o1, o3-mini 等新大模型启用，使用 max_completion_tokens 代替 max_tokens", "Enable for newer models like o1, o3-mini, using max_completion_tokens instead of max_tokens")}
                  </span>
                </div>
              </label>

              <label className="vsField">
                <span className="vsFieldLabel">{t("自定义请求头 (JSON 可选)", "Custom Headers (JSON Optional)")}</span>
                <textarea
                  className="vsInput"
                  style={{ fontFamily: "monospace", minHeight: "60px", fontSize: "13px", padding: "8px" }}
                  value={settings.settingsProviderHeadersJson || "{}"}
                  onChange={(e) => settings.onHeadersJsonChange(e.target.value)}
                  placeholder='{ "User-Agent": "my-client/1.0" }'
                />
              </label>
            </>
          )}

          {settings.settingsProvider !== "Deepgram" && settings.settingsProvider !== "OpenAI" && settings.settingsProvider !== "Tavus" && (
            <label className="vsField">
              <span className="vsFieldLabel">{t("默认主模型", "Default Model")}</span>
              <select
                className="vsSelect"
                value={settings.settingsDefaultModel || ""}
                onChange={(e) => settings.onDefaultModelChange(e.target.value)}
                disabled={settings.settingsBusy || settings.settingsSaving}
              >
                <option value="">{t("-- 请选择 --", "-- Select --")}</option>
                {availableModels.map((modelId) => (
                  <option key={modelId} value={modelId}>
                    {modelId}
                  </option>
                ))}
              </select>
            </label>
          )}

          {isTtsSupported && (
            <label className="vsField">
              <span className="vsFieldLabel">{t("默认 TTS 语音模型", "Default TTS Model")}</span>
              {ttsAvailableModels.length > 0 ? (
                <select
                  className="vsSelect"
                  value={settings.settingsTtsDefaultModel || ""}
                  onChange={(e) => settings.onTtsDefaultModelChange?.(e.target.value)}
                  disabled={settings.settingsBusy || settings.settingsSaving}
                >
                  <option value="">{t("-- 请选择或使用默认 --", "-- Select or use default --")}</option>
                  {ttsAvailableModels.map((modelId) => (
                    <option key={modelId} value={modelId}>
                      {modelId}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="vsInput"
                  value={settings.settingsTtsDefaultModel || ""}
                  onChange={(e) => settings.onTtsDefaultModelChange?.(e.target.value)}
                  placeholder={t("输入或选择 TTS 模型 ID", "Enter or select TTS model ID")}
                />
              )}
              <span className="vsFieldHint">
                {t(
                  "用于语音中心合成的标准 TTS 模型 (例如 sonic-preview, qwen-audio-3.0-tts-flash, speech-02-hd, tts-1-hd 等)",
                  "Model used for Voice Center synthesis (e.g. sonic-preview, qwen-audio-3.0-tts-flash, speech-02-hd, tts-1-hd, etc.)"
                )}
              </span>
            </label>
          )}
        </div>

        {/* Model Management Section */}
        {settings.settingsProvider === "Tavus" ? (
          <div className="vsProviderModelSection">
            <div className="vsSettingsNotice ok">
              {t(
                "Tavus 是实时视频分身对话引擎 (Conversational Video Interface)，支持与数字人进行低延迟双向音视频通话。配置 API Key 后，可在左侧导航栏的「视频分身 (Video PAL)」页面直接开启实时视频对话。",
                "Tavus provides real-time Conversational Video Interface (CVI) for interactive video avatars. After configuring your API Key, head to the \"Video PAL\" page in the sidebar to start a real-time video conversation."
              )}
            </div>
          </div>
        ) : settings.settingsProvider === "Deepgram" || settings.settingsProvider === "OpenAI" ? (
          <div className="vsProviderModelSection">
            <div className="vsSettingsNotice ok">
              {settings.settingsProvider === "Deepgram"
                ? t("Deepgram 用于语音识别 (ASR)，使用 nova-3 模型，支持精确单词级时间戳。", "Deepgram is used for speech recognition (ASR) with the nova-3 model, supporting precise word-level timestamps.")
                : t("OpenAI 用于语音识别 (ASR)，使用 Whisper 模型。", "OpenAI is used for speech recognition (ASR) with the Whisper model.")}
            </div>
          </div>
        ) : (
          <div className="vsProviderModelSection" style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {/* LLM / Chat Models Section */}
            <div className="vsModelCardSection">
              <div className="vsModelManagerHeader" style={{ flexWrap: "wrap", gap: "8px", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <h3 className="vsCardSubTitle" style={{ margin: 0 }}>
                    {t(
                      `💬 对话 / 大语言模型 (已启用 ${(settings.settingsEnabledModels || []).length} / 共 ${availableModels.length})`,
                      `💬 LLM Models (Enabled ${(settings.settingsEnabledModels || []).length} / Total ${availableModels.length})`
                    )}
                  </h3>
                  {availableModels.length > 0 && (
                    <div style={{ display: "flex", gap: "4px" }}>
                      <button
                        type="button"
                        className="vsBtnSecondary vsBtnSmall"
                        style={{ padding: "2px 8px", height: "26px", fontSize: "12px" }}
                        onClick={() => settings.onEnableAllModels()}
                        title={t("启用当前所有可用对话模型", "Enable all available LLM models")}
                      >
                        {t("全选", "All")}
                      </button>
                      <button
                        type="button"
                        className="vsBtnSecondary vsBtnSmall"
                        style={{ padding: "2px 8px", height: "26px", fontSize: "12px" }}
                        onClick={() => settings.onDisableAllModels()}
                        title={t("取消启用所有对话模型", "Disable all LLM models")}
                      >
                        {t("清空", "Clear")}
                      </button>
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  <input
                    type="text"
                    className="vsInput vsInputSmall"
                    style={{ width: "150px" }}
                    value={modelSearch}
                    onChange={(e) => setModelSearch(e.target.value)}
                    placeholder={t("筛选对话模型...", "Filter LLM models...")}
                  />
                  <button
                    type="button"
                    className="vsBtnSecondary vsBtnSmall"
                    style={{ whiteSpace: "nowrap", flexShrink: 0, padding: "0 12px", height: "32px", display: "inline-flex", alignItems: "center", gap: "4px" }}
                    onClick={() => void settings.onFetchModels()}
                    disabled={settings.settingsFetchingModels || settings.settingsBusy}
                  >
                    {settings.settingsFetchingModels ? t("拉取中...", "Fetching...") : t("🔄 自动获取", "🔄 Auto Fetch")}
                  </button>
                </div>
              </div>

              <div className="vsModelListContainer">
                {availableModels
                  .filter(m => !modelSearch.trim() || m.toLowerCase().includes(modelSearch.toLowerCase()))
                  .map((modelId) => (
                    <div key={modelId} className="vsModelListItem">
                      <span className="vsModelListItemName" title={modelId}>{modelId}</span>
                      {settings.settingsDefaultModel === modelId && (
                        <span className="vsModelListItemTag default">{t("默认", "Default")}</span>
                      )}
                      <input
                        type="checkbox"
                        className="vsSwitch vsSwitchSmall"
                        checked={(settings.settingsEnabledModels || []).includes(modelId)}
                        onChange={() => settings.onToggleModelEnabled(modelId)}
                      />
                    </div>
                  ))}
                {availableModels.length === 0 && (
                  <div className="vsModelListEmpty">
                    {t("暂无对话模型。点击“自动获取”或手动输入添加。", "No LLM models configured. Click Auto Fetch or enter manually.")}
                  </div>
                )}
              </div>

              <button
                type="button"
                className="vsRawModelsToggle"
                onClick={() => setShowRawModels(v => !v)}
              >
                {showRawModels
                  ? t("▾ 收起手动编辑", "▾ Hide raw editor")
                  : t("▸ 手动编辑可用模型（高级）", "▸ Edit raw models (advanced)")}
              </button>
              {showRawModels && (
                <div style={{ marginTop: 8 }}>
                  <textarea
                    className="vsTextarea"
                    rows={4}
                    value={settings.settingsAvailableModelsText || ""}
                    onChange={(e) => settings.onAvailableModelsChange(e.target.value)}
                    placeholder={"model-a\nmodel-b"}
                  />
                </div>
              )}
            </div>

            {/* TTS Models Management (when supported or present) */}
            {isTtsSupported && (
              <div className="vsModelCardSection" style={{ marginTop: "4px", paddingTop: "12px", borderTop: "1px dashed var(--line)" }}>
                <div className="vsModelManagerHeader" style={{ flexWrap: "wrap", gap: "8px", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <h3 className="vsCardSubTitle" style={{ margin: 0 }}>
                      {t(
                        `🔊 TTS 语音合成模型 (已启用 ${(settings.settingsTtsEnabledModels || []).length} / 共 ${ttsAvailableModels.length})`,
                        `🔊 TTS Models (Enabled ${(settings.settingsTtsEnabledModels || []).length} / Total ${ttsAvailableModels.length})`
                      )}
                    </h3>
                    {ttsAvailableModels.length > 0 && (
                      <div style={{ display: "flex", gap: "4px" }}>
                        <button
                          type="button"
                          className="vsBtnSecondary vsBtnSmall"
                          style={{ padding: "2px 8px", height: "26px", fontSize: "12px" }}
                          onClick={() => settings.onEnableAllTtsModels?.()}
                          title={t("启用当前所有可用 TTS 语音模型", "Enable all available TTS models")}
                        >
                          {t("全选", "All")}
                        </button>
                        <button
                          type="button"
                          className="vsBtnSecondary vsBtnSmall"
                          style={{ padding: "2px 8px", height: "26px", fontSize: "12px" }}
                          onClick={() => settings.onDisableAllTtsModels?.()}
                          title={t("取消启用所有 TTS 语音模型", "Disable all TTS models")}
                        >
                          {t("清空", "Clear")}
                        </button>
                      </div>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                    <input
                      type="text"
                      className="vsInput vsInputSmall"
                      style={{ width: "150px" }}
                      value={ttsModelSearch}
                      onChange={(e) => setTtsModelSearch(e.target.value)}
                      placeholder={t("筛选 TTS 模型...", "Filter TTS models...")}
                    />
                  </div>
                </div>

                <div className="vsModelListContainer">
                  {ttsAvailableModels
                    .filter(m => !ttsModelSearch.trim() || m.toLowerCase().includes(ttsModelSearch.toLowerCase()))
                    .map((modelId) => (
                      <div key={modelId} className="vsModelListItem">
                        <span className="vsModelListItemName" title={modelId}>{modelId}</span>
                        {settings.settingsTtsDefaultModel === modelId && (
                          <span className="vsModelListItemTag default">{t("默认", "Default")}</span>
                        )}
                        <input
                          type="checkbox"
                          className="vsSwitch vsSwitchSmall"
                          checked={(settings.settingsTtsEnabledModels || []).includes(modelId)}
                          onChange={() => settings.onToggleTtsModelEnabled?.(modelId)}
                        />
                      </div>
                    ))}
                  {ttsAvailableModels.length === 0 && (
                    <div className="vsModelListEmpty">
                      {t("暂无 TTS 语音模型。点击上方“自动获取”或手动输入添加。", "No TTS models configured. Click Auto Fetch or enter manually.")}
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  className="vsRawModelsToggle"
                  onClick={() => setShowRawTtsModels(v => !v)}
                >
                  {showRawTtsModels
                    ? t("▾ 收起手动编辑", "▾ Hide raw editor")
                    : t("▸ 手动编辑可用 TTS 模型（高级）", "▸ Edit raw TTS models (advanced)")}
                </button>
                {showRawTtsModels && (
                  <div style={{ marginTop: 8 }}>
                    <textarea
                      className="vsTextarea"
                      rows={3}
                      value={settings.settingsTtsAvailableModelsText || ""}
                      onChange={(e) => settings.onTtsAvailableModelsChange?.(e.target.value)}
                      placeholder={"sonic-preview\nsonic-3.5\nsonic-3"}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Modal: Add Custom Provider */}
      {showAddCustomModal && (
        <div className="vsModalOverlay">
          <div className="vsModalCard" style={{ maxWidth: "480px" }}>
            <h3 className="vsModalTitle">{t("添加自定义 OpenAI 兼容服务商", "Add Custom OpenAI-Compatible Provider")}</h3>
            {customModalError && (
              <div className="vsSettingsNotice warning" style={{ marginBottom: "12px" }}>
                {customModalError}
              </div>
            )}
            <div className="vsFormRow" style={{ flexDirection: "column", gap: "12px" }}>
              <label className="vsField">
                <span className="vsFieldLabel">{t("服务商名称 (英文/中文)", "Provider Name")}</span>
                <input
                  className="vsInput"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  placeholder={t("例如: MyLocalOllama", "e.g. MyLocalOllama")}
                />
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">Base URL</span>
                <input
                  className="vsInput"
                  value={customBaseUrl}
                  onChange={(e) => setCustomBaseUrl(e.target.value)}
                  placeholder="https://api.example.com/v1"
                />
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">API Key</span>
                <input
                  className="vsInput"
                  type="password"
                  value={customApiKey}
                  onChange={(e) => setCustomApiKey(e.target.value)}
                  placeholder={t("输入 API Key (若无需可留空)", "API Key (optional)")}
                />
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">{t("使用 max_completion_tokens", "Use max_completion_tokens")}</span>
                <div style={{ display: "flex", alignItems: "center", marginTop: "4px" }}>
                  <input
                    type="checkbox"
                    checked={customUseMaxTokens}
                    onChange={(e) => setCustomUseMaxTokens(e.target.checked)}
                    style={{ width: "16px", height: "16px", cursor: "pointer" }}
                  />
                  <span style={{ marginLeft: "8px", fontSize: "12px", color: "#666" }}>
                    {t("针对 o1, o3-mini 等新模型开启", "Enable for o1, o3-mini etc.")}
                  </span>
                </div>
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">{t("自定义请求头 (JSON)", "Custom Headers (JSON)")}</span>
                <textarea
                  className="vsInput"
                  style={{ fontFamily: "monospace", minHeight: "50px", fontSize: "12px" }}
                  value={customHeadersJson}
                  onChange={(e) => setCustomHeadersJson(e.target.value)}
                  placeholder='{"User-Agent": "CustomApp/1.0"}'
                />
              </label>
            </div>
            <div className="vsModalActions" style={{ marginTop: "20px", display: "flex", justifyContent: "flex-end", gap: "10px" }}>
              <button
                type="button"
                className="vsBtnSecondary"
                onClick={() => setShowAddCustomModal(false)}
              >
                {t("取消", "Cancel")}
              </button>
              <button
                type="button"
                className="vsBtnPrimary"
                onClick={() => {
                  if (!customName.trim()) {
                    setCustomModalError(t("请输入服务商名称", "Please enter a provider name"));
                    return;
                  }
                  if (!customBaseUrl.trim()) {
                    setCustomModalError(t("请输入 Base URL", "Please enter Base URL"));
                    return;
                  }
                  try {
                    JSON.parse(customHeadersJson);
                  } catch {
                    setCustomModalError(t("请求头 JSON 格式无效", "Invalid Headers JSON format"));
                    return;
                  }

                  void settings.onAddCustomProvider(
                    customName.trim(),
                    customBaseUrl.trim(),
                    customApiKey.trim(),
                    customUseMaxTokens,
                    customHeadersJson.trim()
                  );
                  setShowAddCustomModal(false);
                }}
              >
                {t("确认添加", "Confirm Add")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
