import { describe, expect, it } from "vitest";
import { practiceLevel, practiceStreaks } from "./hostedFormat";

const days = (...minutes: number[]) =>
  minutes.map((m, i) => ({ day: `2026-10-${String(i + 1).padStart(2, "0")}`, wall_seconds: m * 60, billed_seconds: m * 60, users: m ? 1 : 0 }));

describe("practiceStreaks", () => {
  it("counts the run ending today", () => {
    expect(practiceStreaks(days(5, 0, 3, 4, 2))).toEqual({ current: 3, longest: 3 });
  });

  it("keeps the streak alive when today has no practice yet", () => {
    expect(practiceStreaks(days(1, 1, 0))).toEqual({ current: 2, longest: 2 });
  });

  it("breaks after a full missed day", () => {
    expect(practiceStreaks(days(1, 1, 1, 0, 0))).toEqual({ current: 0, longest: 3 });
  });

  it("handles no data", () => {
    expect(practiceStreaks([])).toEqual({ current: 0, longest: 0 });
  });
});

describe("practiceLevel", () => {
  it("buckets minutes", () => {
    expect([0, 60, 5 * 60, 15 * 60, 30 * 60].map(practiceLevel)).toEqual([0, 1, 2, 3, 4]);
  });
});
