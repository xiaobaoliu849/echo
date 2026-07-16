import { useEffect, useMemo, useRef, useState } from "react";
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
  type VoiceAgentSource,
  type VoiceAgentSessionHistory,
  type VoiceAgentSessionHistoryDetailResponse,
  type VoiceAgentMetricsSummary,
  type VoiceChatServerEvent,
  type VoiceAgentToolRecord,
} from "../api";
import { createInlineTranslator, type UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";

type ProviderModelCatalog = Record<
  string,
  {
    defaultModel: string;
    availableModels: string[];
    enabledModels?: string[];
  }
>;

type Options = {
  formatErrorMessage: FormatErrorMessage;
  providerOptions?: string[];
  providerModelCatalog?: ProviderModelCatalog;
  preferredProvider?: string;
  preferredModel?: string;
  language?: UiLanguage;
};

export type VoiceChatInterruptionState = {
  phase: "idle" | "evaluating" | "interrupted";
  classification?: "TRUE_BARGE_IN" | "BACKCHANNEL" | "NOISE_OR_SILENCE";
  rule?: string;
};

export type VoiceChatMetrics = {
  firstAudioMs: number | null;
  interruptionStopMs: number | null;
  decisionCount: number;
  trueBargeInCount: number;
  backchannelCount: number;
  noiseCount: number;
  falseInterruptionRate: number | null;
};

const EMPTY_VOICE_CHAT_METRICS: VoiceChatMetrics = {
  firstAudioMs: null,
  interruptionStopMs: null,
  decisionCount: 0,
  trueBargeInCount: 0,
  backchannelCount: 0,
  noiseCount: 0,
  falseInterruptionRate: null,
};

type AudioContextWindow = Window & {
  webkitAudioContext?: typeof AudioContext;
};

const GOOGLE_PROVIDER = "Google";
const DASHSCOPE_PROVIDER = "DashScope";
const OPENAI_PROVIDER = "OpenAI";
const DEFAULT_GOOGLE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025";
const GOOGLE_FLASH_LIVE_MODEL = "gemini-3.1-flash-live-preview";
const GOOGLE_LIVE_TRANSLATE_MODEL = "gemini-3.5-live-translate-preview";
const DEFAULT_DASHSCOPE_MODEL = "qwen3-omni-flash-realtime-2025-12-01";
const DEFAULT_OPENAI_MODEL = "gpt-realtime-2";
const SUPPORTED_GOOGLE_REALTIME_MODEL_PATTERNS = [
  "native-audio",
  "live",
  "realtime",
];

const GOOGLE_REALTIME_VOICES = [
  "Puck",
  "Aoede",
  "Zephyr",
  "Lyra",
  "Leda",
  "Achird",
  "Autonoe",
  "Despina",
  "Fenrir",
  "Sadachbia",
].map((name) => ({ value: name, label: name }));

const LIVE_TRANSLATE_LANGUAGE_PRIORITY = [
  "zh-Hans",
  "zh-Hant",
  "en",
  "ja",
  "ko",
  "fr",
  "de",
  "es",
  "pt-BR",
  "ru",
  "it",
  "ar",
  "th",
  "vi",
  "id",
];

const LIVE_TRANSLATE_TARGET_LANGUAGES = [
  { value: "af", label: "Afrikaans" },
  { value: "ak", label: "Akan" },
  { value: "sq", label: "Albanian" },
  { value: "am", label: "Amharic" },
  { value: "ar", label: "Arabic" },
  { value: "hy", label: "Armenian" },
  { value: "az", label: "Azerbaijani" },
  { value: "eu", label: "Basque" },
  { value: "be", label: "Belarusian" },
  { value: "bn", label: "Bengali" },
  { value: "bg", label: "Bulgarian" },
  { value: "my", label: "Burmese (Myanmar)" },
  { value: "ca", label: "Catalan" },
  { value: "zh-Hans", label: "Chinese (Simplified)" },
  { value: "zh-Hant", label: "Chinese (Traditional)" },
  { value: "hr", label: "Croatian" },
  { value: "cs", label: "Czech" },
  { value: "da", label: "Danish" },
  { value: "nl", label: "Dutch" },
  { value: "en", label: "English" },
  { value: "et", label: "Estonian" },
  { value: "fil", label: "Filipino" },
  { value: "fi", label: "Finnish" },
  { value: "fr", label: "French" },
  { value: "gl", label: "Galician" },
  { value: "ka", label: "Georgian" },
  { value: "de", label: "German" },
  { value: "el", label: "Greek" },
  { value: "gu", label: "Gujarati" },
  { value: "ha", label: "Hausa" },
  { value: "he", label: "Hebrew" },
  { value: "hi", label: "Hindi" },
  { value: "hu", label: "Hungarian" },
  { value: "is", label: "Icelandic" },
  { value: "id", label: "Indonesian" },
  { value: "it", label: "Italian" },
  { value: "ja", label: "Japanese" },
  { value: "jv", label: "Javanese" },
  { value: "kn", label: "Kannada" },
  { value: "kk", label: "Kazakh" },
  { value: "km", label: "Khmer" },
  { value: "rw", label: "Kinyarwanda" },
  { value: "ko", label: "Korean" },
  { value: "lo", label: "Lao" },
  { value: "lv", label: "Latvian" },
  { value: "lt", label: "Lithuanian" },
  { value: "mk", label: "Macedonian" },
  { value: "ms", label: "Malay" },
  { value: "ml", label: "Malayalam" },
  { value: "mr", label: "Marathi" },
  { value: "mn", label: "Mongolian" },
  { value: "ne", label: "Nepali" },
  { value: "no", label: "Norwegian" },
  { value: "nb", label: "Norwegian Bokmal" },
  { value: "fa", label: "Persian" },
  { value: "pl", label: "Polish" },
  { value: "pt-BR", label: "Portuguese (Brazil)" },
  { value: "pt-PT", label: "Portuguese (Portugal)" },
  { value: "pa", label: "Punjabi" },
  { value: "ro", label: "Romanian" },
  { value: "ru", label: "Russian" },
  { value: "sr", label: "Serbian" },
  { value: "sd", label: "Sindhi" },
  { value: "si", label: "Sinhala" },
  { value: "sk", label: "Slovak" },
  { value: "sl", label: "Slovenian" },
  { value: "es", label: "Spanish" },
  { value: "su", label: "Sundanese" },
  { value: "sw", label: "Swahili" },
  { value: "sv", label: "Swedish" },
  { value: "ta", label: "Tamil" },
  { value: "te", label: "Telugu" },
  { value: "th", label: "Thai" },
  { value: "tr", label: "Turkish" },
  { value: "uk", label: "Ukrainian" },
  { value: "ur", label: "Urdu" },
  { value: "uz", label: "Uzbek" },
  { value: "vi", label: "Vietnamese" },
  { value: "zu", label: "Zulu" },
];

const OPENAI_REALTIME_VOICES = [
  { value: "alloy", label: "Alloy (Neutral)" },
  { value: "ash", label: "Ash (Male)" },
  { value: "ballad", label: "Ballad (Male)" },
  { value: "coral", label: "Coral (Female)" },
  { value: "echo", label: "Echo (Male)" },
  { value: "sage", label: "Sage (Male)" },
  { value: "shimmer", label: "Shimmer (Female)" },
  { value: "verse", label: "Verse (Male)" },
];

const DASHSCOPE_REALTIME_VOICES = [
  { value: "Cherry", label: "Cherry (Female)" },
  { value: "Bella", label: "Bella (Female)" },
  { value: "Luna", label: "Luna (Female)" },
  { value: "Stella", label: "Stella (Female)" },
  { value: "Raya", label: "Raya (Female)" },
  { value: "Zita", label: "Zita (Female)" },
  { value: "Arda", label: "Arda (Male)" },
  { value: "Kall", label: "Kall (Male)" },
  { value: "Ollo", label: "Ollo (Male)" },
  { value: "Vrom", label: "Vrom (Male)" },
  { value: "Bale", label: "Bale (Male)" },
  { value: "Gale", label: "Gale (Male)" },
];

const QWEN_AUDIO_VOICES = [
  { value: "longanqian", label: "longanqian · 龙千倩 (Female)" },
  { value: "longanlingxin", label: "longanlingxin · 龙灵馨 (Female)" },
  { value: "longanlingxi", label: "longanlingxi · 龙灵犀 (Female)" },
  { value: "longanxiaoxin", label: "longanxiaoxin · 龙小新 (Female)" },
  { value: "longanlufeng", label: "longanlufeng · 龙陆风 (Male)" },
];

function isQwenAudioModel(model: string | undefined): boolean {
  return !!(model && model.toLowerCase().includes("qwen-audio"));
}

function formatVoiceOptionLabel(label: string, language: UiLanguage): string {
  if (language === "en-US") {
    return label;
  }
  return label
    .replace(" (Female)", " · 女声")
    .replace(" (Male)", " · 男声");
}

function formatRealtimeVoiceOptions(
  provider: string,
  language: UiLanguage,
  model?: string,
): Array<{ value: string; label: string }> {
  let options: Array<{ value: string; label: string }>;
  if (provider === DASHSCOPE_PROVIDER) {
    options = isQwenAudioModel(model) ? QWEN_AUDIO_VOICES : DASHSCOPE_REALTIME_VOICES;
  } else if (provider === OPENAI_PROVIDER) {
    options = OPENAI_REALTIME_VOICES;
  } else {
    options = GOOGLE_REALTIME_VOICES;
  }
  return options.map((item) => ({
    value: item.value,
    label: formatVoiceOptionLabel(item.label, language),
  }));
}

function getDisplayLanguageName(code: string, fallback: string, language: UiLanguage): string {
  try {
    const displayNames = new Intl.DisplayNames([language], { type: "language" });
    const name = displayNames.of(code);
    if (name) {
      return name;
    }
  } catch {
    // Intl.DisplayNames is not available in every embedded WebView/test runtime.
  }
  return fallback;
}

function formatLiveTranslateLanguageOptions(language: UiLanguage): Array<{ value: string; label: string }> {
  const priority = new Map(LIVE_TRANSLATE_LANGUAGE_PRIORITY.map((code, index) => [code, index]));
  return [...LIVE_TRANSLATE_TARGET_LANGUAGES]
    .sort((left, right) => {
      const leftRank = priority.get(left.value) ?? Number.MAX_SAFE_INTEGER;
      const rightRank = priority.get(right.value) ?? Number.MAX_SAFE_INTEGER;
      if (leftRank !== rightRank) {
        return leftRank - rightRank;
      }
      return left.label.localeCompare(right.label);
    })
    .map((item) => {
      if (language === "en-US") {
        return { ...item, label: `${item.label} (${item.value})` };
      }
      const zhName = getDisplayLanguageName(item.value, item.label, "zh-CN");
      return {
        ...item,
        label: `${zhName} / ${item.label} (${item.value})`,
      };
    });
}

function resolveRealtimeProvider(preferredProvider: string | undefined, providerOptions: string[]): string {
  const realtimeProviders = [GOOGLE_PROVIDER, DASHSCOPE_PROVIDER, OPENAI_PROVIDER];
  if (preferredProvider && realtimeProviders.includes(preferredProvider) && providerOptions.includes(preferredProvider)) {
    return preferredProvider;
  }
  if (providerOptions.includes(DASHSCOPE_PROVIDER)) {
    return DASHSCOPE_PROVIDER;
  }
  if (providerOptions.includes(GOOGLE_PROVIDER)) {
    return GOOGLE_PROVIDER;
  }
  if (providerOptions.includes(OPENAI_PROVIDER)) {
    return OPENAI_PROVIDER;
  }
  return providerOptions[0] || GOOGLE_PROVIDER;
}

function resolveDefaultModel(provider: string, providerModelCatalog: ProviderModelCatalog): string {
  return resolveRealtimeModelOptions(provider, providerModelCatalog)[0] || "";
}

function isRealtimeVoiceModel(provider: string, model: string): boolean {
  const normalizedProvider = (provider || "").trim().toLowerCase();
  const normalizedModel = (model || "").trim().toLowerCase();
  if (!normalizedModel) {
    return false;
  }
  if (normalizedProvider === DASHSCOPE_PROVIDER.toLowerCase()) {
    return normalizedModel.includes("realtime") || normalizedModel.includes("livetranslate");
  }
  if (normalizedProvider === GOOGLE_PROVIDER.toLowerCase()) {
    return SUPPORTED_GOOGLE_REALTIME_MODEL_PATTERNS.some((item) => normalizedModel.includes(item));
  }
  if (normalizedProvider === OPENAI_PROVIDER.toLowerCase()) {
    return normalizedModel.includes("realtime") || normalizedModel.includes("gpt-realtime");
  }
  return normalizedModel.includes("realtime");
}

function isLiveTranslateModel(provider: string, model: string): boolean {
  return provider.trim().toLowerCase() === GOOGLE_PROVIDER.toLowerCase()
    && model.trim().toLowerCase().includes("live-translate");
}

function resolveRealtimeFallbackModel(provider: string): string {
  if (provider === DASHSCOPE_PROVIDER) {
    return DEFAULT_DASHSCOPE_MODEL;
  }
  if (provider === GOOGLE_PROVIDER) {
    return DEFAULT_GOOGLE_MODEL;
  }
  if (provider === OPENAI_PROVIDER) {
    return DEFAULT_OPENAI_MODEL;
  }
  return "";
}

function resolveRealtimeModelOptions(
  provider: string,
  providerModelCatalog: ProviderModelCatalog
): string[] {
  const providerMeta = providerModelCatalog[provider];
  const enabledModels = Array.isArray(providerMeta?.enabledModels)
    ? providerMeta.enabledModels.map((item) => item.trim()).filter(Boolean)
    : [];
  const rawAvailable = Array.isArray(providerMeta?.availableModels)
    ? providerMeta.availableModels.map((item) => item.trim()).filter(Boolean)
    : [];

  const configuredModels = enabledModels.length > 0 ? enabledModels : rawAvailable;
  const realtimeModels = configuredModels.filter((item) => isRealtimeVoiceModel(provider, item));
  const preferredDefault = (providerMeta?.defaultModel || "").trim();
  const isPreferredValid = enabledModels.length === 0 || enabledModels.includes(preferredDefault);

  const fallbackModel = (isPreferredValid && isRealtimeVoiceModel(provider, preferredDefault))
    ? preferredDefault
    : resolveRealtimeFallbackModel(provider);
  const googleBuiltIns = provider === GOOGLE_PROVIDER
    ? [DEFAULT_GOOGLE_MODEL, GOOGLE_FLASH_LIVE_MODEL, GOOGLE_LIVE_TRANSLATE_MODEL]
    : [];
  const openaiBuiltIns = provider === OPENAI_PROVIDER
    ? [DEFAULT_OPENAI_MODEL]
    : [];
  const allBuiltIns = [...googleBuiltIns, ...openaiBuiltIns];
  const ordered = fallbackModel ? [fallbackModel, ...allBuiltIns, ...realtimeModels] : [...allBuiltIns, ...realtimeModels];
  return [...new Set(ordered.filter(Boolean))];
}

function getAudioContextCtor(): typeof AudioContext | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  const audioWindow = window as AudioContextWindow;
  return window.AudioContext || audioWindow.webkitAudioContext;
}

