import type { WordTimestamp } from "../api";

export function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

export function pad3(n: number): string {
  if (n < 10) return `00${n}`;
  if (n < 100) return `0${n}`;
  return `${n}`;
}

export function formatSrtTime(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = Math.floor(totalSeconds % 60);
  const ms = Math.round((totalSeconds % 1) * 1000);
  return `${pad2(h)}:${pad2(m)}:${pad2(s)},${pad3(ms)}`;
}

export function formatVttTime(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = Math.floor(totalSeconds % 60);
  const ms = Math.round((totalSeconds % 1) * 1000);
  return `${pad2(h)}:${pad2(m)}:${pad2(s)}.${pad3(ms)}`;
}

export function splitTranscriptToSegments(text: string): string[] {
  const cleaned = text.replace(/\r\n/g, "\n").trim();
  if (!cleaned) return [];

  // Split by sentence-ending punctuation (CJK + Western) or double newlines
  const raw = cleaned.split(/(?<=[。！？!?\n])\s*/);
  const segments: string[] = [];
  let buf = "";

  for (const part of raw) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    // If buffer + part is too long for a subtitle line, flush first
    if (buf && (buf.length + trimmed.length > 60 || buf.includes("\n"))) {
      segments.push(buf.trim());
      buf = "";
    }
    buf += (buf ? " " : "") + trimmed;
    // Flush if we hit a natural sentence boundary
    if (/[。！？!?\n]$/.test(trimmed)) {
      segments.push(buf.trim());
      buf = "";
    }
  }
  if (buf.trim()) segments.push(buf.trim());

  // If we ended up with very few segments, split by character count
  if (segments.length <= 1 && cleaned.length > 80) {
    const chunks: string[] = [];
    const chars = [...cleaned];
    let chunk = "";
    for (const ch of chars) {
      chunk += ch;
      if (chunk.length >= 50 && /[，,。！？!?\s]/.test(ch)) {
        chunks.push(chunk.trim());
        chunk = "";
      }
    }
    if (chunk.trim()) chunks.push(chunk.trim());
    return chunks.length > 0 ? chunks : segments;
  }

  return segments;
}

export type SubtitleCue = { start: number; end: number; text: string };

/**
 * Join word tokens into a display string. ASR word lists for CJK audio carry
 * one token per character/phrase, so joining with a space would sprinkle spaces
 * through Chinese text. Join without spaces when the tokens are CJK-dominant.
 */
function joinWordTokens(words: WordTimestamp[]): string {
  const joined = words.map((w) => w.text).join("");
  const cjkCount = (joined.match(/[一-鿿぀-ヿ]/g) || []).length;
  if (joined.length > 0 && cjkCount / joined.length >= 0.3) {
    return joined;
  }
  return words.map((w) => w.text).join(" ").replace(/\s+/g, " ").trim();
}

/**
 * Group word-level timestamps into subtitle cues. A cue closes on a sentence
 * boundary, after ~10 tokens, or once it spans ~5s — whichever comes first —
 * mirroring the SRT/VTT export so on-screen cues match exported files.
 */
export function buildCuesFromWords(words: WordTimestamp[]): SubtitleCue[] {
  if (!words || words.length === 0) return [];

  const segments: SubtitleCue[] = [];
  let currentSegment: WordTimestamp[] = [];

  for (let i = 0; i < words.length; i++) {
    const word = words[i];

    if (currentSegment.length === 0) {
      currentSegment.push(word);
      continue;
    }

    const segStart = currentSegment[0].start;
    const segDuration = word.end - segStart;
    const isSentenceEnd = /[。！？!?\n]$/.test(word.text);
    const hasPunctuation = /[，,;；]$/.test(word.text);
    const hasSpeechPause = i < words.length - 1 && (words[i + 1].start - word.end > 0.6);

    // Group into complete, readable subtitle lines:
    // Close cue on sentence end, or on comma/pause after 3.5s, or once segment reaches 18 words / 6.5s
    const shouldFlush =
      isSentenceEnd ||
      (segDuration >= 3.5 && (hasPunctuation || hasSpeechPause)) ||
      currentSegment.length >= 18 ||
      segDuration >= 6.5;

    currentSegment.push(word);

    if (shouldFlush) {
      segments.push({
        start: currentSegment[0].start,
        end: word.end,
        text: joinWordTokens(currentSegment),
      });
      currentSegment = [];
    }
  }

  if (currentSegment.length > 0) {
    segments.push({
      start: currentSegment[0].start,
      end: currentSegment[currentSegment.length - 1].end,
      text: joinWordTokens(currentSegment),
    });
  }

  return segments;
}

/**
 * Build display cues from whatever timing data is available: prefer word-level
 * timestamps, otherwise fall back to evenly splitting the transcript across the
 * known duration (used for providers without per-word timing).
 */
export function buildCues(
  text: string,
  durationSec: number,
  words?: WordTimestamp[] | null
): SubtitleCue[] {
  if (words && words.length > 0) {
    return buildCuesFromWords(words);
  }
  const segments = splitTranscriptToSegments(text);
  if (segments.length === 0) return [];
  const safeDuration = durationSec > 0 ? durationSec : segments.length * 5;
  const segDuration = safeDuration / segments.length;
  return segments.map((seg, i) => ({
    start: i * segDuration,
    end: Math.min((i + 1) * segDuration, safeDuration),
    text: seg,
  }));
}

export function generateSrtFromWords(words: WordTimestamp[]): string {
  return buildCuesFromWords(words)
    .map((seg, i) => {
      return `${i + 1}\n${formatSrtTime(seg.start)} --> ${formatSrtTime(seg.end)}\n${seg.text}`;
    })
    .join("\n\n");
}

export function generateSrt(text: string, durationSec: number, words?: WordTimestamp[] | null): string {
  if (words && words.length > 0) {
    return generateSrtFromWords(words);
  }

  const segments = splitTranscriptToSegments(text);
  if (segments.length === 0) return "";
  const safeDuration = durationSec > 0 ? durationSec : segments.length * 5;
  const segDuration = safeDuration / segments.length;

  return segments
    .map((seg, i) => {
      const start = i * segDuration;
      const end = Math.min((i + 1) * segDuration, safeDuration);
      return `${i + 1}\n${formatSrtTime(start)} --> ${formatSrtTime(end)}\n${seg}`;
    })
    .join("\n\n");
}

export function generateVttFromWords(words: WordTimestamp[]): string {
  const cues = buildCuesFromWords(words)
    .map((seg) => {
      return `${formatVttTime(seg.start)} --> ${formatVttTime(seg.end)}\n${seg.text}`;
    })
    .join("\n\n");

  return `WEBVTT\n\n${cues}\n`;
}

export function generateVtt(text: string, durationSec: number, words?: WordTimestamp[] | null): string {
  if (words && words.length > 0) {
    return generateVttFromWords(words);
  }

  const segments = splitTranscriptToSegments(text);
  if (segments.length === 0) return "WEBVTT\n";
  const safeDuration = durationSec > 0 ? durationSec : segments.length * 5;
  const segDuration = safeDuration / segments.length;

  const cues = segments
    .map((seg, i) => {
      const start = i * segDuration;
      const end = Math.min((i + 1) * segDuration, safeDuration);
      return `${formatVttTime(start)} --> ${formatVttTime(end)}\n${seg}`;
    })
    .join("\n\n");

  return `WEBVTT\n\n${cues}\n`;
}
