import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ALargeSmall,
  Captions,
  ChevronDown,
  ChevronUp,
  Download,
  FileText,
  Loader2,
  LocateFixed,
  Maximize,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  Search,
  TriangleAlert,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import type { WordTimestamp } from "../../api";
import { useI18n } from "../../i18n";
import { downloadBinaryFile } from "../../utils/desktopFileSave";
import { buildCues, normalizeWords, type SubtitleCue } from "../../utils/subtitleGenerator";

type Props = {
  transcript: string;
  words: WordTimestamp[];
  audioSourceUrl?: string;
  audioDuration: number;
  fileName?: string;
  onAudioDurationChange: (dur: number) => void;
};

const VIDEO_EXTS = new Set([
  "mp4", "webm", "mov", "m4v", "mkv", "avi", "flv", "ts", "mpg", "mpeg",
]);

const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 1.75, 2];
const FONT_SIZES = [13, 15, 17];

function isVideoFile(name?: string | null): boolean {
  if (!name) return false;
  const ext = name.split(".").pop()?.toLowerCase() || "";
  return VIDEO_EXTS.has(ext);
}

function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = safe % 60;
  const mm = m < 10 ? `0${m}` : `${m}`;
  const ss = s < 10 ? `0${s}` : `${s}`;
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Index of the last cue whose start <= time (binary search; cues are ordered). */
function findCueIndex(cues: SubtitleCue[], time: number): number {
  let lo = 0;
  let hi = cues.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (cues[mid].start <= time) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

/**
 * Component-local media clock: follows the media element via timeupdate/seeked
 * events.  The browser fires timeupdate ~4 Hz which is plenty for slider
 * position and word-level karaoke — no rAF loop needed.
 */
function useMediaClock(mediaEl: HTMLMediaElement | null): number {
  const [time, setTime] = useState(0);
  useEffect(() => {
    if (!mediaEl) return;
    const sync = () =>
      setTime((prev) =>
        Math.abs(mediaEl.currentTime - prev) > 0.04 ? mediaEl.currentTime : prev
      );
    sync();
    mediaEl.addEventListener("timeupdate", sync);
    mediaEl.addEventListener("seeked", sync);
    mediaEl.addEventListener("loadedmetadata", sync);
    return () => {
      mediaEl.removeEventListener("timeupdate", sync);
      mediaEl.removeEventListener("seeked", sync);
      mediaEl.removeEventListener("loadedmetadata", sync);
    };
  }, [mediaEl]);
  return time;
}

/** Split cue text into fragments, wrapping search hits in <mark>. */
function highlightText(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const parts: React.ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < text.length) {
    const hit = lower.indexOf(q, i);
    if (hit === -1) {
      parts.push(text.slice(i));
      break;
    }
    if (hit > i) parts.push(text.slice(i, hit));
    parts.push(<mark key={k++}>{text.slice(hit, hit + q.length)}</mark>);
    i = hit + q.length;
  }
  return parts;
}

type CueRowProps = {
  index: number;
  cue: SubtitleCue;
  active: boolean;
  matchState: 0 | 1 | 2; // 0 = no match, 1 = match, 2 = current match
  seekable: boolean;
  showTime: boolean;
  fontSize: number;
  query: string;
  onSeek: (start: number) => void;
  register: (index: number, el: HTMLButtonElement | null) => void;
};

/** Memoized so a change of the active cue only re-renders the two rows that
 * actually changed state, not the whole (potentially multi-thousand-row) list. */
const CueRow = memo(function CueRow({
  index,
  cue,
  active,
  matchState,
  seekable,
  showTime,
  fontSize,
  query,
  onSeek,
  register,
}: CueRowProps) {
  return (
    <button
      type="button"
      ref={(el) => register(index, el)}
      className={`vsSubtitleCue ${active ? "active" : ""} ${
        matchState === 2 ? "match-current" : matchState === 1 ? "match" : ""
      }`}
      onClick={(e) => {
        onSeek(cue.start);
        // Drop focus so the global Space/arrow shortcuts are not swallowed by
        // this button re-activating on the next keypress.
        e.currentTarget.blur();
      }}
      disabled={!seekable}
    >
      {showTime && (
        <span className="vsSubtitleCueTime">{formatClock(cue.start)}</span>
      )}
      <span className="vsSubtitleCueText" style={{ fontSize }}>
        {highlightText(cue.text, query)}
      </span>
    </button>
  );
});

