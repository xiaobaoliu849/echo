/** Input capability, independent of avatar output. Gateway realtime is audio-only. */
export function supportsLiveScreenShare(provider: string, model: string): boolean {
  return ["google", "agentplatform", "vertexai"].includes(provider.trim().toLowerCase()) &&
    model.split("/").pop() === "gemini-3.8-live";
}

export const SCREEN_FRAME_INTERVAL_MS = 1000;
export const SCREEN_FRAME_MAX_BYTES = 96 * 1024;
export const SCREEN_FRAME_MAX_DIMENSION = 768;
