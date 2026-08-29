/**
 * ASR engine metadata shared by the transcription modal and detail drawer.
 *
 * Grouping principle (the core of the redesigned picker): separate engines by
 * what they can actually produce, so the user knows exactly what they get —
 * "字级时间戳" engines can export precise SRT/VTT subtitles, "仅文本" engines
 * fall back to evenly-split (fake) timestamps.
 */

export type AsrEngineGroup = "auto" | "timestamps" | "text-only";

export type AsrEngine = {
  id: string;
  group: AsrEngineGroup;
  zh: string;
  en: string;
  /** One-line capability note shown under the picker when selected. */
  noteZh: string;
  noteEn: string;
};

export const ASR_ENGINES: AsrEngine[] = [
  {
    id: "auto",
    group: "auto",
    zh: "自动选择",
    en: "Auto",
    noteZh: "按你已配置的密钥依次尝试（Deepgram → Google → OpenAI → AssemblyAI → 豆包 → Qwen → MiMo），选第一个可用的。",
    noteEn: "Tries your configured keys in order (Deepgram → Google → OpenAI → AssemblyAI → Doubao → Qwen → MiMo) and uses the first available.",
  },
  {
    id: "google",
    group: "timestamps",
    zh: "Google Gemini 3.5 Transcribe",
    en: "Google Gemini 3.5 Transcribe",
    noteZh: "字级时间戳，可导出精确字幕；85+ 语种智能识别、去除语气词与说话人分离。",
    noteEn: "Word-level timestamps for precise subtitles; 85+ languages, smart formatting, and speaker diarization.",
  },
  {
    id: "dashscope",
    group: "timestamps",
    zh: "Qwen-Audio 3.0 ASR Flash（阿里云）",
    en: "Qwen-Audio 3.0 ASR Flash (Alibaba Cloud)",
    noteZh: "字级时间戳，可导出精确字幕；支持即时热词与多语种混合识别。中文场景首选。",
    noteEn: "Word-level timestamps for precise subtitles; instant hotwords and mixed-language. Best for Chinese.",
  },
  {
    id: "deepgram",
    group: "timestamps",
    zh: "Deepgram Nova-3",
    en: "Deepgram Nova-3",
    noteZh: "字级时间戳，可导出精确字幕；英文识别强。",
    noteEn: "Word-level timestamps for precise subtitles; strong English accuracy.",
  },
  {
    id: "openai",
    group: "timestamps",
    zh: "OpenAI Whisper",
    en: "OpenAI Whisper",
    noteZh: "字级时间戳，可导出精确字幕；多语种通用兜底。",
    noteEn: "Word-level timestamps for precise subtitles; solid multilingual fallback.",
  },
  {
    id: "assemblyai",
    group: "timestamps",
    zh: "AssemblyAI",
    en: "AssemblyAI",
    noteZh: "字级时间戳，可导出精确字幕；独有说话人分离与自动高亮，适合会议纪要。",
    noteEn: "Word-level timestamps plus speaker diarization and highlights — ideal for meeting notes.",
  },
  {
    id: "doubao",
    group: "timestamps",
    zh: "豆包 ASR 2.0（火山引擎）",
    en: "Doubao ASR 2.0 (Volcengine)",
    noteZh: "字级时间戳，可导出精确字幕；支持 25+ 语种识别、说话人分离与情绪检测。中英混合识别表现优异。",
    noteEn: "Word-level timestamps for precise subtitles; 25+ languages, speaker diarization and emotion detection. Excellent for Chinese-English mix.",
  },
  {
    id: "xiaomi",
    group: "text-only",
    zh: "小米 MiMo",
    en: "Xiaomi MiMo",
    noteZh: "仅输出文本，无字级时间戳；导出字幕会退化为按句均分的时间轴。",
    noteEn: "Text only, no word timestamps — exported subtitles fall back to evenly-split timing.",
  },
  {
    id: "qwen-legacy",
    group: "text-only",
    zh: "Qwen3 ASR Flash（旧版）",
    en: "Qwen3 ASR Flash (Legacy)",
    noteZh: "仅输出文本，无字级时间戳；导出字幕会退化为按句均分的时间轴。",
    noteEn: "Text only, no word timestamps — exported subtitles fall back to evenly-split timing.",
  },
];

/** Async ("链式") URL jobs are DashScope-only — the choice is which ASR model
 * the DashScope file-transcription task runs. */
export type AsyncAsrModel = {
  id: string;
  zh: string;
  en: string;
  noteZh: string;
  noteEn: string;
};

export const ASYNC_ASR_MODELS: AsyncAsrModel[] = [
  {
    id: "qwen-audio-filetrans",
    zh: "Qwen-Audio 3.0 ASR Flash Filetrans（新）",
    en: "Qwen-Audio 3.0 ASR Flash Filetrans (New)",
    noteZh: "新一代离线文件转写模型，含字级时间戳，识别更准。",
    noteEn: "New-generation offline file-transcription model with word timestamps.",
  },
  {
    id: "qwen-filetrans",
    zh: "Qwen3 ASR Flash Filetrans（默认）",
    en: "Qwen3 ASR Flash Filetrans (Default)",
    noteZh: "当前默认的离线文件转写模型，含字级时间戳。",
    noteEn: "Current default offline file-transcription model with word timestamps.",
  },
];

