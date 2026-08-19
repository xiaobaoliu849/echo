import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  buildVoiceChatSessionConfig,
  buildVoiceChatWebSocketUrl,
  clearPersistedEverMemConversationGroupId,
  ensureEverMemConversationGroupId,
  fetchVoiceAgentMetricsSummary,
  fetchVoiceAgentSession,
  getPersistedEverMemConversationGroupId,
  listVoiceAgentSessions,
  persistEverMemConversationGroupId,
  type ChatMessage,
  type ChatAttachment,
  type VoiceAgentSource,
  type VoiceAgentSessionHistory,
  type VoiceAgentSessionHistoryDetailResponse,
  type VoiceAgentMetricsSummary,
  type VoiceChatServerEvent,
  type VoiceAgentToolRecord,
} from "../api";
import { createInlineTranslator } from "../i18n";
import { createMessageId, ensureMessageIds } from "../utils/messageId";
import {
  DASHSCOPE_PROVIDER,
  DEFAULT_DASHSCOPE_MODEL,
  DEFAULT_PERSONAPLEX_VOICE,
  DOUBAO_PROVIDER,
  DOUBAO_REALTIME_VOICES,
  EMPTY_VOICE_CHAT_METRICS,
  GOOGLE_PROVIDER,
  GOOGLE_REALTIME_VOICES,
  GLM4VOICE_PROVIDER,
  CARTESIA_PROVIDER,
  CARTESIA_REALTIME_VOICES,
  OPENAI_PROVIDER,
  OPENAI_REALTIME_VOICES,
  PERSONAPLEX_PROVIDER,
  PERSONAPLEX_REALTIME_VOICES,
  QWEN_AUDIO_VOICES,
  QWEN_LIVETRANSLATE_VOICES,
  QWEN_OMNI_REALTIME_VOICES,
  buildToolMeta,
  decodeBase64Pcm,
  encodePcm16k,
  endsWithSentencePunctuation,
  formatLiveTranslateLanguageOptions,
  formatRealtimeVoiceOptions,
  getAudioContextCtor,
  isLiveTranslateModel,
  isQwenAudioModel,
  isRealtimeVoiceModel,
  isTranscriptContinuation,
  mergeAssistantText,
  normalizeVoiceCaptureError,
  resolveDefaultModel,
  resolveRealtimeModelOptions,
  resolveRealtimeProvider,
  shouldCoalesceLiveTranslateSegment,
  isCJKPredominant,
  type Options,
  type TranslationMode,
  type VoiceChatInterruptionState,
  type VoiceChatMetrics
} from "./useVoiceChatHelpers";

