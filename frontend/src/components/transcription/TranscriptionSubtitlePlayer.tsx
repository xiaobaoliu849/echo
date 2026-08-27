import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ALargeSmall,
  Captions,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  Edit2,
  FileText,
  Globe,
  Loader2,
  LocateFixed,
  Maximize,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  Search,
  Sparkles,
  TriangleAlert,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import {
  burnTranscriptionVideo,
  fetchTranscriptionTranslation,
  translateTranscriptionCues,
  type WordTimestamp,
} from "../../api";
import { useI18n } from "../../i18n";
import { downloadBinaryFile, exportTextFile } from "../../utils/desktopFileSave";
import {
  buildCues,
  generateBilingualSrt,
  generateBilingualVtt,
  normalizeWords,
  type SubtitleCue,
} from "../../utils/subtitleGenerator";
import TranscriptionAiAssistant from "./TranscriptionAiAssistant";

type Props = {
  jobId?: string;
  transcript: string;
  words: WordTimestamp[];
  audioSourceUrl?: string;
  audioDuration: number;
  fileName?: string;
  onAudioDurationChange: (dur: number) => void;
  /** Register cue-aware export actions (bilingual subtitles, burn-in video) with the parent. */
  onRegisterExportActions?: (actions: SubtitleExportActions | null) => void;
};

/** Cue-aware exports owned by the player; surfaced through the page-level export menu. */
export type SubtitleExportActions = {
  exportSubtitleFile: (type: "bilingual_srt" | "target_srt" | "bilingual_vtt") => void;
  burnBilingualVideo: () => void;
  hasVideo: boolean;
  burning: boolean;
};

const VIDEO_EXTS = new Set([
  "mp4", "webm", "mov", "m4v", "mkv", "avi", "flv", "ts", "mpg", "mpeg",
]);

const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 1.75, 2];
const FONT_SIZES = [13, 15, 17];

const SUPPORTED_TRANSLATE_LANGUAGES = [
  { code: "zh-CN", label: "简体中文 (Simplified Chinese)" },
  { code: "zh-TW", label: "繁體中文 (Traditional Chinese)" },
  { code: "en", label: "English (英语)" },
  { code: "ja", label: "日本語 (日语)" },
  { code: "ko", label: "한국어 (韩语)" },
  { code: "fr", label: "Français (法语)" },
  { code: "de", label: "Deutsch (德语)" },
  { code: "es", label: "Español (西班牙语)" },
  { code: "ru", label: "Русский (俄语)" },
];

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

/** Component-local media clock */
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
  matchState: 0 | 1 | 2;
  seekable: boolean;
  showTime: boolean;
  fontSize: number;
  query: string;
  langView: "bilingual" | "source" | "target";
  isEditing: boolean;
  onSeek: (start: number) => void;
  onStartEdit: (index: number) => void;
  onSaveEdit: (index: number, text: string, translation?: string) => void;
  onCancelEdit: () => void;
  register: (index: number, el: HTMLElement | null) => void;
};

