// Hosted (paid, shared-server) build: `vite build --mode hosted`.
//
// The page is served by the operator's server, talks to it same-origin, and
// only exposes the realtime voice coach. Accounts and minutes are managed on
// the server (see backend/services/hosted_mode.py).

export const IS_HOSTED_BUILD = import.meta.env.VITE_HOSTED === "true";

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
