import { describe, it, expect } from "vitest";
import {
  isCJKPredominant,
  appendStreamingText,
  mergeAssistantText,
} from "./useVoiceChatHelpers";

// ---------------------------------------------------------------------------
// isCJKPredominant
// ---------------------------------------------------------------------------
describe("isCJKPredominant", () => {
  it("returns true for Japanese text (hiragana + kanji)", () => {
    expect(isCJKPredominant("こんにちは今日はいい天気ですね")).toBe(true);
  });

  it("returns true for Japanese text (katakana)", () => {
    expect(isCJKPredominant("コンニチハ")).toBe(true);
  });

  it("returns true for Chinese text", () => {
    expect(isCJKPredominant("这是一个中文测试句子")).toBe(true);
  });

  it("returns true for Korean text (hangul)", () => {
    expect(isCJKPredominant("안녕하세요 오늘 날씨가 좋네요")).toBe(true);
  });

  it("returns false for pure English text", () => {
    expect(isCJKPredominant("Hello, how are you today?")).toBe(false);
  });

  it("returns true for mixed CJK+Latin when CJK exceeds 30%", () => {
    // "Dota 是一款非常有趣的游戏" — CJK chars > 30% of total
    expect(isCJKPredominant("Dota 是一款非常有趣的游戏")).toBe(true);
  });

  it("returns false for mixed CJK+Latin when CJK is below 30%", () => {
    // "Hello world 你好" — only 2 CJK chars out of 14 total = ~14%
    expect(isCJKPredominant("Hello world 你好")).toBe(false);
  });

  it("returns false for empty string", () => {
    expect(isCJKPredominant("")).toBe(false);
  });

  it("returns false for whitespace-only string", () => {
    expect(isCJKPredominant("   \t\n  ")).toBe(false);
  });

  it("returns true when CJK is exactly at the threshold boundary (just over 30%)", () => {
    // 4 chars total: 2 CJK + 2 Latin = 50% → true
    // 10 chars total: need 4 CJK out of 10 = 40% → true
    expect(isCJKPredominant("AB测试CD")).toBe(true); // 2 CJK out of 6 = 33%
  });

  it("handles CJK compatibility ideographs", () => {
    // U+F900..U+FAFF range — these are rare CJK compat chars
    expect(isCJKPredominant("これは豈テストです")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// appendStreamingText
// ---------------------------------------------------------------------------
describe("appendStreamingText", () => {
  it("inserts a space between two pure Latin segments", () => {
    expect(appendStreamingText("Hello", "world")).toBe("Hello world");
  });

  it("does not insert a space inside a CJK-predominant sentence", () => {
    // Surrounding text is CJK-heavy → no space even for Latin token
    expect(appendStreamingText("今天我们要聊", "Dota")).toBe("今天我们要聊Dota");
  });

  it("does not insert a space when the second segment is CJK-predominant", () => {
    expect(appendStreamingText("Dota", "是一款好玩的游戏")).toBe("Dota是一款好玩的游戏");
  });

  it("does not insert a space for pure CJK segments", () => {
    expect(appendStreamingText("你好", "世界")).toBe("你好世界");
  });

  it("inserts a space when both segments are Latin and neither is CJK-predominant", () => {
    expect(appendStreamingText("The quick brown fox", "jumps over")).toBe(
      "The quick brown fox jumps over"
    );
  });

  it("handles empty previous gracefully", () => {
    expect(appendStreamingText("", "Hello")).toBe("Hello");
  });

  it("handles empty incoming gracefully", () => {
    expect(appendStreamingText("Hello", "")).toBe("Hello");
  });

  it("handles both empty gracefully", () => {
    expect(appendStreamingText("", "")).toBe("");
  });

  it("does not insert a leading space when Latin token follows CJK text", () => {
    // Japanese text ending with a Latin proper noun
    expect(appendStreamingText("今日の", "Dota2の試合")).toBe("今日のDota2の試合");
  });

  it("does not insert a space when Chinese text contains an English name", () => {
    expect(appendStreamingText("我叫", "John")).toBe("我叫John");
  });

  it("removes space before punctuation in Latin text", () => {
    expect(appendStreamingText("Hello world", ".")).toBe("Hello world.");
    expect(appendStreamingText("Hello world", ",")).toBe("Hello world,");
  });
});

// ---------------------------------------------------------------------------
// mergeAssistantText — streaming delta merging
// ---------------------------------------------------------------------------
describe("mergeAssistantText", () => {
  it("appends novel text that is not contained in previous", () => {
    const previous = "Hello world";
    const incoming = "how are you";
    expect(mergeAssistantText(previous, incoming)).toBe("Hello world how are you");
  });

  it("handles the case where incoming extends previous (overlap merge)", () => {
    const previous = "今日の試合は";
    const incoming = "試合はとても面白かったです";
    // "試合は" overlaps, so it should merge
    const result = mergeAssistantText(previous, incoming);
    expect(result).toBe("今日の試合はとても面白かったです");
  });

  it("returns previous when incoming is empty after trimming", () => {
    expect(mergeAssistantText("Hello", "   ")).toBe("Hello");
  });

  it("returns incoming when previous is empty", () => {
    expect(mergeAssistantText("", "Hello world")).toBe("Hello world");
  });

  it("handles the exact equality case", () => {
    const previous = "Hello world";
    const incoming = "Hello world";
    expect(mergeAssistantText(previous, incoming)).toBe(previous);
  });

  it("handles cumulative prefix: if incoming starts with previous, adopt incoming", () => {
    const previous = "Hello world";
    const incoming = "Hello world and more text";
    expect(mergeAssistantText(previous, incoming)).toBe("Hello world and more text");
  });

  it("handles true tail duplicate: previous ends with exact incoming", () => {
    const previous = "This is a test message";
    const incoming = "test message";
    expect(mergeAssistantText(previous, incoming)).toBe(previous);
  });

  // ---- CRITICAL FIX: repeated words/phrases must NOT be dropped ----

  it("preserves repeated words in natural language", () => {
    // The assistant says: "I think this is good. I think you should try."
    // Streaming: first delta "I think this is good.", then delta "I think"
    // The old buggy code dropped "I think" because includes() found it.
    const previous = "I think this is good.";
    const incoming = "I think";
    // "I think" is NOT a tail of "I think this is good." and is not a
    // cumulative extension, so it MUST be appended as new content.
    const result = mergeAssistantText(previous, incoming);
    expect(result).toBe("I think this is good. I think");
  });

  it("preserves repeated CJK phrases", () => {
    // "我觉得这个想法很好。" then "我觉得" — a new sentence starting
    const previous = "我觉得这个想法很好。";
    const incoming = "我觉得";
    const result = mergeAssistantText(previous, incoming);
    expect(result).toBe("我觉得这个想法很好。我觉得");
  });

  it("preserves repeated words in numbered lists", () => {
    const previous = "Step 1: do something.";
    const incoming = "Step 2: do something else.";
    const result = mergeAssistantText(previous, incoming);
    expect(result).toBe("Step 1: do something. Step 2: do something else.");
  });

  it("preserves punctuation-only deltas", () => {
    // The old code stripped trailing punctuation, making "!" → "" and dropping it.
    const previous = "Hello world";
    const incoming = "!";
    const result = mergeAssistantText(previous, incoming);
    expect(result).toBe("Hello world!");
  });

  it("preserves Chinese punctuation deltas", () => {
    const previous = "你好世界";
    const incoming = "。";
    const result = mergeAssistantText(previous, incoming);
    expect(result).toBe("你好世界。");
  });

  it("preserves repeated function words across sentences", () => {
    const previous = "这是一个很好的问题。";
    const incoming = "这是";
    const result = mergeAssistantText(previous, incoming);
    expect(result).toBe("这是一个很好的问题。这是");
  });

  it("handles exact tail duplicate correctly", () => {
    // If the same delta arrives twice, it should be deduplicated.
    const previous = "Hello world foo bar";
    const incoming = "foo bar";
    expect(mergeAssistantText(previous, incoming)).toBe(previous);
  });
});
