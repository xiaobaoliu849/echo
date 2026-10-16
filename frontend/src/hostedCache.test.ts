import { describe, expect, it } from "vitest";
import { loadCached, peekCached, putCached } from "./hostedCache";

describe("hostedCache", () => {
  it("shares one request per key", async () => {
    let calls = 0;
    const fetcher = () => Promise.resolve(++calls);
    const [a, b] = await Promise.all([loadCached("shared", fetcher), loadCached("shared", fetcher)]);
    expect([a, b, calls]).toEqual([1, 1, 1]);
  });

  it("never lets a slower revalidation undo a local write", async () => {
    let resolve: (value: string) => void = () => undefined;
    const pending = loadCached("toggle", () => new Promise<string>((r) => (resolve = r)), true);
    putCached("toggle", "after-toggle");
    resolve("before-toggle");
    expect(await pending).toBe("after-toggle");
    expect(peekCached("toggle")).toBe("after-toggle");
  });

  it("keeps the last good value when a refresh fails", async () => {
    putCached("flaky", "good");
    await expect(loadCached("flaky", () => Promise.reject(new Error("offline")), true)).rejects.toThrow("offline");
    expect(peekCached("flaky")).toBe("good");
  });
});
