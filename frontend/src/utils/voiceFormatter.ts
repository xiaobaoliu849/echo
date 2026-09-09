import type { VoiceInfo } from "../api";

// Map of common locales to human readable names in Chinese and English
const LOCALE_DISPLAY_MAP: Record<string, { zh: string; en: string }> = {
  "zh-cn": { zh: "中文 (大陆)", en: "Chinese (Mainland)" },
  "zh-hk": { zh: "中文 (香港)", en: "Chinese (HK)" },
  "zh-tw": { zh: "中文 (台湾)", en: "Chinese (TW)" },
  "en-us": { zh: "英语 (美国)", en: "English (US)" },
  "en-gb": { zh: "英语 (英国)", en: "English (UK)" },
  "ja-jp": { zh: "日语", en: "Japanese" },
  "ko-kr": { zh: "韩语", en: "Korean" },
  "fr-fr": { zh: "法语", en: "French" },
  "de-de": { zh: "德语", en: "German" },
  "ru-ru": { zh: "俄语", en: "Russian" },
  "es-es": { zh: "西班牙语", en: "Spanish" },
  "it-it": { zh: "意大利语", en: "Italian" },
  "pt-br": { zh: "葡萄牙语 (巴西)", en: "Portuguese (BR)" },
};

/**
 * Resolve a locale string to its display entry, tolerating dialect sub-tags.
 * e.g. "zh-CN-liaoning" → looks up "zh-CN" first, then "zh"
 */
function resolveLocaleDisplay(
  locale: string
): { zh: string; en: string } | undefined {
  const lower = locale.toLowerCase();
  if (lower in LOCALE_DISPLAY_MAP) return LOCALE_DISPLAY_MAP[lower];
  // Strip dialect/region sub-tag: "zh-CN-liaoning" → "zh-CN"
  const base = lower.split("-").slice(0, 2).join("-");
  if (base in LOCALE_DISPLAY_MAP) return LOCALE_DISPLAY_MAP[base];
  return undefined;
}

/**
 * Formats a voice item into a clean and intuitive label.
 *
 * Full mode (default): "Xiaoxiao (女) - 中文 (大陆)"
 * Compact mode:        "Xiaoxiao (女)"  — omits locale, for tight UI spaces
 */
export function formatVoiceLabel(
  item: VoiceInfo,
  t: (zh: string, en: string) => string,
  options?: { compact?: boolean }
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

  const genderPart = genderStr ? ` (${genderStr})` : "";

  // Compact mode: skip locale entirely
  if (options?.compact) {
    return `${name}${genderPart}`;
  }

  // Full mode: resolve locale with dialect-tolerant lookup
  const localeEntry = resolveLocaleDisplay(item.locale || "");
  let localeStr = localeEntry
    ? t(localeEntry.zh, localeEntry.en)
    : (item.locale || "");
  const localePart = localeStr ? ` - ${localeStr}` : "";

  return `${name}${genderPart}${localePart}`;
}
