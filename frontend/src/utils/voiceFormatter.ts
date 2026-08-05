import type { VoiceInfo } from "../api";

// Map of common locales to human readable names in Chinese and English
const LOCALE_DISPLAY_MAP: Record<string, { zh: string; en: string }> = {
  "zh-cn": { zh: "中文 (中国大陆)", en: "Chinese (Mainland)" },
  "zh-hk": { zh: "中文 (中国香港)", en: "Chinese (Hong Kong)" },
  "zh-tw": { zh: "中文 (中国台湾)", en: "Chinese (Taiwan)" },
  "en-us": { zh: "英语 (美国)", en: "English (US)" },
  "en-gb": { zh: "英语 (英国)", en: "English (UK)" },
  "ja-jp": { zh: "日语 (日本)", en: "Japanese (Japan)" },
  "ko-kr": { zh: "韩语 (韩国)", en: "Korean (South Korea)" },
  "fr-fr": { zh: "法语 (法国)", en: "French (France)" },
  "de-de": { zh: "德语 (德国)", en: "German (Germany)" },
  "ru-ru": { zh: "俄语 (俄罗斯)", en: "Russian (Russia)" },
  "es-es": { zh: "西班牙语 (西班牙)", en: "Spanish (Spain)" },
  "it-it": { zh: "意大利语 (意大利)", en: "Italian (Italy)" },
  "pt-br": { zh: "葡萄牙语 (巴西)", en: "Portuguese (Brazil)" },
};

/**
 * Formats a voice item into a clean and intuitive label.
 * E.g., "Xiaoxiao (女) - 中文 (中国大陆)" or "Jenny (Female) - English (US)"
 */
export function formatVoiceLabel(
  item: VoiceInfo,
  t: (zh: string, en: string) => string
): string {
  let name = item.short_name || item.name || "";

  // If it's Edge style (e.g. "zh-CN-XiaoxiaoNeural")
  if (name.includes("-")) {
    const parts = name.split("-");
    const lastPart = parts[parts.length - 1];
    if (lastPart) {
      name = lastPart;
    }
  }

  // Remove "Neural" suffix if present
  if (name.endsWith("Neural")) {
    name = name.slice(0, -6);
  }

  // Drop parenthesized ids/pinyin to keep labels short,
  // e.g. "龙安风悦 (longanfengyue)" → "龙安风悦"
  const stripped = name.replace(/\s*\([^)]*\)/g, "").trim();
  if (stripped) {
    name = stripped;
  }

  // Format gender
  let genderStr = "";
  const genderLower = (item.gender || "").toLowerCase();
  if (genderLower === "female") {
    genderStr = t("女", "Female");
  } else if (genderLower === "male") {
    genderStr = t("男", "Male");
  } else if (genderLower === "custom") {
    genderStr = t("自定义", "Custom");
  } else if (genderLower === "neutral") {
    genderStr = t("中性", "Neutral");
  }

  // Format locale
  const localeLower = (item.locale || "").toLowerCase();
  let localeStr = item.locale || "";
  if (localeLower in LOCALE_DISPLAY_MAP) {
    localeStr = t(LOCALE_DISPLAY_MAP[localeLower].zh, LOCALE_DISPLAY_MAP[localeLower].en);
  }

  const genderPart = genderStr ? ` (${genderStr})` : "";
  const localePart = localeStr ? ` - ${localeStr}` : "";
  return `${name}${genderPart}${localePart}`;
}
