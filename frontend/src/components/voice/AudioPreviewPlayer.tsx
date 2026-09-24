import React, { useEffect, useRef, useState } from "react";
import { Play, Pause, Trash2, Volume2, VolumeX, RotateCcw, FileAudio } from "lucide-react";
import { useI18n } from "../../i18n";

type AudioPreviewPlayerProps = {
  file: File;
  onRemove?: () => void;
  onReplace?: () => void;
  title?: string;
  className?: string;
};

function formatTime(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) return "00:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export const AudioPreviewPlayer: React.FC<AudioPreviewPlayerProps> = ({
  file,
  onRemove,
  onReplace,
  title,
  className = "",
}) => {
  const { t } = useI18n();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string>("");

  useEffect(() => {
    let url = "";
    try {
      url = URL.createObjectURL(file);
      setAudioUrl(url);
      setIsPlaying(false);
      setCurrentTime(0);
      setDuration(0);
    } catch {
      // Ignore if createObjectURL not supported
    }

    return () => {
      if (url) {
        URL.revokeObjectURL(url);
      }
    };
  }, [file]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      try {
        const playPromise = audio.play();
        if (playPromise && typeof playPromise.catch === "function") {
          playPromise.catch(() => {
            setIsPlaying(false);
          });
        }
      } catch {
        setIsPlaying(false);
      }
    }
  };

  const handleTimeUpdate = () => {
    const audio = audioRef.current;
    if (audio) {
      setCurrentTime(audio.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    const audio = audioRef.current;
    if (audio && !isNaN(audio.duration) && isFinite(audio.duration)) {
      setDuration(audio.duration);
    }
  };

  const handleEnded = () => {
    setIsPlaying(false);
    setCurrentTime(0);
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const targetTime = Number(e.target.value);
    const audio = audioRef.current;
    if (audio) {
      audio.currentTime = targetTime;
      setCurrentTime(targetTime);
    }
  };

  const toggleMute = () => {
    const audio = audioRef.current;
    if (audio) {
      audio.muted = !isMuted;
      setIsMuted(!isMuted);
    }
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;
  const isVideo = file.type.startsWith("video/");
  const fileExt = file.name.split(".").pop()?.toUpperCase() || (isVideo ? "VIDEO" : "AUDIO");

  return (
    <div className={`vsAudioPreviewCard ${className}`}>
      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={handleEnded}
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          preload="metadata"
        />
      )}

      <div className="vsAudioPreviewTop">
        <div className="vsAudioPreviewFileInfo">
          <div className="vsAudioPreviewIcon">
            <FileAudio size={20} strokeWidth={2} />
          </div>
          <div className="vsAudioPreviewMeta">
            <div className="vsAudioPreviewName" title={file.name}>
              {title || file.name}
            </div>
            <div className="vsAudioPreviewBadges">
              <span className="vsAudioPreviewBadge format">{fileExt}</span>
              <span className="vsAudioPreviewBadge size">{formatFileSize(file.size)}</span>
              {duration > 0 && (
                <span className="vsAudioPreviewBadge duration">
                  ⏱️ {formatTime(duration)}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="vsAudioPreviewActions">
          {onReplace && (
            <button
              type="button"
              className="vsAudioPreviewBtn replace"
              onClick={onReplace}
              title={t("重新录制 / 更换", "Re-record / Replace")}
            >
              <RotateCcw size={14} />
              <span>{t("重选 / 重录", "Retake")}</span>
            </button>
          )}
          {onRemove && (
            <button
              type="button"
              className="vsAudioPreviewBtn remove"
              onClick={onRemove}
              title={t("移除音频", "Remove audio")}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="vsAudioPreviewControls">
        <button
          type="button"
          className={`vsAudioPreviewPlayBtn ${isPlaying ? "playing" : ""}`}
          onClick={togglePlay}
          aria-label={isPlaying ? t("暂停试听", "Pause preview") : t("试听样本", "Play preview")}
        >
          {isPlaying ? <Pause size={18} /> : <Play size={18} style={{ marginLeft: 2 }} />}
        </button>

        <div className="vsAudioPreviewScrubber">
          <input
            type="range"
            min={0}
            max={duration || 100}
            step={0.05}
            value={currentTime}
            onChange={handleSeek}
            disabled={duration === 0}
            className="vsAudioRangeSlider"
            style={{ "--seek-percent": `${progressPercent}%` } as React.CSSProperties}
            aria-label={t("播放进度", "Playback progress")}
          />
          <div className="vsAudioPreviewTimes">
            <span className="current">{formatTime(currentTime)}</span>
            <span className="divider">/</span>
            <span className="total">{formatTime(duration)}</span>
          </div>
        </div>

        <button
          type="button"
          className="vsAudioPreviewMuteBtn"
          onClick={toggleMute}
          title={isMuted ? t("取消静音", "Unmute") : t("静音", "Mute")}
        >
          {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>
      </div>
    </div>
  );
};
