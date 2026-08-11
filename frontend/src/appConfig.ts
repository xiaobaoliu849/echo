export type ActiveTab =
  | "chat"
  | "translate"
  | "tts"
  | "voice_design"
  | "voice_clone"
  | "transcription"
  | "voice_center"
  | "audio_overview"
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
  "DeepSeek",
  "OpenRouter",
  "SiliconFlow",
  "Groq",
  "Ollama",
  "PersonaPlex",
  "GLM4Voice",
  "SesameCSM"
];

export function getDefaultText(t: TranslatePair): string {
  return t(
    "你好，这是 VoiceSpirit Web 迁移阶段的语音测试。",
    "Hello, this is a VoiceSpirit speech test for the web migration build."
  );
}

export function getSidebarItems(t: TranslatePair): SidebarItem[] {
  return [
    { tab: "chat", label: t("聊天", "Chat"), icon: "Bot", tooltip: t("AI 助理聊天", "AI assistant chat") },
    { tab: "voice_center", label: t("语音中心", "Voice Center"), icon: "Mic2", tooltip: t("统一语音工作台", "Voice workspace") },
    { tab: "audio_overview", label: t("播客", "Podcast"), icon: "FileAudio", tooltip: t("播客与多人对白", "Podcast & mixed dialogue") },
    { tab: "translate", label: t("翻译", "Translate"), icon: "Languages", tooltip: t("智能翻译", "Translation") }
  ];
}