/** Realtime streaming ASR models selectable in the mic panel. */
export type RealtimeAsrModel = {
  id: string;
  zh: string;
  en: string;
  noteZh: string;
  noteEn: string;
};

export const REALTIME_ASR_MODELS: RealtimeAsrModel[] = [
  {
    id: "gemini-3.5-transcribe-live",
    zh: "Google Gemini 3.5 Transcribe Live（推荐）",
    en: "Google Gemini 3.5 Transcribe Live (Recommended)",
    noteZh: "Google 最新实时流式转写，低延迟高准确率，支持 85+ 语种智能识别与语气词过滤。",
    noteEn: "Google's latest low-latency streaming transcription with 85+ languages and smart formatting.",
  },
  {
    id: "qwen-audio-3.0-asr-flash-streaming",
    zh: "Qwen-Audio 3.0 ASR Streaming",
    en: "Qwen-Audio 3.0 ASR Streaming",
    noteZh: "阿里云实时流式识别，支持即时热词与最多 4 个语种提示。中文场景推荐。",
    noteEn: "Realtime streaming with instant hotwords and up to 4 language hints. Recommended for Chinese.",
  },
  {
    id: "fun-asr-realtime",
    zh: "Fun-ASR Realtime（经典）",
    en: "Fun-ASR Realtime (Classic)",
    noteZh: "经典实时模型，仅支持 1 个语种提示，无即时热词。",
    noteEn: "Classic realtime model — a single language hint, no instant hotwords.",
  },
];

const ENGINE_LABEL: Record<string, { zh: string; en: string }> = Object.fromEntries(
  ASR_ENGINES.map((e) => [e.id, { zh: e.zh, en: e.en }])
);
const ASYNC_LABEL: Record<string, { zh: string; en: string }> = Object.fromEntries(
  ASYNC_ASR_MODELS.map((e) => [e.id, { zh: e.zh, en: e.en }])
);
const REALTIME_LABEL: Record<string, { zh: string; en: string }> = Object.fromEntries(
  REALTIME_ASR_MODELS.map((e) => [e.id, { zh: e.zh, en: e.en }])
);

/** Human-readable label for an engine/provider id echoed back by the backend.
 * Falls back to the raw id when unknown. */
export function asrProviderLabel(provider: string | null | undefined, language: string): string {
  if (!provider) return "";
  const map = { ...ENGINE_LABEL, ...ASYNC_LABEL, ...REALTIME_LABEL };
  const hit = map[provider];
  if (!hit) return provider;
  return language === "en-US" ? hit.en : hit.zh;
}

export const ASR_ENGINE_PROVIDER_MAP: Record<string, { providerName: string; keyField: string; labelZh: string; labelEn: string }> = {
  google: { providerName: "Google", keyField: "google_api_key", labelZh: "Google Gemini", labelEn: "Google Gemini" },
  dashscope: { providerName: "DashScope", keyField: "dashscope_api_key", labelZh: "阿里云 DashScope", labelEn: "Alibaba DashScope" },
  deepgram: { providerName: "Deepgram", keyField: "deepgram_api_key", labelZh: "Deepgram", labelEn: "Deepgram" },
  openai: { providerName: "OpenAI", keyField: "openai_api_key", labelZh: "OpenAI", labelEn: "OpenAI" },
  assemblyai: { providerName: "AssemblyAI", keyField: "assemblyai_api_key", labelZh: "AssemblyAI", labelEn: "AssemblyAI" },
  doubao: { providerName: "Doubao", keyField: "doubao_api_key", labelZh: "豆包 (火山引擎)", labelEn: "Doubao (Volcengine)" },
  xiaomi: { providerName: "Xiaomi", keyField: "xiaomi_api_key", labelZh: "小米 mimo", labelEn: "Xiaomi mimo" },
  "qwen-legacy": { providerName: "DashScope", keyField: "dashscope_api_key", labelZh: "阿里云 DashScope", labelEn: "Alibaba DashScope" },
  "qwen-audio-filetrans": { providerName: "DashScope", keyField: "dashscope_api_key", labelZh: "阿里云 DashScope", labelEn: "Alibaba DashScope" },
  "qwen-filetrans": { providerName: "DashScope", keyField: "dashscope_api_key", labelZh: "阿里云 DashScope", labelEn: "Alibaba DashScope" },
  "gemini-3.5-transcribe-live": { providerName: "Google", keyField: "google_api_key", labelZh: "Google Gemini", labelEn: "Google Gemini" },
  "qwen-audio-3.0-asr-flash-streaming": { providerName: "DashScope", keyField: "dashscope_api_key", labelZh: "阿里云 DashScope", labelEn: "Alibaba DashScope" },
  "fun-asr-realtime": { providerName: "DashScope", keyField: "dashscope_api_key", labelZh: "阿里云 DashScope", labelEn: "Alibaba DashScope" },
};

export function isAsrEngineConfigured(engineId: string, settingsObj?: Record<string, any> | null): boolean {
  if (!settingsObj || engineId === "auto") return true;
  const target = ASR_ENGINE_PROVIDER_MAP[engineId];
  if (!target) return true;
  const val = settingsObj[target.keyField];
  return typeof val === "string" ? val.trim().length > 0 : Boolean(val);
}