type TransportBarProps = {
  mediaEl: HTMLMediaElement | null;
  duration: number;
  isPlaying: boolean;
  rate: number;
  muted: boolean;
  volume: number;
  downloading: boolean;
  onDownload: () => void;
  onTogglePlay: () => void;
  onSkip: (delta: number) => void;
  onCycleRate: () => void;
  onToggleMute: () => void;
  onVolumeChange: (v: number) => void;
};

/** `--vs-fill` drives the played-portion gradient on the range tracks; WebKit
 * (and therefore the WebView2 desktop shell) has no `::-moz-range-progress`
 * equivalent, so without this the seek bar shows no progress at all. */
function fillStyle(value: number, max: number): React.CSSProperties {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return { ["--vs-fill" as string]: `${pct}%` };
}

/** Custom transport: play/pause, ±10s skip, seek slider, speed, volume,
 * download. Keeps its own clock so the 20 Hz slider updates stay local. */
function TransportBar({
  mediaEl,
  duration,
  isPlaying,
  rate,
  muted,
  volume,
  downloading,
  onDownload,
  onTogglePlay,
  onSkip,
  onCycleRate,
  onToggleMute,
  onVolumeChange,
}: TransportBarProps) {
  const { t } = useI18n();
  const time = useMediaClock(mediaEl);
  // While dragging, show the thumb where the pointer is rather than where the
  // media clock is: seeking a range-request stream lags, and snapping the thumb
  // back to the stale currentTime on every render makes the bar fight the drag.
  const [scrub, setScrub] = useState<number | null>(null);
  const shownTime = scrub ?? Math.min(time, duration || time);
  const effectiveVolume = muted ? 0 : volume;

  return (
    <div className="vsTransport">
      <button
        type="button"
        className="vsIconBtn vsTransportBtn"
        onClick={() => onSkip(-10)}
        title={t("快退 10 秒", "Back 10s")}
        aria-label={t("快退 10 秒", "Back 10 seconds")}
      >
        <RotateCcw size={18} />
        <span className="vsTransportSkipLabel">10</span>
      </button>
      <button
        type="button"
        className="vsIconBtn vsTransportPlay"
        onClick={onTogglePlay}
        title={isPlaying ? t("暂停", "Pause") : t("播放", "Play")}
        aria-label={isPlaying ? t("暂停", "Pause") : t("播放", "Play")}
      >
        {isPlaying ? <Pause size={20} /> : <Play size={20} />}
      </button>
      <button
        type="button"
        className="vsIconBtn vsTransportBtn"
        onClick={() => onSkip(10)}
        title={t("快进 10 秒", "Forward 10s")}
        aria-label={t("快进 10 秒", "Forward 10 seconds")}
      >
        <RotateCw size={18} />
        <span className="vsTransportSkipLabel">10</span>
      </button>

      <span className="vsTransportDivider" aria-hidden />

      <span className="vsTimeLabel current">{formatClock(shownTime)}</span>
      <input
        type="range"
        className="vsSeek"
        min={0}
        max={duration > 0 ? duration : 0}
        step={0.1}
        value={shownTime}
        style={fillStyle(shownTime, duration)}
        disabled={duration <= 0}
        onChange={(e) => {
          const next = Number(e.target.value);
          setScrub(next);
          if (mediaEl) mediaEl.currentTime = next;
        }}
        onPointerUp={() => setScrub(null)}
        onBlur={() => setScrub(null)}
        onKeyUp={() => setScrub(null)}
        aria-label={t("播放进度", "Seek")}
      />
      <span className="vsTimeLabel">{formatClock(duration)}</span>

      <span className="vsTransportDivider" aria-hidden />

      <button
        type="button"
        className="vsIconBtn vsTransportBtn vsRateBtn"
        onClick={onCycleRate}
        title={t("播放速度", "Playback speed")}
      >
        {rate}×
      </button>

      <button
        type="button"
        className="vsIconBtn vsTransportBtn"
        onClick={onToggleMute}
        title={muted ? t("取消静音", "Unmute") : t("静音", "Mute")}
        aria-label={muted ? t("取消静音", "Unmute") : t("静音", "Mute")}
      >
        {muted || volume === 0 ? <VolumeX size={18} /> : <Volume2 size={18} />}
      </button>
      <input
        type="range"
        className="vsVolume"
        min={0}
        max={1}
        step={0.05}
        value={effectiveVolume}
        style={fillStyle(effectiveVolume, 1)}
        onChange={(e) => onVolumeChange(Number(e.target.value))}
        aria-label={t("音量", "Volume")}
      />

      <button
        type="button"
        className="vsIconBtn vsTransportBtn"
        onClick={onDownload}
        disabled={downloading}
        title={t("下载源文件", "Download source file")}
        aria-label={t("下载源文件", "Download source file")}
      >
        {downloading ? (
          <Loader2 size={18} className="vsSpin" />
        ) : (
          <Download size={18} />
        )}
      </button>
    </div>
  );
}

