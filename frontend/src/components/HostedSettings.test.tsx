import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchHostedMemory: vi.fn(),
  fetchHostedHistory: vi.fn(),
  fetchHostedRenewal: vi.fn(),
  fetchHostedPrefs: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api")>()), ...api }));
vi.mock("./UpdateCard", () => ({ default: () => null }));

import HostedSettings from "./HostedSettings";

const history = { account: "1203", remaining_seconds: 3600, daily: [], calls: [], grants: [], lots: [] };

describe("HostedSettings memory tab", () => {
  beforeEach(() => {
    api.fetchHostedHistory.mockResolvedValue(history);
    api.fetchHostedRenewal.mockResolvedValue({ text: "", qr: "" });
    api.fetchHostedPrefs.mockResolvedValue({ learner: "adult", level: "beginner", coach: true, native_language: "Chinese", ui_language: "zh-CN" });
  });

  it("shows profile facts and dated past conversations, newest first", async () => {
    api.fetchHostedMemory.mockResolvedValue({
      configured: true,
      member: true,
      memory_until: 1_800_000_000,
      opted_out: false,
      active: true,
      facts: [{ label: "hobbies", text: "足球、恐龙" }],
      episodes: [
        { id: "a", title: "", text: "聊了周末去公园", at: 1_760_000_000 },
        { id: "b", title: "Football", text: "聊了最喜欢的球队", at: "2026-10-15T08:00:00Z" },
      ],
    });
    render(<HostedSettings initialTab="memory" onClose={() => undefined} />);

    expect(await screen.findByText("足球、恐龙")).toBeTruthy();
    expect(screen.getByText("兴趣爱好")).toBeTruthy();
    expect(screen.getByRole("switch")).toHaveProperty("checked", true);
    const items = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
    const football = items.findIndex((text) => text.includes("最喜欢的球队"));
    const park = items.findIndex((text) => text.includes("周末去公园"));
    expect(football).toBeGreaterThanOrEqual(0);
    expect(football).toBeLessThan(park);
    // Every tab was prefetched when the page opened.
    await waitFor(() => expect(api.fetchHostedPrefs).toHaveBeenCalled());
  });
});
