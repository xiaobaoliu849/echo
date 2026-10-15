import type { HostedPrefs } from "./api";
import { getHostedLanguage, setHostedLanguage } from "./hosted";
import { COACH_CONFIG_EVENT, readStoredCoachConfig, writeStoredCoachConfig } from "./utils/speakingCoach";

/**
 * Make this device follow the account's preferences: the speaking coach
 * defaults and the interface language. Returns true when the language
 * changed, i.e. the page must reload to re-render in it.
 */
export function applyHostedPrefs(prefs: HostedPrefs): boolean {
  const patch = {
    tutor: prefs.coach,
    level: prefs.level,
    native_language: prefs.native_language,
    learner: prefs.learner,
    target_language: "English",
  } as const;
  writeStoredCoachConfig({ ...readStoredCoachConfig(), ...patch });
  // A running voice chat picks the change up live.
  window.dispatchEvent(new CustomEvent(COACH_CONFIG_EVENT, { detail: patch }));
  const languageChanged = getHostedLanguage() !== prefs.ui_language;
  setHostedLanguage(prefs.ui_language);
  return languageChanged;
}