/** Max words to render with word-level karaoke.  Beyond this we degrade to
 * plain cue text to avoid flooding the DOM with <span> elements when a
 * provider returns giant single-token cues. */
const KARAOKE_WORD_CAP = 80;

type NowLineProps = {
  mediaEl: HTMLMediaElement | null;
  cue: SubtitleCue | null;
  cueWords: WordTimestamp[];
  variant: "card" | "overlay";
};

/** Karaoke-style current line: highlights words as they are spoken when
 * word-level timestamps exist, otherwise shows the cue text as-is. */
function NowLine({ mediaEl, cue, cueWords, variant }: NowLineProps) {
  const { t } = useI18n();
  const time = useMediaClock(mediaEl);

  if (!cue) {
    if (variant === "overlay") return null;
    return (
      <div className="vsNowLine card">
        <span className="vsNowLinePlaceholder">
          {t("播放音频以同步显示字幕", "Play the audio to sync subtitles")}
        </span>
      </div>
    );
  }

  return (
    <div className={`vsNowLine ${variant}`}>
      <span className="vsNowLineText">
        {cueWords.length > 0 && cueWords.length <= KARAOKE_WORD_CAP
          ? cueWords.map((w, i) => (
              <span
                key={i}
                className={`vsNowWord ${w.end <= time ? "spoken" : ""}`}
              >
                {w.text}
                {/[A-Za-z0-9]$/.test(w.text) ? " " : ""}
              </span>
            ))
          : cue.text}
      </span>
    </div>
  );
}

/**
 * Memo-style transcription player: media stage (video or audio card) with a
 * custom transport on the left, a scrolling synced subtitle panel with small
 * tool buttons (search / follow / locate / paragraph mode / font size) on the
 * right. Degrades to a plain transcript column when there is no playable media
 * (e.g. realtime mic transcriptions).
 */
