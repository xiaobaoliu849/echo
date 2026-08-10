import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ALargeSmall,
  Captions,
  ChevronDown,
  ChevronUp,
  Download,
  FileText,
  LocateFixed,
  Maximize,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  Search,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import type { WordTimestamp } from "../../api";
import { useI18n } from "../../i18n";
import { buildCues, type SubtitleCue } from "../../utils/subtitleGenerator";

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
 * Component-local media clock: follows the element via timeupdate/seeked while
 * paused and a rAF loop while playing, so only the small component using the
 * clock re-renders — never the whole cue list.
 */
function useMediaClock(
  mediaRef: React.RefObject<HTMLMediaElement | null>,
  isPlaying: boolean
): number {
  const [time, setTime] = useState(0);
  useEffect(() => {
    const m = mediaRef.current;
    if (!m) return;
    const sync = () =>
      setTime((prev) =>
        Math.abs(m.currentTime - prev) > 0.04 ? m.currentTime : prev
      );
    sync();
    m.addEventListener("timeupdate", sync);
    m.addEventListener("seeked", sync);
    m.addEventListener("loadedmetadata", sync);
    let raf = 0;
    const loop = () => {
      sync();
      raf = requestAnimationFrame(loop);
    };
    if (isPlaying) raf = requestAnimationFrame(loop);
    return () => {
      m.removeEventListener("timeupdate", sync);
      m.removeEventListener("seeked", sync);
      m.removeEventListener("loadedmetadata", sync);
      cancelAnimationFrame(raf);
    };
  }, [mediaRef, isPlaying]);
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
      onClick={() => onSeek(cue.start)}
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
  mediaRef: React.RefObject<HTMLMediaElement | null>;
  duration: number;
  isPlaying: boolean;
  rate: number;
  muted: boolean;
  volume: number;
  sourceUrl: string;
  onTogglePlay: () => void;
  onSkip: (delta: number) => void;
  onCycleRate: () => void;
  onToggleMute: () => void;
  onVolumeChange: (v: number) => void;
};

/** Custom transport: play/pause, ±10s skip, seek slider, speed, volume,
 * download. Keeps its own clock so the 20 Hz slider updates stay local. */
function TransportBar({
  mediaRef,
  duration,
  isPlaying,
  rate,
  muted,
  volume,
  sourceUrl,
  onTogglePlay,
  onSkip,
  onCycleRate,
  onToggleMute,
  onVolumeChange,
}: TransportBarProps) {
  const { t } = useI18n();
  const time = useMediaClock(mediaRef, isPlaying);

  return (
    <div className="vsTransport">
      <button
        type="button"
        className="vsTransportBtn"
        onClick={() => onSkip(-10)}
        title={t("快退 10 秒", "Back 10s")}
        aria-label={t("快退 10 秒", "Back 10 seconds")}
      >
        <RotateCcw size={16} />
        <span className="vsTransportSkipLabel">10</span>
      </button>
      <button
        type="button"
        className="vsTransportPlay"
        onClick={onTogglePlay}
        title={isPlaying ? t("暂停", "Pause") : t("播放", "Play")}
        aria-label={isPlaying ? t("暂停", "Pause") : t("播放", "Play")}
      >
        {isPlaying ? <Pause size={20} /> : <Play size={20} />}
      </button>
      <button
        type="button"
        className="vsTransportBtn"
        onClick={() => onSkip(10)}
        title={t("快进 10 秒", "Forward 10s")}
        aria-label={t("快进 10 秒", "Forward 10 seconds")}
      >
        <RotateCw size={16} />
        <span className="vsTransportSkipLabel">10</span>
      </button>

      <span className="vsTimeLabel">{formatClock(time)}</span>
      <input
        type="range"
        className="vsSeek"
        min={0}
        max={duration > 0 ? duration : 0}
        step={0.1}
        value={Math.min(time, duration || time)}
        onChange={(e) => {
          const m = mediaRef.current;
          if (m) m.currentTime = Number(e.target.value);
        }}
        aria-label={t("播放进度", "Seek")}
      />
      <span className="vsTimeLabel">{formatClock(duration)}</span>

      <button
        type="button"
        className="vsTransportBtn vsRateBtn"
        onClick={onCycleRate}
        title={t("播放速度", "Playback speed")}
      >
        {rate}×
      </button>

      <button
        type="button"
        className="vsTransportBtn"
        onClick={onToggleMute}
        title={muted ? t("取消静音", "Unmute") : t("静音", "Mute")}
        aria-label={muted ? t("取消静音", "Unmute") : t("静音", "Mute")}
      >
        {muted || volume === 0 ? <VolumeX size={16} /> : <Volume2 size={16} />}
      </button>
      <input
        type="range"
        className="vsVolume"
        min={0}
        max={1}
        step={0.05}
        value={muted ? 0 : volume}
        onChange={(e) => onVolumeChange(Number(e.target.value))}
        aria-label={t("音量", "Volume")}
      />

      <a
        className="vsTransportBtn"
        href={sourceUrl}
        download
        title={t("下载源文件", "Download source file")}
        aria-label={t("下载源文件", "Download source file")}
      >
        <Download size={16} />
      </a>
    </div>
  );
}