export default function useVoiceChat({
  formatErrorMessage,
  providerOptions = [],
  providerModelCatalog = {},
  preferredProvider,
  preferredModel,
  language = "zh-CN",
}: Options) {
  const t = createInlineTranslator(language);
  const resolvedProviders = useMemo(
    () => [GOOGLE_PROVIDER, DASHSCOPE_PROVIDER, OPENAI_PROVIDER, DOUBAO_PROVIDER, PERSONAPLEX_PROVIDER, GLM4VOICE_PROVIDER, CARTESIA_PROVIDER]
      .filter(p => providerOptions.includes(p)),
    [providerOptions],
  );

  const initialProvider = resolveRealtimeProvider(preferredProvider, resolvedProviders);
  const initialModel = resolveDefaultModel(initialProvider, providerModelCatalog);
  const [voiceChatProvider, setVoiceChatProvider] = useState(initialProvider);
  const [voiceChatModel, setVoiceChatModel] = useState(initialModel);
  const [voiceChatVoice, setVoiceChatVoice] = useState(
    initialProvider === DASHSCOPE_PROVIDER
      ? (isQwenAudioModel(initialModel) ? "longanqian" : "Tina")
      : initialProvider === OPENAI_PROVIDER ? "alloy"
      : initialProvider === DOUBAO_PROVIDER ? "zh_female_vv_jupiter_bigtts"
      : initialProvider === CARTESIA_PROVIDER ? "f786b574-daa5-4673-aa0c-cbe3e8534c02"
      : "Puck"
  );
  const [voiceChatTranslationMode, setVoiceChatTranslationMode] = useState<TranslationMode>("bidirectional");
  const [voiceChatSourceLanguageCode, setVoiceChatSourceLanguageCode] = useState("zh-Hans");
  const [voiceChatTargetLanguageCode, setVoiceChatTargetLanguageCode] = useState("en");
  const [voiceChatEchoTargetLanguage, setVoiceChatEchoTargetLanguage] = useState(true);
  const [voiceChatEnableVoiceClone, setVoiceChatEnableVoiceClone] = useState(false);
  const [voiceChatVoiceCloneFrequency, setVoiceChatVoiceCloneFrequency] = useState<"once" | "always" | "never">("once");
  const [voiceChatBusy, setVoiceChatBusy] = useState(false);
  const [voiceChatRecording, setVoiceChatRecording] = useState(false);
  const [voiceChatSupported, setVoiceChatSupported] = useState(true);
  const [voiceChatStatus, setVoiceChatStatus] = useState(
    t("点击开始实时语音聊天", "Click to start realtime voice chat")
  );
  const [voiceChatError, setVoiceChatError] = useState("");
  const [voiceChatTranscript, setVoiceChatTranscript] = useState("");
  const [voiceChatReply, setVoiceChatReply] = useState("");
  const [voiceChatMessages, setVoiceChatMessages] = useState<ChatMessage[]>([]);
  const [voiceChatConnected, setVoiceChatConnected] = useState(false);
  const [voiceChatMemoriesRetrieved, setVoiceChatMemoriesRetrieved] = useState(0);
  const [voiceChatMemoryWriteStatus, setVoiceChatMemoryWriteStatus] = useState("");
  const [voiceChatMemorySourceStatus, setVoiceChatMemorySourceStatus] = useState("");
  const [voiceChatMemoryScope, setVoiceChatMemoryScope] = useState("");
  const [voiceChatAgentToolStatus, setVoiceChatAgentToolStatus] = useState("");
  const [voiceChatAgentSources, setVoiceChatAgentSources] = useState<VoiceAgentSource[]>([]);
  const [voiceChatAgentRunMeta, setVoiceChatAgentRunMeta] = useState("");
  const [voiceChatInterruptionState, setVoiceChatInterruptionState] =
    useState<VoiceChatInterruptionState>({ phase: "idle" });
  const [voiceChatAssistantInterrupted, setVoiceChatAssistantInterrupted] = useState(false);
  const [voiceChatMetrics, setVoiceChatMetrics] = useState<VoiceChatMetrics>(EMPTY_VOICE_CHAT_METRICS);
  const [voiceChatMemoryGroupId, setVoiceChatMemoryGroupId] = useState(
    () => getPersistedEverMemConversationGroupId("voice_chat")
  );
  const [voiceAgentHistorySessions, setVoiceAgentHistorySessions] = useState<VoiceAgentSessionHistory[]>([]);
  const [voiceAgentHistoryDetail, setVoiceAgentHistoryDetail] =
    useState<VoiceAgentSessionHistoryDetailResponse | null>(null);
  const [voiceAgentHistoryBusy, setVoiceAgentHistoryBusy] = useState(false);
  const [voiceAgentHistoryError, setVoiceAgentHistoryError] = useState("");
  const [voiceAgentHistoryExportText, setVoiceAgentHistoryExportText] = useState("");
  const [voiceAgentMetricsSummary, setVoiceAgentMetricsSummary] =
    useState<VoiceAgentMetricsSummary | null>(null);

  const websocketRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const muteGainRef = useRef<GainNode | null>(null);
  const assistantGainRef = useRef<GainNode | null>(null);
  const micAnalyserRef = useRef<AnalyserNode | null>(null);
  const assistantAnalyserRef = useRef<AnalyserNode | null>(null);
  const playingSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const assistantPlaybackGenerationRef = useRef(0);
  const nextPlaybackTimeRef = useRef(0);
  const audioInputReadyRef = useRef(false);
  const voiceChatConnectedRef = useRef(false);
  const currentUserTurnRef = useRef("");
  const currentUserTurnIsInterimRef = useRef(false);  // streaming ASR preview — replaced in place by the final transcript
  const currentAssistantTurnRef = useRef("");
  const liveTranslateSourceStreamRef = useRef("");
  const liveTranslateTargetStreamRef = useRef("");
  const liveTranslatePreviewRef = useRef("");  // speculative text from stash — NOT in the confirmed stream
  const liveTranslateConsumedSourceLengthRef = useRef(0);
  const liveTranslateConsumedTargetLengthRef = useRef(0);
  const liveTranslateBoundaryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const liveTranslateLastSourceActivityAtRef = useRef(0);
  const liveTranslateLastTargetActivityAtRef = useRef(0);
  const liveTranslatePairStartedAtRef = useRef(0);
  const liveTranslateSpeechActiveRef = useRef(false);
  const currentMemoriesRetrievedRef = useRef(0);
  const currentMemorySavedRef = useRef(false);
  const currentMemoryRetrieveAttemptedRef = useRef(false);
  const currentLocalPendingCountRef = useRef(0);
  const currentCloudCountRef = useRef(0);
  const currentToolRecordsRef = useRef<VoiceAgentToolRecord[]>([]);
  const currentTurnIdRef = useRef("");
  const currentAssistantInterruptedRef = useRef(false);
  const pendingInterruptionRef = useRef<{ candidateId: string; receivedAt: number } | null>(null);
  const interruptionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handledInterruptionCandidatesRef = useRef<Set<string>>(new Set());
  const finalizedInterruptionCandidatesRef = useRef<Set<string>>(new Set());
  const finalizedInterruptedTurnsRef = useRef<Set<string>>(new Set());
  const lastPreferredProviderRef = useRef(preferredProvider);
  const lastPreferredModelRef = useRef(preferredModel);
  const sessionEpochRef = useRef(0);
  const pendingInitialPromptRef = useRef<{ prompt: string; attachments?: ChatAttachment[] } | null>(null);

  const voiceChatModelOptions = resolveRealtimeModelOptions(voiceChatProvider, providerModelCatalog);
  // Realtime-capable models for every configured provider, so pickers can offer
  // cross-provider switching without going through the text-chat model list.
  const voiceChatRealtimeChoicesByProvider = resolvedProviders
    .map((provider) => ({
      provider,
      models: resolveRealtimeModelOptions(provider, providerModelCatalog),
    }))
    .filter((group) => group.models.length > 0);
  const voiceChatLiveTranslate = isLiveTranslateModel(voiceChatProvider, voiceChatModel);
  const voiceChatVoiceOptions = useMemo(
    () => formatRealtimeVoiceOptions(voiceChatProvider, language, voiceChatModel),
    [language, voiceChatProvider, voiceChatModel]
  );
  // Voice list for an arbitrary (possibly uncommitted) provider/model so pickers
  // can preview voices before committing the selection.
  const voiceChatVoiceOptionsFor = useCallback(
    (provider: string, model: string) => formatRealtimeVoiceOptions(provider, language, model),
    [language]
  );
  const voiceChatTargetLanguageOptions = useMemo(
    () => formatLiveTranslateLanguageOptions(language),
    [language]
  );
  const voiceChatVoiceLabel = voiceChatVoiceOptions.find((item) => item.value === voiceChatVoice)?.label || voiceChatVoice;
  const voiceChatTargetLanguageLabel =
    voiceChatTargetLanguageOptions.find((item) => item.value === voiceChatTargetLanguageCode)?.label ||
    voiceChatTargetLanguageCode;

  useEffect(() => {
    const preferredProviderChanged = lastPreferredProviderRef.current !== preferredProvider;
    lastPreferredProviderRef.current = preferredProvider;
    const preferredModelChanged = lastPreferredModelRef.current !== preferredModel;
    lastPreferredModelRef.current = preferredModel;

    const nextProvider = resolveRealtimeProvider(preferredProvider, resolvedProviders);
    if (preferredProviderChanged && voiceChatProvider !== nextProvider) {
      setVoiceChatProvider(nextProvider);
      const nextModel =
        preferredModel &&
        isRealtimeVoiceModel(nextProvider, preferredModel) &&
        (preferredModelChanged || nextProvider !== voiceChatProvider)
        ? preferredModel
        : resolveDefaultModel(nextProvider, providerModelCatalog);
      setVoiceChatModel(nextModel);
      return;
    }

    if (
      preferredModel &&
      preferredModelChanged &&
      preferredModel !== voiceChatModel &&
      isRealtimeVoiceModel(voiceChatProvider, preferredModel)
    ) {
      const availableModels = resolveRealtimeModelOptions(voiceChatProvider, providerModelCatalog);
      if (availableModels.length === 0 || availableModels.includes(preferredModel)) {
        setVoiceChatModel(preferredModel);
        return;
      }
    }

    const defaultModel = resolveDefaultModel(voiceChatProvider, providerModelCatalog);
    const availableModels = resolveRealtimeModelOptions(voiceChatProvider, providerModelCatalog);
    const currentModelValid =
      availableModels.length === 0 ||
      !voiceChatModel.trim() ||
      availableModels.includes(voiceChatModel.trim());
    if (!voiceChatModel.trim() || !currentModelValid) {
      setVoiceChatModel(defaultModel);
    }
  }, [
    preferredProvider,
    preferredModel,
    providerModelCatalog,
    resolvedProviders,
    voiceChatModel,
    voiceChatProvider,
  ]);

  useEffect(() => {
    if (voiceChatProvider === DASHSCOPE_PROVIDER) {
      const validVoices = isQwenAudioModel(voiceChatModel)
        ? QWEN_AUDIO_VOICES
        : isLiveTranslateModel(voiceChatProvider, voiceChatModel)
          ? QWEN_LIVETRANSLATE_VOICES
          : QWEN_OMNI_REALTIME_VOICES;
      if (!validVoices.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice(isQwenAudioModel(voiceChatModel) ? "longanqian" : "Tina");
      }
    } else if (voiceChatProvider === OPENAI_PROVIDER) {
      if (!OPENAI_REALTIME_VOICES.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice("alloy");
      }
    } else if (voiceChatProvider === DOUBAO_PROVIDER) {
      if (!DOUBAO_REALTIME_VOICES.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice("zh_female_vv_jupiter_bigtts");
      }
    } else if (voiceChatProvider === PERSONAPLEX_PROVIDER) {
      if (!PERSONAPLEX_REALTIME_VOICES.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice(DEFAULT_PERSONAPLEX_VOICE);
      }
    } else if (voiceChatProvider === GOOGLE_PROVIDER) {
      if (!GOOGLE_REALTIME_VOICES.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice("Puck");
      }
    } else if (voiceChatProvider === CARTESIA_PROVIDER) {
      if (!CARTESIA_REALTIME_VOICES.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice("f786b574-daa5-4673-aa0c-cbe3e8534c02");
      }
    }
    // voiceChatModel must be a dependency: switching between qwen-audio and other
    // DashScope models changes the valid voice set, so re-validate on model change.
  }, [voiceChatProvider, voiceChatModel, voiceChatVoice]);

  useEffect(() => {
    if (isLiveTranslateModel(voiceChatProvider, voiceChatModel)) {
      if (voiceChatTranslationMode !== "unidirectional") {
        setVoiceChatTranslationMode("unidirectional");
      }
    }
  }, [voiceChatProvider, voiceChatModel, voiceChatTranslationMode]);

  useEffect(() => {
    return () => {
      stopSessionResources();
    };
  }, []);

  function stopAssistantPlayback() {
    assistantPlaybackGenerationRef.current += 1;
    playingSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch {
        // Ignore already-finished nodes.
      }
    });
    playingSourcesRef.current = [];
    if (audioContextRef.current) {
      nextPlaybackTimeRef.current = audioContextRef.current.currentTime;
    }
  }

  function setAssistantPlaybackGain(value: number) {
    const gainNode = assistantGainRef.current;
    const context = audioContextRef.current;
    if (!gainNode || !context) {
      return;
    }
    const safeValue = Math.max(0, Math.min(1, value));
    try {
      gainNode.gain.cancelScheduledValues(context.currentTime);
      gainNode.gain.setTargetAtTime(safeValue, context.currentTime, 0.015);
    } catch {
      gainNode.gain.value = safeValue;
    }
  }

  function clearInterruptionTimeout() {
    if (interruptionTimeoutRef.current !== null) {
      clearTimeout(interruptionTimeoutRef.current);
      interruptionTimeoutRef.current = null;
    }
  }

  function clearLiveTranslateBoundaryTimer() {
    if (liveTranslateBoundaryTimerRef.current !== null) {
      clearTimeout(liveTranslateBoundaryTimerRef.current);
      liveTranslateBoundaryTimerRef.current = null;
    }
  }

  function resetLiveTranslateStreamTracking() {
    clearLiveTranslateBoundaryTimer();
    liveTranslateSourceStreamRef.current = "";
    liveTranslateTargetStreamRef.current = "";
    liveTranslatePreviewRef.current = "";
    liveTranslateConsumedSourceLengthRef.current = 0;
    liveTranslateConsumedTargetLengthRef.current = 0;
    liveTranslateLastSourceActivityAtRef.current = 0;
    liveTranslateLastTargetActivityAtRef.current = 0;
    liveTranslatePairStartedAtRef.current = 0;
    liveTranslateSpeechActiveRef.current = false;
  }

  function stopSessionResources() {
    const ws = websocketRef.current;
    websocketRef.current = null;
    audioInputReadyRef.current = false;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      try {
        ws.close();
      } catch {
        // Ignore close failures.
      }
    }

    processorRef.current?.disconnect();
    sourceRef.current?.disconnect();
    muteGainRef.current?.disconnect();
    assistantGainRef.current?.disconnect();
    micAnalyserRef.current?.disconnect();
    assistantAnalyserRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current = null;
    muteGainRef.current = null;
    assistantGainRef.current = null;
    micAnalyserRef.current = null;
    assistantAnalyserRef.current = null;

    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;

    stopAssistantPlayback();
    if (audioContextRef.current) {
      const context = audioContextRef.current;
      audioContextRef.current = null;
      void context.close().catch(() => { });
    }

    voiceChatConnectedRef.current = false;
    setVoiceChatConnected(false);
    setVoiceChatRecording(false);
    setVoiceChatBusy(false);
    clearInterruptionTimeout();
    clearLiveTranslateBoundaryTimer();
    pendingInterruptionRef.current = null;
    setVoiceChatInterruptionState({ phase: "idle" });
    setVoiceChatAssistantInterrupted(false);
  }

  function markNewSessionEpoch(): number {
    sessionEpochRef.current += 1;
    return sessionEpochRef.current;
  }

  function appendCurrentToolRecord(record: VoiceAgentToolRecord) {
    currentToolRecordsRef.current = [...currentToolRecordsRef.current, record];
  }

  function cloneCurrentToolRecords(): VoiceAgentToolRecord[] {
    return currentToolRecordsRef.current.map((record) => ({
      ...record,
      sources: record.sources?.map((source) => ({ ...source })),
      artifact: record.artifact ? { ...record.artifact } : undefined,
    }));
  }

  function resetCurrentToolRecords() {
    currentToolRecordsRef.current = [];
  }

  function getPendingLiveTranslatePair(): { source: string; target: string } {
    const confirmedTarget = liveTranslateTargetStreamRef.current
      .slice(liveTranslateConsumedTargetLengthRef.current)
      .trim();
    // Include the speculative stash as a trailing overlay so the user sees
    // the full predicted translation, but do NOT merge it into the confirmed
    // stream — that would cause confirmed deltas to double-append later.
    // The stash may carry a leading space for Latin-script translations
    // (e.g. " world") — preserve it so the concatenation below produces
    // correct word boundaries ("Hello" + " world" = "Hello world").
    const preview = liveTranslatePreviewRef.current;
    return {
      source: liveTranslateSourceStreamRef.current
        .slice(liveTranslateConsumedSourceLengthRef.current)
        .trim(),
      target: confirmedTarget + (preview ? preview : ""),
    };
  }

  function syncPendingLiveTranslatePair() {
    const { source, target } = getPendingLiveTranslatePair();
    currentUserTurnRef.current = source;
    currentAssistantTurnRef.current = target;
    setVoiceChatTranscript(source);
    setVoiceChatReply(target);
  }

  function commitPendingLiveTranslatePair(): boolean {
    clearLiveTranslateBoundaryTimer();
    const { source, target } = getPendingLiveTranslatePair();
    if (!source || !target) {
      return false;
    }
    const turnId = currentTurnIdRef.current || undefined;
    setVoiceChatMessages((previous) => [
      ...previous,
      { role: "user", content: source, memorySaved: false, id: createMessageId(), ...(turnId ? { turnId } : {}) },
      {
        role: "assistant",
        content: target,
        memoriesUsed: undefined,
        memorySourceSummary: undefined,
        memoryRetrievalAttempted: false,
        id: createMessageId(),
        ...(turnId ? { turnId } : {}),
      },
    ]);
    if (liveTranslatePreviewRef.current) {
      liveTranslateTargetStreamRef.current = mergeAssistantText(
        liveTranslateTargetStreamRef.current,
        liveTranslatePreviewRef.current
      );
      liveTranslatePreviewRef.current = "";
    }
    liveTranslateConsumedSourceLengthRef.current = liveTranslateSourceStreamRef.current.length;
    liveTranslateConsumedTargetLengthRef.current = liveTranslateTargetStreamRef.current.length;
    liveTranslatePairStartedAtRef.current = 0;
    currentUserTurnRef.current = "";
    currentAssistantTurnRef.current = "";
    currentTurnIdRef.current = "";
    setVoiceChatTranscript("");
    setVoiceChatReply("");
    return true;
  }

  function scheduleLiveTranslateBoundary(delayMs = 120) {
    clearLiveTranslateBoundaryTimer();
    const { source, target } = getPendingLiveTranslatePair();
    if (!source || !target || liveTranslateSpeechActiveRef.current) {
      return;
    }
    const now = Date.now();
    if (!liveTranslatePairStartedAtRef.current) {
      liveTranslatePairStartedAtRef.current = now;
    }
    liveTranslateBoundaryTimerRef.current = setTimeout(() => {
      liveTranslateBoundaryTimerRef.current = null;
      if (liveTranslateSpeechActiveRef.current) {
        return;
      }
      const pending = getPendingLiveTranslatePair();
      if (!pending.source || !pending.target) {
        return;
      }
      const checkedAt = Date.now();
      const sourceStableMs = checkedAt - liveTranslateLastSourceActivityAtRef.current;
      const targetStableMs = checkedAt - liveTranslateLastTargetActivityAtRef.current;
      const pairAgeMs = checkedAt - liveTranslatePairStartedAtRef.current;
      const hasCompletePunctuation =
        endsWithSentencePunctuation(pending.source) &&
        endsWithSentencePunctuation(pending.target);
      const naturallySettled = hasCompletePunctuation && sourceStableMs >= 500 && targetStableMs >= 600;
      const fallbackSettled = pairAgeMs >= 4500 && sourceStableMs >= 1200 && targetStableMs >= 1200;
      if ((naturallySettled || fallbackSettled) && commitPendingLiveTranslatePair()) {
        setVoiceChatStatus(t("本句翻译已完成，继续说话即可", "Sentence translated; keep speaking"));
        return;
      }
      scheduleLiveTranslateBoundary(120);
    }, delayMs);
  }

  function markLiveTranslateSpeechStarted() {
    const pending = getPendingLiveTranslatePair();
    const targetStableMs = Date.now() - liveTranslateLastTargetActivityAtRef.current;
    if (
      pending.source &&
      pending.target &&
      endsWithSentencePunctuation(pending.source) &&
      endsWithSentencePunctuation(pending.target) &&
      targetStableMs >= 150
    ) {
      commitPendingLiveTranslatePair();
    }
    clearLiveTranslateBoundaryTimer();
    liveTranslateSpeechActiveRef.current = true;
  }

  function markLiveTranslateSpeechEnded() {
    liveTranslateSpeechActiveRef.current = false;
    if (!liveTranslatePairStartedAtRef.current) {
      liveTranslatePairStartedAtRef.current = Date.now();
    }
    scheduleLiveTranslateBoundary();
  }

  function commitCompletedTurn() {
    const userText = currentUserTurnRef.current.trim();
    const assistantText = currentAssistantTurnRef.current.trim();
    const toolCalls = cloneCurrentToolRecords();
    const memorySaved = currentMemorySavedRef.current;
    const memoriesUsed = currentMemoriesRetrievedRef.current;
    const turnId = currentTurnIdRef.current || undefined;
    const assistantInterrupted = currentAssistantInterruptedRef.current;
    const memorySourceSummary = buildMemorySourceSummary({
      attempted: currentMemoryRetrieveAttemptedRef.current,
      total: memoriesUsed,
      localPendingCount: currentLocalPendingCountRef.current,
      cloudCount: currentCloudCountRef.current,
    });
    if (!userText && !assistantText && toolCalls.length === 0) {
      currentTurnIdRef.current = "";
      currentAssistantInterruptedRef.current = false;
      return;
    }
    setVoiceChatMessages((prev) => {
      const next = [...prev];
      if (userText) {
        next.push({ role: "user", content: userText, memorySaved, turnId, id: createMessageId() });
      }
      if (assistantText || toolCalls.length > 0) {
        const fallbackToolMessage = toolCalls.at(-1)?.message || t("工具调用已记录", "Tool call recorded");
        next.push({
          role: "assistant",
          content: assistantText || fallbackToolMessage,
          memoriesUsed: memoriesUsed > 0 ? memoriesUsed : undefined,
          memorySourceSummary: memorySourceSummary || undefined,
          memoryRetrievalAttempted: currentMemoryRetrieveAttemptedRef.current,
          toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
          turnId,
          interrupted: assistantInterrupted || undefined,
          id: createMessageId(),
        });
      }
      return next;
    });
    currentUserTurnRef.current = "";
    currentUserTurnIsInterimRef.current = false;
    currentAssistantTurnRef.current = "";
    currentTurnIdRef.current = "";
    currentAssistantInterruptedRef.current = false;
    resetCurrentToolRecords();
    currentMemorySavedRef.current = false;
    currentMemoryRetrieveAttemptedRef.current = false;
    currentLocalPendingCountRef.current = 0;
    currentCloudCountRef.current = 0;
    setVoiceChatTranscript("");
    setVoiceChatReply("");
  }

  function describeMemoryWriteResult(event: Extract<VoiceChatServerEvent, { type: "memory_write" }>): string {
    if (event.saved_count > 0 && event.failed_count === 0) {
      if ((event.local_pending_count || 0) > 0) {
        return t(
          `本轮已提交 EverMind ${event.saved_count} 条记忆，并加入本地待同步缓存`,
          `Submitted ${event.saved_count} memories to EverMind this turn and added them to the local pending cache`
        );
      }
      return t(
        `本轮已提交 EverMind ${event.saved_count} 条记忆`,
        `Submitted ${event.saved_count} memories to EverMind this turn`
      );
    }
    if (event.saved_count > 0 && event.failed_count > 0) {
      return t(
        `本轮部分提交 EverMind（${event.saved_count}/${event.attempted_count}）`,
        `Partially submitted EverMind memories this turn (${event.saved_count}/${event.attempted_count})`
      );
    }
    if (event.attempted_count === 0 && event.reason === "no_candidate_memory") {
      return t(
        "本轮未提炼出可保存的长期记忆",
        "No long-term memories were extracted from this turn"
      );
    }
    if (event.attempted_count === 0) {
      return "";
    }
    return t("本轮写入 EverMind 失败", "Failed to write EverMind memories for this turn");
  }

  function buildMemorySourceSummary(params: {
    attempted: boolean;
    total: number;
    localPendingCount: number;
    cloudCount: number;
  }): string {
    const local = Math.max(0, params.localPendingCount);
    const cloud = Math.max(0, params.cloudCount);
    if (!params.attempted) {
      return "";
    }
    if (params.total > 0) {
      return t(
        `来源：本地待同步 ${local} 条，云端 ${cloud} 条`,
        `Source: local pending ${local}, cloud ${cloud}`
      );
    }
    return t(
      `已尝试回忆：本地待同步 ${local} 条，云端 ${cloud} 条`,
      `Attempted recall: local pending ${local}, cloud ${cloud}`
    );
  }

  function describeMemoryContext(event: Extract<VoiceChatServerEvent, { type: "memory_context" }>): string {
    const local = Math.max(0, event.local_pending_count || 0);
    const cloud = Math.max(0, event.cloud_count || 0);
    if (event.memories_retrieved > 0) {
      return t(
        `已回忆 ${event.memories_retrieved} 条长期记忆（本地待同步 ${local}，云端 ${cloud}）`,
        `Recalled ${event.memories_retrieved} long-term memories (local pending ${local}, cloud ${cloud})`
      );
    }
    if (event.attempted) {
      return t(
        `已尝试回忆，但未命中匹配记忆（本地待同步 ${local}，云端 ${cloud}）`,
        `Attempted recall but found no matching memories (local pending ${local}, cloud ${cloud})`
      );
    }
    return "";
  }

  async function playAssistantAudio(base64Audio: string, sampleRate: number) {
    const context = audioContextRef.current;
    if (!context) {
      return;
    }
    const playbackGeneration = assistantPlaybackGenerationRef.current;
    if (context.state === "suspended") {
      await context.resume();
    }
    if (
      playbackGeneration !== assistantPlaybackGenerationRef.current
      || context !== audioContextRef.current
    ) {
      return;
    }
    if (nextPlaybackTimeRef.current < context.currentTime) {
      nextPlaybackTimeRef.current = context.currentTime + 0.08;
    }

    try {
      const pcm = decodeBase64Pcm(base64Audio);
      if (!pcm.length) {
        return;
      }

      const buffer = context.createBuffer(1, pcm.length, sampleRate);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i += 1) {
        channel[i] = pcm[i] / 32768;
      }

      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(assistantGainRef.current || context.destination);
      const startAt = Math.max(context.currentTime + 0.04, nextPlaybackTimeRef.current);
      source.start(startAt);
      nextPlaybackTimeRef.current = startAt + buffer.duration;
      playingSourcesRef.current.push(source);
      source.addEventListener("ended", () => {
        playingSourcesRef.current = playingSourcesRef.current.filter((item) => item !== source);
      });
    } catch (err) {
      // Log but do NOT propagate — a single corrupt chunk must not kill the
      // playback timeline for all subsequent chunks in this turn.
      console.warn("[VoiceChat] playAssistantAudio chunk error:", err);
    }
  }

  function recordInterruptionDecision(
    classification: "TRUE_BARGE_IN" | "BACKCHANNEL" | "NOISE_OR_SILENCE",
    stopLatencyMs: number | null
  ) {
    setVoiceChatMetrics((previous) => {
      const decisionCount = previous.decisionCount + 1;
      const trueBargeInCount = previous.trueBargeInCount + (classification === "TRUE_BARGE_IN" ? 1 : 0);
      const backchannelCount = previous.backchannelCount + (classification === "BACKCHANNEL" ? 1 : 0);
      const noiseCount = previous.noiseCount + (classification === "NOISE_OR_SILENCE" ? 1 : 0);
      return {
        ...previous,
        decisionCount,
        trueBargeInCount,
        backchannelCount,
        noiseCount,
        interruptionStopMs: stopLatencyMs ?? previous.interruptionStopMs,
        falseInterruptionRate: (backchannelCount + noiseCount) / decisionCount,
      };
    });
  }

  function handleRealtimeEvent(event: VoiceChatServerEvent) {
    switch (event.type) {
      case "session_open":
        voiceChatConnectedRef.current = true;
        setVoiceChatConnected(true);
        setVoiceChatRecording(true);
        setVoiceChatBusy(false);
        const currentEpoch = sessionEpochRef.current;
        const isTest = typeof (globalThis as any).process !== "undefined" && (globalThis as any).process.env?.VITEST === "true";
        if (isTest) {
          audioInputReadyRef.current = true;
        } else {
          setTimeout(() => {
            if (sessionEpochRef.current === currentEpoch) {
              audioInputReadyRef.current = true;
            }
          }, 400);
        }
        setVoiceChatInterruptionState({ phase: "idle" });
        setAssistantPlaybackGain(1);
        setVoiceChatStatus(t(`实时会话已连接：${event.model}`, `Realtime session connected: ${event.model}`));
        if (pendingInitialPromptRef.current) {
          const { prompt, attachments } = pendingInitialPromptRef.current;
          pendingInitialPromptRef.current = null;
          setTimeout(() => {
            sendTextMessage(prompt, attachments);
          }, 50);
        }
        return;
      case "memory_config":
        setVoiceChatMemoryScope(event.enabled ? event.scope : "");
        {
          const nextGroupId = event.enabled
            ? persistEverMemConversationGroupId("voice_chat", event.group_id || "")
            : "";
          if (!event.enabled) {
            clearPersistedEverMemConversationGroupId("voice_chat");
          }
          setVoiceChatMemoryGroupId(nextGroupId);
        }
        return;
      case "user_transcript":
        if (voiceChatLiveTranslate) {
          currentTurnIdRef.current = event.turn_id || currentTurnIdRef.current;
          liveTranslateLastSourceActivityAtRef.current = Date.now();
          const incomingSource = event.text || event.tentative || "";

          if (event.final && event.text) {
            // Completed ASR event: Qwen's canonical final text for this input item.
            // Replace the uncommitted portion of the source stream with this exact
            // text instead of merging (which would append the corrected text onto
            // early flawed ASR drafts).
            const consumed = liveTranslateConsumedSourceLengthRef.current;
            const prefix = liveTranslateSourceStreamRef.current.slice(0, consumed);
            const finalText = event.text.trim();
            if (prefix) {
              const needsSpace =
                !isCJKPredominant(prefix) && !isCJKPredominant(finalText);
              liveTranslateSourceStreamRef.current = `${prefix}${needsSpace ? " " : ""}${finalText}`;
            } else {
              liveTranslateSourceStreamRef.current = finalText;
            }
          } else {
            // Streaming cumulative transcript: compute pending source delta & merge
            const previousPendingSource = liveTranslateSourceStreamRef.current
              .slice(liveTranslateConsumedSourceLengthRef.current)
              .trim();
            const mergedSource = mergeAssistantText(
              liveTranslateSourceStreamRef.current,
              incomingSource
            );
            const newPendingSource = mergedSource
              .slice(liveTranslateConsumedSourceLengthRef.current)
              .trim();
            const sourceDelta = newPendingSource.startsWith(previousPendingSource)
              ? newPendingSource.slice(previousPendingSource.length).trim()
              : newPendingSource;
            const pendingTarget = getPendingLiveTranslatePair().target;
            if (
              previousPendingSource &&
              sourceDelta &&
              pendingTarget &&
              endsWithSentencePunctuation(pendingTarget) &&
              endsWithSentencePunctuation(previousPendingSource) &&
              !shouldCoalesceLiveTranslateSegment(previousPendingSource, sourceDelta)
            ) {
              commitPendingLiveTranslatePair();
            }
            liveTranslateSourceStreamRef.current = mergedSource;
          }

          syncPendingLiveTranslatePair();
          scheduleLiveTranslateBoundary();
          setVoiceChatStatus(t("正在识别本句原文…", "Transcribing this sentence…"));
          return;
        }
        if (event.interim) {
          // Streaming interim ASR (qwen-audio): show words as they are
          // recognized, updating the in-progress user turn in place. Never
          // commits a turn or resets tool/memory state — the final
          // transcript replaces this preview via the branch below.
          currentUserTurnIsInterimRef.current = true;
          currentUserTurnRef.current = event.text;
          setVoiceChatTranscript(event.text);
          setVoiceChatStatus(t("正在听你说话…", "Listening…"));
          return;
        }
        // A final transcript that replaces our interim preview must update
        // the same turn in place — ASR corrections mean it is NOT always a
        // prefix extension, so skip the continuation/commit checks that
        // would otherwise split one utterance into two bubbles.
        const replacingInterimPreview = currentUserTurnIsInterimRef.current;
        currentUserTurnIsInterimRef.current = false;
        if (
          !replacingInterimPreview &&
          event.turn_id &&
          currentUserTurnRef.current.trim() &&
          (currentUserTurnRef.current.trim().endsWith(event.text.trim()) ||
            event.text.trim().endsWith(currentUserTurnRef.current.trim()))
        ) {
          currentTurnIdRef.current = event.turn_id;
          return;
        }
        if (
          !replacingInterimPreview &&
          currentUserTurnRef.current.trim() &&
          !isTranscriptContinuation(currentUserTurnRef.current, event.text)
        ) {
          if (
            voiceChatLiveTranslate &&
            shouldCoalesceLiveTranslateSegment(currentUserTurnRef.current, event.text)
          ) {
            currentUserTurnRef.current = mergeAssistantText(currentUserTurnRef.current, event.text);
            setVoiceChatTranscript(currentUserTurnRef.current);
            setVoiceChatStatus(t("正在整理实时译文…", "Refining the live translation…"));
            return;
          }
          commitCompletedTurn();
        }
        setVoiceChatAgentToolStatus("");
        setVoiceChatAgentSources([]);
        setVoiceChatAgentRunMeta("");
        setVoiceChatInterruptionState({ phase: "idle" });
        setVoiceChatAssistantInterrupted(false);
        setAssistantPlaybackGain(1);
        currentAssistantInterruptedRef.current = false;
        currentUserTurnRef.current = event.text;
        currentTurnIdRef.current = event.turn_id || currentTurnIdRef.current;
        currentMemorySavedRef.current = false;
        currentMemoryRetrieveAttemptedRef.current = false;
        currentLocalPendingCountRef.current = 0;
        currentCloudCountRef.current = 0;
        setVoiceChatTranscript(event.text);
        currentMemoriesRetrievedRef.current = 0;
        setVoiceChatMemoriesRetrieved(0);
        setVoiceChatMemoryWriteStatus("");
        setVoiceChatMemorySourceStatus("");
        setVoiceChatStatus(t("正在听你说话…", "Listening…"));
        return;
      case "translation_preview":
        if (voiceChatLiveTranslate) {
          currentTurnIdRef.current = event.turn_id || currentTurnIdRef.current;
          liveTranslateLastTargetActivityAtRef.current = Date.now();
          // The stash from the translation model is a full speculative
          // suffix — it REPLACES the previous prediction, not extends it.
          // Always apply (even when empty) so the preview is cleared
          // when the model drops its speculative prediction without
          // changing the confirmed text.
          liveTranslatePreviewRef.current = event.tentative || "";
          syncPendingLiveTranslatePair();
          scheduleLiveTranslateBoundary();
          setVoiceChatStatus(t("正在生成本句译文…", "Translating this sentence…"));
        }
        return;
      case "memory_context":
        currentMemoryRetrieveAttemptedRef.current = Boolean(event.attempted);
        currentMemoriesRetrievedRef.current = event.memories_retrieved;
        currentLocalPendingCountRef.current = event.local_pending_count || 0;
        currentCloudCountRef.current = event.cloud_count || 0;
        setVoiceChatMemoriesRetrieved(event.memories_retrieved);
        setVoiceChatMemorySourceStatus(describeMemoryContext(event));
        setVoiceChatStatus(
          event.memories_retrieved > 0
            ? t(
              `已回忆 ${event.memories_retrieved} 条长期记忆，准备回答…`,
              `Recalled ${event.memories_retrieved} long-term memories, preparing a reply…`
            )
            : t("已尝试回忆，准备继续回答…", "Recall attempted, preparing the reply…")
        );
        return;
      case "memory_write":
        currentMemorySavedRef.current = event.saved_count > 0;
        setVoiceChatMemoryWriteStatus(describeMemoryWriteResult(event));
        return;
      case "assistant_text":
        if (voiceChatLiveTranslate) {
          currentTurnIdRef.current = event.turn_id || currentTurnIdRef.current;
          liveTranslateLastTargetActivityAtRef.current = Date.now();
          liveTranslateTargetStreamRef.current = mergeAssistantText(
            liveTranslateTargetStreamRef.current,
            event.text
          );
          // Clear the speculative preview — confirmed text has arrived and
          // the preview is incorporated into the confirmed stream above.
          liveTranslatePreviewRef.current = "";
          syncPendingLiveTranslatePair();
          scheduleLiveTranslateBoundary();
          setVoiceChatStatus(t("正在生成本句译文…", "Translating this sentence…"));
          return;
        }
        if (event.turn_id && finalizedInterruptedTurnsRef.current.has(event.turn_id)) {
          return;
        }
        if (event.turn_id && currentTurnIdRef.current && event.turn_id !== currentTurnIdRef.current) {
          commitCompletedTurn();
        }
        currentTurnIdRef.current = event.turn_id || currentTurnIdRef.current;
        if (!currentAssistantTurnRef.current && !currentAssistantInterruptedRef.current) {
          setVoiceChatAssistantInterrupted(false);
          setAssistantPlaybackGain(1);
        }
        currentAssistantTurnRef.current = mergeAssistantText(currentAssistantTurnRef.current, event.text);
        setVoiceChatReply(currentAssistantTurnRef.current);
        setVoiceChatStatus(t("助手正在说话…", "Assistant speaking…"));
        return;
      case "assistant_audio":
        if (voiceChatLiveTranslate) {
          liveTranslateLastTargetActivityAtRef.current = Date.now();
          scheduleLiveTranslateBoundary();
        }
        if (event.turn_id && finalizedInterruptedTurnsRef.current.has(event.turn_id)) {
          return;
        }
        if (event.turn_id && currentTurnIdRef.current && event.turn_id !== currentTurnIdRef.current) {
          commitCompletedTurn();
        }
        currentTurnIdRef.current = event.turn_id || currentTurnIdRef.current;
        if (!currentAssistantTurnRef.current && !currentAssistantInterruptedRef.current) {
          setVoiceChatAssistantInterrupted(false);
          setAssistantPlaybackGain(1);
        }
        if (typeof event.first_audio_ms === "number") {
          setVoiceChatMetrics((previous) => ({ ...previous, firstAudioMs: event.first_audio_ms ?? null }));
        }
        playAssistantAudio(event.audio, event.sample_rate).catch((err) => {
          console.warn("[VoiceChat] assistant audio promise rejected:", err);
        });
        return;
      case "interruption_pending":
        if (handledInterruptionCandidatesRef.current.has(event.candidate_id)) {
          return;
        }
        clearInterruptionTimeout();
        const receivedAt = performance.now();
        pendingInterruptionRef.current = {
          candidateId: event.candidate_id,
          receivedAt,
        };
        setAssistantPlaybackGain(0.18);
        setVoiceChatInterruptionState({ phase: "evaluating" });
        setVoiceChatStatus(t("检测到说话，正在判断是否打断…", "Speech detected, checking interruption intent…"));
        interruptionTimeoutRef.current = setTimeout(() => {
          interruptionTimeoutRef.current = null;
          const pending = pendingInterruptionRef.current;
          if (!pending || pending.candidateId !== event.candidate_id) {
            return;
          }
          const socket = websocketRef.current;
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
              type: "interruption_timeout",
              candidate_id: event.candidate_id,
            }));
          }
          setAssistantPlaybackGain(1);
          setVoiceChatInterruptionState({ phase: "idle" });
          setVoiceChatStatus(t("中断判断超时，已恢复助手播放", "Interruption check timed out; playback resumed"));
        }, 2500);
        return;
      case "interruption_decision": {
        if (handledInterruptionCandidatesRef.current.has(event.candidate_id)) {
          return;
        }
        const pending = pendingInterruptionRef.current;
        const matchesPending = !pending || pending.candidateId === event.candidate_id;
        if (!matchesPending) {
          return;
        }
        handledInterruptionCandidatesRef.current.add(event.candidate_id);
        clearInterruptionTimeout();
        pendingInterruptionRef.current = null;
        let stopLatencyMs: number | null = null;
        if (event.classification === "TRUE_BARGE_IN") {
          stopAssistantPlayback();
          setAssistantPlaybackGain(1);
          stopLatencyMs = pending
            ? Math.max(0, Math.round(performance.now() - pending.receivedAt))
            : null;
          const socket = websocketRef.current;
          if (stopLatencyMs !== null && socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
              type: "interruption_client_stopped",
              candidate_id: event.candidate_id,
              turn_id: event.interrupted_turn_id || currentTurnIdRef.current,
              stop_latency_ms: stopLatencyMs,
            }));
          }
        }
        recordInterruptionDecision(event.classification, stopLatencyMs);
        setVoiceChatInterruptionState({
          phase: event.classification === "TRUE_BARGE_IN" ? "interrupted" : "idle",
          classification: event.classification,
          rule: event.rule,
        });
        if (event.classification === "TRUE_BARGE_IN") {
          currentAssistantInterruptedRef.current = true;
          setVoiceChatAssistantInterrupted(true);
          return;
        }
        setAssistantPlaybackGain(1);
        setVoiceChatStatus(
          event.classification === "BACKCHANNEL"
            ? t("已识别为回应语，助手继续说话", "Backchannel detected; assistant continues")
            : t("已忽略噪声，助手继续说话", "Noise ignored; assistant continues")
        );
        return;
      }
      case "interrupted":
        if (event.candidate_id && finalizedInterruptionCandidatesRef.current.has(event.candidate_id)) {
          return;
        }
        if (event.turn_id && finalizedInterruptedTurnsRef.current.has(event.turn_id)) {
          return;
        }
        if (event.turn_id && currentTurnIdRef.current && event.turn_id !== currentTurnIdRef.current) {
          return;
        }
        stopAssistantPlayback();
        setAssistantPlaybackGain(1);
        currentAssistantInterruptedRef.current = true;
        currentTurnIdRef.current = event.turn_id || currentTurnIdRef.current;
        setVoiceChatAssistantInterrupted(true);
        if (event.candidate_id) {
          finalizedInterruptionCandidatesRef.current.add(event.candidate_id);
        }
        if (event.turn_id) {
          finalizedInterruptedTurnsRef.current.add(event.turn_id);
        }
        commitCompletedTurn();
        setVoiceChatAgentToolStatus("");
        setVoiceChatAgentSources([]);
        setVoiceChatAgentRunMeta("");
        setVoiceChatStatus(t("已打断助手，继续说话中…", "Assistant interrupted, continue speaking…"));
        return;
      case "tool_call_started":
        appendCurrentToolRecord({
          status: "started",
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          route: event.route,
          query: event.query,
          message: event.message,
        });
        setVoiceChatAgentSources([]);
        setVoiceChatAgentToolStatus(event.message || t("正在调用工具…", "Calling a tool…"));
        setVoiceChatAgentRunMeta(buildToolMeta({
          toolName: event.tool_name,
          turnId: event.turn_id,
        }));
        setVoiceChatStatus(event.message || t("正在调用工具…", "Calling a tool…"));
        return;
      case "agent_progress":
        appendCurrentToolRecord({
          status: "progress",
          stage: event.stage,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          route: event.route,
          message: event.message,
          elapsed_ms: event.elapsed_ms,
        });
        setVoiceChatAgentToolStatus(event.message);
        setVoiceChatAgentRunMeta(buildToolMeta({
          turnId: event.turn_id,
          elapsedMs: event.elapsed_ms,
        }));
        setVoiceChatStatus(event.message);
        return;
      case "tool_call_completed":
        appendCurrentToolRecord({
          status: "completed",
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          route: event.route,
          query: event.query,
          source_count: event.source_count,
          elapsed_ms: event.elapsed_ms,
          sources: event.sources || [],
        });
        setVoiceChatAgentToolStatus(
          t(
            `工具调用完成，已整理 ${event.source_count || 0} 个来源`,
            `Tool completed, organized ${event.source_count || 0} sources`
          )
        );
        setVoiceChatAgentRunMeta(buildToolMeta({
          toolName: event.tool_name,
          turnId: event.turn_id,
          sourceCount: event.source_count || 0,
          elapsedMs: event.elapsed_ms,
        }));
        return;
      case "tool_call_failed":
        appendCurrentToolRecord({
          status: "failed",
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          route: event.route,
          query: event.query,
          message: event.message,
          elapsed_ms: event.elapsed_ms,
        });
        setVoiceChatAgentToolStatus(
          event.message || t("工具调用失败", "Tool call failed")
        );
        setVoiceChatAgentRunMeta(buildToolMeta({
          toolName: event.tool_name,
          turnId: event.turn_id,
          elapsedMs: event.elapsed_ms,
        }));
        return;
      case "tool_call_cancelled":
        appendCurrentToolRecord({
          status: "cancelled",
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          route: event.route,
          query: event.query,
          reason: event.reason,
          elapsed_ms: event.elapsed_ms,
        });
        setVoiceChatAgentToolStatus(t("工具调用已取消", "Tool call cancelled"));
        setVoiceChatAgentRunMeta(buildToolMeta({
          toolName: event.tool_name,
          turnId: event.turn_id,
          elapsedMs: event.elapsed_ms,
          reason: event.reason,
        }));
        return;
      case "tool_context_injected":
        appendCurrentToolRecord({
          status: "context_injected",
          provider: event.provider,
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          query: event.query,
          source_count: event.source_count,
          elapsed_ms: event.elapsed_ms,
          sources: event.sources || [],
        });
        setVoiceChatAgentToolStatus(
          t(
            `已将搜索结果交给 ${event.provider} 生成语音回答`,
            `Passed search results to ${event.provider} for a voice answer`
          )
        );
        setVoiceChatAgentRunMeta(buildToolMeta({
          toolName: event.tool_name,
          turnId: event.turn_id,
          sourceCount: event.source_count,
          elapsedMs: event.elapsed_ms,
        }));
        setVoiceChatStatus(t("正在基于搜索结果语音回答…", "Answering from search results…"));
        return;
      case "tool_result_delivered":
        appendCurrentToolRecord({
          status: "result_delivered",
          provider: event.provider,
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          route: event.route,
          query: event.query,
          source_count: event.source_count,
          elapsed_ms: event.elapsed_ms,
          sources: event.sources || [],
        });
        setVoiceChatAgentToolStatus(
          event.status === "failed"
            ? t("工具失败信息已交给模型", "Tool failure was delivered to the model")
            : t("工具结果已交给模型，正在生成回答…", "Tool result delivered; generating the answer…")
        );
        setVoiceChatStatus(t("正在基于工具结果回答…", "Answering from the tool result…"));
        return;
      case "tool_result_delivery_failed":
        appendCurrentToolRecord({
          status: "delivery_failed",
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          route: event.route,
          query: event.query,
          message: event.message,
        });
        setVoiceChatAgentToolStatus(event.message || t("工具结果提交失败", "Failed to deliver tool result"));
        setVoiceChatStatus(t("工具结果提交失败", "Tool result delivery failed"));
        return;
      case "response_gated":
        stopAssistantPlayback();
        appendCurrentToolRecord({
          status: "response_gated",
          provider: event.provider,
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          query: event.query,
          message: event.message,
        });
        setVoiceChatAgentToolStatus(
          event.message || t("已暂停直接回答，等待工具结果", "Direct answer paused while waiting for tool results")
        );
        setVoiceChatAgentRunMeta(buildToolMeta({
          toolName: event.tool_name,
          turnId: event.turn_id,
        }));
        setVoiceChatStatus(t("正在等待搜索工具结果…", "Waiting for search tool results…"));
        return;
      case "agent_result":
        appendCurrentToolRecord({
          status: "result",
          tool_name: event.tool_name,
          turn_id: event.turn_id,
          tool_call_id: event.tool_call_id,
          provider_call_id: event.provider_call_id,
          route: event.route,
          query: event.query,
          answer: event.answer,
          source_count: event.source_count,
          elapsed_ms: event.elapsed_ms,
          artifact: event.artifact,
          sources: event.sources || [],
        });
        setVoiceChatAgentSources(event.sources || []);
        setVoiceChatAgentRunMeta(buildToolMeta({
          toolName: event.tool_name,
          turnId: event.turn_id,
          sourceCount: event.source_count ?? event.sources.length,
          elapsedMs: event.elapsed_ms,
        }));
        setVoiceChatAgentToolStatus(
          t(
            `已基于 ${event.sources.length} 个来源生成搜索摘要`,
            `Generated a search summary from ${event.sources.length} sources`
          )
        );
        setVoiceChatStatus(t("工具已完成，等待模型回答…", "Tool finished; waiting for the model…"));
        return;
      case "turn_complete":
        {
          if (event.turn_id && finalizedInterruptedTurnsRef.current.has(event.turn_id)) {
            return;
          }
          if (event.turn_id && currentTurnIdRef.current && event.turn_id !== currentTurnIdRef.current) {
            return;
          }
          currentTurnIdRef.current = event.turn_id || currentTurnIdRef.current;
          if (event.interrupted) {
            currentAssistantInterruptedRef.current = true;
            setVoiceChatAssistantInterrupted(true);
          }
          const retrievedCount = currentMemoriesRetrievedRef.current;
          const retrieveAttempted = currentMemoryRetrieveAttemptedRef.current;
          if (voiceChatLiveTranslate) {
            if (!commitPendingLiveTranslatePair()) {
              // Boundary timer may have already committed; falling through
              // to commitCompletedTurn() would re-commit currentUserTurnRef /
              // currentAssistantTurnRef from the last syncPendingLiveTranslatePair
              // call, producing exact duplicate messages.
              currentUserTurnRef.current = "";
              currentAssistantTurnRef.current = "";
              setVoiceChatTranscript("");
              setVoiceChatReply("");
            }
            resetLiveTranslateStreamTracking();
          } else {
            commitCompletedTurn();
          }
          setVoiceChatAgentToolStatus("");
          setVoiceChatAgentSources([]);
          setVoiceChatAgentRunMeta("");
          setVoiceChatStatus(
            retrievedCount > 0
              ? t(
                `本轮已完成，回忆了 ${retrievedCount} 条长期记忆`,
                `Turn completed, recalled ${retrievedCount} long-term memories`
              )
              : retrieveAttempted
                ? t("本轮已完成，已尝试回忆但未命中", "Turn completed, recall attempted with no match")
                : t("本轮已完成，继续说话即可", "Turn completed, keep speaking when ready")
          );
          return;
        }
      case "error":
        setVoiceChatError(
          event.message ||
          t(
            `实时语音后端返回错误。建议先选择 DashScope / ${DEFAULT_DASHSCOPE_MODEL} 重试。`,
            `The realtime voice backend returned an error. Try DashScope / ${DEFAULT_DASHSCOPE_MODEL} first.`
          )
        );
        setVoiceChatStatus(t("实时语音会话出错", "Realtime voice session failed"));
        stopSessionResources();
        return;
      case "pong":
      default:
        return;
    }
  }

  async function startSession() {
    if (voiceChatBusy || voiceChatConnected || voiceChatRecording) {
      return;
    }
    setVoiceChatBusy(true);
    setVoiceChatError("");
    const AudioContextCtor = getAudioContextCtor();
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof WebSocket === "undefined" ||
      !AudioContextCtor
    ) {
      setVoiceChatSupported(false);
      setVoiceChatBusy(false);
      setVoiceChatError(
        t("当前环境不支持实时语音聊天。", "Realtime voice chat is not supported in this environment.")
      );
      return;
    }

    const effectiveModel = (
      voiceChatModel && isRealtimeVoiceModel(voiceChatProvider, voiceChatModel)
        ? voiceChatModel
        : resolveDefaultModel(voiceChatProvider, providerModelCatalog)
    ).trim();

    if (!effectiveModel || !isRealtimeVoiceModel(voiceChatProvider, effectiveModel)) {
      setVoiceChatBusy(false);
      setVoiceChatError(
        t(
          "当前选择的服务商或模型不支持实时语音通话，请选择实时语音模型后重试。",
          "The selected provider or model does not support realtime voice calls. Please select a realtime voice model and try again."
        )
      );
      return;
    }

    try {
      const sessionEpoch = markNewSessionEpoch();
      setVoiceChatStatus(t("正在连接实时语音会话…", "Connecting to the realtime voice session…"));
      let memoryGroupId = "";
      try {
        memoryGroupId = await ensureEverMemConversationGroupId("voice_chat", voiceChatMemoryGroupId);
      } catch {
        memoryGroupId = "";
      }
      memoryGroupId = persistEverMemConversationGroupId("voice_chat", memoryGroupId);
      currentUserTurnRef.current = "";
      currentAssistantTurnRef.current = "";
      resetLiveTranslateStreamTracking();
      currentTurnIdRef.current = "";
      currentAssistantInterruptedRef.current = false;
      pendingInterruptionRef.current = null;
      handledInterruptionCandidatesRef.current.clear();
      finalizedInterruptionCandidatesRef.current.clear();
      finalizedInterruptedTurnsRef.current.clear();
      currentMemoriesRetrievedRef.current = 0;
      currentMemorySavedRef.current = false;
      currentMemoryRetrieveAttemptedRef.current = false;
      currentLocalPendingCountRef.current = 0;
      currentCloudCountRef.current = 0;
      setVoiceChatTranscript("");
      setVoiceChatReply("");
      setVoiceChatMemoriesRetrieved(0);
      setVoiceChatMemoryWriteStatus("");
      setVoiceChatMemorySourceStatus("");
      setVoiceChatAgentToolStatus("");
      setVoiceChatAgentSources([]);
      setVoiceChatAgentRunMeta("");
      setVoiceChatAssistantInterrupted(false);
      setVoiceChatInterruptionState({ phase: "idle" });
      setVoiceChatMetrics(EMPTY_VOICE_CHAT_METRICS);
      setVoiceChatMemoryScope("");
      setVoiceChatMemoryGroupId(memoryGroupId);

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;

      const audioContext = new AudioContextCtor();
      audioContextRef.current = audioContext;
      await audioContext.resume();
      const assistantGain = audioContext.createGain();
      assistantGain.gain.value = 1;
      assistantGain.connect(audioContext.destination);
      assistantGainRef.current = assistantGain;

      const micAnalyser = audioContext.createAnalyser();
      micAnalyser.fftSize = 64;
      micAnalyserRef.current = micAnalyser;

      const assistantAnalyser = audioContext.createAnalyser();
      assistantAnalyser.fftSize = 64;
      assistantGain.connect(assistantAnalyser);
      assistantAnalyserRef.current = assistantAnalyser;

      const wsUrl = buildVoiceChatWebSocketUrl({
        provider: voiceChatProvider,
        model: effectiveModel || undefined,
        voice: voiceChatVoice,
        translationMode: voiceChatLiveTranslate ? voiceChatTranslationMode : undefined,
        sourceLanguageCode: voiceChatLiveTranslate ? voiceChatSourceLanguageCode : undefined,
        targetLanguageCode: voiceChatLiveTranslate ? voiceChatTargetLanguageCode : undefined,
        echoTargetLanguage: voiceChatLiveTranslate ? voiceChatEchoTargetLanguage : undefined,
        enableVoiceClone: (voiceChatProvider === DASHSCOPE_PROVIDER && voiceChatLiveTranslate) ? voiceChatEnableVoiceClone : undefined,
        voiceCloneFrequency: (voiceChatProvider === DASHSCOPE_PROVIDER && voiceChatLiveTranslate) ? voiceChatVoiceCloneFrequency : undefined,
      });
      const ws = new WebSocket(wsUrl);
      const memoryConfig = buildVoiceChatSessionConfig(memoryGroupId || undefined);
      ws.binaryType = "arraybuffer";
      websocketRef.current = ws;
      audioInputReadyRef.current = false;
      nextPlaybackTimeRef.current = audioContext.currentTime + 0.12;

      ws.onmessage = (message) => {
        if (sessionEpochRef.current !== sessionEpoch) {
          return;
        }
        if (typeof message.data !== "string") {
          return;
        }
        try {
          handleRealtimeEvent(JSON.parse(message.data) as VoiceChatServerEvent);
        } catch {
          setVoiceChatError(t("实时语音消息解析失败。", "Failed to parse a realtime voice message."));
        }
      };

      ws.onerror = () => {
        if (sessionEpochRef.current !== sessionEpoch) {
          return;
        }
        setVoiceChatError(
          t(
            `实时语音连接失败。请确认后端正在运行，并且模型支持实时语音：${voiceChatProvider} / ${voiceChatModel || "默认模型"}。WebSocket: ${wsUrl}`,
            `Realtime voice connection failed. Confirm the backend is running and the model supports realtime voice: ${voiceChatProvider} / ${voiceChatModel || "default model"}. WebSocket: ${wsUrl}`
          )
        );
        setVoiceChatStatus(t("实时语音连接失败", "Realtime voice connection failed"));
      };

      ws.onclose = (event) => {
        if (sessionEpochRef.current !== sessionEpoch) {
          return;
        }
        const wasConnected = voiceChatConnectedRef.current;
        stopSessionResources();
        if (!wasConnected && event.code !== 1000) {
          setVoiceChatError((prev) => prev || t(
            `实时语音连接已关闭（code=${event.code}${event.reason ? `, reason=${event.reason}` : ""}）。建议先选择 DashScope / ${DEFAULT_DASHSCOPE_MODEL} 重试。`,
            `Realtime voice connection closed (code=${event.code}${event.reason ? `, reason=${event.reason}` : ""}). Try DashScope / ${DEFAULT_DASHSCOPE_MODEL} first.`
          ));
        }
        setVoiceChatStatus((prev) => (
          prev.includes(t("出错", "failed"))
            ? prev
            : t("实时语音会话已结束", "Realtime voice session ended")
        ));
      };

      ws.onopen = () => {
        if (sessionEpochRef.current !== sessionEpoch || websocketRef.current !== ws) {
          return;
        }
        if (memoryConfig) {
          ws.send(JSON.stringify({ type: "config", memory: memoryConfig }));
        }
        const source = audioContext.createMediaStreamSource(stream);
        if (micAnalyserRef.current) {
          source.connect(micAnalyserRef.current);
        }
        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        const muteGain = audioContext.createGain();
        muteGain.gain.value = 0;
        let localSpeechActive = false;
        let localSpeechFrames = 0;
        let localSilenceFrames = 0;

        processor.onaudioprocess = (audioEvent) => {
          if (sessionEpochRef.current !== sessionEpoch || ws.readyState !== WebSocket.OPEN) {
            return;
          }
          if (!audioInputReadyRef.current) {
            return;
          }
          const input = audioEvent.inputBuffer.getChannelData(0);
          if ((voiceChatProvider === GOOGLE_PROVIDER || voiceChatLiveTranslate) && input.length > 0) {
            let energy = 0;
            for (let index = 0; index < input.length; index += 1) {
              energy += input[index] * input[index];
            }
            const rms = Math.sqrt(energy / input.length);
            if (rms >= 0.025) {
              localSpeechFrames += 1;
              localSilenceFrames = 0;
              if (!localSpeechActive && localSpeechFrames >= 2) {
                localSpeechActive = true;
                if (voiceChatLiveTranslate) {
                  markLiveTranslateSpeechStarted();
                } else {
                  ws.send(JSON.stringify({ type: "speech_activity_started" }));
                }
              }
            } else {
              localSpeechFrames = 0;
              if (localSpeechActive) {
                localSilenceFrames += 1;
                if (localSilenceFrames >= 5) {
                  localSpeechActive = false;
                  localSilenceFrames = 0;
                  if (voiceChatLiveTranslate) {
                    markLiveTranslateSpeechEnded();
                  }
                }
              }
            }
          }
          const pcm = encodePcm16k(input, audioContext.sampleRate);
          if (pcm.byteLength > 0) {
            ws.send(pcm);
          }
        };

        source.connect(processor);
        processor.connect(muteGain);
        muteGain.connect(audioContext.destination);

        sourceRef.current = source;
        processorRef.current = processor;
        muteGainRef.current = muteGain;
      };
    } catch (err) {
      stopSessionResources();
      setVoiceChatError(
        normalizeVoiceCaptureError(
          err,
          formatErrorMessage(err, t("启动实时语音聊天失败。", "Failed to start realtime voice chat.")),
          t
        )
      );
      setVoiceChatStatus(t("实时语音不可用", "Realtime voice chat is unavailable"));
    }
  }

  function stopSession() {
    const ws = websocketRef.current;
    markNewSessionEpoch();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
    }
    if (voiceChatLiveTranslate) {
      if (!commitPendingLiveTranslatePair()) {
        commitCompletedTurn();
      }
      resetLiveTranslateStreamTracking();
    } else {
      commitCompletedTurn();
    }
    stopSessionResources();
    setVoiceChatStatus(t("实时语音会话已结束", "Realtime voice session ended"));
  }

  async function onToggleRecording() {
    if (voiceChatBusy) {
      return;
    }
    if (voiceChatConnected || voiceChatRecording) {
      stopSession();
      return;
    }
    await startSession();
  }

  async function onLoadVoiceAgentHistory(limit = 20) {
    setVoiceAgentHistoryBusy(true);
    setVoiceAgentHistoryError("");
    try {
      const [response, metrics] = await Promise.all([
        listVoiceAgentSessions(limit),
        fetchVoiceAgentMetricsSummary(200),
      ]);
      setVoiceAgentHistorySessions(Array.isArray(response.sessions) ? response.sessions : []);
      setVoiceAgentMetricsSummary(metrics);
    } catch (err) {
      setVoiceAgentHistoryError(
        formatErrorMessage(
          err,
          t("加载历史语音 Agent 会话失败。", "Failed to load voice agent session history.")
        )
      );
    } finally {
      setVoiceAgentHistoryBusy(false);
    }
  }

  async function onOpenVoiceAgentSession(sessionId: string) {
    const cleanSessionId = String(sessionId || "").trim();
    if (!cleanSessionId) {
      return;
    }
    setVoiceAgentHistoryBusy(true);
    setVoiceAgentHistoryError("");
    setVoiceAgentHistoryDetail(null);
    setVoiceAgentHistoryExportText("");
    try {
      const detail = await fetchVoiceAgentSession(cleanSessionId);
      setVoiceAgentHistoryDetail(detail);
    } catch (err) {
      setVoiceAgentHistoryError(
        formatErrorMessage(
          err,
          t("加载历史语音 Agent 会话详情失败。", "Failed to load voice agent session detail.")
        )
      );
    } finally {
      setVoiceAgentHistoryBusy(false);
    }
  }

  function onExportVoiceAgentSession(): string {
    if (!voiceAgentHistoryDetail) {
      setVoiceAgentHistoryError(
        t("请先打开一个历史语音 Agent 会话。", "Open a voice agent session before exporting.")
      );
      return "";
    }
    const exported = JSON.stringify(
      {
        exported_at: new Date().toISOString(),
        session: voiceAgentHistoryDetail,
      },
      null,
      2
    );
    setVoiceAgentHistoryExportText(exported);
    const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
    if (clipboard?.writeText) {
      void clipboard.writeText(exported).catch(() => undefined);
    }
    return exported;
  }

  const sessionSummary = useMemo(() => voiceChatMessages, [voiceChatMessages]);
  const voiceChatArchiveMessages = useMemo(() => {
    const currentUser = voiceChatTranscript.trim();
    const currentAssistant = voiceChatReply.trim();
    if (!currentUser && !currentAssistant) {
      return voiceChatMessages;
    }
    const next = [...voiceChatMessages];
    if (currentUser) {
      next.push({
        role: "user" as const,
        content: currentUser,
        memorySaved: currentMemorySavedRef.current,
        turnId: currentTurnIdRef.current || undefined,
      });
    }
    if (currentAssistant) {
      next.push({
        role: "assistant" as const,
        content: currentAssistant,
        memoriesUsed: currentMemoriesRetrievedRef.current > 0 ? currentMemoriesRetrievedRef.current : undefined,
        memorySourceSummary: buildMemorySourceSummary({
          attempted: currentMemoryRetrieveAttemptedRef.current,
          total: currentMemoriesRetrievedRef.current,
          localPendingCount: currentLocalPendingCountRef.current,
          cloudCount: currentCloudCountRef.current,
        }) || undefined,
        memoryRetrievalAttempted: currentMemoryRetrieveAttemptedRef.current,
        turnId: currentTurnIdRef.current || undefined,
        interrupted: currentAssistantInterruptedRef.current || undefined,
      });
    }
    return next;
  }, [voiceChatMessages, voiceChatTranscript, voiceChatReply]);

  const sendTextMessage = useCallback((text: string, attachments: ChatAttachment[] = []): boolean => {
    const ws = websocketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    const cleanText = text.trim();
    if (!cleanText && attachments.length === 0) {
      return false;
    }

    // Format attachments
    let formattedText = cleanText;
    const textAttachments = attachments.filter((att) => att.type !== "image" && !att.dataUrl?.startsWith("data:image/"));
    const imageAttachments = attachments.filter((att) => att.type === "image" || att.dataUrl?.startsWith("data:image/"));

    if (textAttachments.length > 0) {
      const formatted = textAttachments
        .map((att) => `[Attachment: ${att.name}]\n---\n${att.content || ""}\n---`)
        .join("\n\n");
      formattedText = formattedText ? `${formatted}\n\n${formattedText}` : formatted;
    }

    if (imageAttachments.length > 0) {
      const firstImage = imageAttachments[0];
      ws.send(
        JSON.stringify({
          type: "media_input",
          media_type: "image",
          mime_type: firstImage.mimeType || "image/jpeg",
          data: firstImage.dataUrl || firstImage.content,
          text: formattedText,
        })
      );
    } else {
      ws.send(
        JSON.stringify({
          type: "text_input",
          text: formattedText,
        })
      );
    }

    const userMsg: ChatMessage = {
      role: "user",
      content: cleanText || (imageAttachments.length > 0 ? t("[发送图片]", "[Sent image]") : t("[发送附件]", "[Sent attachment]")),
      attachments: attachments.map((att) => ({ ...att })),
      id: createMessageId(),
    };
    setVoiceChatMessages((prev) => [...prev, userMsg]);
    setVoiceChatReply("");
    setVoiceChatStatus(t("已发送输入，等待回复…", "Message sent, waiting for reply…"));
    return true;
  }, [t]);

  const startRecordingWithInitialPrompt = useCallback(async (prompt: string, attachments: ChatAttachment[] = []) => {
    pendingInitialPromptRef.current = { prompt, attachments };
    await startSession();
  }, []);

  function replaceSession(messages: ChatMessage[], memoryGroupId = "") {
    const normalizedGroupId = (memoryGroupId || "").trim();
    markNewSessionEpoch();
    stopSessionResources();
    currentUserTurnRef.current = "";
    currentAssistantTurnRef.current = "";
    resetLiveTranslateStreamTracking();
    currentTurnIdRef.current = "";
    currentAssistantInterruptedRef.current = false;
    pendingInterruptionRef.current = null;
    handledInterruptionCandidatesRef.current.clear();
    finalizedInterruptionCandidatesRef.current.clear();
    finalizedInterruptedTurnsRef.current.clear();
    currentMemoriesRetrievedRef.current = 0;
    currentMemorySavedRef.current = false;
    currentMemoryRetrieveAttemptedRef.current = false;
    currentLocalPendingCountRef.current = 0;
    currentCloudCountRef.current = 0;
    resetCurrentToolRecords();
    setVoiceChatMessages(Array.isArray(messages) ? ensureMessageIds(messages) : []);
    setVoiceChatTranscript("");
    setVoiceChatReply("");
    setVoiceChatMemoriesRetrieved(0);
    setVoiceChatError("");
    setVoiceChatMemoryWriteStatus("");
    setVoiceChatMemorySourceStatus("");
    setVoiceChatAgentToolStatus("");
    setVoiceChatAgentSources([]);
    setVoiceChatAgentRunMeta("");
    setVoiceChatAssistantInterrupted(false);
    setVoiceChatInterruptionState({ phase: "idle" });
    setVoiceChatMetrics(EMPTY_VOICE_CHAT_METRICS);
    setVoiceChatStatus(
      messages.length
        ? t("已恢复历史实时语音会话", "Restored a previous realtime voice session")
        : t("点击开始实时语音聊天", "Click to start realtime voice chat")
    );
    if (normalizedGroupId) {
      setVoiceChatMemoryGroupId(persistEverMemConversationGroupId("voice_chat", normalizedGroupId));
    } else {
      clearPersistedEverMemConversationGroupId("voice_chat");
      setVoiceChatMemoryGroupId("");
    }
  }

  return {
    voiceChatProvider,
    voiceChatProviderOptions: resolvedProviders,
    voiceChatModel,
    voiceChatModelOptions,
    voiceChatRealtimeChoicesByProvider,
    voiceChatVoice,
    voiceChatVoiceLabel,
    voiceChatVoiceOptions,
    voiceChatVoiceOptionsFor,
    voiceChatLiveTranslate,
    voiceChatTranslationMode,
    voiceChatSourceLanguageCode,
    voiceChatTargetLanguageCode,
    voiceChatTargetLanguageLabel,
    voiceChatTargetLanguageOptions,
    voiceChatEchoTargetLanguage,
    voiceChatEnableVoiceClone,
    voiceChatVoiceCloneFrequency,
    voiceChatBusy,
    voiceChatRecording,
    voiceChatConnected,
    voiceChatSupported,
    voiceChatStatus,
    voiceChatError,
    voiceChatTranscript,
    voiceChatReply,
    voiceChatMemoriesRetrieved,
    voiceChatMessages,
    voiceChatArchiveMessages,
    voiceChatInterruptionState,
    voiceChatAssistantInterrupted,
    voiceChatMetrics,
    sessionSummary,
    onToggleRecording,
    onProviderChange: (provider: string) => {
      setVoiceChatProvider(provider);
      setVoiceChatModel(resolveDefaultModel(provider, providerModelCatalog));
    },
    onModelChange: setVoiceChatModel,
    onVoiceChange: setVoiceChatVoice,
    onTranslationModeChange: setVoiceChatTranslationMode,
    onSourceLanguageCodeChange: setVoiceChatSourceLanguageCode,
    onTargetLanguageCodeChange: setVoiceChatTargetLanguageCode,
    onEchoTargetLanguageChange: setVoiceChatEchoTargetLanguage,
    onVoiceCloneToggle: setVoiceChatEnableVoiceClone,
    onVoiceCloneFrequencyChange: setVoiceChatVoiceCloneFrequency,
    onSwapLanguages: () => {
      const nextSource = voiceChatTargetLanguageCode;
      const nextTarget = voiceChatSourceLanguageCode;
      setVoiceChatSourceLanguageCode(nextSource);
      setVoiceChatTargetLanguageCode(nextTarget);
    },
    onPresetLanguagePairSelect: (source: string, target: string) => {
      setVoiceChatSourceLanguageCode(source);
      setVoiceChatTargetLanguageCode(target);
    },
    onResetSession: () => {
      markNewSessionEpoch();
      stopSessionResources();
      currentUserTurnRef.current = "";
      currentAssistantTurnRef.current = "";
      resetLiveTranslateStreamTracking();
      currentTurnIdRef.current = "";
      currentAssistantInterruptedRef.current = false;
      pendingInterruptionRef.current = null;
      handledInterruptionCandidatesRef.current.clear();
      finalizedInterruptionCandidatesRef.current.clear();
      finalizedInterruptedTurnsRef.current.clear();
      currentMemoriesRetrievedRef.current = 0;
      currentMemoryRetrieveAttemptedRef.current = false;
      currentLocalPendingCountRef.current = 0;
      currentCloudCountRef.current = 0;
      resetCurrentToolRecords();
      setVoiceChatTranscript("");
      setVoiceChatReply("");
      setVoiceChatMemoriesRetrieved(0);
      setVoiceChatMessages([]);
      setVoiceChatError("");
      setVoiceChatStatus(t("点击开始实时语音聊天", "Click to start realtime voice chat"));
      setVoiceChatMemoryWriteStatus("");
      setVoiceChatMemorySourceStatus("");
      setVoiceChatMemoryScope("");
      setVoiceChatAgentToolStatus("");
      setVoiceChatAgentSources([]);
      setVoiceChatAgentRunMeta("");
      setVoiceChatAssistantInterrupted(false);
      setVoiceChatInterruptionState({ phase: "idle" });
      setVoiceChatMetrics(EMPTY_VOICE_CHAT_METRICS);
      clearPersistedEverMemConversationGroupId("voice_chat");
      setVoiceChatMemoryGroupId("");
    },
    voiceChatMemoryWriteStatus,
    voiceChatMemorySourceStatus,
    voiceChatMemoryScope,
    voiceChatAgentToolStatus,
    voiceChatAgentSources,
    voiceChatAgentRunMeta,
    voiceChatMemoryGroupId,
    voiceAgentHistorySessions,
    voiceAgentHistoryDetail,
    voiceAgentHistoryBusy,
    voiceAgentHistoryError,
    voiceAgentHistoryExportText,
    voiceAgentMetricsSummary,
    onLoadVoiceAgentHistory,
    onOpenVoiceAgentSession,
    onExportVoiceAgentSession,
    replaceSession,
    sendTextMessage,
    startRecordingWithInitialPrompt,
    micAnalyser: micAnalyserRef.current,
    assistantAnalyser: assistantAnalyserRef.current,
  };
}

export type UseVoiceChatResult = ReturnType<typeof useVoiceChat>;
