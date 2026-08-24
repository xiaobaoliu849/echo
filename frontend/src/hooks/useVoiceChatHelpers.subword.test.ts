import { describe, it, expect } from "vitest";
import { appendAssistantDelta, mergeAssistantText } from "./useVoiceChatHelpers";

// Realtime providers stream sub-word (BPE) token deltas whose whitespace is
// authoritative. The backend's ground truth for a delta stream is a verbatim
// concatenation ("".join(assistant_parts) in realtime_cartesia_provider.py,
// ai_acc + content in realtime_doubao_provider.py). appendAssistantDelta is the
// display-path counterpart and must agree with it character-for-character.
function streamDeltas(deltas: string[]): string {
  return deltas.reduce((acc, d) => appendAssistantDelta(acc, d), "");
}

describe("appendAssistantDelta — sub-word delta streams", () => {
  it("keeps a word split across tokens intact (wonder+ful)", () => {
    expect(streamDeltas(["That is ", "wonder", "ful", "!"])).toBe("That is wonderful!");
  });

  it("does not split or drop on ambiguous overlaps (Hel+lo)", () => {
    expect(streamDeltas(["Hel", "lo"])).toBe("Hello");
  });

  it("joins many continuation tokens without inventing spaces", () => {
    expect(streamDeltas(["It is ", "un", "bel", "iev", "able"])).toBe("It is unbelievable");
  });

  it("respects leading-space tokens as the only word boundary", () => {
    const deltas = ["Certainly", "!", " I", " can", " help", " you", " transc", "ribe", " that", "."];
    expect(streamDeltas(deltas)).toBe("Certainly! I can help you transcribe that.");
  });

  it("treats a pure-whitespace delta as a real word boundary", () => {
    expect(streamDeltas(["Hello", " ", "world"])).toBe("Hello world");
  });

  it("joins CJK with an embedded Latin proper noun split across tokens", () => {
    expect(streamDeltas(["我们来聊聊", "Dot", "a2", "吧"])).toBe("我们来聊聊Dota2吧");
  });

  it("preserves genuinely repeated fragments (ha+ha)", () => {
    expect(streamDeltas(["ha", "ha", "ha"])).toBe("hahaha");
  });

  it("drops only a stray leading space on the first fragment", () => {
    expect(streamDeltas([" Hello", " world"])).toBe("Hello world");
  });

  it("is a no-op for an empty delta", () => {
    expect(appendAssistantDelta("Hello", "")).toBe("Hello");
    expect(appendAssistantDelta("", "")).toBe("");
  });
});

describe("mergeAssistantText — cumulative snapshots still replace in place", () => {
  it("adopts a prefix-extending snapshot without duplicating", () => {
    let acc = "";
    acc = mergeAssistantText(acc, "Hello there");
    acc = mergeAssistantText(acc, "Hello there, how are you");
    expect(acc).toBe("Hello there, how are you");
  });

  it("is idempotent when the same snapshot is re-sent", () => {
    expect(mergeAssistantText("Hello there", "Hello there")).toBe("Hello there");
  });
});
