import type { UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";

export type ProviderModelCatalog = Record<
  string,
  {
    defaultModel: string;
    availableModels: string[];
    enabledModels?: string[];
    ttsDefaultModel?: string;
    ttsAvailableModels?: string[];
    ttsEnabledModels?: string[];
  }
>;

export type Options = {
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

export const EMPTY_VOICE_CHAT_METRICS: VoiceChatMetrics = {
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

export const GOOGLE_PROVIDER = "Google";
export const DASHSCOPE_PROVIDER = "DashScope";
export const OPENAI_PROVIDER = "OpenAI";
export const DOUBAO_PROVIDER = "Doubao";
export const GOOGLE_FLASH_LIVE_MODEL = "gemini-3.1-flash-live-preview";
export const GOOGLE_LIVE_TRANSLATE_MODEL = "gemini-3.5-live-translate-preview";
// The legacy gemini-2.5-flash-native-audio-preview-12-2025 model has been retired;
// the current Flash Live model is the default Google realtime voice model.
export const DEFAULT_GOOGLE_MODEL = GOOGLE_FLASH_LIVE_MODEL;
export const DEFAULT_DASHSCOPE_MODEL = "qwen3.5-omni-plus-realtime";
export const DEFAULT_OPENAI_MODEL = "gpt-realtime-2";
export const DEFAULT_DOUBAO_MODEL = "doubao-realtime";
export const SUPPORTED_GOOGLE_REALTIME_MODEL_PATTERNS = [
  "native-audio",
  "live",
  "realtime",
];

export const GOOGLE_REALTIME_VOICES = [
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

export type TranslationMode = "bidirectional" | "unidirectional";

export const LIVE_TRANSLATE_LANGUAGE_PRIORITY = [
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

export const LIVE_TRANSLATE_TARGET_LANGUAGES = [
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

export function getLanguageShortLabel(code: string, fallback: string = ""): string {
  const item = LIVE_TRANSLATE_TARGET_LANGUAGES.find((lang) => lang.value === code);
  if (item) {
    if (code === "zh-Hans") return "中文";
    if (code === "zh-Hant") return "繁体";
    if (code === "en") return "English";
    if (code === "ja") return "日本語";
    if (code === "ko") return "한국어";
    if (code === "fr") return "Français";
    if (code === "de") return "Deutsch";
    if (code === "es") return "Español";
    return item.label;
  }
  return fallback || code;
}

export function formatTranslationSummary(
  mode: TranslationMode,
  sourceCode: string,
  targetCode: string
): string {
  const tgt = getLanguageShortLabel(targetCode);
  if (mode === "bidirectional") {
    const src = getLanguageShortLabel(sourceCode);
    return `双向互翻 (${src} ⇄ ${tgt})`;
  }
  // Unidirectional live-translate auto-detects the source language, so the
  // summary shows only the target (e.g. "单向翻译 (→ English)"). Rendering a
  // source→target pair would imply a fixed direction the user never chose.
  return `单向翻译 (→ ${tgt})`;
}

/**
 * The secondary label shown next to the model name (settings pill + live-call badge).
 * Voice Clone takes precedence; live-translate models show the target language
 * instead of a (meaningless) TTS voice label.
 * Both DashScope and Google live-translate are unidirectional (single
 * target_language, source auto-detected), so the label is always rendered as
 * 单向翻译 (→ target) and never a source→target pair.
 */
export function formatVoiceChatSecondaryLabel(params: {
  liveTranslate: boolean;
  voiceCloneEnabled: boolean;
  translationMode: TranslationMode;
  sourceLanguageCode: string;
  targetLanguageCode: string;
  voiceLabel: string;
  provider?: string;
  model?: string;
  t: (zh: string, en: string) => string;
}): string {
  const {
    liveTranslate,
    voiceCloneEnabled,
    translationMode,
    sourceLanguageCode,
    targetLanguageCode,
    voiceLabel,
    provider = "",
    model = "",
    t,
  } = params;
  if (liveTranslate) {
    if (voiceCloneEnabled) {
      return t("声音复刻 (本人)", "Voice Clone");
    }
    const effectiveMode: TranslationMode = isLiveTranslateModel(provider, model)
      ? "unidirectional"
      : translationMode;
    return formatTranslationSummary(effectiveMode, sourceLanguageCode, targetLanguageCode);
  }
  return voiceCloneEnabled
    ? t("声音复刻 (本人音色)", "Voice Clone (Your Voice)")
    : voiceLabel;
}

export const OPENAI_REALTIME_VOICES = [
  { value: "alloy", label: "Alloy (Neutral)" },
  { value: "ash", label: "Ash (Male)" },
  { value: "ballad", label: "Ballad (Male)" },
  { value: "coral", label: "Coral (Female)" },
  { value: "echo", label: "Echo (Male)" },
  { value: "sage", label: "Sage (Male)" },
  { value: "shimmer", label: "Shimmer (Female)" },
  { value: "verse", label: "Verse (Male)" },
];

// Voices for the Doubao OpenSpeech end-to-end realtime dialogue API
// (volc.speech.dialog, O2.0 model 1.2.1.1), per the official RealtimeAPI docs
// (docs/豆包时时语音.txt).
export const DOUBAO_REALTIME_VOICES = [
  { value: "zh_female_vv_jupiter_bigtts", label: "vv · 活泼灵动 (Female)", description: "活泼灵动的女声，有很强的分享欲" },
  { value: "zh_female_xiaohe_jupiter_bigtts", label: "xiaohe · 甜美台腔 (Female)", description: "甜美活泼的女声，有明显的台湾口音" },
  { value: "zh_male_yunzhou_jupiter_bigtts", label: "yunzhou · 清爽沉稳 (Male)", description: "清爽沉稳的男声" },
  { value: "zh_male_xiaotian_jupiter_bigtts", label: "xiaotian · 清爽磁性 (Male)", description: "清爽磁性的男声" },
  { value: "en_male_tim_uranus_bigtts", label: "Tim · American English (Male)", description: "美式英语男声（仅 O2.0）" },
  { value: "en_female_dacey_uranus_bigtts", label: "Dacey · American English (Female)", description: "美式英语女声（仅 O2.0）" },
  { value: "en_female_stokie_uranus_bigtts", label: "Stokie · American English (Female)", description: "美式英语女声（仅 O2.0）" },
];

// Voices for qwen3.5-omni-*-realtime models (default: Tina), per the official
// omni voice list (docs/全模态.txt). The older Cherry-era voices belong to
// qwen3-omni / qwen-omni-turbo and are rejected by qwen3.5-omni models.
export const QWEN_OMNI_REALTIME_VOICES = [
  { value: "Tina", label: "Tina · 甜甜 (Female)", description: "像温热的奶茶，甜甜的暖暖的" },
  { value: "Ethan", label: "Ethan · 晨煦 (Male)", description: "标准普通话，阳光温暖有活力" },
  { value: "Serena", label: "Serena · 苏瑶 (Female)", description: "温柔小姐姐" },
  { value: "Maia", label: "Maia · 四月 (Female)", description: "知性与温柔的碰撞" },
  { value: "Momo", label: "Momo · 茉兔 (Female)", description: "撒娇搞怪，逗你开心" },
  { value: "Ryan", label: "Ryan · 甜茶 (Male)", description: "节奏拉满，戏感炸裂" },
  { value: "Jennifer", label: "Jennifer · 詹妮弗 (Female)", description: "品牌级电影质感美语女声" },
  { value: "Katerina", label: "Katerina · 卡捷琳娜 (Female)", description: "御姐音色，韵律回味十足" },
  { value: "Aiden", label: "Aiden · 艾登 (Male)", description: "精通厨艺的美语大男孩" },
  { value: "Dylan", label: "Dylan · 北京-晓东 (Male)", description: "北京胡同里长大的少年" },
  { value: "Sunny", label: "Sunny · 四川-晴儿 (Female)", description: "甜到你心里的川妹子" },
  { value: "Peter", label: "Peter · 天津-李彼得 (Male)", description: "天津相声，专业捧哏" },
];

export const QWEN_AUDIO_VOICES = [
  { value: "longanqian", label: "longanqian · 龙千倩 (Female)", description: "qwen-audio 女声" },
  { value: "longanlingxin", label: "longanlingxin · 龙灵馨 (Female)", description: "qwen-audio 女声" },
  { value: "longanlingxi", label: "longanlingxi · 龙灵犀 (Female)", description: "qwen-audio 女声" },
  { value: "longanxiaoxin", label: "longanxiaoxin · 龙小新 (Female)", description: "qwen-audio 女声" },
  { value: "longanlufeng", label: "longanlufeng · 龙陆风 (Male)", description: "qwen-audio 男声" },
];

// Voices for qwen3.5-livetranslate-*-realtime (default: Tina), per the official
// LiveTranslate voice list (音色列表.txt). A small convenient subset — all are
// valid for the translation model. NOTE: the dialect voices offered for omni
// (Dylan/Sunny/Peter/...) are NOT supported by livetranslate and are deliberately
// excluded so picking one can never silently break the session.
export const QWEN_LIVETRANSLATE_VOICES = [
  { value: "Tina", label: "Tina · 甜甜 (Female)", description: "像温热的奶茶，甜甜的暖暖的" },
  { value: "Cindy", label: "Cindy · 林欣宜 (Female)", description: "台湾说话嗲嗲的小姐姐" },
  { value: "Liora Mira", label: "Liora Mira · 清欢 (Female)", description: "用声音织就烟火人间的温柔" },
  { value: "Sunnybobi", label: "Sunnybobi · 知芝 (Female)", description: "大大咧咧的社恐邻家姑娘" },
  { value: "Raymond", label: "Raymond · 林川野 (Male)", description: "声音清亮，爱吃外卖的宅男" },
  { value: "Ethan", label: "Ethan · 晨煦 (Male)", description: "标准普通话，阳光温暖有活力" },
  { value: "Theo Calm", label: "Theo Calm · 予安 (Male)", description: "在静默处传递理解，在言语间疗愈人心" },
  { value: "Serena", label: "Serena · 苏瑶 (Female)", description: "温柔小姐姐" },
  { value: "Harvey", label: "Harvey · 厚 (Male)", description: "低沉温和，带有咖啡与旧书的气息" },
  { value: "Maia", label: "Maia · 四月 (Female)", description: "知性与温柔的碰撞" },
  { value: "Evan", label: "Evan · 江晨 (Male)", description: "男大学生，年下奶狗" },
  { value: "Qiao", label: "Qiao · 小乔妹 (Female)", description: "表面甜妹，个性十足" },
  { value: "Momo", label: "Momo · 茉兔 (Female)", description: "撒娇搞怪，逗你开心" },
  { value: "Wil", label: "Wil · 伟伦 (Male)", description: "在深圳长大的港台腔小哥哥" },
  { value: "Angel", label: "Angel · 安琪 (Female)", description: "略带台式口音，超甜女声" },
  { value: "Li Cassian", label: "Li Cassian · 李公公 (Male)", description: "话中三分留白、七分察言观色" },
  { value: "Mia", label: "Mia · 舒然 (Female)", description: "传递慢生活美学与日常治愈力量" },
  { value: "Joyner", label: "Joyner · 阿逗 (Male)", description: "搞笑、夸张、接地气" },
  { value: "Gold", label: "Gold · 金爷 (Male)", description: "西海岸黑人 Rapper" },
  { value: "Katerina", label: "Katerina · 卡捷琳娜 (Female)", description: "御姐音色，韵律回味十足" },
  { value: "Ryan", label: "Ryan · 甜茶 (Male)", description: "节奏拉满，戏感炸裂" },
  { value: "Jennifer", label: "Jennifer · 詹妮弗 (Female)", description: "品牌级电影质感美语女声" },
  { value: "Aiden", label: "Aiden · 艾登 (Male)", description: "精通厨艺的美语大男孩" },
  { value: "Mione", label: "Mione · 敏儿 (Female)", description: "成熟知性英国邻家妹妹" },
  { value: "Sohee", label: "Sohee · 素熙 (Female)", description: "温柔开朗情绪丰富的韩国欧尼" },
  { value: "Lenn", label: "Lenn · 莱恩 (Male)", description: "理性是底色，穿西装听后朋克的德国青年" },
  { value: "Ono Anna", label: "Ono Anna · 小野杏 (Female)", description: "鬼灵精怪的青梅竹马" },
  { value: "Sonrisa", label: "Sonrisa · 索尼莎 (Female)", description: "热情开朗的拉美大姐" },
  { value: "Bodega", label: "Bodega · 博德加 (Male)", description: "热情的西班牙大叔" },
  { value: "Emilien", label: "Emilien · 埃米尔安 (Male)", description: "浪漫的法国大哥哥" },
  { value: "Andre", label: "Andre · 安德雷 (Male)", description: "磁性自然舒服沉稳男生" },
];

export function isQwenAudioModel(model: string | undefined): boolean {
  return !!(model && model.toLowerCase().includes("qwen-audio"));
}

export function formatVoiceOptionLabel(label: string, language: UiLanguage): string {
  if (language === "en-US") {
    return label;
  }
  return label
    .replace(" (Female)", " · 女声")
    .replace(" (Male)", " · 男声");
}

export function formatRealtimeVoiceOptions(
  provider: string,
  language: UiLanguage,
  model?: string,
): Array<{ value: string; label: string; description?: string }> {
  let options: Array<{ value: string; label: string; description?: string }>;
  if (provider === DOUBAO_PROVIDER) {
    options = DOUBAO_REALTIME_VOICES;
  } else if (provider === DASHSCOPE_PROVIDER) {
    if (isQwenAudioModel(model)) {
      options = QWEN_AUDIO_VOICES;
    } else if (isLiveTranslateModel(provider, model ?? "")) {
      options = QWEN_LIVETRANSLATE_VOICES;
    } else {
      options = QWEN_OMNI_REALTIME_VOICES;
    }
  } else if (provider === OPENAI_PROVIDER) {
    options = OPENAI_REALTIME_VOICES;
  } else {
    options = GOOGLE_REALTIME_VOICES;
  }
  return options.map((item) => ({
    value: item.value,
    label: formatVoiceOptionLabel(item.label, language),
    // Voice descriptions are display-only metadata for richer pickers; they
    // must never be appended to the label itself.
    ...(item.description ? { description: item.description } : {}),
  }));
}

export function getDisplayLanguageName(code: string, fallback: string, language: UiLanguage): string {
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

export function formatLiveTranslateLanguageOptions(language: UiLanguage): Array<{ value: string; label: string }> {
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

export function resolveRealtimeProvider(preferredProvider: string | undefined, providerOptions: string[]): string {
  const realtimeProviders = [GOOGLE_PROVIDER, DASHSCOPE_PROVIDER, OPENAI_PROVIDER, DOUBAO_PROVIDER];
  if (preferredProvider && realtimeProviders.includes(preferredProvider) && providerOptions.includes(preferredProvider)) {
    return preferredProvider;
  }
  if (providerOptions.includes(DOUBAO_PROVIDER)) {
    return DOUBAO_PROVIDER;
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

export function resolveDefaultModel(provider: string, providerModelCatalog: ProviderModelCatalog): string {
  return resolveRealtimeModelOptions(provider, providerModelCatalog)[0] || "";
}

export function isRealtimeVoiceModel(provider: string, model: string): boolean {
  const normalizedProvider = (provider || "").trim().toLowerCase();
  const normalizedModel = (model || "").trim().toLowerCase();
  if (!normalizedModel) {
    return false;
  }
  if (normalizedProvider === DOUBAO_PROVIDER.toLowerCase()) {
    return true;
  }
  if (normalizedProvider === DASHSCOPE_PROVIDER.toLowerCase()) {
    return /^qwen3\.5-omni-(plus|flash)-realtime(?:-\d{4}-\d{2}-\d{2})?$/.test(normalizedModel) ||
           /^qwen-audio-3\.0-realtime-(plus|flash)$/.test(normalizedModel) ||
           /^qwen3\.5-livetranslate-(flash|plus)-realtime(?:-\d{4}-\d{2}-\d{2})?$/.test(normalizedModel);
  }
  if (normalizedProvider === GOOGLE_PROVIDER.toLowerCase()) {
    return SUPPORTED_GOOGLE_REALTIME_MODEL_PATTERNS.some((item) => normalizedModel.includes(item));
  }
  if (normalizedProvider === OPENAI_PROVIDER.toLowerCase()) {
    return normalizedModel.includes("realtime") || normalizedModel.includes("gpt-realtime");
  }
  return normalizedModel.includes("realtime");
}

export function isLiveTranslateModel(provider: string, model: string): boolean {
  const normalizedProvider = provider.trim().toLowerCase();
  const normalizedModel = model.trim().toLowerCase();
  if (normalizedProvider === GOOGLE_PROVIDER.toLowerCase()) {
    return normalizedModel.includes("live-translate");
  }
  if (normalizedProvider === DASHSCOPE_PROVIDER.toLowerCase()) {
    // qwen3.5-livetranslate-flash-realtime only — the legacy qwen3-livetranslate
    // series is removed (superseded by 3.5, which also covers more languages).
    // (mirror the backend _is_dashscope_live_translate_model regex exactly)
    return /^qwen3\.5-livetranslate-(flash|plus)-realtime(?:-\d{4}-\d{2}-\d{2})?$/.test(
      normalizedModel
    );
  }
  return false;
}

export function resolveRealtimeFallbackModel(provider: string): string {
  if (provider === DASHSCOPE_PROVIDER) {
    return DEFAULT_DASHSCOPE_MODEL;
  }
  if (provider === GOOGLE_PROVIDER) {
    return DEFAULT_GOOGLE_MODEL;
  }
  if (provider === OPENAI_PROVIDER) {
    return DEFAULT_OPENAI_MODEL;
  }
  if (provider === DOUBAO_PROVIDER) {
    return DEFAULT_DOUBAO_MODEL;
  }
  return "";
}

export function resolveRealtimeModelOptions(
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
    ? [GOOGLE_FLASH_LIVE_MODEL, GOOGLE_LIVE_TRANSLATE_MODEL]
    : [];
  const openaiBuiltIns = provider === OPENAI_PROVIDER
    ? [DEFAULT_OPENAI_MODEL]
    : [];
  const dashscopeBuiltIns = provider === DASHSCOPE_PROVIDER
    ? [
        DEFAULT_DASHSCOPE_MODEL,
        "qwen3.5-livetranslate-flash-realtime",
        "qwen-audio-3.0-realtime-plus",
        "qwen-audio-3.0-realtime-flash",
      ]
    : [];
  const doubaoBuiltIns = provider === DOUBAO_PROVIDER
    ? [DEFAULT_DOUBAO_MODEL]
    : [];
  const allBuiltIns = [...googleBuiltIns, ...openaiBuiltIns, ...dashscopeBuiltIns, ...doubaoBuiltIns];
  const ordered = fallbackModel ? [fallbackModel, ...allBuiltIns, ...realtimeModels] : [...allBuiltIns, ...realtimeModels];
  return [...new Set(ordered.filter(Boolean))];
}

export function getAudioContextCtor(): typeof AudioContext | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  const audioWindow = window as AudioContextWindow;
  return window.AudioContext || audioWindow.webkitAudioContext;
}

export function encodePcm16k(input: Float32Array, inputRate: number): ArrayBuffer {
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

export function decodeBase64Pcm(base64Audio: string): Int16Array {
  const binary = atob(base64Audio);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer);
}

function stripTrailingPunctuation(text: string): string {
  return text.trim().replace(/[.!?。！？,，:：;\s]+$/, "");
}

export function mergeAssistantText(previous: string, incoming: string): string {
  const next = incoming.trim();
  if (!next) {
    return previous;
  }
  if (!previous) {
    return next;
  }
  const cleanPrev = stripTrailingPunctuation(previous);
  const cleanNext = stripTrailingPunctuation(next);
  if (!cleanNext) {
    return previous;
  }
  if (!cleanPrev) {
    return next;
  }
  if (cleanNext === cleanPrev || cleanPrev.endsWith(cleanNext)) {
    return previous;
  }
  // Safety-net: if the incoming text is already a substring of the
  // accumulated text, it adds nothing new — return unmodified.
  if (cleanPrev.includes(cleanNext)) {
    return previous;
  }
  if (cleanNext.startsWith(cleanPrev)) {
    return next;
  }

  // Find longest overlap between suffix of cleanPrev and prefix of cleanNext
  let maxOverlap = 0;
  const maxSearchLen = Math.min(cleanPrev.length, cleanNext.length);
  for (let len = maxSearchLen; len >= 1; len--) {
    if (cleanPrev.endsWith(cleanNext.slice(0, len))) {
      maxOverlap = len;
      break;
    }
  }

  if (maxOverlap > 0) {
    const novel = next.slice(maxOverlap);
    return appendStreamingText(previous, novel);
  }

  return appendStreamingText(previous, next);
}

export function containsLatinText(value: string): boolean {
  return /[A-Za-z]/.test(value);
}

/** Return true when CJK ideographs / kana / hangul occupy >30 % of *s*.
 *  Used by {@link appendStreamingText} to avoid inserting word-boundary
 *  spaces inside sentences whose primary script is Chinese / Japanese /
 *  Korean. */
export function isCJKPredominant(value: string): boolean {
  if (!value) {
    return false;
  }
  let cjk = 0;
  for (const c of value) {
    const cp = c.codePointAt(0)!;
    if (
      (cp >= 0x4e00 && cp <= 0x9fff) || // CJK Unified Ideographs
      (cp >= 0x3400 && cp <= 0x4dbf) || // CJK Extension A
      (cp >= 0xf900 && cp <= 0xfaff) || // CJK Compatibility Ideographs
      (cp >= 0x3040 && cp <= 0x309f) || // Hiragana
      (cp >= 0x30a0 && cp <= 0x30ff) || // Katakana
      (cp >= 0xac00 && cp <= 0xd7af) || // Hangul Syllables
      (cp >= 0x1100 && cp <= 0x11ff)    // Hangul Jamo
    ) {
      cjk += 1;
    }
  }
  return cjk > value.length * 0.3;
}

export function appendStreamingText(previous: string, incoming: string): string {
  const before = previous.trim();
  const next = incoming.trim();
  if (!before) {
    return next;
  }
  if (!next) {
    return before;
  }
  // Only insert a word-boundary space when the surrounding text is
  // primarily Latin-script.  For CJK-heavy sentences an embedded Latin
  // token (e.g. "Dota") is a proper noun, not a separate English word.
  if (
    (containsLatinText(before) || containsLatinText(next)) &&
    !isCJKPredominant(before) &&
    !isCJKPredominant(next)
  ) {
    return `${before} ${next}`.replace(/\s+([,.!?;:])/g, "$1");
  }
  return `${before}${next}`;
}

export function endsWithSentencePunctuation(value: string): boolean {
  return /[.!?。！？]\s*$/.test(value.trim());
}

export function countLatinWords(value: string): number {
  return (value.match(/[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?/g) || []).length;
}

export function shouldCoalesceLiveTranslateSegment(previousSource: string, nextSource: string): boolean {
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

export function isTranscriptContinuation(previous: string, incoming: string): boolean {
  const before = previous.trim();
  const next = incoming.trim();
  if (!before || !next) {
    return true;
  }
  return next.startsWith(before) || before.startsWith(next);
}

export function formatElapsedMs(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return "";
  }
  if (value < 1000) {
    return `${Math.round(value)}ms`;
  }
  return `${(value / 1000).toFixed(1)}s`;
}

export function buildToolMeta(params: {
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

export function normalizeVoiceCaptureError(
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

