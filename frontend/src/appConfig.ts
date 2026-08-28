export type ActiveTab =
  | "chat"
  | "translate"
  | "tts"
  | "voice_design"
  | "voice_clone"
  | "transcription"
  | "voice_center"
  | "audio_overview"
  | "pal"
  | "settings";

export type SidebarItem = {
  tab: ActiveTab;
  label: string;
  icon: string;
  tooltip: string;
};


export type HistoryItem = {
  id: string;
  content: string;
};

type TranslatePair = (zh: string, en: string) => string;

export const PROVIDERS = [
  "Google",
  "DashScope",
  "Doubao",
  "Cartesia",
  "DeepSeek",
  "OpenRouter",
  "SiliconFlow",
  "Groq",
  "Ollama",
  "PersonaPlex",
  "GLM4Voice",
  "Tavus"
];

export function getDefaultText(t: TranslatePair): string {
  return t(
    "你好，这是 Echo 的语音测试。",
    "Hello, this is an Echo speech test."
  );
}

export function getSidebarItems(t: TranslatePair): SidebarItem[] {
  return [
    { tab: "chat", label: t("聊天", "Chat"), icon: "Bot", tooltip: t("AI 助理聊天", "AI assistant chat") },
    { tab: "voice_center", label: t("语音中心", "Voice Center"), icon: "Mic2", tooltip: t("统一语音工作台", "Voice workspace") },
    { tab: "audio_overview", label: t("播客", "Podcast"), icon: "FileAudio", tooltip: t("播客与多人对白", "Podcast & mixed dialogue") },
    { tab: "pal", label: t("视频分身", "Video PAL"), icon: "Video", tooltip: t("与 AI 分身实时视频对话", "Realtime video conversation with an AI PAL") },
    { tab: "translate", label: t("翻译", "Translate"), icon: "Languages", tooltip: t("智能翻译", "Translation") }
  ];
}