type NowLineProps = {
  mediaRef: React.RefObject<HTMLMediaElement | null>;
  isPlaying: boolean;
  cue: SubtitleCue | null;
  cueWords: WordTimestamp[];
  variant: "card" | "overlay";
};

/** Karaoke-style current line: highlights words as they are spoken when
 * word-level timestamps exist, otherwise shows the cue text as-is. */
function NowLine({ mediaRef, isPlaying, cue, cueWords, variant }: NowLineProps) {
  const { t } = useI18n();
  const time = useMediaClock(mediaRef, isPlaying);

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
        {cueWords.length > 0
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
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const rowEls = useRef<Array<HTMLButtonElement | null>>([]);
  const userScrollingRef = useRef(false);
  const userScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [activeIndex, setActiveIndex] = useState(-1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [mediaDuration, setMediaDuration] = useState(audioDuration);
  const [mediaError, setMediaError] = useState(false);
  const [rate, setRate] = useState(1);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);

  const [follow, setFollow] = useState(true);
  const [mode, setMode] = useState<"cues" | "paragraph">("cues");
  const [showTime, setShowTime] = useState(true);
  const [fontSizeIdx, setFontSizeIdx] = useState(1);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [matchCursor, setMatchCursor] = useState(0);

  const video = isVideoFile(fileName);
  const hasMedia = Boolean(audioSourceUrl) && !mediaError;
  const fontSize = FONT_SIZES[fontSizeIdx];

  const cues = useMemo<SubtitleCue[]>(
    () => buildCues(transcript, audioDuration, words),
    [transcript, audioDuration, words]
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

  const activeCueWords = useMemo(() => {
    if (activeIndex < 0 || !words || words.length === 0) return [];
    const cue = cues[activeIndex];
    if (!cue) return [];
    return words.filter(
      (w) => w.start >= cue.start - 0.1 && w.start <= cue.end + 0.1
    );
  }, [activeIndex, cues, words]);

  const registerRow = useCallback(
    (index: number, el: HTMLButtonElement | null) => {
      rowEls.current[index] = el;
    },
    []
  );

  // Track the active cue. rAF while playing keeps word-level karaoke smooth;
  // timeupdate/seeked cover the paused case. setState bails out when the index
  // is unchanged, so this only re-renders on cue boundaries.
  useEffect(() => {
    const m = mediaRef.current;
    if (!m) return;
    const update = () => {
      const idx = findCueIndex(cues, m.currentTime);
      setActiveIndex((prev) => (prev === idx ? prev : idx));
    };
    update();
    m.addEventListener("timeupdate", update);
    m.addEventListener("seeked", update);
    let raf = 0;
    const loop = () => {
      update();
      raf = requestAnimationFrame(loop);
    };
    if (isPlaying) raf = requestAnimationFrame(loop);
    return () => {
      m.removeEventListener("timeupdate", update);
      m.removeEventListener("seeked", update);
      cancelAnimationFrame(raf);
    };
  }, [cues, isPlaying]);

  // Keep the active cue in view while playing: one smooth scroll per cue
  // change (not per timeupdate), suppressed briefly after manual scrolling.
  useEffect(() => {
    if (!follow || !isPlaying || activeIndex < 0 || userScrollingRef.current)
      return;
    const el = rowEls.current[activeIndex];
    const container = listRef.current;
    if (!el || !container) return;
    const cRect = container.getBoundingClientRect();
    const eRect = el.getBoundingClientRect();
    if (eRect.top < cRect.top + 48 || eRect.bottom > cRect.bottom - 48) {
      container.scrollTo({
        top: el.offsetTop - container.clientHeight * 0.3,
        behavior: "smooth",
      });
    }
  }, [activeIndex, follow, isPlaying]);

  useEffect(() => {
    return () => {
      if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
    };
  }, []);

  // Keyboard shortcuts: space = play/pause, ←/→ = ∓5s.
  useEffect(() => {
    if (!hasMedia) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      )
        return;
      const m = mediaRef.current;
      if (!m) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (m.paused) void m.play().catch(() => {});
        else m.pause();
      } else if (e.code === "ArrowLeft") {
        e.preventDefault();
        m.currentTime = Math.max(0, m.currentTime - 5);
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        m.currentTime = Math.min(m.duration || Infinity, m.currentTime + 5);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hasMedia]);

  function handleListScroll() {
    userScrollingRef.current = true;
    if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
    userScrollTimerRef.current = setTimeout(() => {
      userScrollingRef.current = false;
    }, 2500);
  }

  function seekTo(start: number) {
    const m = mediaRef.current;
    if (!m) return;
    m.currentTime = start;
    void m.play().catch(() => {
      /* autoplay may be blocked; the cue still highlights on manual play */
    });
  }

  function locateActive() {
    userScrollingRef.current = false;
    setFollow(true);
    const idx = activeIndex >= 0 ? activeIndex : findCueIndex(cues, mediaRef.current?.currentTime ?? 0);
    const el = rowEls.current[Math.max(0, idx)];
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function jumpMatch(direction: 1 | -1) {
    if (matches.length === 0) return;
    const next =
      (Math.min(matchCursor, matches.length - 1) + direction + matches.length) %
      matches.length;
    setMatchCursor(next);
    setMode("cues");
    const el = rowEls.current[matches[next]];
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
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
                ref={(el) => {
                  mediaRef.current = el;
                }}
                src={audioSourceUrl}
                preload="metadata"
                playsInline
                aria-label={t("转写视频播放器", "Transcription video player")}
                {...mediaEvents}
              />
              <NowLine
                mediaRef={mediaRef}
                isPlaying={isPlaying}
                cue={activeCue}
                cueWords={activeCueWords}
                variant="overlay"
              />
              <button
                type="button"
                className="vsFullscreenBtn"
                onClick={() => stageRef.current?.requestFullscreen?.()}
                title={t("全屏", "Fullscreen")}
                aria-label={t("全屏", "Fullscreen")}
              >
                <Maximize size={15} />
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
                mediaRef={mediaRef}
                isPlaying={isPlaying}
                cue={activeCue}
                cueWords={activeCueWords}
                variant="card"
              />
              {/* Hidden media element: all playback goes through the custom transport. */}
              <audio
                ref={(el) => {
                  mediaRef.current = el;
                }}
                src={audioSourceUrl}
                preload="metadata"
                aria-label={t("转写音频播放器", "Transcription audio player")}
                {...mediaEvents}
              />
            </div>
          )}

          <TransportBar
            mediaRef={mediaRef}
            duration={mediaDuration}
            isPlaying={isPlaying}
            rate={rate}
            muted={muted}
            volume={volume}
            sourceUrl={audioSourceUrl!}
            onTogglePlay={() => {
              const m = mediaRef.current;
              if (!m) return;
              if (m.paused) void m.play().catch(() => {});
              else m.pause();
            }}
            onSkip={(delta) => {
              const m = mediaRef.current;
              if (!m) return;
              m.currentTime = Math.min(
                Math.max(0, m.currentTime + delta),
                m.duration || Infinity
              );
            }}
            onCycleRate={() => {
              const next =
                PLAYBACK_RATES[(PLAYBACK_RATES.indexOf(rate) + 1) % PLAYBACK_RATES.length];
              setRate(next);
              if (mediaRef.current) mediaRef.current.playbackRate = next;
            }}
            onToggleMute={() => {
              const next = !muted;
              setMuted(next);
              if (mediaRef.current) mediaRef.current.muted = next;
            }}
            onVolumeChange={(v) => {
              setVolume(v);
              setMuted(v === 0);
              const m = mediaRef.current;
              if (m) {
                m.volume = v;
                m.muted = v === 0;
              }
            }}
          />
        </div>
      )}

      <div className="vsSubtitlePanel">
        <div className="vsSubtitleToolbar">
          {searchOpen && (
            <div className="vsSubtitleSearch">
              <Search size={13} />
              <input
                autoFocus
                value={query}
                placeholder={t("搜索字幕…", "Search subtitles…")}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setMatchCursor(0);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") jumpMatch(e.shiftKey ? -1 : 1);
                  if (e.key === "Escape") {
                    setQuery("");
                    setSearchOpen(false);
                  }
                }}
              />
              {query && (
                <span className="vsSubtitleSearchCount">
                  {matches.length > 0
                    ? `${Math.min(matchCursor + 1, matches.length)}/${matches.length}`
                    : "0/0"}
                </span>
              )}
              <button
                type="button"
                className="vsToolBtn"
                onClick={() => jumpMatch(-1)}
                disabled={matches.length === 0}
                title={t("上一个匹配", "Previous match")}
              >
                <ChevronUp size={14} />
              </button>
              <button
                type="button"
                className="vsToolBtn"
                onClick={() => jumpMatch(1)}
                disabled={matches.length === 0}
                title={t("下一个匹配", "Next match")}
              >
                <ChevronDown size={14} />
              </button>
            </div>
          )}
          <div className="vsSubtitleTools">
            <button
              type="button"
              className={`vsToolBtn ${searchOpen ? "active" : ""}`}
              onClick={() => {
                setSearchOpen((v) => !v);
                if (searchOpen) setQuery("");
              }}
              title={t("搜索字幕", "Search subtitles")}
            >
              {searchOpen ? <X size={15} /> : <Search size={15} />}
            </button>
            {hasMedia && (
              <>
                <button
                  type="button"
                  className={`vsToolBtn ${follow ? "active" : ""}`}
                  onClick={() => {
                    setFollow((v) => !v);
                    userScrollingRef.current = false;
                  }}
                  title={t("跟随播放自动滚动", "Auto-scroll with playback")}
                >
                  <Captions size={15} />
                </button>
                <button
                  type="button"
                  className="vsToolBtn"
                  onClick={locateActive}
                  title={t("回到当前字幕", "Jump to current cue")}
                >
                  <LocateFixed size={15} />
                </button>
              </>
            )}
            <button
              type="button"
              className={`vsToolBtn ${mode === "paragraph" ? "active" : ""}`}
              onClick={() =>
                setMode((m) => (m === "cues" ? "paragraph" : "cues"))
              }
              title={
                mode === "cues"
                  ? t("切换为段落阅读", "Switch to paragraph view")
                  : t("切换为字幕列表", "Switch to subtitle list")
              }
            >
              {mode === "cues" ? <FileText size={15} /> : <Captions size={15} />}
            </button>
            <button
              type="button"
              className={`vsToolBtn ${showTime ? "active" : ""}`}
              onClick={() => setShowTime((v) => !v)}
              title={t("显示/隐藏时间戳", "Toggle timestamps")}
            >
              <span className="vsToolBtnClock">00:00</span>
            </button>
            <button
              type="button"
              className="vsToolBtn"
              onClick={() => setFontSizeIdx((i) => (i + 1) % FONT_SIZES.length)}
              title={t("调整字号", "Cycle font size")}
            >
              <ALargeSmall size={15} />
            </button>
          </div>
        </div>

        {mode === "paragraph" ? (
          <div className="vsTranscriptParagraph custom-scrollbar" style={{ fontSize }}>
            {transcript}
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
