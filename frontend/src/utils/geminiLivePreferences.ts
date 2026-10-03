export const GEMINI_LIVE_ACCENTS = [
  { value: "", zh: "自然口音", en: "Natural accent" },
  { value: "en-US", zh: "美式英语", en: "American English" },
  { value: "en-GB", zh: "英式英语", en: "British English" },
  { value: "en-AU", zh: "澳大利亚英语", en: "Australian English" },
  { value: "en-IN", zh: "印度英语", en: "Indian English" },
  { value: "zh-CN", zh: "普通话", en: "Mainland Mandarin" },
  { value: "zh-TW", zh: "台湾国语", en: "Taiwanese Mandarin" },
  { value: "ja-JP", zh: "标准日语", en: "Standard Japanese" },
  { value: "fr-FR", zh: "法国法语", en: "French" },
] as const;

export function supportsGeminiAccent(provider: string, model: string): boolean {
  return ["google", "agentplatform", "vertexai"].includes(provider.toLowerCase()) &&
    model.split("/").pop()?.startsWith("gemini-3.8-live") === true && !model.endsWith("-avatar");
}

export function formatAvatarCallLabel(avatarName: string, voiceLabel: string, t: (zh: string, en: string) => string): string {
  return `Gemini 3.8 Live · Avatar · ${avatarName.trim() || t("选择形象", "Choose avatar")} · ${voiceLabel}`;
}