export default function TranscriptionSubtitlePlayer({
  transcript,
  words,
  audioSourceUrl,
  audioDuration,
  fileName,
  onAudioDurationChange,
}: Props) {
  const { t } = useI18n();
  const [mediaEl, setMediaEl] = useState<HTMLMediaElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const rowEls = useRef<Array<HTMLButtonElement | null>>([]);
  const userScrollingRef = useRef(false);
  // Timestamp of our last follow-mode scrollTo, not a boolean flag: scrollTo is
  // a no-op when the target offset already matches, so a flag set before the
  // call would never be cleared and would swallow the user's next real scroll.
  const programmaticScrollAtRef = useRef(0);
  const userScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Bumped to re-run the match-scroll effect even when the target row index is
  // unchanged (single-match queries, or re-pressing Enter after scrolling away).
  const [scrollTick, setScrollTick] = useState(0);

  const [activeIndex, setActiveIndex] = useState(-1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [mediaDuration, setMediaDuration] = useState(audioDuration);
  const [mediaError, setMediaError] = useState(false);
  const [rate, setRate] = useState(1);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");

  const [follow, setFollow] = useState(true);
  const [mode, setMode] = useState<"cues" | "paragraph">("cues");
  const [showTime, setShowTime] = useState(true);
  const [fontSizeIdx, setFontSizeIdx] = useState(1);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [matchCursor, setMatchCursor] = useState(0);

  const video = isVideoFile(fileName);
  const hasMedia = Boolean(audioSourceUrl) && !mediaError;
  // A job that has a source URL but whose media failed to load: distinguish it
  // from a job with no media at all (realtime mic) so the panel can say why the
  // player disappeared instead of silently collapsing to a transcript column.
  const mediaFailed = Boolean(audioSourceUrl) && mediaError;
  const fontSize = FONT_SIZES[fontSizeIdx];

  // Normalize once here too: the karaoke lookup below binary-searches this
  // list, which requires ascending starts.  buildCues() cleans its own copy,
  // so without this the two would disagree on indices.
  const safeWords = useMemo(() => normalizeWords(words), [words]);

  // buildCues only consults the duration on the no-word-timestamps fallback
  // path.  Feeding it 0 when words exist keeps this memo stable across the
  // loadedmetadata -> onAudioDurationChange update that fires as playback
  // starts — otherwise every play click rebuilt the whole cue list.
  const durationForCues = safeWords.length > 0 ? 0 : audioDuration;
  const cues = useMemo<SubtitleCue[]>(
    () => buildCues(transcript, durationForCues, safeWords),
    [transcript, durationForCues, safeWords]
  );

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const out: number[] = [];
    for (let i = 0; i < cues.length; i++) {
      if (cues[i].text.toLowerCase().includes(q)) out.push(i);
    }
    return out;
  }, [cues, query]);

  const matchSet = useMemo(() => new Set(matches), [matches]);
  const currentMatchIndex =
    matches.length > 0 ? matches[Math.min(matchCursor, matches.length - 1)] : -1;

  const activeCue = activeIndex >= 0 ? cues[activeIndex] : null;

  // Binary-search for the word range within the current cue instead of
  // scanning the entire words[] array with .filter() on every cue change.
  const activeCueWords = useMemo(() => {
    if (activeIndex < 0 || safeWords.length === 0) return [];
    const cue = cues[activeIndex];
    if (!cue) return [];
    const lo = cue.start - 0.1;
    const hi = cue.end + 0.1;
    // Binary search for the first word with start >= lo
    let left = 0;
    let right = safeWords.length;
    while (left < right) {
      const mid = (left + right) >> 1;
      if (safeWords[mid].start < lo) left = mid + 1;
      else right = mid;
    }
    // Collect words until start > hi
    const result: WordTimestamp[] = [];
    for (let i = left; i < safeWords.length && safeWords[i].start <= hi; i++) {
      result.push(safeWords[i]);
    }
    return result;
  }, [activeIndex, cues, safeWords]);

  const registerRow = useCallback(
    (index: number, el: HTMLButtonElement | null) => {
      rowEls.current[index] = el;
    },
    []
  );

  // Reset per-media state when the drawer swaps in another job. Without this a
  // job whose audio 404s latches mediaError for every job opened afterwards,
  // and the previous job's duration / play state / active cue bleed through.
  // Deliberately does NOT clear rowEls: effects run after refs are attached, so
  // wiping it here would discard the refs the new rows just registered. React
  // calls each ref with null on unmount, which already clears stale entries.
  useEffect(() => {
    setMediaError(false);
    setIsPlaying(false);
    setActiveIndex(-1);
    setDownloadError("");
    // Seed from the parent (sync jobs know the duration up front); the media
    // element overwrites this on loadedmetadata.
    setMediaDuration(audioDuration > 0 ? audioDuration : 0);
    userScrollingRef.current = false;
    // audioDuration is intentionally not a dependency — this is a reset keyed
    // on the media source, and the effect below tracks later duration updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioSourceUrl]);

  // Adopt a duration that arrives after mount, until the media element reports
  // its own (which is authoritative and set via loadedmetadata).
  useEffect(() => {
    if (audioDuration > 0) {
      setMediaDuration((prev) => (prev > 0 ? prev : audioDuration));
    }
  }, [audioDuration]);

  // Re-apply transport settings to a freshly mounted media element: <audio>/
  // <video> are remounted on job change and reset to rate 1 / volume 1.
  useEffect(() => {
    if (!mediaEl) return;
    mediaEl.playbackRate = rate;
    mediaEl.volume = volume;
    mediaEl.muted = muted;
  }, [mediaEl, rate, volume, muted]);

  // Track the active cue via timeupdate/seeked events (no rAF loop).
  // timeupdate fires ~4 Hz which is more than sufficient since cue changes
  // happen every 3–7 seconds.  setState bails out when the index is unchanged,
  // so this only re-renders on cue boundaries.
  useEffect(() => {
    if (!mediaEl) return;
    const update = () => {
      const idx = findCueIndex(cues, mediaEl.currentTime);
      setActiveIndex((prev) => (prev === idx ? prev : idx));
    };
    update();
    mediaEl.addEventListener("timeupdate", update);
    mediaEl.addEventListener("seeked", update);
    return () => {
      mediaEl.removeEventListener("timeupdate", update);
      mediaEl.removeEventListener("seeked", update);
    };
  }, [cues, mediaEl]);

  /** Scroll a cue row to the middle of the list. Assigns scrollTop rather than
   * calling scrollTo: the jump is instant either way, and scrollTo would also
   * scroll ancestors (below 1080px the player grid itself scrolls). */
  const scrollRowToCenter = useCallback((index: number) => {
    const el = rowEls.current[index];
    const container = listRef.current;
    if (!el || !container) return;
    // Stamp the upcoming scroll event as ours so handleListScroll does not
    // mistake it for a manual scroll and suspend follow mode.
    programmaticScrollAtRef.current = performance.now();
    container.scrollTop =
      el.offsetTop - container.clientHeight / 2 + el.offsetHeight / 2;
  }, []);

  // Keep the active cue in view while playing: one scroll per cue change
  // (not per timeupdate), suppressed briefly after manual scrolling.
  // Use behavior: "auto" instead of "smooth" to prevent Chromium layout
  // thrashing while media timeupdates fire.
  useEffect(() => {
    if (!follow || !isPlaying || activeIndex < 0 || userScrollingRef.current)
      return;
    // An active search owns the viewport: yanking the list back to the playhead
    // would fight the user reading through matches.
    if (currentMatchIndex >= 0) return;
    const el = rowEls.current[activeIndex];
    const container = listRef.current;
    if (!el || !container) return;
    const cRect = container.getBoundingClientRect();
    const eRect = el.getBoundingClientRect();
    if (eRect.top < cRect.top + 48 || eRect.bottom > cRect.bottom - 48) {
      programmaticScrollAtRef.current = performance.now();
      container.scrollTop = el.offsetTop - container.clientHeight * 0.3;
    }
  }, [activeIndex, follow, isPlaying, currentMatchIndex]);

  // Reveal the current search match. An effect (rather than a call inside
  // jumpMatch) so that it also fires for the very first match as the user
  // types, and so row refs exist after a paragraph -> cues switch.
  useEffect(() => {
    if (mode !== "cues" || currentMatchIndex < 0) return;
    scrollRowToCenter(currentMatchIndex);
  }, [currentMatchIndex, mode, scrollTick, cues, scrollRowToCenter]);

  useEffect(() => {
    return () => {
      if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
    };
  }, []);

  // Keyboard shortcuts: space = play/pause, ←/→ = ∓5s.
  useEffect(() => {
    if (!hasMedia || !mediaEl) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      )
        return;
      // A focused control owns Space/arrows: preventDefault here would otherwise
      // swallow the activation of whichever toolbar button the user just
      // tabbed to. Cue rows blur themselves on pointer click so that clicking a
      // line and then pressing Space still toggles playback.
      if (target?.closest("button, a, [role='button']")) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (mediaEl.paused) void mediaEl.play().catch(() => {});
        else mediaEl.pause();
      } else if (e.code === "ArrowLeft") {
        e.preventDefault();
        mediaEl.currentTime = Math.max(0, mediaEl.currentTime - 5);
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        mediaEl.currentTime = Math.min(mediaEl.duration || Infinity, mediaEl.currentTime + 5);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hasMedia, mediaEl]);

  function handleListScroll() {
    // Ignore the scroll event our own follow-mode scrollTo just produced.
    // The window self-expires, so a scrollTo that turned out to be a no-op
    // cannot leave the guard armed against the user's next real scroll.
    if (performance.now() - programmaticScrollAtRef.current < 150) return;
    userScrollingRef.current = true;
    if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
    userScrollTimerRef.current = setTimeout(() => {
      userScrollingRef.current = false;
    }, 2500);
  }

  const seekTo = useCallback(
    (start: number) => {
      if (!mediaEl) return;
      mediaEl.currentTime = start;
      void mediaEl.play().catch(() => {
        /* autoplay may be blocked; the cue still highlights on manual play */
      });
    },
    [mediaEl]
  );

  function locateActive() {
    userScrollingRef.current = false;
    setFollow(true);
    setMode("cues");
    const idx = activeIndex >= 0 ? activeIndex : findCueIndex(cues, mediaEl?.currentTime ?? 0);
    scrollRowToCenter(Math.max(0, idx));
  }

  function jumpMatch(direction: 1 | -1) {
    if (matches.length === 0) return;
    const next =
      (Math.min(matchCursor, matches.length - 1) + direction + matches.length) %
      matches.length;
    setMatchCursor(next);
    setMode("cues");
    // The scroll itself is handled by the match effect; bump the tick so it
    // re-runs even when `next` lands on the row it is already showing.
    setScrollTick((n) => n + 1);
    userScrollingRef.current = false;
  }

  async function handleDownloadSource() {
    if (!audioSourceUrl || downloading) return;
    setDownloading(true);
    setDownloadError("");
    // Force an attachment disposition so browsers save rather than navigate,
    // and give the file the job's original name instead of the job id.
    // No auth header needed: the endpoint has to stay reachable without one
    // because the <audio>/<video> element cannot send headers either.
    const url = `${audioSourceUrl}${audioSourceUrl.includes("?") ? "&" : "?"}download=1`;
    const outcome = await downloadBinaryFile(url, fileName || "audio");
    setDownloading(false);
    if (outcome.kind === "failed") {
      setDownloadError(
        t(`下载失败: ${outcome.message}`, `Download failed: ${outcome.message}`)
      );
    }
  }

  function enterFullscreen() {
    // requestFullscreen rejects rather than throwing synchronously; an
    // unhandled rejection here shows up as a console error in Chromium and
    // pywebview when the gesture is not recognised as user-activated.
    void stageRef.current?.requestFullscreen?.().catch(() => {});
  }

  const handleMediaLoaded = (e: React.SyntheticEvent<HTMLMediaElement>) => {
    const d = (e.target as HTMLMediaElement).duration;
    if (d && isFinite(d) && d > 0) {
      setMediaDuration(d);
      if (audioDuration === 0) onAudioDurationChange(d);
    }
  };

  const mediaEvents = {
    onLoadedMetadata: handleMediaLoaded,
    onPlay: () => setIsPlaying(true),
    onPause: () => setIsPlaying(false),
    onEnded: () => setIsPlaying(false),
    onError: () => setMediaError(true),
  };

  return (
    <div className={`vsPlayerGrid ${hasMedia ? "" : "no-media"}`}>
      {hasMedia && (
        <div className="vsMediaPanel">
          {video ? (
            <div className="vsMediaStage" ref={stageRef}>
              <video
                ref={setMediaEl}
                src={audioSourceUrl}
                preload="metadata"
                playsInline
                aria-label={t("转写视频播放器", "Transcription video player")}
                {...mediaEvents}
              />
              <NowLine
                mediaEl={mediaEl}
                cue={activeCue}
                cueWords={activeCueWords}
                variant="overlay"
              />
              <button
                type="button"
                className="vsIconBtn vsFullscreenBtn"
                onClick={enterFullscreen}
                title={t("全屏", "Fullscreen")}
                aria-label={t("全屏", "Fullscreen")}
              >
                <Maximize size={18} />
              </button>
            </div>
          ) : (
            <div className="vsAudioCard">
              <div className={`vsEq ${isPlaying ? "playing" : ""}`} aria-hidden>
                {Array.from({ length: 5 }).map((_, i) => (
                  <span key={i} className="vsEqBar" style={{ animationDelay: `${i * 0.12}s` }} />
                ))}
              </div>
              <div className="vsAudioCardName" title={fileName}>
                {fileName || t("音频文件", "Audio file")}
              </div>
              <NowLine
                mediaEl={mediaEl}
                cue={activeCue}
                cueWords={activeCueWords}
                variant="card"
              />
              {/* Hidden media element: all playback goes through the custom transport. */}
              <audio
                ref={setMediaEl}
                src={audioSourceUrl}
                preload="metadata"
                aria-label={t("转写音频播放器", "Transcription audio player")}
                {...mediaEvents}
              />
            </div>
          )}

          <TransportBar
            mediaEl={mediaEl}
            duration={mediaDuration}
            isPlaying={isPlaying}
            rate={rate}
            muted={muted}
            volume={volume}
            downloading={downloading}
            onDownload={handleDownloadSource}
            onTogglePlay={() => {
              if (!mediaEl) return;
              if (mediaEl.paused) {
                void mediaEl.play().then(() => setIsPlaying(true)).catch(() => {});
              } else {
                mediaEl.pause();
                setIsPlaying(false);
              }
            }}
            onSkip={(delta) => {
              if (!mediaEl) return;
              mediaEl.currentTime = Math.min(
                Math.max(0, mediaEl.currentTime + delta),
                mediaEl.duration || Infinity
              );
            }}
            onCycleRate={() => {
              const next =
                PLAYBACK_RATES[(PLAYBACK_RATES.indexOf(rate) + 1) % PLAYBACK_RATES.length];
              setRate(next);
              if (mediaEl) mediaEl.playbackRate = next;
            }}
            onToggleMute={() => {
              const next = !muted;
              setMuted(next);
              if (mediaEl) mediaEl.muted = next;
            }}
            onVolumeChange={(v) => {
              setVolume(v);
              setMuted(v === 0);
              if (mediaEl) {
                mediaEl.volume = v;
                mediaEl.muted = v === 0;
              }
            }}
          />

          {downloadError && (
            <div className="vsPlayerAlert" role="alert">
              <TriangleAlert size={14} />
              <span>{downloadError}</span>
              <button
                type="button"
                className="vsIconBtn vsPlayerAlertClose"
                onClick={() => setDownloadError("")}
                aria-label={t("关闭", "Dismiss")}
              >
                <X size={14} />
              </button>
            </div>
          )}
        </div>
      )}

      <div className="vsSubtitlePanel">
        {mediaFailed && (
          <div className="vsPlayerAlert vsPlayerAlertTop" role="alert">
            <TriangleAlert size={14} />
            <span>
              {t(
                "源音频无法播放（文件可能已被移动或删除），以下仍可阅读文稿。",
                "The source audio could not be played (the file may have been moved or deleted). The transcript is still available below."
              )}
            </span>
          </div>
        )}
        <div className="vsSubtitleToolbar">
          <div className="vsSubtitleTools">
            <button
              type="button"
              className={`vsIconBtn vsToolBtn ${searchOpen ? "active" : ""}`}
              onClick={() => {
                setSearchOpen((v) => !v);
                if (searchOpen) {
                  setQuery("");
                  setMatchCursor(0);
                }
              }}
              title={t("搜索字幕", "Search subtitles")}
              aria-label={t("搜索字幕", "Search subtitles")}
              aria-expanded={searchOpen}
            >
              {searchOpen ? <X size={18} /> : <Search size={18} />}
            </button>
            {hasMedia && (
              <>
                <button
                  type="button"
                  className={`vsIconBtn vsToolBtn ${follow ? "active" : ""}`}
                  onClick={() => {
                    setFollow((v) => !v);
                    userScrollingRef.current = false;
                  }}
                  title={t("跟随播放自动滚动", "Auto-scroll with playback")}
                  aria-pressed={follow}
                >
                  <Captions size={18} />
                </button>
                <button
                  type="button"
                  className="vsIconBtn vsToolBtn"
                  onClick={locateActive}
                  title={t("回到当前字幕", "Jump to current cue")}
                  aria-label={t("回到当前字幕", "Jump to current cue")}
                >
                  <LocateFixed size={18} />
                </button>
              </>
            )}
            <button
              type="button"
              className={`vsIconBtn vsToolBtn ${mode === "paragraph" ? "active" : ""}`}
              onClick={() =>
                setMode((m) => (m === "cues" ? "paragraph" : "cues"))
              }
              title={
                mode === "cues"
                  ? t("切换为段落阅读", "Switch to paragraph view")
                  : t("切换为字幕列表", "Switch to subtitle list")
              }
              aria-pressed={mode === "paragraph"}
            >
              {mode === "cues" ? <FileText size={18} /> : <Captions size={18} />}
            </button>
            <button
              type="button"
              className={`vsIconBtn vsToolBtn ${showTime ? "active" : ""}`}
              onClick={() => setShowTime((v) => !v)}
              title={t("显示/隐藏时间戳", "Toggle timestamps")}
              aria-label={t("显示/隐藏时间戳", "Toggle timestamps")}
              aria-pressed={showTime}
            >
              <span className="vsToolBtnClock">00:00</span>
            </button>
            <button
              type="button"
              className="vsIconBtn vsToolBtn"
              onClick={() => setFontSizeIdx((i) => (i + 1) % FONT_SIZES.length)}
              title={t("调整字号", "Cycle font size")}
              aria-label={t("调整字号", "Cycle font size")}
            >
              <ALargeSmall size={18} />
            </button>
          </div>
        </div>

        {/* Own row rather than sharing the toolbar line: at the panel's
         * minmax(340px, 1fr) width the input was squeezed to a few pixels
         * between the five tool buttons and became untypeable. */}
        {searchOpen && (
          <div className="vsSubtitleSearchRow">
            <div className="vsSubtitleSearch">
              <Search size={15} className="vsSubtitleSearchIcon" />
              <input
                autoFocus
                value={query}
                placeholder={t("搜索字幕…", "Search subtitles…")}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setMatchCursor(0);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    // Match 1 is already revealed by the match effect as the
                    // user types, so Enter advances — same as find-in-page.
                    e.preventDefault();
                    jumpMatch(e.shiftKey ? -1 : 1);
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    setQuery("");
                    setMatchCursor(0);
                    setSearchOpen(false);
                  }
                }}
              />
              {query && (
                <span
                  className={`vsSubtitleSearchCount ${
                    matches.length === 0 ? "empty" : ""
                  }`}
                >
                  {matches.length > 0
                    ? `${Math.min(matchCursor + 1, matches.length)}/${matches.length}`
                    : t("无结果", "No results")}
                </span>
              )}
            </div>
            <button
              type="button"
              className="vsIconBtn vsSearchNavBtn"
              onClick={() => jumpMatch(-1)}
              disabled={matches.length === 0}
              title={t("上一个匹配", "Previous match")}
              aria-label={t("上一个匹配", "Previous match")}
            >
              <ChevronUp size={16} />
            </button>
            <button
              type="button"
              className="vsIconBtn vsSearchNavBtn"
              onClick={() => jumpMatch(1)}
              disabled={matches.length === 0}
              title={t("下一个匹配", "Next match")}
              aria-label={t("下一个匹配", "Next match")}
            >
              <ChevronDown size={16} />
            </button>
          </div>
        )}

        {mode === "paragraph" ? (
          <div className="vsTranscriptParagraph custom-scrollbar" style={{ fontSize }}>
            {highlightText(transcript, query.trim())}
          </div>
        ) : (
          <div
            className="vsSubtitleList custom-scrollbar"
            ref={listRef}
            onScroll={handleListScroll}
          >
            {cues.map((cue, i) => (
              <CueRow
                key={i}
                index={i}
                cue={cue}
                active={i === activeIndex}
                matchState={
                  i === currentMatchIndex ? 2 : matchSet.has(i) ? 1 : 0
                }
                seekable={hasMedia}
                showTime={showTime && hasMedia}
                fontSize={fontSize}
                query={query.trim()}
                onSeek={seekTo}
                register={registerRow}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
