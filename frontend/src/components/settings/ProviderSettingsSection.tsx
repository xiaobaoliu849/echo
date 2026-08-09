import { useState, useMemo, ReactNode } from "react";
import { Terminal, Brain, Eye, EyeOff } from "lucide-react";
import type { UseSettingsResult } from "../../hooks/useSettings";
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
  return lower;
};

const PROVIDER_COLORS: Record<string, string> = {
  qwen: "#6366f1", deepseek: "#4f46e5", google: "#4285f4", openai: "#10a37f",
  groq: "#f55036", openrouter: "#8b5cf6", siliconcloud: "#7c3aed",
  xiaomimimo: "#ff6900", anthropic: "#d4a574", nvidia: "#76b900",
  ollama: "#6b7280", deepgram: "#13ef93", zenmux: "#a855f7",
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
  const [providerSearch, setProviderSearch] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [showDoubaoAccessToken, setShowDoubaoAccessToken] = useState(false);
  const [showDoubaoAppId, setShowDoubaoAppId] = useState(false);
  const [showDoubaoWebsearchKey, setShowDoubaoWebsearchKey] = useState(false);

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
            <div className="vsPasswordFieldWrap">
              <input
                className="vsInput"
                type={showApiKey ? "text" : "password"}
                value={settings.settingsApiKey || ""}
                onChange={(e) => settings.onApiKeyChange(e.target.value)}
                placeholder={settings.settingsProvider === "Doubao"
                  ? t("ark- 开头，仅用于文字聊天；实时语音用下面的 Access Token", "ark- key, text chat only; realtime voice uses the Access Token below")
                  : t("输入供应商 API Key", "Enter your API key")}
              />
              <button
                type="button"
                className="vsPasswordToggleBtn"
                onMouseDown={(e) => e.preventDefault()}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setShowApiKey((v) => !v);
                }}
                title={showApiKey ? t("隐藏", "Hide") : t("显示", "Show")}
              >
                {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </label>

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
                <span className="vsFieldLabel">{t("Access Token（豆包语音 · TTS合成 / ASR识别 / 实时语音）", "Access Token (Doubao Voice · TTS / ASR / Realtime)")}</span>
                <div className="vsPasswordFieldWrap">
                  <input
                    className="vsInput"
                    type={showDoubaoAccessToken ? "text" : "password"}
                    value={settings.settingsDoubaoAccessToken || ""}
                    onChange={(e) => settings.onDoubaoAccessTokenChange(e.target.value)}
                    placeholder={t("豆包语音控制台「服务接口认证信息」的 Access Token", "Access Token from the Doubao Voice console auth info")}
                  />
                  <button
                    type="button"
                    className="vsPasswordToggleBtn"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setShowDoubaoAccessToken((v) => !v);
                    }}
                    title={showDoubaoAccessToken ? t("隐藏", "Hide") : t("显示", "Show")}
                  >
                    {showDoubaoAccessToken ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                <span className="vsFieldHint">
                  {t(
                    "语音合成（TTS）、语音识别（ASR）与实时语音通用凭证，与上面的文本 API Key 是两套体系；填入并保存后，语音中心与转写页面将直接启用豆包。通常为以 x- 开头的字符串。",
                    "Universal credential for TTS, ASR, and Realtime voice, separate from the text API key above; after saving, Doubao TTS and ASR are ready to use. Usually starts with x-."
                  )}
                </span>
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">{t("豆包语音 APP ID（TTS/ASR/实时语音必填）", "Doubao Voice APP ID (required for TTS / ASR / Realtime)")}</span>
                <div className="vsPasswordFieldWrap">
                  <input
                    className="vsInput"
                    type={showDoubaoAppId ? "text" : "password"}
                    value={settings.settingsDoubaoAppId || ""}
                    onChange={(e) => settings.onDoubaoAppIdChange(e.target.value)}
                    placeholder={t("火山引擎「豆包语音」控制台概览页的 APP ID", "APP ID from the Volcengine Doubao Voice console overview page")}
                  />
                  <button
                    type="button"
                    className="vsPasswordToggleBtn"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setShowDoubaoAppId((v) => !v);
                    }}
                    title={showDoubaoAppId ? t("隐藏", "Hide") : t("显示", "Show")}
                  >
                    {showDoubaoAppId ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                <span className="vsFieldHint">
                  {t(
                    "豆包语音（TTS/ASR/实时语音）使用「豆包语音」控制台的 Access Token + APP ID 鉴权（两者在「服务接口认证信息」里成对出现）。",
                    "Doubao voice services (TTS/ASR/Realtime) authenticate with the Access Token + APP ID pair from the Doubao Voice console."
                  )}{" "}
                  <a
                    href="https://console.volcengine.com/speech/overview"
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("打开豆包语音控制台", "Open the Doubao Voice console")}
                  </a>
                </span>
              </label>
              <label className="vsField">
                <span className="vsFieldLabel">{t("融合信息搜索 API Key（可选，开启联网）", "Web Search API Key (optional, enables online search)")}</span>
                <div className="vsPasswordFieldWrap">
                  <input
                    className="vsInput"
                    type={showDoubaoWebsearchKey ? "text" : "password"}
                    value={settings.settingsDoubaoWebsearchKey || ""}
                    onChange={(e) => settings.onDoubaoWebsearchKeyChange(e.target.value)}
                    placeholder={t("火山引擎「融合信息搜索」服务的 API Key", "API Key of the Volcengine fused web search service")}
                  />
                  <button
                    type="button"
                    className="vsPasswordToggleBtn"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setShowDoubaoWebsearchKey((v) => !v);
                    }}
                    title={showDoubaoWebsearchKey ? t("隐藏", "Hide") : t("显示", "Show")}
                  >
                    {showDoubaoWebsearchKey ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
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
                  placeholder="wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
                />
                <span className="vsFieldHint">
                  {t("留空则使用豆包端到端实时语音官方地址。", "Leave empty to use the official Doubao end-to-end realtime dialogue endpoint.")}
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

          {settings.settingsProvider !== "Deepgram" && settings.settingsProvider !== "OpenAI" && (
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

          {["DashScope", "MiniMax", "Xiaomi", "OpenAI", "ElevenLabs"].includes(settings.settingsProvider) && (
            <label className="vsField">
              <span className="vsFieldLabel">{t("默认 TTS 语音模型", "Default TTS Model")}</span>
              <input
                className="vsInput"
                value={settings.settingsTtsDefaultModel || ""}
                onChange={(e) => settings.onTtsDefaultModelChange?.(e.target.value)}
                placeholder={t("输入或选择 TTS 模型 ID", "Enter or select TTS model ID")}
              />
              <span className="vsFieldHint">
                {t(
                  "用于语音中心合成的标准 TTS 模型 (例如 qwen-audio-3.0-tts-flash, qwen3-tts-flash-2025-11-27, speech-02-hd, tts-1-hd 等)",
                  "Model used for Voice Center synthesis (e.g. qwen-audio-3.0-tts-flash, qwen3-tts-flash-2025-11-27, speech-02-hd, tts-1-hd, etc.)"
                )}
              </span>
            </label>
          )}
        </div>

        {/* Model Management Section */}
        {settings.settingsProvider === "Deepgram" || settings.settingsProvider === "OpenAI" ? (
          <div className="vsProviderModelSection">
            <div className="vsSettingsNotice ok">
              {settings.settingsProvider === "Deepgram"
                ? t("Deepgram 用于语音识别 (ASR)，使用 nova-3 模型，支持精确单词级时间戳。", "Deepgram is used for speech recognition (ASR) with the nova-3 model, supporting precise word-level timestamps.")
                : t("OpenAI 用于语音识别 (ASR)，使用 Whisper 模型。", "OpenAI is used for speech recognition (ASR) with the Whisper model.")}
            </div>
          </div>
        ) : (
        <div className="vsProviderModelSection">
          <div className="vsModelManagerHeader">
            <h3 className="vsCardSubTitle" style={{ margin: 0 }}>
              {t(`模型 (${availableModels.length})`, `Models (${availableModels.length})`)}
            </h3>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <input
                type="text"
                className="vsInput vsInputSmall"
                style={{ width: "160px" }}
                value={modelSearch}
                onChange={(e) => setModelSearch(e.target.value)}
                placeholder={t("筛选已有模型...", "Filter models...")}
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
                {t("暂无模型。点击“自动获取”或手动输入添加。", "No models configured. Click Auto Fetch or enter manually.")}
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
