import { useEffect, useMemo, useRef, useState } from "react";
import type { WordTimestamp } from "../../api";
import { useI18n } from "../../i18n";
import { buildCues, type SubtitleCue } from "../../utils/subtitleGenerator";

type Props = {
  transcript: string;
  words: WordTimestamp[];
  audioSourceUrl?: string;
  audioDuration: number;
  onAudioDurationChange: (dur: number) => void;
};

function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = safe % 60;
  const mm = m < 10 ? `0${m}` : `${m}`;
  const ss = s < 10 ? `0${s}` : `${s}`;
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/**
 * Classic player + synced subtitles: transport controls on top, the currently
 * spoken line shown large (karaoke-style), and a scrollable transcript below
 * that highlights the active cue, auto-scrolls during playback, and seeks on
 * click. Degrades to a plain scrollable transcript when there is no audio
 * (e.g. realtime mic transcriptions) or no timing data.
 */
export default function TranscriptionSubtitlePlayer({
  transcript,
  words,
  audioSourceUrl,
  audioDuration,
  onAudioDurationChange,
}: Props) {
  const { t } = useI18n();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const cueRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const userScrollingRef = useRef(false);
  const userScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [activeIndex, setActiveIndex] = useState(-1);
  const [isPlaying, setIsPlaying] = useState(false);

  const cues = useMemo<SubtitleCue[]>(
    () => buildCues(transcript, audioDuration, words),
    [transcript, audioDuration, words]
  );

  const handleTimeUpdate = (e: React.SyntheticEvent<HTMLAudioElement>) => {
    const time = (e.target as HTMLAudioElement).currentTime;
    let idx = -1;
    for (let i = 0; i < cues.length; i++) {
      if (time >= cues[i].start) idx = i;
      else break;
    }
    setActiveIndex((prev) => (prev !== idx ? idx : prev));
  };

  // Auto-scroll the active cue into view while playing only when it moves out of view.
  // Suppressed briefly after the user scrolls manually so we don't fight their scroll position.
  useEffect(() => {
    if (!isPlaying || activeIndex < 0 || userScrollingRef.current) return;
    const el = cueRefs.current[activeIndex];
    const container = listRef.current;
    if (el && container) {
      const cRect = container.getBoundingClientRect();
      const eRect = el.getBoundingClientRect();
      // Only trigger smooth scroll if the active cue is outside the visible container area
      if (eRect.top < cRect.top + 30 || eRect.bottom > cRect.bottom - 30) {
        el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    }
  }, [activeIndex, isPlaying]);

  useEffect(() => {
    return () => {
      if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
    };
  }, []);

  function handleListScroll() {
    // Mark the list as user-driven so auto-scroll backs off for a moment.
    userScrollingRef.current = true;
    if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
    userScrollTimerRef.current = setTimeout(() => {
      userScrollingRef.current = false;
    }, 2500);
  }

  function seekTo(start: number) {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = start;
    void audio.play().catch(() => {
      /* autoplay may be blocked; the cue still highlights on manual play */
    });
  }

  const activeCue = activeIndex >= 0 ? cues[activeIndex] : null;

  return (
    <div className="vsSubtitlePlayer">
      {audioSourceUrl && (
        <div className="vsSubtitlePlayerTransport">
          <audio
            ref={audioRef}
            controls
            preload="metadata"
            src={audioSourceUrl}
            aria-label={t("转写音频播放器", "Transcription audio player")}
            controlsList="nodownload"
            onLoadedMetadata={(e) => {
              const d = (e.target as HTMLAudioElement).duration;
              if (d && isFinite(d) && d > 0 && audioDuration === 0) {
                onAudioDurationChange(d);
              }
            }}
            onTimeUpdate={handleTimeUpdate}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            onEnded={() => setIsPlaying(false)}
          />
        </div>
      )}

      {/* Karaoke-style current subtitle line */}
      {audioSourceUrl && (
        <div className="vsSubtitleNow">
          {activeCue ? (
            <span className="vsSubtitleNowText">{activeCue.text}</span>
          ) : (
            <span className="vsSubtitleNowPlaceholder">
              {t("播放音频以同步显示字幕", "Play the audio to sync subtitles")}
            </span>
          )}
        </div>
      )}

      {/* Scrollable, click-to-seek transcript */}
      <div
        className="vsSubtitleList custom-scrollbar"
        ref={listRef}
        onScroll={handleListScroll}
      >
        {cues.map((cue, i) => (
          <button
            key={i}
            type="button"
            ref={(el) => {
              cueRefs.current[i] = el;
            }}
            className={`vsSubtitleCue ${i === activeIndex ? "active" : ""}`}
            onClick={() => seekTo(cue.start)}
            disabled={!audioSourceUrl}
          >
            {audioSourceUrl && (
              <span className="vsSubtitleCueTime">{formatClock(cue.start)}</span>
            )}
            <span className="vsSubtitleCueText">{cue.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