function encodePcm16k(input: Float32Array, inputRate: number): ArrayBuffer {
  if (!input.length) {
    return new ArrayBuffer(0);
  }
  const targetRate = 16000;
  if (inputRate === targetRate) {
    const direct = new Int16Array(input.length);
    for (let i = 0; i < input.length; i += 1) {
      const clamped = Math.max(-1, Math.min(1, input[i]));
      direct[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    }
    return direct.buffer;
  }

  const ratio = inputRate / targetRate;
  const targetLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Int16Array(targetLength);
  let sourceIndex = 0;

  for (let i = 0; i < targetLength; i += 1) {
    const nextSourceIndex = Math.min(input.length, Math.round((i + 1) * ratio));
    let total = 0;
    let count = 0;
    while (sourceIndex < nextSourceIndex) {
      total += input[sourceIndex];
      count += 1;
      sourceIndex += 1;
    }
    const sample = count > 0 ? total / count : input[Math.min(sourceIndex, input.length - 1)] || 0;
    const clamped = Math.max(-1, Math.min(1, sample));
    output[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }

  return output.buffer;
}

function decodeBase64Pcm(base64Audio: string): Int16Array {
  const binary = atob(base64Audio);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer);
}

function mergeAssistantText(previous: string, incoming: string): string {
  const next = incoming.trim();
  if (!next) {
    return previous;
  }
  if (!previous) {
    return next;
  }
  if (next.startsWith(previous)) {
    return next;
  }
  if (previous.endsWith(next)) {
    return previous;
  }
  return appendStreamingText(previous, next);
}

function containsLatinText(value: string): boolean {
  return /[A-Za-z]/.test(value);
}

function appendStreamingText(previous: string, incoming: string): string {
  const before = previous.trim();
  const next = incoming.trim();
  if (!before) {
    return next;
  }
  if (!next) {
    return before;
  }
  if (containsLatinText(before) || containsLatinText(next)) {
    return `${before} ${next}`.replace(/\s+([,.!?;:])/g, "$1");
  }
  return `${before}${next}`;
}

function endsWithSentencePunctuation(value: string): boolean {
  return /[.!?。！？]\s*$/.test(value.trim());
}

function countLatinWords(value: string): number {
  return (value.match(/[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?/g) || []).length;
}

function shouldCoalesceLiveTranslateSegment(previousSource: string, nextSource: string): boolean {
  const before = previousSource.trim();
  const next = nextSource.trim();
  if (!before || !next) {
    return false;
  }
  if (isTranscriptContinuation(before, next)) {
    return true;
  }
  if (!endsWithSentencePunctuation(before)) {
    return true;
  }
  const latinBefore = containsLatinText(before);
  const latinNext = containsLatinText(next);
  if (latinBefore || latinNext) {
    return countLatinWords(next) <= 3 && next.length <= 20;
  }
  return next.length <= 6;
}

function isTranscriptContinuation(previous: string, incoming: string): boolean {
  const before = previous.trim();
  const next = incoming.trim();
  if (!before || !next) {
    return true;
  }
  return next.startsWith(before) || before.startsWith(next);
}

function formatElapsedMs(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return "";
  }
  if (value < 1000) {
    return `${Math.round(value)}ms`;
  }
  return `${(value / 1000).toFixed(1)}s`;
}

function buildToolMeta(params: {
  toolName?: string;
  turnId?: string;
  sourceCount?: number;
  elapsedMs?: number;
  reason?: string;
}): string {
  const parts = [
    params.turnId || "",
    params.toolName || "",
    typeof params.sourceCount === "number" ? `${params.sourceCount} sources` : "",
    formatElapsedMs(params.elapsedMs),
    params.reason || "",
  ].filter(Boolean);
  return parts.join(" · ");
}

function normalizeVoiceCaptureError(
  error: unknown,
  fallback: string,
  t: (zh: string, en: string) => string
): string {
  if (!(error instanceof Error)) {
    return fallback;
  }

  const name = (error.name || "").trim();
  const message = (error.message || "").trim();
  const lowerMessage = message.toLowerCase();

  if (
    name === "NotFoundError" ||
    name === "DevicesNotFoundError" ||
    lowerMessage.includes("requested device not found") ||
    lowerMessage.includes("device not found")
  ) {
    return t(
      "未检测到可用麦克风设备。若你在 Ubuntu/WSL 中运行桌面版，请改用 Windows 的 run_web_desktop.bat，或先配置麦克风透传。",
      "No microphone device was detected. If you are running the desktop app from Ubuntu/WSL, use Windows run_web_desktop.bat or configure microphone passthrough first."
    );
  }

  if (name === "NotAllowedError" || lowerMessage.includes("permission denied")) {
    return t(
      "麦克风权限被拒绝。请允许当前页面/桌面壳访问麦克风后重试：浏览器中打开地址栏左侧站点权限，允许 http://127.0.0.1 的麦克风；桌面版请在 Windows 麦克风隐私里允许 Python/VoiceSpirit/WebView，并可通过菜单「系统 -> 重置桌面缓存并重启」清掉之前的拒绝记录。注意：打开 Codex 的麦克风权限不会授权 VoiceSpirit。",
      "Microphone access was denied. Allow microphone access for the current page/desktop shell and try again: in a browser, open the site permissions beside the address bar and allow microphone access for http://127.0.0.1; in the desktop app, allow Python/VoiceSpirit/WebView in Windows microphone privacy settings, and use System -> Reset Cache to clear a previously denied WebView permission. Enabling microphone access for Codex does not grant it to VoiceSpirit."
    );
  }

  if (name === "NotReadableError" || lowerMessage.includes("could not start audio source")) {
    return t(
      "麦克风当前不可读，可能被其他应用占用。请关闭占用麦克风的软件后重试。",
      "The microphone is not readable right now, likely because another app is using it. Close the competing app and try again."
    );
  }

  return message || fallback;
}

export default function useVoiceChat({
  formatErrorMessage,
  providerOptions = [],
  providerModelCatalog = {},
  preferredProvider,
  preferredModel,
  language = "zh-CN",
}: Options) {
  const t = createInlineTranslator(language);
  const resolvedProviders = [GOOGLE_PROVIDER, DASHSCOPE_PROVIDER, OPENAI_PROVIDER].filter(p => providerOptions.includes(p));

  const initialProvider = resolveRealtimeProvider(preferredProvider, resolvedProviders);
  const initialModel = resolveDefaultModel(initialProvider, providerModelCatalog);
  const [voiceChatProvider, setVoiceChatProvider] = useState(initialProvider);
  const [voiceChatModel, setVoiceChatModel] = useState(initialModel);
  const [voiceChatVoice, setVoiceChatVoice] = useState(
    initialProvider === DASHSCOPE_PROVIDER
      ? (isQwenAudioModel(initialModel) ? "longanqian" : "Cherry")
      : initialProvider === OPENAI_PROVIDER ? "alloy"
      : "Puck"
  );
  const [voiceChatTargetLanguageCode, setVoiceChatTargetLanguageCode] = useState("en");
  const [voiceChatEchoTargetLanguage, setVoiceChatEchoTargetLanguage] = useState(true);
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
  const playingSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const assistantPlaybackGenerationRef = useRef(0);
  const nextPlaybackTimeRef = useRef(0);
  const audioInputReadyRef = useRef(false);
  const currentUserTurnRef = useRef("");
  const currentAssistantTurnRef = useRef("");
  const liveTranslateSourceStreamRef = useRef("");
  const liveTranslateTargetStreamRef = useRef("");
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

  const voiceChatModelOptions = resolveRealtimeModelOptions(voiceChatProvider, providerModelCatalog);
  const voiceChatLiveTranslate = isLiveTranslateModel(voiceChatProvider, voiceChatModel);
  const voiceChatVoiceOptions = useMemo(
    () => formatRealtimeVoiceOptions(voiceChatProvider, language, voiceChatModel),
    [language, voiceChatProvider, voiceChatModel]
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
      const validVoices = isQwenAudioModel(voiceChatModel) ? QWEN_AUDIO_VOICES : DASHSCOPE_REALTIME_VOICES;
      if (!validVoices.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice(isQwenAudioModel(voiceChatModel) ? "longanqian" : "Cherry");
      }
    } else if (voiceChatProvider === OPENAI_PROVIDER) {
      if (!OPENAI_REALTIME_VOICES.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice("alloy");
      }
    } else if (voiceChatProvider === GOOGLE_PROVIDER) {
      if (!GOOGLE_REALTIME_VOICES.some(v => v.value === voiceChatVoice)) {
        setVoiceChatVoice("Puck");
      }
    }
  }, [voiceChatProvider, voiceChatVoice]);

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
    processorRef.current = null;
    sourceRef.current = null;
    muteGainRef.current = null;
    assistantGainRef.current = null;

    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;

    stopAssistantPlayback();
    if (audioContextRef.current) {
      const context = audioContextRef.current;
      audioContextRef.current = null;
      void context.close().catch(() => { });
    }

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
    return {
      source: liveTranslateSourceStreamRef.current
        .slice(liveTranslateConsumedSourceLengthRef.current)
        .trim(),
      target: liveTranslateTargetStreamRef.current
        .slice(liveTranslateConsumedTargetLengthRef.current)
        .trim(),
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
      { role: "user", content: source, memorySaved: false, ...(turnId ? { turnId } : {}) },
      {
        role: "assistant",
        content: target,
        memoriesUsed: undefined,
        memorySourceSummary: undefined,
        memoryRetrievalAttempted: false,
        ...(turnId ? { turnId } : {}),
      },
    ]);
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
      const naturallySettled = hasCompletePunctuation && sourceStableMs >= 200 && targetStableMs >= 400;
      const fallbackSettled = pairAgeMs >= 2500 && sourceStableMs >= 400 && targetStableMs >= 600;
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
        next.push({ role: "user", content: userText, memorySaved, turnId });
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
        });
      }
      return next;
    });
    currentUserTurnRef.current = "";
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
        setVoiceChatConnected(true);
        setVoiceChatRecording(true);
        setVoiceChatBusy(false);
        audioInputReadyRef.current = true;
        setVoiceChatInterruptionState({ phase: "idle" });
        setAssistantPlaybackGain(1);
        setVoiceChatStatus(t(`实时会话已连接：${event.model}`, `Realtime session connected: ${event.model}`));
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
          // Compute the previous pending (unconsumed) source text BEFORE merging
          const previousPendingSource = liveTranslateSourceStreamRef.current
            .slice(liveTranslateConsumedSourceLengthRef.current)
            .trim();
          // Determine what new text this event would add beyond the consumed pointer.
          // For cumulative transcripts (Google Live Translate): event.text contains the
          // full accumulated source. We merge it to get the updated stream, then derive
          // the delta by comparing the new pending portion against the old one.
          const mergedSource = mergeAssistantText(
            liveTranslateSourceStreamRef.current,
            event.text
          );
          const newPendingSource = mergedSource
            .slice(liveTranslateConsumedSourceLengthRef.current)
            .trim();
          const sourceDelta = newPendingSource.startsWith(previousPendingSource)
            ? newPendingSource.slice(previousPendingSource.length).trim()
            : newPendingSource;
          const pendingTarget = getPendingLiveTranslatePair().target;
          // Commit the PREVIOUS pending pair if it forms a complete sentence and the
          // incoming delta is genuinely new content (not a continuation/short fragment).
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
          // NOW apply the merge
          liveTranslateSourceStreamRef.current = mergedSource;
          syncPendingLiveTranslatePair();
          scheduleLiveTranslateBoundary();
          setVoiceChatStatus(t("正在识别本句原文…", "Transcribing this sentence…"));
          return;
        }
        if (
          event.turn_id &&
          currentUserTurnRef.current.trim() &&
          (currentUserTurnRef.current.trim().endsWith(event.text.trim()) ||
            event.text.trim().endsWith(currentUserTurnRef.current.trim()))
        ) {
          currentTurnIdRef.current = event.turn_id;
          return;
        }
        if (
          currentUserTurnRef.current.trim() &&
          !isTranscriptContinuation(currentUserTurnRef.current, event.text)
        ) {
          if (
            voiceChatLiveTranslate &&
            shouldCoalesceLiveTranslateSegment(currentUserTurnRef.current, event.text)
          ) {
            currentUserTurnRef.current = appendStreamingText(currentUserTurnRef.current, event.text);
            setVoiceChatTranscript(currentUserTurnRef.current);
            setVoiceChatStatus(t("正在整理实时译文…", "Refining the live translation…"));
            return;
          }
          commitCompletedTurn();
        }
        setVoiceChatInterruptionState({ phase: "idle" });
        setVoiceChatAssistantInterrupted(false);
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
        }
        if (typeof event.first_audio_ms === "number") {
          setVoiceChatMetrics((previous) => ({ ...previous, firstAudioMs: event.first_audio_ms ?? null }));
        }
        void playAssistantAudio(event.audio, event.sample_rate);
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
        setVoiceChatStatus(t("已打断助手，继续说话中…", "Assistant interrupted, continue speaking…"));
        return;
      case "tool_call_started":
        appendCurrentToolRecord({
          status: "started",
          tool_name: event.tool_name,
          turn_id: event.turn_id,
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
          query: event.query,
          source_count: event.source_count,
          elapsed_ms: event.elapsed_ms,
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
      case "response_gated":
        appendCurrentToolRecord({
          status: "response_gated",
          provider: event.provider,
          tool_name: event.tool_name,
          turn_id: event.turn_id,
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
          query: event.query,
          answer: event.answer,
          source_count: event.source_count,
          elapsed_ms: event.elapsed_ms,
          artifact: event.artifact,
          sources: event.sources || [],
        });
        currentAssistantTurnRef.current = mergeAssistantText(
          currentAssistantTurnRef.current,
          event.answer
        );
        setVoiceChatReply(currentAssistantTurnRef.current);
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
        setVoiceChatStatus(t("搜索摘要已生成", "Search summary generated"));
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
              commitCompletedTurn();
            }
            resetLiveTranslateStreamTracking();
          } else {
            commitCompletedTurn();
          }
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

      const wsUrl = buildVoiceChatWebSocketUrl({
        provider: voiceChatProvider,
        model: voiceChatModel.trim() || undefined,
        voice: voiceChatVoice,
        targetLanguageCode: voiceChatLiveTranslate ? voiceChatTargetLanguageCode : undefined,
        echoTargetLanguage: voiceChatLiveTranslate ? voiceChatEchoTargetLanguage : undefined,
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
        const wasConnected = voiceChatConnected;
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
          if (voiceChatProvider === GOOGLE_PROVIDER && input.length > 0) {
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
    setVoiceChatMessages(Array.isArray(messages) ? messages : []);
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
    voiceChatVoice,
    voiceChatVoiceLabel,
    voiceChatVoiceOptions,
    voiceChatLiveTranslate,
    voiceChatTargetLanguageCode,
    voiceChatTargetLanguageLabel,
    voiceChatTargetLanguageOptions,
    voiceChatEchoTargetLanguage,
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
    onTargetLanguageCodeChange: setVoiceChatTargetLanguageCode,
    onEchoTargetLanguageChange: setVoiceChatEchoTargetLanguage,
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
  };
}

export type UseVoiceChatResult = ReturnType<typeof useVoiceChat>;
