import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  configureEverMemRuntime,
  fetchDesktopStatus,
  getEverMemRuntimeConfig,
  fetchApiRuntimeInfo,
  fetchSettings,
  fetchProviderModels,
  updateSettings,
  type AppSettings,
  type DesktopStatusResponse,
  type SettingsModelValue
} from "../api";
import { createInlineTranslator, normalizeUiLanguage, type UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";

const PROVIDER_API_KEY_FIELD: Record<string, string> = {
  DeepSeek: "deepseek_api_key",
  OpenRouter: "openrouter_api_key",
  SiliconFlow: "siliconflow_api_key",
  Groq: "groq_api_key",
  DashScope: "dashscope_api_key",
  Google: "google_api_key",
  Xiaomi: "xiaomi_api_key",
  Ollama: "ollama_api_key",
  Deepgram: "deepgram_api_key",
  OpenAI: "openai_api_key",
  ElevenLabs: "elevenlabs_api_key",
  "GPT-SoVITS": "gpt_sovits_api_key",
  Doubao: "doubao_api_key"
};

const ALL_PROVIDER_KEYS = Object.keys(PROVIDER_API_KEY_FIELD);

function parseModelValue(
  value: SettingsModelValue | undefined
): {
  defaultModel: string;
  availableModels: string[];
  enabledModels: string[];
  ttsDefaultModel: string;
  ttsAvailableModels: string[];
  ttsEnabledModels: string[];
} {
  if (typeof value === "string") {
    return { defaultModel: value, availableModels: [], enabledModels: [], ttsDefaultModel: "", ttsAvailableModels: [], ttsEnabledModels: [] };
  }
  if (!value || typeof value !== "object") {
    return { defaultModel: "", availableModels: [], enabledModels: [], ttsDefaultModel: "", ttsAvailableModels: [], ttsEnabledModels: [] };
  }
  const defaultModel = typeof value.default === "string" ? value.default : "";
  const availableModels = Array.isArray(value.available)
    ? value.available.filter((item) => typeof item === "string")
    : [];
  const enabledModels = Array.isArray(value.enabled)
    ? value.enabled.filter((item) => typeof item === "string")
    : [];
  const ttsDefaultModel = typeof (value as any).tts_default === "string" ? (value as any).tts_default : "";
  const ttsAvailableModels = Array.isArray((value as any).tts_available)
    ? (value as any).tts_available.filter((item: any) => typeof item === "string")
    : [];
  const ttsEnabledModels = Array.isArray((value as any).tts_enabled)
    ? (value as any).tts_enabled.filter((item: any) => typeof item === "string")
    : [];
  return { defaultModel, availableModels, enabledModels, ttsDefaultModel, ttsAvailableModels, ttsEnabledModels };
}

type Options = {
  formatErrorMessage: FormatErrorMessage;
};

function trimOrEmpty(value: string) {
  return value.trim();
}

type ProviderModelCatalog = Record<
  string,
  {
    defaultModel: string;
    availableModels: string[];
    enabledModels: string[];
    ttsDefaultModel?: string;
    ttsAvailableModels?: string[];
    ttsEnabledModels?: string[];
  }
>;

export default function useSettings({ formatErrorMessage }: Options) {
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [settingsInfo, setSettingsInfo] = useState("");
  const [settingsConfigPath, setSettingsConfigPath] = useState("");
  const [settingsProviders, setSettingsProviders] = useState<string[]>([]);
  const [settingsData, setSettingsData] = useState<AppSettings | null>(null);
  const [settingsProvider, setSettingsProvider] = useState("DashScope");
  const [settingsApiKey, setSettingsApiKey] = useState("");
  const [settingsApiUrl, setSettingsApiUrl] = useState("");
  const [settingsRealtimeApiUrl, setSettingsRealtimeApiUrl] = useState("");
  const [settingsDoubaoAppId, setSettingsDoubaoAppId] = useState("");
  const [settingsDoubaoAccessToken, setSettingsDoubaoAccessToken] = useState("");
  const [settingsDoubaoWebsearchKey, setSettingsDoubaoWebsearchKey] = useState("");
  const [settingsDefaultModel, setSettingsDefaultModel] = useState("");
  const [settingsAvailableModels, setSettingsAvailableModels] = useState<string[]>([]);
  const [settingsEnabledModels, setSettingsEnabledModels] = useState<string[]>([]);
  const [settingsTtsDefaultModel, setSettingsTtsDefaultModel] = useState("");
  const [settingsTtsAvailableModels, setSettingsTtsAvailableModels] = useState<string[]>([]);
  const [settingsTtsEnabledModels, setSettingsTtsEnabledModels] = useState<string[]>([]);
  const [settingsFetchingModels, setSettingsFetchingModels] = useState(false);
  const settingsAvailableModelsText = settingsAvailableModels.join("\n");
  const [transcriptionUploadMode, setTranscriptionUploadMode] = useState("static");
  const [transcriptionPublicBaseUrl, setTranscriptionPublicBaseUrl] = useState("");
  const [transcriptionS3Bucket, setTranscriptionS3Bucket] = useState("");
  const [transcriptionS3Region, setTranscriptionS3Region] = useState("");
  const [transcriptionS3EndpointUrl, setTranscriptionS3EndpointUrl] = useState("");
  const [transcriptionS3AccessKeyId, setTranscriptionS3AccessKeyId] = useState("");
  const [transcriptionS3SecretAccessKey, setTranscriptionS3SecretAccessKey] = useState("");
  const [transcriptionS3KeyPrefix, setTranscriptionS3KeyPrefix] = useState("transcription");
  const [xiaomiApiKey, setXiaomiApiKey] = useState("");
  const [xiaomiApiUrl, setXiaomiApiUrl] = useState("");
  const [customProviders, setCustomProviders] = useState<any[]>([]);
  const [settingsProviderUseMaxCompletionTokens, setSettingsProviderUseMaxCompletionTokens] = useState(false);
  const [settingsProviderHeadersJson, setSettingsProviderHeadersJson] = useState("{}");

  const [evermemEnabled, setEvermemEnabled] = useState(false);
  const [evermemApiUrl, setEvermemApiUrl] = useState("");
  const [evermemApiKey, setEvermemApiKey] = useState("");
  const [evermemScopeId, setEvermemScopeId] = useState("");
  const [evermemTempSession, setEvermemTempSession] = useState(false);
  const [evermemRememberChat, setEvermemRememberChat] = useState(true);
  const [evermemRememberVoiceChat, setEvermemRememberVoiceChat] = useState(true);
  const [evermemRememberRecordings, setEvermemRememberRecordings] = useState(true);
  const [evermemRememberPodcast, setEvermemRememberPodcast] = useState(true);
  const [evermemRememberTts, setEvermemRememberTts] = useState(false);
  const [evermemStoreTranscript, setEvermemStoreTranscript] = useState(false);

  const [backendPhase, setBackendPhase] = useState("");
  const [backendAuthMode, setBackendAuthMode] = useState("");
  const [backendAuthEnabled, setBackendAuthEnabled] = useState<boolean | null>(null);
  const [backendVersion, setBackendVersion] = useState("");
  const [backendStatus, setBackendStatus] = useState("");
  const [backendRuntimeRaw, setBackendRuntimeRaw] = useState("{}");
  const [backendRuntimeOpen, setBackendRuntimeOpen] = useState(false);
  const [runtimeCopyStatus, setRuntimeCopyStatus] = useState<"idle" | "ok" | "fail">("idle");
  const [desktopRememberWindowPosition, setDesktopRememberWindowPosition] = useState(false);
  const [desktopAlwaysOnTop, setDesktopAlwaysOnTop] = useState(false);
  const [desktopShowTrayIcon, setDesktopShowTrayIcon] = useState(false);
  const [desktopWakeShortcut, setDesktopWakeShortcut] = useState("Alt+Shift+S");
  const [displayLanguage, setDisplayLanguage] = useState<UiLanguage>("zh-CN");
  const [desktopPreflightStatus, setDesktopPreflightStatus] = useState<DesktopStatusResponse["preflight"]>({
    available: false,
    ok: null,
    timestamp: "",
    failed_checks: [],
    failed_count: 0,
  });
  const [desktopLatestError, setDesktopLatestError] = useState<DesktopStatusResponse["latest_error"]>({
    available: false,
    timestamp: "",
    error_type: "",
    message: "",
    recovery_hints: [],
  });
  const [desktopDiagnosticsDir, setDesktopDiagnosticsDir] = useState("");
  const [desktopRuntimeDir, setDesktopRuntimeDir] = useState("");

  useEffect(() => {
    let disposed = false;

    async function loadApiRuntimeInfo() {
      try {
        const [info, desktopStatus] = await Promise.all([
          fetchApiRuntimeInfo(),
          fetchDesktopStatus().catch(() => null)
        ]);
        if (disposed) {
          return;
        }
        setBackendPhase(typeof info.phase === "string" ? info.phase : "");
        setBackendAuthMode(typeof info.auth_mode === "string" ? info.auth_mode : "");
        setBackendAuthEnabled(
          typeof info.auth_enabled === "boolean" ? info.auth_enabled : null
        );
        setBackendVersion(typeof info.version === "string" ? info.version : "");
        setBackendStatus(typeof info.status === "string" ? info.status : "");
        setBackendRuntimeRaw(JSON.stringify(info.raw || {}, null, 2));
        setDesktopPreflightStatus(desktopStatus?.preflight || {
          available: false,
          ok: null,
          timestamp: "",
          failed_checks: [],
          failed_count: 0,
        });
        setDesktopLatestError(desktopStatus?.latest_error || {
          available: false,
          timestamp: "",
          error_type: "",
          message: "",
          recovery_hints: [],
        });
        setDesktopDiagnosticsDir(desktopStatus?.diagnostics_dir || "");
        setDesktopRuntimeDir(desktopStatus?.runtime_dir || "");
      } catch {
        if (disposed) {
          return;
        }
        setBackendPhase("");
        setBackendAuthMode("");
        setBackendAuthEnabled(null);
        setBackendVersion("");
        setBackendStatus("");
        setBackendRuntimeRaw("{}");
        setDesktopPreflightStatus({
          available: false,
          ok: null,
          timestamp: "",
          failed_checks: [],
          failed_count: 0,
        });
        setDesktopLatestError({
          available: false,
          timestamp: "",
          error_type: "",
          message: "",
          recovery_hints: [],
        });
        setDesktopDiagnosticsDir("");
        setDesktopRuntimeDir("");
      }
    }

    void loadApiRuntimeInfo();
    return () => {
      disposed = true;
    };
  }, []);

  const errorRuntimeContext = useMemo(
    () => ({
      backend_phase: backendPhase,
      backend_auth_mode: backendAuthMode,
      backend_auth_enabled: backendAuthEnabled,
      backend_version: backendVersion,
      backend_status: backendStatus
    }),
    [backendPhase, backendAuthMode, backendAuthEnabled, backendVersion, backendStatus]
  );
  const t = useMemo(() => createInlineTranslator(displayLanguage), [displayLanguage]);

  const providerSection = useMemo(() => {
    return {
      provider: settingsProvider,
      apiKeyConfigured: Boolean(trimOrEmpty(settingsApiKey)),
      apiUrlConfigured: Boolean(trimOrEmpty(settingsApiUrl)),
      defaultModelConfigured: Boolean(trimOrEmpty(settingsDefaultModel)),
      availableModelCount: settingsAvailableModels.length,
      availableModels: settingsAvailableModels,
      enabledModels: settingsEnabledModels
    };
  }, [
    settingsApiKey,
    settingsApiUrl,
    settingsAvailableModels,
    settingsEnabledModels,
    settingsDefaultModel,
    settingsProvider
  ]);
  const dashscopeApiKeyConfigured = useMemo(() => {
    const apiKeys = settingsData?.api_keys || {};
    return Boolean(trimOrEmpty(String(apiKeys.dashscope_api_key || "")));
  }, [settingsData]);

  const xiaomiApiKeyConfigured = useMemo(() => {
    const apiKeys = settingsData?.api_keys || {};
    return Boolean(trimOrEmpty(String(apiKeys.xiaomi_api_key || "")));
  }, [settingsData]);

  const providerModelCatalog = useMemo<ProviderModelCatalog>(() => {
    if (!settingsData) {
      return {};
    }
    const catalog = Object.fromEntries(
      Object.entries(settingsData.default_models || {}).map(([provider, value]) => {
        const parsed = parseModelValue(value);
        return [provider, parsed];
      })
    );

    const rawCustom = settingsData.custom_providers || [];
    for (const cp of rawCustom) {
      if (cp && cp.id) {
        catalog[cp.id] = {
          defaultModel: cp.default_model || "",
          availableModels: cp.available_models || [],
          enabledModels: cp.enabled_models || [],
          ttsDefaultModel: "",
          ttsAvailableModels: [],
          ttsEnabledModels: []
        };
      }
    }

    return catalog;
  }, [settingsData]);

  const memorySection = useMemo(() => {
    return {
      enabled: evermemEnabled,
      configured:
        evermemEnabled &&
        Boolean(trimOrEmpty(evermemApiUrl)) &&
        Boolean(trimOrEmpty(evermemApiKey)),
      temporarySession: evermemTempSession,
      scopeIdConfigured: Boolean(trimOrEmpty(evermemScopeId)),
      scenes: [
        { id: "chat", enabled: evermemRememberChat, label: t("聊天", "Chat") },
        { id: "voice_chat", enabled: evermemRememberVoiceChat, label: t("语音聊天", "Voice Chat") },
        { id: "transcription", enabled: evermemRememberRecordings, label: t("录音转写", "Transcription") },
        { id: "podcast", enabled: evermemRememberPodcast, label: t("播客脚本", "Podcast Script") },
        { id: "tts", enabled: evermemRememberTts, label: t("语音合成", "Text to Speech") }
      ],
      storeTranscriptFulltext: evermemStoreTranscript
    };
  }, [
    t,
    evermemApiKey,
    evermemApiUrl,
    evermemEnabled,
    evermemRememberChat,
    evermemRememberPodcast,
    evermemRememberRecordings,
    evermemRememberTts,
    evermemRememberVoiceChat,
    evermemScopeId,
    evermemStoreTranscript,
    evermemTempSession
  ]);

  const transcriptionSection = useMemo(() => {
    const missingS3Fields = [
      ["s3_bucket", transcriptionS3Bucket],
      ["s3_region", transcriptionS3Region],
      ["s3_access_key_id", transcriptionS3AccessKeyId],
      ["s3_secret_access_key", transcriptionS3SecretAccessKey]
    ]
      .filter(([, value]) => !trimOrEmpty(value))
      .map(([key]) => key);

    return {
      uploadMode: transcriptionUploadMode,
      publicBaseUrlConfigured: Boolean(trimOrEmpty(transcriptionPublicBaseUrl)),
      s3Configured:
        transcriptionUploadMode === "s3" ? missingS3Fields.length === 0 : false,
      s3MissingFields: missingS3Fields,
      s3KeyPrefix: trimOrEmpty(transcriptionS3KeyPrefix) || "transcription"
    };
  }, [
    transcriptionPublicBaseUrl,
    transcriptionS3AccessKeyId,
    transcriptionS3Bucket,
    transcriptionS3KeyPrefix,
    transcriptionS3Region,
    transcriptionS3SecretAccessKey,
    transcriptionUploadMode
  ]);

  const desktopSection = useMemo(() => {
    return {
      configPath: settingsConfigPath,
      backendPhase,
      backendAuthMode,
      backendAuthEnabled,
      backendVersion,
      backendStatus,
      rememberWindowPosition: desktopRememberWindowPosition,
      alwaysOnTop: desktopAlwaysOnTop,
      showTrayIcon: desktopShowTrayIcon,
      wakeShortcut: trimOrEmpty(desktopWakeShortcut),
      runtimeDir: desktopRuntimeDir,
      diagnosticsDir: desktopDiagnosticsDir,
      preflight: desktopPreflightStatus,
      latestError: desktopLatestError,
      runtimeVisible: backendRuntimeOpen,
      runtimeCopyStatus
    };
  }, [
    backendAuthEnabled,
    backendAuthMode,
    backendPhase,
    backendRuntimeOpen,
    backendStatus,
    backendVersion,
    desktopDiagnosticsDir,
    desktopAlwaysOnTop,
    desktopLatestError,
    desktopPreflightStatus,
    desktopRememberWindowPosition,
    desktopRuntimeDir,
    desktopShowTrayIcon,
    desktopWakeShortcut,
    runtimeCopyStatus,
    settingsConfigPath
  ]);

  useEffect(() => {
    if (runtimeCopyStatus !== "ok") {
      return;
    }
    const timer = window.setTimeout(() => {
      setRuntimeCopyStatus("idle");
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [runtimeCopyStatus]);

  async function onCopyBackendRuntime() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(backendRuntimeRaw || "{}");
      } else {
        throw new Error(t("剪贴板接口不可用", "Clipboard API is unavailable."));
      }
      setRuntimeCopyStatus("ok");
    } catch {
      setRuntimeCopyStatus("fail");
    }
  }

  async function loadSettings() {
    setSettingsBusy(true);
    setSettingsError("");
    try {
      const result = await fetchSettings();
      setSettingsData(result.settings);
      setSettingsConfigPath(result.config_path);
      setSettingsProviders(result.providers);
      if (result.providers.length > 0 && !result.providers.includes(settingsProvider)) {
        setSettingsProvider(result.providers[0]);
      }
    } catch (err) {
      setSettingsError(formatErrorMessage(err, t("加载设置失败。", "Failed to load settings.")));
    } finally {
      setSettingsBusy(false);
    }
  }

  useEffect(() => {
    void loadSettings();
    const runtimeConfig = getEverMemRuntimeConfig();

    setEvermemEnabled(runtimeConfig.enabled);
    setEvermemApiUrl(runtimeConfig.api_url);
    setEvermemApiKey(runtimeConfig.api_key);
    setEvermemScopeId(runtimeConfig.scope_id);
    setEvermemTempSession(runtimeConfig.temporary_session);
    setEvermemRememberChat(runtimeConfig.remember_chat);
    setEvermemRememberVoiceChat(runtimeConfig.remember_voice_chat);
    setEvermemRememberRecordings(runtimeConfig.remember_recordings);
    setEvermemRememberPodcast(runtimeConfig.remember_podcast);
    setEvermemRememberTts(runtimeConfig.remember_tts);
    setEvermemStoreTranscript(runtimeConfig.store_transcript_fulltext);

    configureEverMemRuntime({
      enabled: runtimeConfig.enabled,
      api_url: runtimeConfig.api_url,
      api_key: runtimeConfig.api_key,
      scope_id: runtimeConfig.scope_id,
      temporary_session: runtimeConfig.temporary_session,
      remember_chat: runtimeConfig.remember_chat,
      remember_voice_chat: runtimeConfig.remember_voice_chat,
      remember_recordings: runtimeConfig.remember_recordings,
      remember_podcast: runtimeConfig.remember_podcast,
      remember_tts: runtimeConfig.remember_tts,
      store_transcript_fulltext: runtimeConfig.store_transcript_fulltext,
    });
    localStorage.removeItem("evermem_key");
  }, []);

  useEffect(() => {
    if (!settingsData) {
      return;
    }
    
    // Sync custom providers list
    const rawCustom = settingsData.custom_providers || [];
    setCustomProviders(rawCustom);

    const isCustom = settingsProvider.startsWith("custom_");
    if (isCustom) {
      const customProv = rawCustom.find((p: any) => p.id === settingsProvider);
      if (customProv) {
        setSettingsApiKey(customProv.api_key || "");
        setSettingsApiUrl(customProv.base_url || "");
        setSettingsDefaultModel(customProv.default_model || "");
        setSettingsAvailableModels(customProv.available_models || []);
        setSettingsEnabledModels(customProv.enabled_models || []);
        setSettingsProviderUseMaxCompletionTokens(!!customProv.use_max_completion_tokens);
        setSettingsProviderHeadersJson(JSON.stringify(customProv.custom_headers || {}, null, 2));
      } else {
        setSettingsApiKey("");
        setSettingsApiUrl("");
        setSettingsDefaultModel("");
        setSettingsAvailableModels([]);
        setSettingsEnabledModels([]);
        setSettingsTtsDefaultModel("");
        setSettingsTtsAvailableModels([]);
        setSettingsTtsEnabledModels([]);
        setSettingsProviderUseMaxCompletionTokens(false);
        setSettingsProviderHeadersJson("{}");
      }
    } else {
      const keyField = PROVIDER_API_KEY_FIELD[settingsProvider];
      const apiKey = (keyField && settingsData?.api_keys) ? settingsData.api_keys[keyField] || "" : "";
      const apiUrl = settingsData?.api_urls?.[settingsProvider] || "";
      const modelValue = settingsData?.default_models?.[settingsProvider];
      const { defaultModel, availableModels, enabledModels, ttsDefaultModel, ttsAvailableModels, ttsEnabledModels } = parseModelValue(modelValue);

      setSettingsApiKey(apiKey);
      setSettingsApiUrl(apiUrl);
      setSettingsRealtimeApiUrl(settingsData.realtime_api_urls?.[settingsProvider] || "");
      setSettingsDoubaoAppId(settingsData.api_keys?.doubao_app_id || "");
      setSettingsDoubaoAccessToken(settingsData.api_keys?.doubao_access_token || "");
      setSettingsDoubaoWebsearchKey(settingsData.api_keys?.doubao_websearch_api_key || "");
      setSettingsDefaultModel(defaultModel);
      setSettingsAvailableModels(availableModels);
      setSettingsEnabledModels(enabledModels);
      setSettingsTtsDefaultModel(ttsDefaultModel);
      setSettingsTtsAvailableModels(ttsAvailableModels);
      setSettingsTtsEnabledModels(ttsEnabledModels);
      setSettingsProviderUseMaxCompletionTokens(false);
      setSettingsProviderHeadersJson("{}");
    }

    const xiaomiSettings = settingsData.xiaomi || {};
    if (typeof xiaomiSettings.api_key === "string") setXiaomiApiKey(xiaomiSettings.api_key);
    if (typeof xiaomiSettings.api_url === "string") setXiaomiApiUrl(xiaomiSettings.api_url);

    const memorySettings = settingsData.memory_settings || {};
    const transcriptionSettings = settingsData.transcription_settings || {};
    const uiSettings = settingsData.ui_settings || {};
    const shortcuts = settingsData.shortcuts || {};
    if (typeof memorySettings.enabled === "boolean") setEvermemEnabled(memorySettings.enabled);
    if (typeof memorySettings.api_url === "string") setEvermemApiUrl(memorySettings.api_url);
    if (typeof memorySettings.api_key === "string") setEvermemApiKey(memorySettings.api_key);
    if (typeof memorySettings.scope_id === "string") setEvermemScopeId(memorySettings.scope_id);
    if (typeof memorySettings.temporary_session === "boolean") setEvermemTempSession(memorySettings.temporary_session);
    if (typeof memorySettings.remember_chat === "boolean") setEvermemRememberChat(memorySettings.remember_chat);
    if (typeof memorySettings.remember_voice_chat === "boolean") setEvermemRememberVoiceChat(memorySettings.remember_voice_chat);
    if (typeof memorySettings.remember_recordings === "boolean") setEvermemRememberRecordings(memorySettings.remember_recordings);
    if (typeof memorySettings.remember_podcast === "boolean") setEvermemRememberPodcast(memorySettings.remember_podcast);
    if (typeof memorySettings.remember_tts === "boolean") setEvermemRememberTts(memorySettings.remember_tts);
    if (typeof memorySettings.store_transcript_fulltext === "boolean") setEvermemStoreTranscript(memorySettings.store_transcript_fulltext);
    if (typeof transcriptionSettings.upload_mode === "string" && transcriptionSettings.upload_mode.trim()) {
      setTranscriptionUploadMode(transcriptionSettings.upload_mode);
    }
    if (typeof transcriptionSettings.public_base_url === "string") {
      setTranscriptionPublicBaseUrl(transcriptionSettings.public_base_url);
    }
    if (typeof transcriptionSettings.s3_bucket === "string") setTranscriptionS3Bucket(transcriptionSettings.s3_bucket);
    if (typeof transcriptionSettings.s3_region === "string") setTranscriptionS3Region(transcriptionSettings.s3_region);
    if (typeof transcriptionSettings.s3_endpoint_url === "string") setTranscriptionS3EndpointUrl(transcriptionSettings.s3_endpoint_url);
    if (typeof transcriptionSettings.s3_access_key_id === "string") setTranscriptionS3AccessKeyId(transcriptionSettings.s3_access_key_id);
    if (typeof transcriptionSettings.s3_secret_access_key === "string") setTranscriptionS3SecretAccessKey(transcriptionSettings.s3_secret_access_key);
    if (typeof transcriptionSettings.s3_key_prefix === "string" && transcriptionSettings.s3_key_prefix.trim()) {
      setTranscriptionS3KeyPrefix(transcriptionSettings.s3_key_prefix);
    }
    if (typeof uiSettings.remember_window_position === "boolean") {
      setDesktopRememberWindowPosition(uiSettings.remember_window_position);
    }
    if (typeof uiSettings.always_on_top === "boolean") {
      setDesktopAlwaysOnTop(uiSettings.always_on_top);
    }
    if (typeof uiSettings.show_tray_icon === "boolean") {
      setDesktopShowTrayIcon(uiSettings.show_tray_icon);
    }
    if (typeof uiSettings.display_language === "string") {
      setDisplayLanguage(normalizeUiLanguage(uiSettings.display_language));
    }
    if (typeof shortcuts.wake_app === "string" && shortcuts.wake_app.trim()) {
      setDesktopWakeShortcut(shortcuts.wake_app);
    }

    // push to runtime to keep consistent
    configureEverMemRuntime({
      enabled: typeof memorySettings.enabled === "boolean" ? memorySettings.enabled : evermemEnabled,
      api_url: typeof memorySettings.api_url === "string" ? memorySettings.api_url : evermemApiUrl,
      api_key: typeof memorySettings.api_key === "string" ? memorySettings.api_key : evermemApiKey,
      scope_id: typeof memorySettings.scope_id === "string" ? memorySettings.scope_id : evermemScopeId,
      temporary_session: typeof memorySettings.temporary_session === "boolean" ? memorySettings.temporary_session : evermemTempSession,
      remember_chat: typeof memorySettings.remember_chat === "boolean" ? memorySettings.remember_chat : evermemRememberChat,
      remember_voice_chat: typeof memorySettings.remember_voice_chat === "boolean" ? memorySettings.remember_voice_chat : evermemRememberVoiceChat,
      remember_recordings: typeof memorySettings.remember_recordings === "boolean" ? memorySettings.remember_recordings : evermemRememberRecordings,
      remember_podcast: typeof memorySettings.remember_podcast === "boolean" ? memorySettings.remember_podcast : evermemRememberPodcast,
      remember_tts: typeof memorySettings.remember_tts === "boolean" ? memorySettings.remember_tts : evermemRememberTts,
      store_transcript_fulltext: typeof memorySettings.store_transcript_fulltext === "boolean" ? memorySettings.store_transcript_fulltext : evermemStoreTranscript
    });
  }, [settingsData, settingsProvider]);

  async function onFetchModels() {
    if (!settingsProvider) return;
    setSettingsFetchingModels(true);
    setSettingsError("");
    try {
      const res = await fetchProviderModels(settingsProvider, settingsApiKey, settingsApiUrl);
      setSettingsAvailableModels(res.models);
      setSettingsEnabledModels((prev) => {
        return prev.filter(m => res.models.includes(m));
      });
      const ttsList = res.tts_models || [];
      if (ttsList.length > 0) {
        setSettingsTtsAvailableModels(ttsList);
        setSettingsTtsEnabledModels((prev) => {
          return Array.from(new Set([...prev, ...ttsList]));
        });
      }
      const totalCount = res.models.length + (res.tts_models?.length || 0);
      setSettingsInfo(
        t(
          `已从 ${settingsProvider} 获取 ${totalCount} 个模型（对话模型 ${res.models.length} 个，TTS 语音模型 ${res.tts_models?.length || 0} 个）。请手动勾选要启用的模型。`,
          `Fetched ${totalCount} models from ${settingsProvider} (${res.models.length} LLM models, ${res.tts_models?.length || 0} TTS models). Please tick the ones you want to enable.`
        )
      );
    } catch (err) {
      setSettingsError(formatErrorMessage(err, t("获取模型列表失败。", "Failed to fetch models.")));
    } finally {
      setSettingsFetchingModels(false);
    }
  }

  function onToggleModelEnabled(modelId: string) {
    setSettingsEnabledModels((prev) => {
      if (prev.includes(modelId)) {
        return prev.filter((id) => id !== modelId);
      } else {
        return [...prev, modelId];
      }
    });
  }

  function onEnableAllModels() {
    setSettingsEnabledModels([...settingsAvailableModels]);
  }

  function onDisableAllModels() {
    setSettingsEnabledModels([]);
  }

  const onAvailableModelsChange = (text: string) => {
    const list = text
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
    setSettingsAvailableModels(list);
  };

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSettingsError("");
    setSettingsInfo("");

    const isCustom = settingsProvider.startsWith("custom_");
    const keyField = PROVIDER_API_KEY_FIELD[settingsProvider];

    if (!isCustom && !keyField) {
      setSettingsError(
        t(
          `暂不支持该供应商的密钥映射：${settingsProvider}`,
          `This provider does not have an API key mapping yet: ${settingsProvider}`
        )
      );
      return;
    }

    setSettingsSaving(true);
    try {
      configureEverMemRuntime({
        enabled: evermemEnabled,
        api_url: evermemApiUrl,
        api_key: evermemApiKey,
        scope_id: evermemScopeId,
        temporary_session: evermemTempSession,
        remember_chat: evermemRememberChat,
        remember_voice_chat: evermemRememberVoiceChat,
        remember_recordings: evermemRememberRecordings,
        remember_podcast: evermemRememberPodcast,
        remember_tts: evermemRememberTts,
        store_transcript_fulltext: evermemStoreTranscript
      });

      let updatedCustomProviders = [...customProviders];
      if (isCustom) {
        let headersObj = {};
        if (settingsProviderHeadersJson.trim()) {
          try {
            headersObj = JSON.parse(settingsProviderHeadersJson);
          } catch (err) {
            setSettingsError(t("自定义请求头 JSON 格式不正确。", "Invalid Custom Headers JSON format."));
            setSettingsSaving(false);
            return;
          }
        }
        updatedCustomProviders = customProviders.map((p) => {
          if (p.id === settingsProvider) {
            return {
              ...p,
              api_key: settingsApiKey.trim(),
              base_url: settingsApiUrl.trim(),
              default_model: settingsDefaultModel.trim(),
              available_models: settingsAvailableModels,
              enabled_models: settingsEnabledModels,
              use_max_completion_tokens: settingsProviderUseMaxCompletionTokens,
              custom_headers: headersObj,
            };
          }
          return p;
        });
      }

      const patch: Record<string, any> = {
        general_settings: {
          display_language: displayLanguage
        },
        memory_settings: {
          enabled: evermemEnabled,
          api_url: evermemApiUrl,
          api_key: evermemApiKey,
          scope_id: evermemScopeId,
          temporary_session: evermemTempSession,
          remember_chat: evermemRememberChat,
          remember_voice_chat: evermemRememberVoiceChat,
          remember_recordings: evermemRememberRecordings,
          remember_podcast: evermemRememberPodcast,
          remember_tts: evermemRememberTts,
          store_transcript_fulltext: evermemStoreTranscript
        },
        transcription_settings: {
          upload_mode: transcriptionUploadMode.trim() || "static",
          public_base_url: transcriptionPublicBaseUrl.trim(),
          s3_bucket: transcriptionS3Bucket.trim(),
          s3_region: transcriptionS3Region.trim(),
          s3_endpoint_url: transcriptionS3EndpointUrl.trim(),
          s3_access_key_id: transcriptionS3AccessKeyId.trim(),
          s3_secret_access_key: transcriptionS3SecretAccessKey.trim(),
          s3_key_prefix: transcriptionS3KeyPrefix.trim() || "transcription"
        },
        xiaomi: {
          api_key: xiaomiApiKey.trim(),
          api_url: xiaomiApiUrl.trim()
        },
        ui_settings: {
          display_language: displayLanguage,
          remember_window_position: desktopRememberWindowPosition,
          always_on_top: desktopAlwaysOnTop,
          show_tray_icon: desktopShowTrayIcon
        },
        shortcuts: {
          wake_app: desktopWakeShortcut.trim()
        },
        custom_providers: updatedCustomProviders
      };

      if (!isCustom) {
        if (keyField) {
          patch.api_keys = {
            [keyField]: settingsApiKey.trim()
          };
        }
        if (settingsProvider === "Doubao") {
          patch.api_keys = {
            ...(patch.api_keys || {}),
            doubao_access_token: settingsDoubaoAccessToken.trim(),
            doubao_app_id: settingsDoubaoAppId.trim(),
            doubao_websearch_api_key: settingsDoubaoWebsearchKey.trim()
          };
        }
        patch.api_urls = {
          [settingsProvider]: settingsApiUrl.trim()
        };
        if (settingsProvider === "DashScope" || settingsProvider === "Doubao") {
          patch.realtime_api_urls = {
            [settingsProvider]: settingsRealtimeApiUrl.trim()
          };
        }
        patch.default_models = {
          [settingsProvider]: {
            default: settingsDefaultModel.trim(),
            available: settingsAvailableModels,
            enabled: settingsEnabledModels
          }
        };
      }

      const result = await updateSettings(patch);
      setSettingsData(result.settings);
      setSettingsConfigPath(result.config_path);
      setSettingsProviders(result.providers);
      setSettingsInfo(
        t(
          `已保存 ${settingsProvider} 的设置。`,
          `Saved settings for ${settingsProvider}.`
        )
      );
    } catch (err) {
      setSettingsError(formatErrorMessage(err, t("保存设置失败。", "Failed to save settings.")));
    } finally {
      setSettingsSaving(false);
    }
  }

  async function onAddCustomProvider(name: string, baseUrl: string, apiKey: string, useMaxTokens: boolean, headersJson: string) {
    let headersObj = {};
    if (headersJson.trim()) {
      try {
        headersObj = JSON.parse(headersJson);
      } catch (err) {
        throw new Error(t("自定义请求头 JSON 格式不正确。", "Invalid Custom Headers JSON format."));
      }
    }

    const newId = `custom_${Date.now()}`;
    const newProvider = {
      id: newId,
      name,
      base_url: baseUrl,
      api_key: apiKey,
      use_max_completion_tokens: useMaxTokens,
      custom_headers: headersObj,
      default_model: "",
      available_models: [],
      enabled_models: [],
    };

    const updatedList = [...customProviders, newProvider];
    setCustomProviders(updatedList);
    setSettingsProvider(newId);

    setSettingsSaving(true);
    try {
      const result = await updateSettings({
        custom_providers: updatedList
      });
      setSettingsData(result.settings);
      setSettingsConfigPath(result.config_path);
      setSettingsProviders(result.providers);
      setSettingsInfo(t("已成功添加自定义服务商。", "Successfully added custom provider."));
    } catch (err) {
      setSettingsError(formatErrorMessage(err, t("添加自定义服务商失败。", "Failed to add custom provider.")));
    } finally {
      setSettingsSaving(false);
    }
  }

  async function onDeleteCustomProvider(id: string) {
    const updatedList = customProviders.filter((p) => p.id !== id);
    setCustomProviders(updatedList);

    if (settingsProvider === id) {
      setSettingsProvider("DashScope");
    }

    setSettingsSaving(true);
    try {
      const result = await updateSettings({
        custom_providers: updatedList
      });
      setSettingsData(result.settings);
      setSettingsConfigPath(result.config_path);
      setSettingsProviders(result.providers);
      setSettingsInfo(t("已成功删除自定义服务商。", "Successfully deleted custom provider."));
    } catch (err) {
      setSettingsError(formatErrorMessage(err, t("删除自定义服务商失败。", "Failed to delete custom provider.")));
    } finally {
      setSettingsSaving(false);
    }
  }

  return {
    settingsData,
    settingsBusy,
    settingsSaving,
    settingsError,
    settingsInfo,
    settingsConfigPath,
    settingsProvider,
    settingsApiKey,
    settingsApiUrl,
    settingsRealtimeApiUrl,
    settingsDoubaoAppId,
    settingsDoubaoAccessToken,
    settingsDoubaoWebsearchKey,
    settingsDefaultModel,
    settingsAvailableModelsText,
    settingsAvailableModels,
    settingsEnabledModels,
    settingsFetchingModels,
    transcriptionUploadMode,
    transcriptionPublicBaseUrl,
    transcriptionS3Bucket,
    transcriptionS3Region,
    xiaomiApiKey,
    xiaomiApiUrl,
    transcriptionS3EndpointUrl,
    transcriptionS3AccessKeyId,
    transcriptionS3SecretAccessKey,
    transcriptionS3KeyPrefix,
    evermemEnabled,
    evermemApiUrl,
    evermemApiKey,
    evermemScopeId,
    evermemTempSession,
    evermemRememberChat,
    evermemRememberVoiceChat,
    evermemRememberRecordings,
    evermemRememberPodcast,
    evermemRememberTts,
    evermemStoreTranscript,
    backendRuntimeRaw,
    backendRuntimeOpen,
    runtimeCopyStatus,
    desktopRememberWindowPosition,
    desktopAlwaysOnTop,
    desktopShowTrayIcon,
    desktopWakeShortcut,
    displayLanguage,
    errorRuntimeContext,
    providerSection,
    dashscopeApiKeyConfigured,
    xiaomiApiKeyConfigured,
    providerModelCatalog,
    memorySection,
    transcriptionSection,
    desktopSection,
    providerOptions: settingsProviders.length ? settingsProviders : ALL_PROVIDER_KEYS,
    customProviders,
    settingsProviderUseMaxCompletionTokens,
    settingsProviderHeadersJson,
    isCustomProvider: settingsProvider.startsWith("custom_"),
    onSubmit,
    onReload: loadSettings,
    onProviderChange: setSettingsProvider,
    onApiKeyChange: setSettingsApiKey,
    onApiUrlChange: setSettingsApiUrl,
    onRealtimeApiUrlChange: setSettingsRealtimeApiUrl,
    onDoubaoAppIdChange: setSettingsDoubaoAppId,
    onDoubaoAccessTokenChange: setSettingsDoubaoAccessToken,
    onDoubaoWebsearchKeyChange: setSettingsDoubaoWebsearchKey,
    onXiaomiApiKeyChange: setXiaomiApiKey,
    onXiaomiApiUrlChange: setXiaomiApiUrl,
    settingsTtsDefaultModel,
    settingsTtsAvailableModels,
    settingsTtsEnabledModels,
    onTtsDefaultModelChange: setSettingsTtsDefaultModel,
    onDefaultModelChange: setSettingsDefaultModel,
    onAvailableModelsChange,
    onToggleModelEnabled,
    onEnableAllModels,
    onDisableAllModels,
    onFetchModels,
    onAddCustomProvider,
    onDeleteCustomProvider,
    onUseMaxCompletionTokensChange: setSettingsProviderUseMaxCompletionTokens,
    onHeadersJsonChange: setSettingsProviderHeadersJson,
    onTranscriptionUploadModeChange: setTranscriptionUploadMode,
    onTranscriptionPublicBaseUrlChange: setTranscriptionPublicBaseUrl,
    onTranscriptionS3BucketChange: setTranscriptionS3Bucket,
    onTranscriptionS3RegionChange: setTranscriptionS3Region,
    onTranscriptionS3EndpointUrlChange: setTranscriptionS3EndpointUrl,
    onTranscriptionS3AccessKeyIdChange: setTranscriptionS3AccessKeyId,
    onTranscriptionS3SecretAccessKeyChange: setTranscriptionS3SecretAccessKey,
    onTranscriptionS3KeyPrefixChange: setTranscriptionS3KeyPrefix,
    onEvermemEnabledChange: setEvermemEnabled,
    onEvermemApiUrlChange: setEvermemApiUrl,
    onEvermemApiKeyChange: setEvermemApiKey,
    onEvermemScopeIdChange: setEvermemScopeId,
    onEvermemTempSessionChange: setEvermemTempSession,
    onEvermemRememberChatChange: setEvermemRememberChat,
    onEvermemRememberVoiceChatChange: setEvermemRememberVoiceChat,
    onEvermemRememberRecordingsChange: setEvermemRememberRecordings,
    onEvermemRememberPodcastChange: setEvermemRememberPodcast,
    onEvermemRememberTtsChange: setEvermemRememberTts,
    onEvermemStoreTranscriptChange: setEvermemStoreTranscript,
    onDesktopRememberWindowPositionChange: setDesktopRememberWindowPosition,
    onDesktopAlwaysOnTopChange: setDesktopAlwaysOnTop,
    onDesktopShowTrayIconChange: setDesktopShowTrayIcon,
    onDesktopWakeShortcutChange: setDesktopWakeShortcut,
    onDisplayLanguageChange: (value: string) => setDisplayLanguage(normalizeUiLanguage(value)),
    onToggleRuntimeOpen: () => setBackendRuntimeOpen((value) => !value),
    onCopyBackendRuntime
  };
}

export type UseSettingsResult = ReturnType<typeof useSettings>;
