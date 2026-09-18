import { describe, expect, it } from "vitest";

import { derivePhase } from "./useLocalVoiceStatus";
import type { LocalVoiceProviderStatus } from "../api/types";

function makeStatus(overrides: Partial<LocalVoiceProviderStatus> = {}): LocalVoiceProviderStatus {
  return {
    provider: "GLM4Voice",
    server_running: false,
    installed: false,
    models_downloaded: false,
    requirements: { min_vram_gb: 10, approx_download_gb: 25 },
    gpu: { available: false },
    disk_free_gb: 500,
    ...overrides,
  };
}

describe("derivePhase", () => {
  it("is not-installed for a fresh machine", () => {
    expect(derivePhase(makeStatus(), null, false, null)).toBe("not-installed");
  });

  it("prioritizes a running setup job over everything else", () => {
    const job = { job_id: "j1", status: "running" as const, percent: 42 };
    expect(derivePhase(makeStatus({ installed: true, server_running: true }), job, false, null)).toBe("installing");
  });

  it("reports running when the server port answers", () => {
    expect(derivePhase(makeStatus({ server_running: true }), null, false, null)).toBe("running");
  });

  it("reports starting while the start request is in flight", () => {
    expect(derivePhase(makeStatus({ installed: true }), null, true, null)).toBe("starting");
  });

  it("reports installed when setup completed but the server is stopped", () => {
    expect(derivePhase(makeStatus({ installed: true, models_downloaded: true }), null, false, null)).toBe("installed");
  });

  it("surfaces errors over the bare not-installed state", () => {
    expect(derivePhase(makeStatus(), null, false, "boom")).toBe("error");
  });
});
