import type { CoachConfig, CoachLevel, TutorScenario } from "../api";

const STORAGE_KEY = "vs_speaking_coach";

/** Window event carrying a Partial<CoachConfig> for the running voice chat (hosted settings use it). */
export const COACH_CONFIG_EVENT = "echo:coach-config";
// v3: start with spoken coaching alone. Transcript review needs a fresh opt-in
// so inherited cards do not compete with feedback from the conversation partner.
const STORAGE_VERSION = 3;

export const COACH_LEVELS: CoachLevel[] = ["beginner", "intermediate", "advanced", "ielts"];

export const TUTOR_SCENARIOS: { value: TutorScenario; zh: string; en: string }[] = [
  { value: "free_talk", zh: "自由聊天", en: "Free talk" },
  { value: "daily_life", zh: "日常生活", en: "Daily life" },
  { value: "workplace", zh: "职场沟通", en: "Workplace" },
  { value: "travel", zh: "旅行出行", en: "Travel" },
  { value: "job_interview", zh: "模拟面试", en: "Job interview" },
  { value: "ielts", zh: "雅思口语模考", en: "IELTS speaking mock" },
];

export const COACH_TARGET_LANGUAGES = ["English", "Japanese", "Korean", "French", "German", "Spanish"];

export const DEFAULT_COACH_CONFIG: CoachConfig = {
  enabled: false,
  target_language: "English",
  native_language: "Chinese",
  level: "intermediate",
  tutor: false,
  scenario: "free_talk",
  feedback_mode: "conversation",
};

export function readStoredCoachConfig(): CoachConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_COACH_CONFIG;
    const parsed = JSON.parse(raw) as Partial<CoachConfig> & { v?: number };
    const legacyCoachOn = (parsed.v ?? 0) < 2 && parsed.enabled === true;
    return {
      enabled: parsed.v === STORAGE_VERSION && parsed.enabled === true,
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
      tutor: parsed.tutor === true || legacyCoachOn,
      scenario: TUTOR_SCENARIOS.some((item) => item.value === parsed.scenario)
        ? (parsed.scenario as TutorScenario)
        : DEFAULT_COACH_CONFIG.scenario,
      feedback_mode: parsed.feedback_mode === "on_request" ? "on_request" : "conversation",
      ...(parsed.learner === "child" || parsed.learner === "adult" ? { learner: parsed.learner } : {}),
    };
  } catch {
    return DEFAULT_COACH_CONFIG;
  }
}

export function writeStoredCoachConfig(config: CoachConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...config, v: STORAGE_VERSION }));
  } catch {
    // Ignore storage errors in restricted contexts
  }
}

/** Written feedback cards are an add-on to the coach, never active on their own. */
export function coachCardsActive(config: CoachConfig): boolean {
  return config.tutor && config.enabled && config.feedback_mode !== "on_request" && config.scenario !== "ielts";
}

/** Transcription-only realtime models take no system prompt, so they cannot coach. */
export function coachSupportedModel(model: string): boolean {
  return !/transcribe/i.test(model || "");
}

/** Fields baked into the realtime system prompt at call start. */
export function tutorPromptKey(config: CoachConfig): string {
  return config.tutor
    ? [config.target_language, config.native_language, config.level, config.scenario, config.learner ?? "", config.feedback_mode ?? "conversation"].join("|")
    : "";
}

/** Normalizes an utterance so a backend review can be matched to its chat bubble. */
export function coachTextKey(text: string): string {
  return (text || "")
    .toLowerCase()
    .replace(/[\s\p{P}]+/gu, " ")
    .trim();
}
