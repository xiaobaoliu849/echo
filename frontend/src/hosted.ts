// Hosted (paid, shared-server) build: `vite build --mode hosted`.
//
// The page is served by the operator's server, talks to it same-origin, and
// only exposes the realtime voice coach. Accounts and minutes are managed on
// the server (see backend/services/hosted_mode.py).

export const IS_HOSTED_BUILD = import.meta.env.VITE_HOSTED === "true";

/** Provider names a neighbour recognises (the internal ones mean nothing to them). */
export const HOSTED_PROVIDER_LABELS: Record<string, string> = {
  Vercel: "谷歌 Gemini",
  DashScope: "通义千问",
  Doubao: "豆包",
};

/** Location hash of the operator console (admin accounts only). */
export const HOSTED_ADMIN_HASH = "#/admin";

/** Opens hosted Settings at a tab (detail: the tab id); the sidebar account card owns it. */
export const HOSTED_OPEN_SETTINGS_EVENT = "echo:hosted-open-settings";

/** Server → client billing frames on the voice WebSocket, re-broadcast here. */
export const HOSTED_BALANCE_EVENT = "echo:hosted-balance";

export type HostedBalanceDetail = { remainingSeconds: number };

export function publishHostedBalance(remainingSeconds: number): void {
  if (!Number.isFinite(remainingSeconds)) {
    return;
  }
  window.dispatchEvent(
    new CustomEvent<HostedBalanceDetail>(HOSTED_BALANCE_EVENT, { detail: { remainingSeconds } }),
  );
}

export function formatRemainingMinutes(seconds: number): string {
  return String(Math.max(0, Math.floor(seconds / 60)));
}

/** Display names for the models sold on the hosted server. */
export const HOSTED_MODEL_LABELS: Record<string, string> = {
  "google/gemini-3.8-live": "Gemini 3.8 Live",
  "google/gemini-3.8-live-extended-thinking": "Gemini 3.8 Live（深度思考）",
  "qwen3.8-omni-flash-realtime": "通义千问 Omni",
  "doubao-realtime": "豆包实时语音",
};

// Minutes deducted per minute of talk, per model, from /api/billing/hosted-info.
let hostedMultipliers: Record<string, number> = {};

export function setHostedMultipliers(next: Record<string, number>): void {
  hostedMultipliers = next;
}

/** Whether the server sells this model (unknown until hosted-info loads). */
export function isHostedModelSold(model: string): boolean {
  const sold = Object.keys(hostedMultipliers);
  return sold.length === 0 || sold.includes(model);
}

/** How a model is billed, e.g. "1 分钟按 1.5 分钟计"; empty for the 1:1 default. */
export function hostedBillingNote(model: string): string {
  const multiplier = hostedMultipliers[model];
  if (!multiplier || multiplier === 1) {
    return "";
  }
  return multiplier < 1
    ? `更省：1 分钟只扣 ${multiplier} 分钟`
    : `1 分钟按 ${multiplier} 分钟计`;
}

const HOSTED_LANGUAGE_KEY = "echo_hosted_ui_language";

/** Interface language of the hosted build (account preference, cached on this device). */
export function getHostedLanguage(): "zh-CN" | "en-US" {
  try {
    return localStorage.getItem(HOSTED_LANGUAGE_KEY) === "en-US" ? "en-US" : "zh-CN";
  } catch {
    return "zh-CN";
  }
}

export function setHostedLanguage(language: string): void {
  try {
    localStorage.setItem(HOSTED_LANGUAGE_KEY, language === "en-US" ? "en-US" : "zh-CN");
  } catch {
    // Private mode: the language simply falls back to Chinese.
  }
}

