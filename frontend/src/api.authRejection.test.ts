import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTH_REJECTED_EVENT, clearAuthRuntime, configureAuthRuntime, fetchSettings, loginAuthUser } from "./api";

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

  it("reads protected settings with the configured admin credential", async () => {
    configureAuthRuntime({ apiToken: "test-user", adminToken: "test-admin" });
    const fetch = vi.fn().mockResolvedValue(jsonResponse(200, {}, "/api/settings/"));
    vi.stubGlobal("fetch", fetch);
    await fetchSettings();
    expect(fetch.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer test-admin");
  });

  it("keeps the account signed in when provider settings require admin access", async () => {
    const settingsUrl = "http://127.0.0.1:8000/api/settings/";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(403, { detail: { code: "AUTH_ADMIN_TOKEN_INVALID", message: "Invalid admin Bearer token." } }, settingsUrl)
      )
    );

    await expect(fetchSettings()).rejects.toThrow();

    expect(handleRejectedMock).not.toHaveBeenCalled();
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
