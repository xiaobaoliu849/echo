import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTH_REJECTED_EVENT, clearAuthRuntime, fetchSettings, loginAuthUser } from "./api";

function jsonResponse(status: number, body: unknown, url: string): Response {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  Object.defineProperty(response, "url", { value: url });
  return response;
}

describe("auth rejection notifications", () => {
  let handleRejected: (event: Event) => void;
  let handleRejectedMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    clearAuthRuntime();
    handleRejectedMock = vi.fn();
    handleRejected = handleRejectedMock as (event: Event) => void;
    window.addEventListener(AUTH_REJECTED_EVENT, handleRejected);
  });

  afterEach(() => {
    window.removeEventListener(AUTH_REJECTED_EVENT, handleRejected);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("notifies listeners when a data endpoint rejects stored credentials", async () => {
    const settingsUrl = "http://127.0.0.1:8000/api/settings/";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(403, { detail: { code: "AUTH_ADMIN_TOKEN_INVALID", message: "Invalid admin Bearer token." } }, settingsUrl)
      )
    );

    await expect(fetchSettings()).rejects.toThrow();

    expect(handleRejectedMock).toHaveBeenCalledTimes(1);
    expect(handleRejectedMock.mock.calls[0][0].detail).toEqual({ code: "AUTH_ADMIN_TOKEN_INVALID" });
  });

  it("does not notify for login endpoint failures", async () => {
    const loginUrl = "http://127.0.0.1:8000/api/auth/login";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(401, { detail: { code: "AUTH_TOKEN_INVALID", message: "Invalid credentials." } }, loginUrl)
      )
    );

    await expect(loginAuthUser("user@example.com", "wrong")).rejects.toThrow();

    expect(handleRejectedMock).not.toHaveBeenCalled();
  });

  it("does not notify for non-AUTH errors", async () => {
    const settingsUrl = "http://127.0.0.1:8000/api/settings/";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(403, { detail: { code: "PERMISSION_DENIED", message: "No access." } }, settingsUrl)
      )
    );

    await expect(fetchSettings()).rejects.toThrow();

    expect(handleRejectedMock).not.toHaveBeenCalled();
  });
});
