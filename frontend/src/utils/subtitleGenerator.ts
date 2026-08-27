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

  for (const part of raw) {
    const trimmed = part.trim();
    if (!trimmed) continue;

    if (trimmed.length <= 70) {
      segments.push(trimmed);
    } else {
      // Split long text block by clause punctuation or spaces
      const subFrags = splitTextIntoFragments(trimmed, 70);
      segments.push(...subFrags);
    }
  }

  return segments.filter((s) => s.length > 0);
}

export type SubtitleCue = {
  start: number;
  end: number;
  text: string;
  translation?: string;
  speaker?: string;
};

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
 * Drop word entries that cannot describe real speech, and collapse the
 * duplicate runs some providers emit.
 *
 * This is a hard safety net, not cosmetics.  Doubao's OpenSpeech ASR resends
 * its whole cumulative result on every response, so a parser that appended
 * rather than replaced turned 870 real words into 892k — which produced tens
 * of thousands of cues, and froze the entire app the moment playback started.
 * Cue building and the karaoke lookup both assume ascending, non-negative
 * timestamps, so anything violating that is discarded here rather than
 * corrupting every downstream consumer.
 */
export function normalizeWords(words: WordTimestamp[] | null | undefined): WordTimestamp[] {
  if (!words || words.length === 0) return [];

  const out: WordTimestamp[] = [];
  const seen = new Set<string>();
  let lastStart = -Infinity;

  for (const w of words) {
    if (!w || typeof w.text !== "string") continue;
    if (!w.text.trim()) continue;
    const { start, end } = w;
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    // Separator tokens arrive with start/end of -1 (i.e. -0.001s after the
    // provider's ms->s conversion); they are not spoken words.
    if (start < 0 || end < 0) continue;
    if (end < start) continue;
    // Timestamps must not go backwards: a repeated block would otherwise
    // rewind the clock and break the binary searches that read this list.
    if (start < lastStart) continue;
    const key = `${w.text}\u0000${start}\u0000${end}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ ...w, start, end });
    lastStart = start;
  }

  return out;
}

/**
 * Group word-level timestamps into subtitle cues. A cue closes on a sentence
 * boundary, after ~10 tokens, or once it spans ~5s — whichever comes first —
 * mirroring the SRT/VTT export so on-screen cues match exported files.
 */
export function buildCuesFromWords(rawWords: WordTimestamp[]): SubtitleCue[] {
  const words = normalizeWords(rawWords);
  if (words.length === 0) return [];

  const segments: SubtitleCue[] = [];
  let currentSegment: WordTimestamp[] = [];
  let segChars = 0;

  for (let i = 0; i < words.length; i++) {
    const word = words[i];

    if (currentSegment.length === 0) {
      currentSegment.push(word);
      segChars = word.text.length;
      continue;
    }

    const segStart = currentSegment[0].start;
    const segDuration = word.end - segStart;
    const isSentenceEnd = /[。！？!?\n]$/.test(word.text);
    const hasPunctuation = /[，,;；]$/.test(word.text);
    const hasSpeechPause = i < words.length - 1 && (words[i + 1].start - word.end > 0.6);

    // Group into complete, readable subtitle lines:
    // Close cue on sentence end, or on comma/pause after 3.5s, or once segment reaches 14 words / 5s.
    const shouldFlush =
      isSentenceEnd ||
      (segDuration >= 3.0 && (hasPunctuation || hasSpeechPause)) ||
      currentSegment.length >= 14 ||
      segChars >= 40 ||
      segDuration >= 5.0;

    currentSegment.push(word);
    segChars += word.text.length;

    if (shouldFlush) {
      segments.push({
        start: currentSegment[0].start,
        end: word.end,
        text: joinWordTokens(currentSegment),
      });
      currentSegment = [];
      segChars = 0;
    }
  }

  if (currentSegment.length > 0) {
    segments.push({
      start: currentSegment[0].start,
      end: currentSegment[currentSegment.length - 1].end,
      text: joinWordTokens(currentSegment),
    });
  }

  // Post-process: split any cue that exceeds character or duration bounds.
  return splitOversizedCues(segments);
}

/** Maximum cue duration before force-splitting (seconds). */
const MAX_CUE_DURATION = 7;
/** Maximum cue text length before force-splitting (characters). */
const MAX_CUE_CHARS = 70;

/**
 * Split cues that are too long in time or text.  This is a safety net for
 * providers that return very few word-level tokens (each being a huge chunk
 * of text).  We try to split on sentence/clause boundaries first, then fall
 * back to splitting by target character count.
 */
function splitOversizedCues(cues: SubtitleCue[]): SubtitleCue[] {
  const result: SubtitleCue[] = [];

  for (const cue of cues) {
    const cueDuration = cue.end - cue.start;
    if (cueDuration <= MAX_CUE_DURATION && cue.text.length <= MAX_CUE_CHARS) {
      result.push(cue);
      continue;
    }

    // Split cue text into fragments of at most MAX_CUE_CHARS characters
    const fragments = splitTextIntoFragments(cue.text, MAX_CUE_CHARS);
    if (fragments.length <= 1) {
      result.push(cue);
      continue;
    }

    // Distribute time proportionally across fragments by character count
    const totalChars = fragments.reduce((sum, f) => sum + f.length, 0);
    let t = cue.start;
    for (let i = 0; i < fragments.length; i++) {
      const ratio = totalChars > 0 ? fragments[i].length / totalChars : 1 / fragments.length;
      const fragDuration = cueDuration * ratio;
      result.push({
        start: t,
        end: i === fragments.length - 1 ? cue.end : t + fragDuration,
        text: fragments[i],
      });
      t += fragDuration;
    }
  }

  return result;
}

const SENTENCE_END_CHAR = /[。！？!?.\n]/;
const CLAUSE_CHAR = /[，,;；、:：]/;
const WHITESPACE_CHAR = /\s/;

/**
 * Split text into fragments of roughly `targetLen` characters, preferring
 * splits at sentence-ending punctuation, then clause punctuation, then
 * spaces.  Never splits mid-word for Latin text.
 *
 * Walks the source with a cursor instead of re-slicing the remainder each
 * round.  The previous `remaining = remaining.slice(...)` form copied the
 * whole tail per fragment, making this O(n²): a 100k-character transcript
 * with no sentence punctuation (common for ASR output) burned hundreds of
 * millions of character copies on the main thread and froze the UI.
 */
function splitTextIntoFragments(text: string, targetLen: number): string[] {
  const source = text.trim();
  if (source.length <= targetLen) return source ? [source] : [];

  const fragments: string[] = [];
  const span = Math.max(1, Math.floor(targetLen * 1.2));
  const minSpan = Math.max(1, Math.floor(targetLen * 0.4));
  let cursor = 0;

  while (source.length - cursor > targetLen) {
    const searchEnd = Math.min(source.length - cursor, span);
    const searchStart = Math.min(minSpan, searchEnd);

    // 1) Sentence-ending punctuation, 2) clause punctuation, 3) word boundary
    let splitAt = -1;
    for (const probe of [SENTENCE_END_CHAR, CLAUSE_CHAR, WHITESPACE_CHAR]) {
      for (let i = searchEnd - 1; i >= searchStart; i--) {
        if (probe.test(source[cursor + i])) {
          splitAt = i + 1;
          break;
        }
      }
      if (splitAt !== -1) break;
    }

    // 4) Hard cut at targetLen as last resort.  Must stay >= 1 so the cursor
    // always advances and the loop terminates.
    if (splitAt < 1) splitAt = Math.max(1, targetLen);

    const frag = source.slice(cursor, cursor + splitAt).trim();
    if (frag) fragments.push(frag);
    cursor += splitAt;
    while (cursor < source.length && WHITESPACE_CHAR.test(source[cursor])) {
      cursor++;
    }
  }

  const tail = source.slice(cursor).trim();
  if (tail) fragments.push(tail);

  return fragments;
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
    // buildCuesFromWords already normalizes and applies splitOversizedCues.
    const cues = buildCuesFromWords(words);
    // Fall through to the text-based path when normalization rejected every
    // word, so unusable timing data degrades to plain cues instead of an
    // empty subtitle panel.
    if (cues.length > 0) return cues;
  }
  const segments = splitTranscriptToSegments(text);
  if (segments.length === 0) return [];
  const safeDuration = durationSec > 0 ? durationSec : segments.length * 5;
  const segDuration = safeDuration / segments.length;
  const cues: SubtitleCue[] = segments.map((seg, i) => ({
    start: i * segDuration,
    end: Math.min((i + 1) * segDuration, safeDuration),
    text: seg,
  }));
  return splitOversizedCues(cues);
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

export function generateBilingualSrt(
  cues: SubtitleCue[],
  mode: "bilingual" | "source" | "target" = "bilingual"
): string {
  if (!cues || cues.length === 0) return "";
  return cues
    .map((cue, i) => {
      let content = cue.text;
      if (mode === "target") {
        content = cue.translation || cue.text;
      } else if (mode === "bilingual") {
        content = cue.translation ? `${cue.text}\n${cue.translation}` : cue.text;
      }
      return `${i + 1}\n${formatSrtTime(cue.start)} --> ${formatSrtTime(cue.end)}\n${content}`;
    })
    .join("\n\n");
}

export function generateBilingualVtt(
  cues: SubtitleCue[],
  mode: "bilingual" | "source" | "target" = "bilingual"
): string {
  if (!cues || cues.length === 0) return "WEBVTT\n";
  const body = cues
    .map((cue) => {
      let content = cue.text;
      if (mode === "target") {
        content = cue.translation || cue.text;
      } else if (mode === "bilingual") {
        content = cue.translation ? `${cue.text}\n${cue.translation}` : cue.text;
      }
      return `${formatVttTime(cue.start)} --> ${formatVttTime(cue.end)}\n${content}`;
    })
    .join("\n\n");
  return `WEBVTT\n\n${body}\n`;
}

