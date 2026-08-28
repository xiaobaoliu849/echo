import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAuthRuntime, configureAuthRuntime, logoutAuthSession } from "./api";

describe("logoutAuthSession", () => {
  beforeEach(() => {
    clearAuthRuntime();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends the captured bearer token and clears the local session", async () => {
    configureAuthRuntime({ apiToken: "token-1", userEmail: "user@example.com", isAdmin: false });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await logoutAuthSession();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/auth/logout");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer token-1");
    expect(localStorage.getItem("voicespirit_api_token")).toBeNull();
    expect(localStorage.getItem("voicespirit_auth_user_email")).toBeNull();
  });

  it("clears the local session even when the server call fails", async () => {
    configureAuthRuntime({ apiToken: "token-2", userEmail: "user@example.com", isAdmin: false });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    await logoutAuthSession();

    expect(localStorage.getItem("voicespirit_api_token")).toBeNull();
  });

  it("is a no-op without a stored session", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await logoutAuthSession();

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
