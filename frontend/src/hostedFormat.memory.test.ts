import { describe, expect, it } from "vitest";
import { memoryEpochSeconds, memoryFacts, memoryLabel } from "./hostedFormat";

describe("memory view helpers", () => {
  it("names known profile fields and tidies unknown ones", () => {
    expect(memoryLabel("english_level", true)).toBe("英语水平");
    expect(memoryLabel("Hobbies", false)).toBe("Hobbies");
    expect(memoryLabel("favourite_food", true)).toBe("Favourite food");
  });

  it("falls back to splitting legacy profile lines", () => {
    expect(memoryFacts({ profile: ["name: 你 / Xiaoming", "plain"] })).toEqual([
      { label: "name", text: "你 / Xiaoming" },
      { label: "", text: "plain" },
    ]);
    expect(memoryFacts({ facts: [{ label: "a", text: "b" }], profile: ["x: y"] })).toEqual([{ label: "a", text: "b" }]);
  });

  it("reads seconds, milliseconds and ISO timestamps", () => {
    expect(memoryEpochSeconds(1_760_000_000)).toBe(1_760_000_000);
    expect(memoryEpochSeconds(1_760_000_000_123)).toBe(1_760_000_000);
    expect(memoryEpochSeconds("2026-10-16T00:00:00Z")).toBe(Date.parse("2026-10-16T00:00:00Z") / 1000);
    expect(memoryEpochSeconds("soon")).toBeNull();
    expect(memoryEpochSeconds(null)).toBeNull();
  });
});
