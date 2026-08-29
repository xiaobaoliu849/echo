import { describe, expect, it } from "vitest";
import type { WordTimestamp } from "../../api";
import {
  buildCues,
  buildCuesFromWords,
  formatSrtTime,
  formatVttTime,
  generateBilingualSrt,
  generateBilingualVtt,
  generateSrt,
  generateSrtFromWords,
  generateVtt,
  generateVttFromWords,
  normalizeWords,
  pad2,
  pad3,
  splitTranscriptToSegments,
  type SubtitleCue,
} from "../subtitleGenerator";

describe("subtitleGenerator", () => {
  describe("pad2 and pad3", () => {
    it("pads numbers correctly with pad2", () => {
      expect(pad2(0)).toBe("00");
      expect(pad2(5)).toBe("05");
      expect(pad2(12)).toBe("12");
      expect(pad2(100)).toBe("100");
    });

    it("pads numbers correctly with pad3", () => {
      expect(pad3(0)).toBe("000");
      expect(pad3(7)).toBe("007");
      expect(pad3(42)).toBe("042");
      expect(pad3(350)).toBe("350");
      expect(pad3(1200)).toBe("1200");
    });
  });

  describe("formatSrtTime and formatVttTime", () => {
    it("formats zero seconds", () => {
      expect(formatSrtTime(0)).toBe("00:00:00,000");
      expect(formatVttTime(0)).toBe("00:00:00.000");
    });

    it("formats seconds with milliseconds and hours", () => {
      // 3661.123 = 1h 1m 1s 123ms
      expect(formatSrtTime(3661.123)).toBe("01:01:01,123");
      expect(formatVttTime(3661.123)).toBe("01:01:01.123");

      // 75.5 = 0h 1m 15s 500ms
      expect(formatSrtTime(75.5)).toBe("00:01:15,500");
      expect(formatVttTime(75.5)).toBe("00:01:15.500");
    });
  });

  describe("splitTranscriptToSegments", () => {
    it("returns empty array for empty or whitespace text", () => {
      expect(splitTranscriptToSegments("")).toEqual([]);
      expect(splitTranscriptToSegments("   \n\r  ")).toEqual([]);
    });

    it("splits by CJK and Western sentence punctuation", () => {
      const text = "你好！这是第一句。Are you ready? Yes, we are!\n换行新段落。";
      const segments = splitTranscriptToSegments(text);
      expect(segments).toContain("你好！");
      expect(segments).toContain("这是第一句。");
      expect(segments).toContain("Are you ready?");
      expect(segments).toContain("Yes, we are!");
      expect(segments).toContain("换行新段落。");
    });

    it("splits long text (>70 chars) without punctuation into fragments", () => {
      const longText =
        "这是一段非常长非常长的连续文本，没有任何标准句号结尾，我们需要测试分词切片器是否能够正确地将其拆分成不超过限制长度的较短字幕片段并保留完整的内容，因此这段文本需要显著超过七十个字符的阈值以触发分段逻辑。";
      const segments = splitTranscriptToSegments(longText);
      expect(segments.length).toBeGreaterThan(1);
      segments.forEach((seg) => {
        expect(seg.length).toBeLessThanOrEqual(100);
      });
    });
  });

  describe("normalizeWords", () => {
    it("handles null, undefined, or empty word lists", () => {
      expect(normalizeWords(null)).toEqual([]);
      expect(normalizeWords(undefined)).toEqual([]);
      expect(normalizeWords([])).toEqual([]);
    });

    it("filters out invalid words, empty strings, negative timestamps, or invalid ranges", () => {
      const raw: WordTimestamp[] = [
        { text: "   ", start: 0, end: 1 },
        { text: "invalid", start: -1, end: 1 },
        { text: "inverted", start: 5, end: 3 },
        { text: "nan", start: NaN, end: 1 },
        { text: "good", start: 0.5, end: 1.2 },
      ];
      const result = normalizeWords(raw);
      expect(result).toHaveLength(1);
      expect(result[0].text).toBe("good");
      expect(result[0].start).toBe(0.5);
      expect(result[0].end).toBe(1.2);
    });

    it("filters out rewinding/backwards timestamps and deduplicates", () => {
      const raw: WordTimestamp[] = [
        { text: "word1", start: 1.0, end: 1.5 },
        { text: "word1", start: 1.0, end: 1.5 }, // duplicate
        { text: "word2", start: 2.0, end: 2.5 },
        { text: "rewind", start: 0.5, end: 1.0 }, // rewinding start < lastStart
        { text: "word3", start: 3.0, end: 3.5 },
      ];
      const result = normalizeWords(raw);
      expect(result).toHaveLength(3);
      expect(result.map((w) => w.text)).toEqual(["word1", "word2", "word3"]);
    });
  });

  describe("buildCuesFromWords", () => {
    it("returns empty array when given empty words", () => {
      expect(buildCuesFromWords([])).toEqual([]);
    });

    it("flushes cue on sentence-ending punctuation", () => {
      const words: WordTimestamp[] = [
        { text: "你好", start: 0.0, end: 0.5 },
        { text: "世界。", start: 0.6, end: 1.2 },
        { text: "欢迎", start: 1.5, end: 2.0 },
        { text: "使用！", start: 2.1, end: 2.8 },
      ];
      const cues = buildCuesFromWords(words);
      expect(cues).toHaveLength(2);
      expect(cues[0].text).toBe("你好世界。");
      expect(cues[0].start).toBe(0.0);
      expect(cues[0].end).toBe(1.2);
      expect(cues[1].text).toBe("欢迎使用！");
      expect(cues[1].start).toBe(1.5);
      expect(cues[1].end).toBe(2.8);
    });

    it("joins English words with spaces and CJK words without spaces", () => {
      const englishWords: WordTimestamp[] = [
        { text: "Hello", start: 0.0, end: 0.5 },
        { text: "world", start: 0.6, end: 1.0 },
      ];
      const englishCues = buildCuesFromWords(englishWords);
      expect(englishCues[0].text).toBe("Hello world");

      const cjkWords: WordTimestamp[] = [
        { text: "语音", start: 0.0, end: 0.5 },
        { text: "助手", start: 0.6, end: 1.0 },
      ];
      const cjkCues = buildCuesFromWords(cjkWords);
      expect(cjkCues[0].text).toBe("语音助手");
    });

    it("splits cues when duration or word count exceeds segment limits", () => {
      const words: WordTimestamp[] = Array.from({ length: 20 }, (_, i) => ({
        text: `词语${i}`,
        start: i * 0.5,
        end: (i + 1) * 0.5,
      }));
      const cues = buildCuesFromWords(words);
      expect(cues.length).toBeGreaterThan(1);
      cues.forEach((c) => {
        expect(c.end - c.start).toBeLessThanOrEqual(7.5);
      });
    });
  });

  describe("buildCues", () => {
    it("uses words if available and valid", () => {
      const words: WordTimestamp[] = [
        { text: "测试", start: 1.0, end: 2.0 },
        { text: "分词。", start: 2.1, end: 3.0 },
      ];
      const cues = buildCues("fallback text", 10, words);
      expect(cues).toHaveLength(1);
      expect(cues[0].text).toBe("测试分词。");
    });

    it("falls back to text splitting when words are absent or invalid", () => {
      const cues = buildCues("第一句。第二句！", 6, null);
      expect(cues).toHaveLength(2);
      expect(cues[0].text).toBe("第一句。");
      expect(cues[0].start).toBe(0);
      expect(cues[0].end).toBe(3);
      expect(cues[1].text).toBe("第二句！");
      expect(cues[1].start).toBe(3);
      expect(cues[1].end).toBe(6);
    });

    it("handles empty text gracefully", () => {
      expect(buildCues("", 0)).toEqual([]);
    });
  });

  describe("generateSrt and generateSrtFromWords", () => {
    it("generates valid SRT format from words", () => {
      const words: WordTimestamp[] = [
        { text: "Hello", start: 0.0, end: 1.0 },
        { text: "world.", start: 1.1, end: 2.0 },
      ];
      const srt = generateSrtFromWords(words);
      expect(srt).toContain("1\n00:00:00,000 --> 00:00:02,000\nHello world.");
    });

    it("generates SRT from plain text segments", () => {
      const srt = generateSrt("第一段。第二段。", 10);
      expect(srt).toContain("1\n00:00:00,000 --> 00:00:05,000\n第一段。");
      expect(srt).toContain("2\n00:00:05,000 --> 00:00:10,000\n第二段。");
    });

    it("returns empty string for empty text", () => {
      expect(generateSrt("", 0)).toBe("");
    });
  });

  describe("generateVtt and generateVttFromWords", () => {
    it("generates valid WebVTT format from words", () => {
      const words: WordTimestamp[] = [
        { text: "Hello", start: 0.0, end: 1.0 },
        { text: "world.", start: 1.1, end: 2.0 },
      ];
      const vtt = generateVttFromWords(words);
      expect(vtt.startsWith("WEBVTT\n\n")).toBe(true);
      expect(vtt).toContain("00:00:00.000 --> 00:00:02.000\nHello world.");
    });

    it("generates WebVTT from plain text", () => {
      const vtt = generateVtt("测试文本。", 5);
      expect(vtt.startsWith("WEBVTT\n\n")).toBe(true);
      expect(vtt).toContain("00:00:00.000 --> 00:00:05.000\n测试文本。");
    });

    it("returns WEBVTT header for empty text", () => {
      expect(generateVtt("", 0)).toBe("WEBVTT\n");
    });
  });

  describe("generateBilingualSrt and generateBilingualVtt", () => {
    const sampleCues: SubtitleCue[] = [
      { start: 0, end: 2, text: "你好", translation: "Hello" },
      { start: 2, end: 4, text: "世界", translation: "World" },
    ];

    it("generates bilingual SRT with both source and target by default", () => {
      const srt = generateBilingualSrt(sampleCues, "bilingual");
      expect(srt).toContain("1\n00:00:00,000 --> 00:00:02,000\n你好\nHello");
      expect(srt).toContain("2\n00:00:02,000 --> 00:00:04,000\n世界\nWorld");
    });

    it("generates source-only or target-only SRT", () => {
      const sourceSrt = generateBilingualSrt(sampleCues, "source");
      expect(sourceSrt).toContain("你好");
      expect(sourceSrt).not.toContain("Hello");

      const targetSrt = generateBilingualSrt(sampleCues, "target");
      expect(targetSrt).toContain("Hello");
      expect(targetSrt).not.toContain("你好");
    });

    it("handles empty cues for bilingual SRT and VTT", () => {
      expect(generateBilingualSrt([])).toBe("");
      expect(generateBilingualVtt([])).toBe("WEBVTT\n");
    });

    it("generates bilingual VTT correctly", () => {
      const vtt = generateBilingualVtt(sampleCues, "bilingual");
      expect(vtt.startsWith("WEBVTT\n\n")).toBe(true);
      expect(vtt).toContain("00:00:00.000 --> 00:00:02.000\n你好\nHello");
    });
  });
});
