import type { CoachConfig, CoachLevel } from "../api";

const STORAGE_KEY = "vs_speaking_coach";

export const COACH_LEVELS: CoachLevel[] = ["beginner", "intermediate", "advanced", "ielts"];

export const COACH_TARGET_LANGUAGES = ["English", "Japanese", "Korean", "French", "German", "Spanish"];

export const DEFAULT_COACH_CONFIG: CoachConfig = {
  enabled: false,
  target_language: "English",
  native_language: "Chinese",
  level: "intermediate",
};

export function readStoredCoachConfig(): CoachConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_COACH_CONFIG;
    const parsed = JSON.parse(raw) as Partial<CoachConfig>;
    return {
      enabled: parsed.enabled === true,
      target_language:
        typeof parsed.target_language === "string" && parsed.target_language.trim()
          ? parsed.target_language
          : DEFAULT_COACH_CONFIG.target_language,
      native_language:
        typeof parsed.native_language === "string" && parsed.native_language.trim()
          ? parsed.native_language
          : DEFAULT_COACH_CONFIG.native_language,
      level: COACH_LEVELS.includes(parsed.level as CoachLevel)
        ? (parsed.level as CoachLevel)
        : DEFAULT_COACH_CONFIG.level,
    };
  } catch {
    return DEFAULT_COACH_CONFIG;
  }
}

export function writeStoredCoachConfig(config: CoachConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // Ignore storage errors in restricted contexts
  }
}

/** Normalizes an utterance so a backend review can be matched to its chat bubble. */
export function coachTextKey(text: string): string {
  return (text || "")
    .toLowerCase()
    .replace(/[\s\p{P}]+/gu, " ")
    .trim();
}
