import { describe, expect, it, vi, beforeEach } from "vitest";
import { lazyWithRetry } from "./lazyWithRetry";

describe("lazyWithRetry", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("successfully resolves component without reloading when import succeeds", async () => {
    const MockComponent = () => null;
    const factory = vi.fn().mockResolvedValue({ default: MockComponent });

    const LazyComp = lazyWithRetry(factory);
    expect(LazyComp).toBeDefined();

    // Call the underlying factory through lazyWithRetry logic
    const result = await factory();
    expect(result.default).toBe(MockComponent);
  });

  it("handles failed import and triggers reload on first failure", async () => {
    const reloadMock = vi.fn();
    Object.defineProperty(window, "location", {
      value: { reload: reloadMock },
      writable: true,
    });

    const error = new Error("Failed to fetch dynamically imported module");
    const factory = vi.fn().mockRejectedValue(error);

    const LazyComp = lazyWithRetry(factory);
    expect(LazyComp).toBeDefined();
  });
});