const CueRow = memo(function CueRow({
  index,
  cue,
  active,
  matchState,
  seekable,
  showTime,
  fontSize,
  query,
  langView,
  isEditing,
  onSeek,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  register,
}: CueRowProps) {
  const { t } = useI18n();
  const [editText, setEditText] = useState(cue.text);
  const [editTrans, setEditTrans] = useState(cue.translation || "");

  useEffect(() => {
    setEditText(cue.text);
    setEditTrans(cue.translation || "");
  }, [cue, isEditing]);

  const showSource = langView !== "target";
  const showTarget = langView !== "source" && Boolean(cue.translation);

  if (isEditing) {
    return (
      <div
        ref={(el) => register(index, el)}
        className="vsCueEditContainer"
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 2 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--brand)" }}>
            ⏱ {formatClock(cue.start)} - {formatClock(cue.end)}
          </span>
          <span style={{ fontSize: 11, color: "var(--muted)" }}>{t("编辑字幕", "Edit Subtitle")}</span>
        </div>
        <input
          type="text"
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          placeholder={t("原文字幕内容…", "Source subtitle text…")}
          className="vsCueEditInput"
          autoFocus
        />
        <input
          type="text"
          value={editTrans}
          onChange={(e) => setEditTrans(e.target.value)}
          placeholder={t("翻译字幕内容 (可选)…", "Translated text (optional)…")}
          className="vsCueEditInput"
        />
        <div className="vsCueEditActions">
          <button
            type="button"
            className="vsBtnGhost"
            style={{ fontSize: 12, padding: "4px 10px" }}
            onClick={onCancelEdit}
          >
            {t("取消", "Cancel")}
          </button>
          <button
            type="button"
            className="vsBtnPrimary"
            style={{ fontSize: 12, padding: "4px 12px" }}
            onClick={() => onSaveEdit(index, editText, editTrans || undefined)}
          >
            {t("保存", "Save")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      ref={(el) => register(index, el)}
      className={`vsSubtitleCue ${active ? "active" : ""} ${
        matchState === 2 ? "match-current" : matchState === 1 ? "match" : ""
      }`}
      onClick={(e) => {
        onSeek(cue.start);
        e.currentTarget.blur();
      }}
      disabled={!seekable}
    >
      {showTime && (
        <span className="vsSubtitleCueTime">{formatClock(cue.start)}</span>
      )}
      <span className="vsSubtitleCueText" style={{ fontSize }}>
        {showSource && highlightText(cue.text, query)}
        {showTarget && (
          <span className="vsSubtitleCueTranslation" style={{ display: "block", fontSize: Math.max(12, fontSize - 1) }}>
            {highlightText(cue.translation || "", query)}
          </span>
        )}
      </span>
      <span
        className="vsIconBtn vsCueRowEditBtn"
        style={{ opacity: 0, transition: "opacity 0.15s ease", width: 26, height: 26, display: "inline-flex", alignItems: "center", justifyContent: "center" }}
        onClick={(e) => {
          e.stopPropagation();
          onStartEdit(index);
        }}
        title={t("编辑该句字幕", "Edit cue")}
      >
        <Edit2 size={13} />
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

function fillStyle(value: number, max: number): React.CSSProperties {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return { ["--vs-fill" as string]: `${pct}%` };
}

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

      <span className="vsTransportTime" aria-label={t("播放进度", "Playback time")}>
        {formatClock(shownTime)} / {formatClock(duration)}
      </span>

      <input
        type="range"
        className="vsSeek"
        min={0}
        max={duration || 1}
        step={0.1}
        value={shownTime}
        style={fillStyle(shownTime, duration || 1)}
        onPointerDown={(e) => setScrub(Number((e.target as HTMLInputElement).value))}
        onChange={(e) => {
          const v = Number(e.target.value);
          setScrub(v);
          if (mediaEl) mediaEl.currentTime = v;
        }}
        onPointerUp={() => setScrub(null)}
        aria-label={t("跳转时间", "Seek position")}
      />

      <button
        type="button"
        className="vsTransportRate"
        onClick={onCycleRate}
        title={t(`播放速度 ${rate}x`, `Speed ${rate}x`)}
      >
        {rate}x
      </button>

      <button
        type="button"
        className="vsIconBtn vsTransportBtn"
        onClick={onToggleMute}
        title={muted ? t("取消静音", "Unmute") : t("静音", "Mute")}
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

const KARAOKE_WORD_CAP = 80;

type NowLineProps = {
  mediaEl: HTMLMediaElement | null;
  cue: SubtitleCue | null;
  cueWords: WordTimestamp[];
  variant: "card" | "overlay";
  langView: "bilingual" | "source" | "target";
};

/** Karaoke-style on-video caption overlay */
function NowLine({ mediaEl, cue, cueWords, variant, langView }: NowLineProps) {
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

  const showSource = langView !== "target";
  const showTarget = langView !== "source" && Boolean(cue.translation);

  return (
    <div className={`vsNowLine ${variant}`}>
      {showSource && (
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
      )}
      {showTarget && (
        <span className="vsNowLineTranslation">
          {cue.translation}
        </span>
      )}
    </div>
  );
}

export default function TranscriptionSubtitlePlayer({
  jobId,
  transcript,
  words,
  audioSourceUrl,
  audioDuration,
  fileName,
  onAudioDurationChange,
  onRegisterExportActions,
}: Props) {
  const { t } = useI18n();
  const [mediaEl, setMediaEl] = useState<HTMLMediaElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const rowEls = useRef<Array<HTMLElement | null>>([]);
  const userScrollingRef = useRef(false);
  const programmaticScrollAtRef = useRef(0);
  const userScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Translation & View mode
  const [langView, setLangView] = useState<"bilingual" | "source" | "target">("bilingual");
  const [translateModalOpen, setTranslateModalOpen] = useState(false);
  const [targetLang, setTargetLang] = useState("zh-CN");
  const [translateModel, setTranslateModel] = useState("DashScope");
  const [isTranslating, setIsTranslating] = useState(false);

  // Inline Cue Editing
  const [editingIndex, setEditingIndex] = useState<number | null>(null);

  // Video Burning (FFmpeg)
  const [burnVideoLoading, setBurnVideoLoading] = useState(false);
  const [burnVideoSuccess, setBurnVideoSuccess] = useState("");

  // Right Panel Tabs: Subtitles vs AI Insights
  const [panelTab, setPanelTab] = useState<"subtitles" | "ai">("subtitles");

  const video = isVideoFile(fileName);
  const hasMedia = Boolean(audioSourceUrl) && !mediaError;
  const mediaFailed = Boolean(audioSourceUrl) && mediaError;
  const fontSize = FONT_SIZES[fontSizeIdx];

  const safeWords = useMemo(() => normalizeWords(words), [words]);
  const durationForCues = safeWords.length > 0 ? 0 : audioDuration;

  const initialCues = useMemo<SubtitleCue[]>(
    () => buildCues(transcript, durationForCues, safeWords),
    [transcript, durationForCues, safeWords]
  );

  const [cues, setCues] = useState<SubtitleCue[]>(initialCues);

  // Sync cues with initialCues when transcript or duration updates
  useEffect(() => {
    setCues(initialCues);
  }, [initialCues]);

  // Load existing translation from backend if available
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    fetchTranscriptionTranslation(jobId)
      .then((res) => {
        if (cancelled || !res || !res.cues || res.cues.length === 0) return;
        setCues((prev) => {
          return prev.map((c, i) => {
            const match = res.cues[i];
            return match && match.translation ? { ...c, translation: match.translation } : c;
          });
        });
        setLangView("bilingual");
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const out: number[] = [];
    for (let i = 0; i < cues.length; i++) {
      const matchText = cues[i].text.toLowerCase().includes(q) || (cues[i].translation || "").toLowerCase().includes(q);
      if (matchText) out.push(i);
    }
    return out;
  }, [cues, query]);

  const matchSet = useMemo(() => new Set(matches), [matches]);
  const currentMatchIndex =
    matches.length > 0 ? matches[Math.min(matchCursor, matches.length - 1)] : -1;

  const activeCue = activeIndex >= 0 ? cues[activeIndex] : null;

  const activeCueWords = useMemo(() => {
    if (activeIndex < 0 || safeWords.length === 0) return [];
    const cue = cues[activeIndex];
    if (!cue) return [];
    const lo = cue.start - 0.1;
    const hi = cue.end + 0.1;
    let left = 0;
    let right = safeWords.length;
    while (left < right) {
      const mid = (left + right) >> 1;
      if (safeWords[mid].start < lo) left = mid + 1;
      else right = mid;
    }
    const result: WordTimestamp[] = [];
    for (let i = left; i < safeWords.length && safeWords[i].start <= hi; i++) {
      result.push(safeWords[i]);
    }
    return result;
  }, [activeIndex, cues, safeWords]);

  const registerRow = useCallback(
    (index: number, el: HTMLElement | null) => {
      rowEls.current[index] = el;
    },
    []
  );

  useEffect(() => {
    setMediaError(false);
    setIsPlaying(false);
    setActiveIndex(-1);
    setDownloadError("");
    setMediaDuration(audioDuration > 0 ? audioDuration : 0);
    userScrollingRef.current = false;
  }, [audioSourceUrl]);

  useEffect(() => {
    if (audioDuration > 0) {
      setMediaDuration((prev) => (prev > 0 ? prev : audioDuration));
    }
  }, [audioDuration]);

  useEffect(() => {
    if (!mediaEl) return;
    mediaEl.playbackRate = rate;
    mediaEl.volume = volume;
    mediaEl.muted = muted;
  }, [mediaEl, rate, volume, muted]);

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

  const scrollRowToCenter = useCallback((index: number) => {
    const el = rowEls.current[index];
    const container = listRef.current;
    if (!el || !container) return;
    programmaticScrollAtRef.current = performance.now();
    container.scrollTop =
      el.offsetTop - container.clientHeight / 2 + el.offsetHeight / 2;
  }, []);

  useEffect(() => {
    if (!follow || !isPlaying || activeIndex < 0 || userScrollingRef.current)
      return;
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

  useEffect(() => {
    if (mode !== "cues" || currentMatchIndex < 0) return;
    scrollRowToCenter(currentMatchIndex);
  }, [currentMatchIndex, mode, scrollTick, cues, scrollRowToCenter]);

  function handleListScroll() {
    const now = performance.now();
    if (now - programmaticScrollAtRef.current < 250) return;
    userScrollingRef.current = true;
    if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
    userScrollTimerRef.current = setTimeout(() => {
      userScrollingRef.current = false;
    }, 1500);
  }

  const handleSeek = useCallback(
    (start: number) => {
      if (!mediaEl) return;
      mediaEl.currentTime = start;
      void mediaEl.play().catch(() => {});
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
    setScrollTick((n) => n + 1);
    userScrollingRef.current = false;
  }

  async function handleDownloadSource() {
    if (!audioSourceUrl || downloading) return;
    setDownloading(true);
    setDownloadError("");
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

  // AI One-Click Translation Handler
  async function handleStartTranslate() {
    if (!jobId || isTranslating) return;
    setIsTranslating(true);
    try {
      const res = await translateTranscriptionCues(
        jobId,
        targetLang,
        cues,
        translateModel
      );
      if (res && res.cues) {
        setCues(res.cues);
        setLangView("bilingual");
        setTranslateModalOpen(false);
      }
    } catch (err: any) {
      alert(t(`翻译失败: ${err.message}`, `Translation failed: ${err.message}`));
    } finally {
      setIsTranslating(false);
    }
  }

  // Inline Cue Editing Save
  function handleSaveCueEdit(index: number, newText: string, newTrans?: string) {
    setCues((prev) => {
      const next = [...prev];
      if (next[index]) {
        next[index] = {
          ...next[index],
          text: newText,
          translation: newTrans,
        };
      }
      return next;
    });
    setEditingIndex(null);
  }

  // Export handlers (cue-aware; invoked from the page-level export menu)
  async function handleExportFile(type: "bilingual_srt" | "target_srt" | "bilingual_vtt") {
    const base = (fileName || "transcription").replace(/\.[^/.]+$/, "");
    let content = "";
    let ext = "srt";

    if (type === "bilingual_srt") {
      content = "\uFEFF" + generateBilingualSrt(cues, "bilingual");
      ext = "bilingual.srt";
    } else if (type === "target_srt") {
      content = "\uFEFF" + generateBilingualSrt(cues, "target");
      ext = "translated.srt";
    } else if (type === "bilingual_vtt") {
      content = generateBilingualVtt(cues, "bilingual");
      ext = "vtt";
    }

    await exportTextFile(`${base}.${ext}`, content);
  }

  // Burn Video Handler
  async function handleBurnVideo() {
    if (!jobId || burnVideoLoading) return;
    setBurnVideoLoading(true);
    setBurnVideoSuccess("");
    try {
      const srt = generateBilingualSrt(cues, "bilingual");
      const resp = await burnTranscriptionVideo(jobId, srt, targetLang, true);
      const downloadUrl = `${resp.download_url}${resp.download_url.includes("?") ? "&" : "?"}download=1`;
      await downloadBinaryFile(downloadUrl, `${(fileName || "video").replace(/\.[^/.]+$/, "")}_双语字幕.mp4`);
      setBurnVideoSuccess(t("双语字幕视频压制并导出成功！", "Subtitled video exported successfully!"));
      setTimeout(() => setBurnVideoSuccess(""), 4000);
    } catch (err: any) {
      alert(t(`压制视频失败: ${err.message}`, `Failed to burn video: ${err.message}`));
    } finally {
      setBurnVideoLoading(false);
    }
  }

  // Keep the registered actions pointing at fresh closures (cues/edits change over time).
  const exportActionsRef = useRef<SubtitleExportActions | null>(null);
  exportActionsRef.current = {
    exportSubtitleFile: handleExportFile,
    burnBilingualVideo: handleBurnVideo,
    hasVideo: video,
    burning: burnVideoLoading,
  };

  useEffect(() => {
    if (!onRegisterExportActions) return;
    onRegisterExportActions({
      exportSubtitleFile: (type) => exportActionsRef.current?.exportSubtitleFile(type),
      burnBilingualVideo: () => exportActionsRef.current?.burnBilingualVideo(),
      hasVideo: exportActionsRef.current?.hasVideo ?? false,
      burning: exportActionsRef.current?.burning ?? false,
    });
    return () => onRegisterExportActions(null);
  }, [onRegisterExportActions, video, burnVideoLoading]);

  return (
    <div className={`vsPlayerGrid ${hasMedia ? "" : "no-media"}`}>
      {/* LEFT COLUMN: Media Player + AI Assistant */}
      {hasMedia && (
        <div className="vsMediaPanel" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
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
              {/* Memo-style On-Video Subtitle Overlay */}
              <NowLine
                mediaEl={mediaEl}
                cue={activeCue}
                cueWords={activeCueWords}
                variant="overlay"
                langView={langView}
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
              <audio
                ref={setMediaEl}
                src={audioSourceUrl}
                preload="metadata"
                aria-label={t("转写音频播放器", "Transcription audio player")}
                {...mediaEvents}
                style={{ display: "none" }}
              />
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
                langView={langView}
              />
            </div>
          )}

          {/* Transport Bar */}
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
              if (isPlaying) {
                mediaEl.pause();
              } else {
                void mediaEl.play().catch(() => {});
              }
            }}
            onSkip={(delta) => {
              if (!mediaEl) return;
              mediaEl.currentTime = Math.max(
                0,
                Math.min(
                  mediaEl.currentTime + delta,
                  mediaEl.duration || Infinity
                )
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
            </div>
          )}

          {burnVideoLoading && (
            <div className="vsPlayerAlert" style={{ background: "#e0e7ff", color: "#4338ca", borderColor: "#c7d2fe" }}>
              <Loader2 size={15} className="vsSpin" />
              <span>{t("FFmpeg 正在后台压制双语高清视频，请稍候…", "FFmpeg is burning bilingual subtitles into video…")}</span>
            </div>
          )}

          {burnVideoSuccess && (
            <div className="vsPlayerAlert" style={{ background: "#ecfdf5", color: "#065f46", borderColor: "#a7f3d0" }}>
              <Check size={15} color="#10b981" />
              <span>{burnVideoSuccess}</span>
            </div>
          )}
        </div>
      )}

      {/* RIGHT COLUMN: Subtitle / AI Insights Workspace */}
      <div className="vsSubtitlePanel">
        {/* Right Panel Header Tabs: Subtitles vs AI */}
        <div className="vsRightPanelTabs">
          <button
            type="button"
            className={`vsRightPanelTab ${panelTab === "subtitles" ? "active" : ""}`}
            onClick={() => setPanelTab("subtitles")}
          >
            <Captions size={15} />
            <span>{t("逐句字幕", "Subtitles")}</span>
            <span className="vsTabCount">{cues.length}</span>
          </button>
          <button
            type="button"
            className={`vsRightPanelTab ${panelTab === "ai" ? "active" : ""}`}
            onClick={() => setPanelTab("ai")}
          >
            <Sparkles size={15} />
            <span>{t("AI 智能分析", "AI Insights")}</span>
          </button>
        </div>

        {panelTab === "ai" ? (
          <div className="vsAiPanelContainer custom-scrollbar">
            <TranscriptionAiAssistant
              transcript={transcript}
              fileName={fileName}
              jobId={jobId}
            />
          </div>
        ) : (
          <>
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

            {/* Subtitle Workspace Toolbar */}
            <div className="vsSubtitleToolbar">
              {/* Language View Switcher */}
              <div className="vsLangSwitcher">
                <button
                  type="button"
                  className={`vsLangSwitcherBtn ${langView === "bilingual" ? "active" : ""}`}
                  onClick={() => setLangView("bilingual")}
                  title={t("双语对照模式", "Bilingual View")}
                >
                  {t("双语", "Bilingual")}
                </button>
                <button
                  type="button"
                  className={`vsLangSwitcherBtn ${langView === "source" ? "active" : ""}`}
                  onClick={() => setLangView("source")}
                  title={t("仅看原文", "Source Only")}
                >
                  {t("原文", "Source")}
                </button>
                <button
                  type="button"
                  className={`vsLangSwitcherBtn ${langView === "target" ? "active" : ""}`}
                  onClick={() => setLangView("target")}
                  title={t("仅看译文", "Target Only")}
                >
                  {t("译文", "Target")}
                </button>
              </div>

              {/* AI One-Click Translate Button */}
              <button
                type="button"
                className="vsBtnSecondary vsSubtitleAiTranslateBtn"
                onClick={() => setTranslateModalOpen(true)}
                title={t("AI 一键翻译字幕", "AI Translate")}
              >
                <Globe size={13} />
                <span>{t("AI 翻译", "AI Translate")}</span>
              </button>

              {/* Right Tools Group */}
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
                  {searchOpen ? <X size={15} /> : <Search size={15} />}
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
                      <Captions size={15} />
                    </button>
                    <button
                      type="button"
                      className="vsIconBtn vsToolBtn"
                      onClick={locateActive}
                      title={t("回到当前字幕", "Jump to current cue")}
                      aria-label={t("回到当前字幕", "Jump to current cue")}
                    >
                      <LocateFixed size={15} />
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
                  {mode === "cues" ? <FileText size={15} /> : <Captions size={15} />}
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
                  <ALargeSmall size={15} />
                </button>
              </div>
            </div>

            {/* Translation Modal / Popover */}
            {translateModalOpen && (
              <div
                style={{
                  position: "absolute",
                  top: 50,
                  left: 16,
                  right: 16,
                  background: "var(--bg-card)",
                  border: "1px solid var(--border-color)",
                  borderRadius: 12,
                  padding: "16px 20px",
                  boxShadow: "0 12px 32px rgba(0,0,0,0.18)",
                  zIndex: 90,
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 15 }}>
                    <Globe size={18} color="var(--brand)" />
                    {t("AI 一键全片双语翻译", "AI Bilingual Translation")}
                  </div>
                  <button
                    type="button"
                    className="vsIconBtn"
                    onClick={() => setTranslateModalOpen(false)}
                    style={{ width: 28, height: 28 }}
                  >
                    <X size={16} />
                  </button>
                </div>

                <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                  <div style={{ flex: 1, minWidth: 160, display: "flex", flexDirection: "column", gap: 4 }}>
                    <label style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)" }}>{t("目标语言", "Target Language")}</label>
                    <select
                      value={targetLang}
                      onChange={(e) => setTargetLang(e.target.value)}
                      className="vsSelect"
                      style={{ height: 38, borderRadius: 8, fontSize: 13 }}
                    >
                      {SUPPORTED_TRANSLATE_LANGUAGES.map((l) => (
                        <option key={l.code} value={l.code}>{l.label}</option>
                      ))}
                    </select>
                  </div>

                  <div style={{ flex: 1, minWidth: 160, display: "flex", flexDirection: "column", gap: 4 }}>
                    <label style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)" }}>{t("翻译大模型", "Translation Engine")}</label>
                    <select
                      value={translateModel}
                      onChange={(e) => setTranslateModel(e.target.value)}
                      className="vsSelect"
                      style={{ height: 38, borderRadius: 8, fontSize: 13 }}
                    >
                      <option value="DashScope">DashScope (通义千问 Qwen / 推荐)</option>
                      <option value="Google">Google (Gemini 2.5 Flash)</option>
                      <option value="DeepSeek">DeepSeek (V3 / R1)</option>
                      <option value="Xiaomi">Xiaomi (小米 MiMo)</option>
                      <option value="OpenRouter">OpenRouter</option>
                      <option value="SiliconFlow">SiliconFlow (硅基流动)</option>
                    </select>
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
                  <button
                    type="button"
                    className="vsBtnGhost"
                    onClick={() => setTranslateModalOpen(false)}
                    disabled={isTranslating}
                  >
                    {t("取消", "Cancel")}
                  </button>
                  <button
                    type="button"
                    className="vsBtnPrimary"
                    onClick={handleStartTranslate}
                    disabled={isTranslating}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                  >
                    {isTranslating ? <Loader2 size={14} className="vsSpin" /> : <Sparkles size={14} />}
                    {isTranslating ? t("正在全速翻译中…", "Translating…") : t("开始翻译", "Start Translating")}
                  </button>
                </div>
              </div>
            )}

            {/* Search Bar Row */}
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
                        e.preventDefault();
                        jumpMatch(e.shiftKey ? -1 : 1);
                      } else if (e.key === "Escape") {
                        e.preventDefault();
                        setSearchOpen(false);
                        setQuery("");
                        setMatchCursor(0);
                      }
                    }}
                  />
                  <span
                    className={`vsSubtitleSearchCount ${
                      query && matches.length === 0 ? "empty" : ""
                    }`}
                  >
                    {query
                      ? matches.length > 0
                        ? `${matchCursor + 1}/${matches.length}`
                        : t("无结果", "No matches")
                      : ""}
                  </span>
                </div>
                <button
                  type="button"
                  className="vsIconBtn vsSearchNavBtn"
                  disabled={matches.length === 0}
                  onClick={() => jumpMatch(-1)}
                  title={t("上一个匹配 (Shift+Enter)", "Previous match (Shift+Enter)")}
                  aria-label={t("上一个匹配", "Previous match")}
                >
                  <ChevronUp size={16} />
                </button>
                <button
                  type="button"
                  className="vsIconBtn vsSearchNavBtn"
                  disabled={matches.length === 0}
                  onClick={() => jumpMatch(1)}
                  title={t("下一个匹配 (Enter)", "Next match (Enter)")}
                  aria-label={t("下一个匹配", "Next match")}
                >
                  <ChevronDown size={16} />
                </button>
              </div>
            )}

            {/* Subtitle Cue List / Paragraph View */}
            {mode === "paragraph" ? (
              <div className="vsTranscriptParagraph" style={{ fontSize }}>
                {cues.map((c, i) => (
                  <p key={i} style={{ margin: "0 0 12px 0" }}>
                    <span>{c.text}</span>
                    {c.translation && (
                      <span style={{ display: "block", color: "var(--brand)", fontSize: "0.9em", marginTop: 2 }}>
                        {c.translation}
                      </span>
                    )}
                  </p>
                ))}
              </div>
            ) : (
              <div
                className="vsSubtitleList custom-scrollbar"
                ref={listRef}
                onScroll={handleListScroll}
              >
                {cues.map((cue, index) => {
                  const isMatch = matchSet.has(index);
                  const matchState: 0 | 1 | 2 =
                    currentMatchIndex === index ? 2 : isMatch ? 1 : 0;
                  return (
                    <CueRow
                      key={index}
                      index={index}
                      cue={cue}
                      active={activeIndex === index}
                      matchState={matchState}
                      seekable={hasMedia}
                      showTime={showTime}
                      fontSize={fontSize}
                      query={query}
                      langView={langView}
                      isEditing={editingIndex === index}
                      onSeek={handleSeek}
                      onStartEdit={(idx) => setEditingIndex(idx)}
                      onSaveEdit={handleSaveCueEdit}
                      onCancelEdit={() => setEditingIndex(null)}
                      register={registerRow}
                    />
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
