import type { AudioOverviewPodcast, VoiceInfo } from "../api";
import type { UseAudioOverviewResult } from "../hooks/useAudioOverview";
import { vi } from "vitest";
import type { UseChatResult } from "../hooks/useChat";
import type { UseSettingsResult } from "../hooks/useSettings";
import type { UseTranslateResult } from "../hooks/useTranslate";
import type { UseTtsResult } from "../hooks/useTts";
import type { UseVoiceChatResult } from "../hooks/useVoiceChat";
import type { UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";
import type { VoiceDesignController, VoiceCloneController } from "../hooks/useVoiceManagement";

export function createFormatErrorMessageStub(): FormatErrorMessage {
  return (_error, fallback) => fallback;
}

export function createChatController(
  overrides: Partial<UseChatResult> = {}
): UseChatResult {
  return {
    chatProvider: "Google",
    chatProviderOptions: ["Google", "DashScope"],
    chatModel: "",
    chatModelOptions: [],
    chatModelChoices: [],
    chatModelChoiceValue: "",
    chatInput: "",
    chatMessages: [],
    chatBusy: false,
    chatError: "",
    chatMemoryGroupId: "",
    onSubmit: vi.fn(),
    onProviderChange: vi.fn(),
    onModelChange: vi.fn(),
    onModelChoiceChange: vi.fn(),
    onInputChange: vi.fn(),
    onQuickAction: vi.fn(),
    onComposerKeyDown: vi.fn(),
    onNewSession: vi.fn(),
    onSelectHistory: vi.fn(),
    replaceSession: vi.fn(),
    injectMessage: vi.fn(),
    onDeleteMessage: vi.fn(),
    onRegenerateMessage: vi.fn(),
    useMemory: true,
    setUseMemory: vi.fn(),
    deepThinking: false,
    setDeepThinking: vi.fn(),
    chatAttachments: [],
    addChatAttachment: vi.fn(),
    removeChatAttachment: vi.fn(),
    clearChatAttachments: vi.fn(),
    ...overrides
  };
}

export function createTtsController(
  overrides: Partial<UseTtsResult> = {}
): UseTtsResult {
  return {
    ttsMode: "text",
    ttsEngine: "edge",
    text: "Sample test text",
    dialogueText: "A: 你好。\nB: 你好，今天想聊什么？",
    pdfText: "",
    pdfFile: null,
    voices: [],
    voice: "zh-CN-XiaoxiaoNeural",
    voiceB: "zh-CN-YunxiNeural",
    rate: "+0%",
    audioUrl: "",
    audioBlob: null,
    loadingVoices: false,
    loadingVoicesB: false,
    generating: false,
    extractingPdf: false,
    polishingPdf: false,
    ttsError: "",
    ttsInfo: "",
    engineOptions: [
      { value: "edge", label: "Edge TTS", hint: "系统级稳定合成，适合基础朗读。" },
      { value: "qwen_flash", label: "Qwen TTS (阿里云)", hint: "阿里云 Qwen 音色，更适合中文与角色感。" },
      { value: "minimax", label: "MiniMax TTS", hint: "MiniMax 多风格音色，适合配音与角色化朗读。" }
    ],
    voiceOptions: [{ value: "zh-CN-XiaoxiaoNeural", label: "Xiaoxiao (zh-CN)" }],
    voiceOptionsB: [{ value: "zh-CN-YunxiNeural", label: "Yunxi (zh-CN)" }],
    ttsEngineB: "edge",
    ttsModel: "",
    ttsModelB: "",
    ttsModelOptions: [],
    ttsModelOptionsB: [],
    voicesB: [],
    activeSourceText: "Sample test text",
    onSubmit: vi.fn(),
    onTtsModeChange: vi.fn(),
    onEngineChange: vi.fn(),
    onEngineBChange: vi.fn(),
    onModelChange: vi.fn(),
    onModelBChange: vi.fn(),
    onTextChange: vi.fn(),
    onDialogueTextChange: vi.fn(),
    onPdfFileChange: vi.fn(),
    onPdfTextChange: vi.fn(),
    onPolishPdfText: vi.fn(),
    onVoiceChange: vi.fn(),
    onVoiceBChange: vi.fn(),
    onRateChange: vi.fn(),

    ...overrides
  };
}

export function createVoiceChatController(
  overrides: Partial<UseVoiceChatResult> = {}
): UseVoiceChatResult {
  const voiceOptions = overrides.voiceChatVoiceOptions ?? [{ value: "Puck", label: "Puck" }];
  return {
    voiceChatProvider: "Google",
    voiceChatProviderOptions: ["Google"],
    voiceChatModel: "gemini-3.1-flash-live-preview",
    voiceChatModelOptions: ["gemini-3.1-flash-live-preview"],
    voiceChatRealtimeChoicesByProvider: [
      { provider: "Google", models: ["gemini-3.1-flash-live-preview"] },
    ],
    voiceChatVoice: "Puck",
    voiceChatVoiceLabel: "Puck",
    voiceChatVoiceOptions: voiceOptions,
    voiceChatVoiceOptionsFor: (_provider: string, _model: string) => voiceOptions,
    voiceChatLiveTranslate: false,
    voiceChatTranslationMode: "bidirectional",
    voiceChatSourceLanguageCode: "zh-Hans",
    voiceChatTargetLanguageCode: "en",
    voiceChatTargetLanguageLabel: "English (en)",
    voiceChatTargetLanguageOptions: [{ value: "en", label: "English (en)" }],
    voiceChatEchoTargetLanguage: true,
    voiceChatEnableVoiceClone: false,
    voiceChatVoiceCloneFrequency: "once",
    voiceChatBusy: false,
    voiceChatRecording: false,
    voiceChatConnected: false,
    voiceChatMuted: overrides.voiceChatMuted ?? false,
    voiceChatDuration: overrides.voiceChatDuration ?? 0,
    voiceChatSupported: true,
    voiceChatStatus: "点击开始实时语音聊天",
    voiceChatError: "",
    voiceChatTranscript: "",
    voiceChatReply: "",
    voiceChatMemoriesRetrieved: 0,
    voiceChatMemoryWriteStatus: "",
    voiceChatMemorySourceStatus: "",
    voiceChatMemoryScope: "",
    voiceChatAgentToolStatus: "",
    voiceChatAgentSources: [],
    voiceChatAgentRunMeta: "",
    voiceChatInterruptionState: { phase: "idle" },
    voiceChatAssistantInterrupted: false,
    voiceChatMetrics: {
      firstAudioMs: null,
      interruptionStopMs: null,
      decisionCount: 0,
      trueBargeInCount: 0,
      backchannelCount: 0,
      noiseCount: 0,
      falseInterruptionRate: null,
    },
    voiceChatMemoryGroupId: "",
    voiceAgentHistorySessions: [],
    voiceAgentHistoryDetail: null,
    voiceAgentHistoryBusy: false,
    voiceAgentHistoryError: "",
    voiceAgentHistoryExportText: "",
    voiceAgentMetricsSummary: null,
    voiceChatMessages: [],
    voiceChatArchiveMessages: [],
    sessionSummary: [],
    onToggleRecording: vi.fn(),
    onToggleMute: vi.fn(),
    onProviderChange: vi.fn(),
    onModelChange: vi.fn(),
    onVoiceChange: vi.fn(),
    onTranslationModeChange: vi.fn(),
    onSourceLanguageCodeChange: vi.fn(),
    onTargetLanguageCodeChange: vi.fn(),
    onEchoTargetLanguageChange: vi.fn(),
    onVoiceCloneToggle: vi.fn(),
    onVoiceCloneFrequencyChange: vi.fn(),
    onSwapLanguages: vi.fn(),
    onPresetLanguagePairSelect: vi.fn(),
    onResetSession: vi.fn(),
    onLoadVoiceAgentHistory: vi.fn(),
    onOpenVoiceAgentSession: vi.fn(),
    onExportVoiceAgentSession: vi.fn(),
    replaceSession: vi.fn(),
    sendTextMessage: vi.fn(),
    startRecordingWithInitialPrompt: vi.fn(),
    micAnalyser: null,
    assistantAnalyser: null,
    ...overrides
  };
}

export function createTranslateController(
  overrides: Partial<UseTranslateResult> = {}
): UseTranslateResult {
  return {
    translateProvider: "TestProvider",
    translateModel: "",
    translateInput: "",
    sourceLanguage: "auto",
    targetLanguage: "en",
    translateBusy: false,
    translateError: "",
    translateInfo: "",
    translateResult: "Mock translation",
    speakingTarget: null,
    onSubmit: vi.fn(),
    onProviderChange: vi.fn(),
    onModelChange: vi.fn(),
    onInputChange: vi.fn(),
    onSourceLanguageChange: vi.fn(),
    onTargetLanguageChange: vi.fn(),
    onSwapLanguages: vi.fn(),
    onCopySource: vi.fn(),
    onCopyResult: vi.fn(),
    onSpeakSource: vi.fn(),
    onSpeakResult: vi.fn(),
    onPasteInput: vi.fn(),
    onClearSource: vi.fn(),
    onClearResult: vi.fn(),
    onClearAll: vi.fn(),
    ...overrides
  };
}

export function createSettingsController(
  overrides: Partial<UseSettingsResult> = {}
): UseSettingsResult {
  const displayLanguage: UiLanguage = overrides.displayLanguage ?? "zh-CN";
  return {
    settingsData: null,
    settingsBusy: false,
    settingsSaving: false,
    settingsError: "",
    settingsInfo: "",
    settingsConfigPath: "/tmp/config.json",
    settingsProvider: "DashScope",
    settingsApiKey: "",
    settingsApiUrl: "",
    settingsRealtimeApiUrl: "",
    settingsDoubaoAppId: "",
    settingsDoubaoAccessToken: "",
    settingsDoubaoWebsearchKey: "",
    xiaomiApiKey: "",
    xiaomiApiUrl: "",
    settingsTavusPalId: overrides.settingsTavusPalId ?? "",
    settingsDefaultModel: "qwen-plus",
    settingsAvailableModelsText: "qwen-plus\nqwen-max",
    settingsAvailableModels: ["qwen-plus", "qwen-max"],
    settingsEnabledModels: ["qwen-plus", "qwen-max"],
    settingsTtsDefaultModel: "",
    settingsTtsAvailableModels: [],
    settingsTtsEnabledModels: [],
    settingsTtsAvailableModelsText: "",
    settingsFetchingModels: false,
    transcriptionUploadMode: "static",
    transcriptionPublicBaseUrl: "",
    transcriptionS3Bucket: "",
    transcriptionS3Region: "",
    transcriptionS3EndpointUrl: "",
    transcriptionS3AccessKeyId: "",
    transcriptionS3SecretAccessKey: "",
    transcriptionS3KeyPrefix: "transcription",
    evermemEnabled: true,
    evermemApiUrl: "https://api.evermind.ai",
    evermemApiKey: "evermem-key",
    evermemScopeId: "workspace-main",
    evermemTempSession: false,
    evermemRememberChat: true,
    evermemRememberVoiceChat: true,
    evermemRememberRecordings: false,
    evermemRememberPodcast: true,
    evermemRememberTts: true,
    evermemStoreTranscript: false,
    backendRuntimeRaw: '{\n  "name": "Echo"\n}',
    backendRuntimeOpen: false,
    runtimeCopyStatus: "idle",
    desktopRememberWindowPosition: true,
    desktopAlwaysOnTop: false,
    desktopShowTrayIcon: false,
    desktopWakeShortcut: "Alt+Shift+S",
    displayLanguage,
    errorRuntimeContext: {
      backend_phase: "B",
      backend_auth_mode: "write-only-with-admin-settings",
      backend_auth_enabled: false,
      backend_version: "test",
      backend_status: "ok"
    },
    providerSection: {
      provider: "DashScope",
      apiKeyConfigured: false,
      apiUrlConfigured: false,
      defaultModelConfigured: true,
      availableModelCount: 2,
      availableModels: ["qwen-plus", "qwen-max"],
      enabledModels: ["qwen-plus", "qwen-max"]
    },
    dashscopeApiKeyConfigured: false,
    xiaomiApiKeyConfigured: false,
    providerModelCatalog: {
      DashScope: { defaultModel: "qwen-plus", availableModels: ["qwen-plus", "qwen-max"], enabledModels: ["qwen-plus", "qwen-max"], ttsDefaultModel: "", ttsAvailableModels: [], ttsEnabledModels: [] },
      Google: { defaultModel: "gemini-2.5-flash", availableModels: ["gemini-2.5-flash"], enabledModels: ["gemini-2.5-flash"], ttsDefaultModel: "", ttsAvailableModels: [], ttsEnabledModels: [] },
      Xiaomi: { defaultModel: "mimo-v2.5-pro", availableModels: ["mimo-v2.5-pro", "mimo-v2.5"], enabledModels: ["mimo-v2.5-pro", "mimo-v2.5"], ttsDefaultModel: "", ttsAvailableModels: [], ttsEnabledModels: [] }
    },
    memorySection: {
      enabled: true,
      configured: true,
      temporarySession: false,
      scopeIdConfigured: true,
      scenes: [
        { id: "chat", enabled: true, label: "聊天" },
        { id: "voice_chat", enabled: true, label: "语音聊天" },
        { id: "transcription", enabled: false, label: "录音转写" },
        { id: "podcast", enabled: true, label: "播客脚本" },
        { id: "tts", enabled: true, label: "语音合成" }
      ],
      storeTranscriptFulltext: false
    },
    transcriptionSection: {
      uploadMode: "static",
      publicBaseUrlConfigured: false,
      s3Configured: false,
      s3MissingFields: [],
      s3KeyPrefix: "transcription"
    },
    desktopSection: {
      configPath: "/tmp/config.json",
      backendPhase: "B",
      backendAuthMode: "write-only-with-admin-settings",
      backendAuthEnabled: false,
      backendVersion: "test",
      backendStatus: "ok",
      rememberWindowPosition: true,
      alwaysOnTop: false,
      showTrayIcon: false,
      wakeShortcut: "Alt+Shift+S",
      runtimeDir: "/tmp/voicespirit-runtime",
      diagnosticsDir: "/tmp/voicespirit-runtime/diagnostics",
      preflight: {
        available: true,
        ok: true,
        timestamp: "2026-03-10T22:45:02+0800",
        failed_checks: [],
        failed_count: 0
      },
      latestError: {
        available: false,
        timestamp: "",
        error_type: "",
        message: "",
        recovery_hints: []
      },
      runtimeVisible: false,
      runtimeCopyStatus: "idle"
    },
    providerOptions: ["DashScope", "Google", "Xiaomi"],
    customProviders: overrides.customProviders ?? [],
    settingsProviderUseMaxCompletionTokens: overrides.settingsProviderUseMaxCompletionTokens ?? false,
    settingsProviderHeadersJson: overrides.settingsProviderHeadersJson ?? "{}",
    isCustomProvider: overrides.isCustomProvider ?? false,
    onSubmit: vi.fn(),
    onReload: vi.fn(),
    onProviderChange: vi.fn(),
    onApiKeyChange: vi.fn(),
    onApiUrlChange: vi.fn(),
    onRealtimeApiUrlChange: vi.fn(),
    onDoubaoAppIdChange: vi.fn(),
    onDoubaoAccessTokenChange: vi.fn(),
    onDoubaoWebsearchKeyChange: vi.fn(),
    onXiaomiApiKeyChange: vi.fn(),
    onXiaomiApiUrlChange: vi.fn(),
    onTavusPalIdChange: overrides.onTavusPalIdChange ?? vi.fn(),
    onTtsDefaultModelChange: vi.fn(),
    onDefaultModelChange: vi.fn(),
    onAvailableModelsChange: vi.fn(),
    onToggleModelEnabled: vi.fn(),
    onEnableAllModels: vi.fn(),
    onDisableAllModels: vi.fn(),
    onTtsAvailableModelsChange: vi.fn(),
    onToggleTtsModelEnabled: vi.fn(),
    onEnableAllTtsModels: vi.fn(),
    onDisableAllTtsModels: vi.fn(),
    onFetchModels: vi.fn(),
    onAddCustomProvider: overrides.onAddCustomProvider ?? vi.fn(),
    onDeleteCustomProvider: overrides.onDeleteCustomProvider ?? vi.fn(),
    onUseMaxCompletionTokensChange: overrides.onUseMaxCompletionTokensChange ?? vi.fn(),
    onHeadersJsonChange: overrides.onHeadersJsonChange ?? vi.fn(),
    onTranscriptionUploadModeChange: vi.fn(),
    onTranscriptionPublicBaseUrlChange: vi.fn(),
    onTranscriptionS3BucketChange: vi.fn(),
    onTranscriptionS3RegionChange: vi.fn(),
    onTranscriptionS3EndpointUrlChange: vi.fn(),
    onTranscriptionS3AccessKeyIdChange: vi.fn(),
    onTranscriptionS3SecretAccessKeyChange: vi.fn(),
    onTranscriptionS3KeyPrefixChange: vi.fn(),
    onEvermemEnabledChange: vi.fn(),
    onEvermemApiUrlChange: vi.fn(),
    onEvermemApiKeyChange: vi.fn(),
    onEvermemScopeIdChange: vi.fn(),
    onEvermemTempSessionChange: vi.fn(),
    onEvermemRememberChatChange: vi.fn(),
    onEvermemRememberVoiceChatChange: vi.fn(),
    onEvermemRememberRecordingsChange: vi.fn(),
    onEvermemRememberPodcastChange: vi.fn(),
    onEvermemRememberTtsChange: vi.fn(),
    onEvermemStoreTranscriptChange: vi.fn(),
    onDesktopRememberWindowPositionChange: vi.fn(),
    onDesktopAlwaysOnTopChange: vi.fn(),
    onDesktopShowTrayIconChange: vi.fn(),
    onDesktopWakeShortcutChange: vi.fn(),
    onDisplayLanguageChange: vi.fn(),
    onToggleRuntimeOpen: vi.fn(),
    onCopyBackendRuntime: vi.fn(),
    ...overrides
  };
}

const defaultVoiceOptions: VoiceInfo[] = [
  {
    name: "zh-CN-XiaoxiaoNeural",
    short_name: "Xiaoxiao",
    locale: "zh-CN",
    gender: "Female"
  },
  {
    name: "zh-CN-YunxiNeural",
    short_name: "Yunxi",
    locale: "zh-CN",
    gender: "Male"
  }
];

const defaultPodcasts: AudioOverviewPodcast[] = [
  {
    id: 12,
    topic: "播客脚本测试",
    language: "zh",
    audio_path: null,
    created_at: "2026-03-07T10:00:00Z",
    updated_at: "2026-03-07T10:00:00Z",
    script_lines: [
      { role: "A", text: "第一段内容" },
      { role: "B", text: "第二段内容" }
    ]
  }
];

export function createAudioOverviewController(
  overrides: Partial<UseAudioOverviewResult> = {}
): UseAudioOverviewResult {
  return {
    audioOverviewWorkspaceMode: "podcast",
    audioOverviewWorkspaceTitle: "播客工作台",
    audioOverviewWorkspaceDescription: "围绕一个主题生成双人节目脚本，并进一步合成为完整音频。",
    audioOverviewBusy: false,
    audioOverviewSaving: false,
    audioOverviewSynthBusy: false,
    audioOverviewListBusy: false,
    audioOverviewError: "",
    audioOverviewInfo: "",
    audioOverviewProvider: "DashScope",
    audioOverviewModel: "",
    audioOverviewLanguage: "zh",
    audioOverviewPodcastId: 12,
    audioOverviewMergeStrategy: "auto",
    audioOverviewIntroMusic: false,
    audioOverviewIntroMusicStyle: "warm",
    audioOverviewIntroMusicDurationMs: 2500,
    audioOverviewTopic: "AI 对个人学习习惯的影响",
    audioOverviewTurnCount: 8,
    audioOverviewAdvancedOpen: false,
    audioOverviewMenuOpen: false,
    synthBarAdvancedOpen: false,
    audioOverviewUseMemory: false,
    audioOverviewMemoryConfigured: false,
    audioOverviewMemoriesRetrieved: 0,
    audioOverviewMemorySaved: false,
    audioAgentSourceText: "",
    audioAgentSourceUrlsText: "",
    audioAgentGenerationConstraints: "",
    audioAgentRunId: null,
    audioAgentStatus: "",
    audioAgentCurrentStep: "",
    audioAgentSteps: [],
    audioAgentSources: [],
    audioAgentResultProvider: "",
    audioAgentResultModel: "",
    audioAgentEvents: [],
    audioAgentErrorMessage: "",
    audioAgentCanRetry: false,
    agentRunHistory: [],
    agentRunHistoryBusy: false,
    audioOverviewScriptLines: [
      { role: "A", text: "第一段内容" },
      { role: "B", text: "第二段内容" }
    ],
    audioOverviewVoiceOptions: defaultVoiceOptions,
    audioOverviewVoiceA: "zh-CN-YunxiNeural",
    audioOverviewVoiceB: "zh-CN-XiaoxiaoNeural",
    audioOverviewSpeakerA: "主播 A",
    audioOverviewSpeakerB: "主播 B",
    audioOverviewRate: "+0%",
    audioOverviewGapMs: 250,
    audioOverviewAudioUrl: "",
    audioOverviewPodcasts: defaultPodcasts,
    currentAudioOverviewLabel: "播客 #12",
    onGenerateScript: vi.fn(),
    onNewDraft: vi.fn(),
    onWorkspaceModeChange: vi.fn(),
    onToggleMenu: vi.fn(),
    onDeleteCurrent: vi.fn(),
    onDeletePodcastById: vi.fn(),
    onTopicChange: vi.fn(),
    onToggleAdvanced: vi.fn(),
    onLanguageChange: vi.fn(),
    onProviderChange: vi.fn(),
    onModelChange: vi.fn(),
    onUseMemoryChange: vi.fn(),
    onSourceTextChange: vi.fn(),
    onSourceUrlsTextChange: vi.fn(),
    onGenerationConstraintsChange: vi.fn(),
    onTurnCountChange: vi.fn(),
    onSaveScript: vi.fn(),
    onCopyScript: vi.fn(),
    onExportScript: vi.fn(),
    onLineRoleChange: vi.fn(),
    onRemoveLine: vi.fn(),
    onLineTextChange: vi.fn(),
    onAddLine: vi.fn(),
    onVoiceAChange: vi.fn(),
    onVoiceBChange: vi.fn(),
    onSpeakerAChange: vi.fn(),
    onSpeakerBChange: vi.fn(),
    onToggleSynthAdvanced: vi.fn(),
    onSynthesize: vi.fn(),
    onRateChange: vi.fn(),
    onGapMsChange: vi.fn(),
    onMergeStrategyChange: vi.fn(),
    onIntroMusicChange: vi.fn(),
    onIntroMusicStyleChange: vi.fn(),
    onIntroMusicDurationChange: vi.fn(),
    onRefreshList: vi.fn(),
    onLoadPodcast: vi.fn(),
    onRetryAgentRun: vi.fn(),
    onLoadAgentRunHistory: vi.fn(),
    onOpenAgentRun: vi.fn(),
    onOpenAgentRunById: vi.fn(),
    ...overrides
  };
}

export function createVoiceDesignController(
  overrides: Partial<VoiceDesignController> = {}
): VoiceDesignController {
  return {
    designName: "",
    designLanguage: "zh",
    designPrompt: "",
    designPreviewText: "",
    designPreviewAudio: "",
    designBusy: false,
    designError: "",
    designInfo: "",
    designVoices: [],
    designCanSubmit: false,
    designPromptPresets: [
      {
        id: "warm_narrator",
        label: "温暖旁白",
        prompt: "温暖、亲和、清晰，适合知识讲解。"
      }
    ],
    designGuidelines: ["描述音色的人设、语气、节奏和使用场景。"],
    designListBusy: false,
    onNameChange: vi.fn(),
    onLanguageChange: vi.fn(),
    onPromptChange: vi.fn(),
    onPreviewTextChange: vi.fn(),
    onApplyPreset: vi.fn(),
    onSubmit: vi.fn(),
    onRefresh: vi.fn(),
    onDeleteVoice: vi.fn(),
    ...overrides
  };
}

export function createVoiceCloneController(
  overrides: Partial<VoiceCloneController> = {}
): VoiceCloneController {
  return {
    cloneName: "",
    cloneAudioFile: null as any,
    cloneBusy: false,
    cloneError: "",
    cloneInfo: "",
    cloneVoices: [],
    cloneCanSubmit: false,
    cloneFileSummary: "",
    cloneAcceptedFormats: ["mp3", "wav"],
    cloneRequirements: ["建议 10 到 30 秒的干净人声。"],
    cloneListBusy: false,
    onNameChange: vi.fn(),
    onAudioFileChange: vi.fn(),
    onSubmit: vi.fn(),
    onRefresh: vi.fn(),
    onDeleteVoice: vi.fn(),
    ...overrides
  };
}
