import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../hosted", () => ({ IS_HOSTED_BUILD: true }));

import { normalizeVoiceCaptureError } from "./useVoiceChatHelpers";

const zh = (text: string) => text;

function domError(name: string, message = ""): Error {
  const error = new Error(message);
  error.name = name;
  return error;
}

describe("normalizeVoiceCaptureError in hosted builds", () => {
  afterEach(() => {
    delete (window as { isElectron?: boolean }).isElectron;
  });

  it("points desktop users at Windows microphone privacy, not developer tools", () => {
    (window as { isElectron?: boolean }).isElectron = true;
    const message = normalizeVoiceCaptureError(domError("NotAllowedError"), "fallback", zh);
    expect(message).toContain("隐私和安全性");
    expect(message).not.toMatch(/Codex|WebView|Python/);
  });

  it("points browser users at the site permission", () => {
    const message = normalizeVoiceCaptureError(domError("NotAllowedError"), "fallback", zh);
    expect(message).toContain("地址栏");
    expect(message).not.toContain("Windows");
  });

  it("tells users without a microphone what to plug in", () => {
    const message = normalizeVoiceCaptureError(domError("NotFoundError"), "fallback", zh);
    expect(message).toContain("麦克风");
    expect(message).not.toMatch(/WSL|Ubuntu|\.bat/);
  });
});
