import { useEffect, useRef, useState, useCallback, type CSSProperties, type ReactNode } from "react";
import {
  Bot,
  Captions,
  CaptionsOff,
  GripHorizontal,
  Maximize2,
  Mic,
  MicOff,
  Minimize2,
  PhoneOff,
  Play,
  Sparkles,
  Volume2,
} from "lucide-react";
import { useI18n } from "../i18n";
import { LiveAvatarPlayback, type AvatarFrame } from "../utils/liveAvatarPlayback";
import { useFloatingAvatar } from "../hooks/useFloatingAvatar";

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

/** Show only the newest tail of a long streaming reply as a caption. */
function captionTail(text: string, max = 220): string {
  const clean = text.trim();
  // Cut on code-point boundaries so emoji/CJK-ext never split into U+FFFD.
  const chars = Array.from(clean);
  return chars.length > max ? `…${chars.slice(-max).join("")}` : clean;
}

export interface LiveAvatarPlayerProps {
  stream: EventTarget;
  avatarName?: string;
  isVoiceActive?: boolean;
  isUserSpeaking?: boolean;
  isAssistantSpeaking?: boolean;
  isThinking?: boolean;
  isMuted?: boolean;
  duration?: number;
  onToggleMute?: () => void;
  onEndCall?: () => void;
  /** Live caption feeds (already streamed by the realtime session). */
  userTranscript?: string;
  userTranscriptInterim?: boolean;
  assistantReply?: string;
  viewMode?: "stage" | "pip";
  onViewModeChange?: (mode: "stage" | "pip") => void;
  captionsEnabled?: boolean;
  showCaptionControl?: boolean;
  className?: string;
  /** Extra call controls (e.g. screen sharing) rendered in the floating control bar. */
  extraControls?: ReactNode;
  /** Reports the rendered portrait width so the page can size its column to the stage. */
  onStageWidthChange?: (width: number | null) => void;
}

export default function LiveAvatarPlayer({
  stream,
  avatarName = "Ben",
  isVoiceActive = false,
  isUserSpeaking = false,
  isAssistantSpeaking = false,
  isThinking = false,
  isMuted = false,
  duration,
  onToggleMute,
  onEndCall,
  userTranscript = "",
  userTranscriptInterim = false,
  assistantReply = "",
  viewMode: controlledViewMode,
  onViewModeChange,
  captionsEnabled = true,
  showCaptionControl = true,
  className = "",
  extraControls,
  onStageWidthChange,
}: LiveAvatarPlayerProps) {
  const { t } = useI18n();
  const videoRef = useRef<HTMLVideoElement>(null);
  const captionRef = useRef<HTMLSpanElement>(null);
  const [status, setStatus] = useState<"waiting" | "playing" | "error">("waiting");
  const [image, setImage] = useState("");
  const [localViewMode, setLocalViewMode] = useState<"stage" | "pip">("stage");
  const viewMode = controlledViewMode ?? localViewMode;
  const floating = useFloatingAvatar(viewMode === "pip");
  const [aspectRatio, setAspectRatio] = useState(9 / 16);
  const [stageHeight, setStageHeight] = useState<number | null>(null);
  const [lastCaption, setLastCaption] = useState<{ text: string; user: boolean; interim: boolean } | null>(null);
  const [lastSnapshot, setLastSnapshot] = useState("");
  const [isInterrupted, setIsInterrupted] = useState(false);
  const [isAvatarPlaying, setIsAvatarPlaying] = useState(false);
  const [captionsVisible, setCaptionsVisible] = useState(true);

  useEffect(() => {
    const player = floating.ref.current;
    const pane = player?.closest<HTMLElement>(".vsAvatarMediaPane");
    if (!player || !pane || viewMode === "pip" || typeof ResizeObserver === "undefined") return;
    const controls = player.querySelector<HTMLElement>(".vsAvatarControlsBar");
    const fitStage = () => {
      // Only the pane and controls determine portrait size, never transcript lines.
      const controlsHeight = (controls?.offsetHeight ?? 52) + 16;
      setStageHeight(Math.max(80, Math.floor(pane.clientHeight - controlsHeight)));
    };
    const observer = new ResizeObserver(fitStage);
    observer.observe(pane);
    if (controls) observer.observe(controls);
    fitStage();
    return () => observer.disconnect();
  }, [viewMode, floating.ref]);

  // Width comes from height and aspect only, so reporting it cannot feed back into fitStage.
  const stageWidthCallback = useRef(onStageWidthChange);
  stageWidthCallback.current = onStageWidthChange;
  const reportedStageWidth = viewMode !== "pip" && stageHeight != null ? Math.round(stageHeight * aspectRatio) : null;
  useEffect(() => {
    stageWidthCallback.current?.(reportedStageWidth);
  }, [reportedStageWidth]);
  useEffect(() => () => stageWidthCallback.current?.(null), []);


  // Playback engine initialization and event wiring
  useEffect(() => {
    if (!videoRef.current) return;
    setIsAvatarPlaying(false);
    const player = new LiveAvatarPlayback(videoRef.current, (error) => {
      if (error) setIsAvatarPlaying(false);
      setStatus(error ? "error" : "playing");
    });

    const reset = () => {
      setIsAvatarPlaying(false);
      setIsInterrupted(false);
      setLastSnapshot("");
      setLastCaption(null);
      player.reset();
      setImage("");
      setStatus("waiting");
    };

    const interrupt = () => {
      setIsAvatarPlaying(false);
      // Capture the current frame into canvas so the video avatar doesn't flash black
      try {
        if (videoRef.current && videoRef.current.videoWidth > 0) {
          const canvas = document.createElement("canvas");
          canvas.width = videoRef.current.videoWidth;
          canvas.height = videoRef.current.videoHeight;
          const ctx = canvas.getContext("2d");
          if (ctx) {
            ctx.drawImage(videoRef.current, 0, 0);
            setLastSnapshot(canvas.toDataURL("image/jpeg", 0.85));
          }
        }
      } catch {
        // Ignore canvas export failures (e.g. cross-origin/empty frames)
      }
      setIsInterrupted(true);
      setLastCaption(null);
      player.reset(true);
      setImage("");
      setStatus("waiting");
    };

    const frame = (event: Event) => {
      setIsInterrupted(false);
      setLastSnapshot("");
      const data = (event as MessageEvent<AvatarFrame>).data;
      if (/^image\/(jpeg|png|webp)$/.test(data.mimeType)) {
        setIsAvatarPlaying(false);
        setImage(`data:${data.mimeType};base64,${data.data}`);
        setStatus("playing");
      } else {
        setImage("");
        player.append(data);
      }
    };

    stream.addEventListener("frame", frame);
    stream.addEventListener("reset", reset);
    stream.addEventListener("interrupt", interrupt);

    return () => {
      stream.removeEventListener("frame", frame);
      stream.removeEventListener("reset", reset);
      stream.removeEventListener("interrupt", interrupt);
      player.reset();
    };
  }, [stream]);

  const handleRecoverPlay = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.play().then(() => {
        setStatus("playing");
      }).catch(() => {
        setStatus("error");
      });
    }
  }, []);

  // Avatar MP4 carries its own speech track; the separate PCM flag can stay false.
  // Follow rendered playback, not frame arrival or server turn completion.
  const assistantSpeaking = isAssistantSpeaking || (isVoiceActive && isAvatarPlaying);
  const stateClass = assistantSpeaking
    ? "state-speaking"
    : isUserSpeaking
    ? "state-listening"
    : isThinking
    ? "state-thinking"
    : "state-idle";

  const userCaption = captionTail(userTranscript);
  const assistantCaption = captionTail(assistantReply);
  const activeCaption = (userTranscriptInterim || isUserSpeaking) && userCaption
    ? { text: userCaption, user: true, interim: userTranscriptInterim }
    : assistantCaption
    ? { text: assistantCaption, user: false, interim: false }
    : userCaption ? { text: userCaption, user: true, interim: userTranscriptInterim } : null;
  const caption = activeCaption ?? lastCaption;
  useEffect(() => {
    if (activeCaption) setLastCaption(activeCaption);
  }, [userCaption, assistantCaption, userTranscriptInterim, isUserSpeaking]);
  const showCaptions = captionsEnabled && captionsVisible && caption;
  const compactStage = viewMode !== "pip" && stageHeight != null && stageHeight < 320;
  useEffect(() => {
    const text = captionRef.current;
    if (text) text.scrollTop = text.scrollHeight;
  }, [caption?.text, captionsEnabled, captionsVisible]);

  return (
    <div
      ref={floating.ref}
      popover={viewMode === "pip" ? "manual" : undefined}
      style={{ ...floating.style, "--avatar-aspect": aspectRatio,
        ...(stageHeight != null ? { "--avatar-video-height": `${stageHeight}px` } : {}) } as CSSProperties}
      {...floating.pointerProps}
      className={`vsLiveAvatarPlayer ${stateClass} ${viewMode === "pip" ? "is-pip" : ""} ${compactStage ? "is-compact-stage" : ""} ${className}`}
    >
      {/* Top Floating Header with Live Status & State Badge */}
      <div className="vsAvatarHeaderBar">
        <div className="vsAvatarHeaderPill" title={avatarName || "Ben"}>
          <span
            className={`vsAvatarLiveDot ${
              isVoiceActive && status === "playing" ? "live" : "connecting"
            }`}
          />
          <span>{avatarName || "Ben"}</span>
          <span className="vsAvatarModelLabel">Gemini 3.8 Live</span>
          {duration != null && duration > 0 && (
            <span className="vsAvatarDurationBadge" title={t("通话时长", "Call Duration")}>{formatDuration(duration)}</span>
          )}
        </div>
        {viewMode === "pip" && (
          <button type="button" className="vsAvatarDragHandle" onKeyDown={floating.onKeyDown}
            aria-label={t("移动分身窗口", "Move avatar window")}
            title={t("拖动移动，或用方向键调整位置", "Drag to move, or use arrow keys")}>
            <GripHorizontal size={18} />
          </button>
        )}


        {assistantSpeaking ? (
          <div className="vsAvatarStateChip speaking">
            <span className="vsAvatarAudioBars">
              <span className="vsAvatarAudioBar" />
              <span className="vsAvatarAudioBar" />
              <span className="vsAvatarAudioBar" />
              <span className="vsAvatarAudioBar" />
            </span>
            <span>{t("正在说话", "Speaking")}</span>
          </div>
        ) : isUserSpeaking ? (
          <div className="vsAvatarStateChip listening">
            <Mic size={12} />
            <span>{t("正在聆听", "Listening")}</span>
          </div>
        ) : isThinking ? (
          <div className="vsAvatarStateChip thinking">
            <Sparkles size={12} />
            <span>{t("正在思考", "Thinking...")}</span>
          </div>
        ) : isInterrupted ? (
          <div className="vsAvatarStateChip listening">
            <Mic size={12} />
            <span>{t("已打断 · 聆听中", "Interrupted · Listening")}</span>
          </div>
        ) : (
          <div className="vsAvatarStateChip connecting">
            <span>
              {status === "playing"
                ? t("在线就绪", "Ready")
                : t("连接中...", "Connecting...")}
            </span>
          </div>
        )}
      </div>

      {/* Main Video Presentation Stage */}
      <div className="vsAvatarVideoContainer">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          onPlaying={() => setIsAvatarPlaying(true)}
          onWaiting={() => setIsAvatarPlaying(false)}
          onPause={() => setIsAvatarPlaying(false)}
          onEnded={() => setIsAvatarPlaying(false)}
          onEmptied={() => setIsAvatarPlaying(false)}
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            if (video.videoWidth && video.videoHeight) setAspectRatio(video.videoWidth / video.videoHeight);
          }}
          hidden={Boolean(image)}
          aria-label={t("Gemini 实时视频分身", "Gemini Live Avatar")}
          onError={() => {
            setIsAvatarPlaying(false);
            setStatus("error");
          }}
        />

        {/* Fallback image frame stream if provider emits raw image frames */}
        {image && (
          <img
            src={image}
            alt={t("Gemini 实时视频分身", "Gemini Live Avatar")}
            draggable={false}
            onLoad={(event) => {
              const img = event.currentTarget;
              if (img.naturalWidth && img.naturalHeight) setAspectRatio(img.naturalWidth / img.naturalHeight);
            }}
          />
        )}

        {/* Interruption snapshot overlay: gracefully prevents black flicker */}
        {lastSnapshot && !image && status !== "playing" && (
          <img src={lastSnapshot} className="vsAvatarSnapshotOverlay" alt="" />
        )}

        {/* Connecting / Idle Stage Placeholder */}
        {status === "waiting" && !image && !lastSnapshot && (
          <div className="vsAvatarConnectingStage">
            <div className="vsAvatarConnectingIconWrap">
              <div className="vsAvatarConnectingRing" />
              <Bot size={32} />
            </div>
            <div>
              <div className="vsAvatarConnectingText">
                {isVoiceActive
                  ? t("正在连接分身…", "Connecting avatar…")
                  : t("分身舞台待命中", "Avatar Stage Standby")}
              </div>
              <div className="vsAvatarConnectingSubtext">
                {isVoiceActive
                  ? t("分身回复时，视频将在此显示", "Video will appear when the avatar responds")
                  : t("点击下方通话按钮，即可与分身进行实时视频对话", "Click the call button below to start video chat")}
              </div>
            </div>
          </div>
        )}

        {/* Autoplay Recovery Overlay if browser policy blocks video */}
        {status === "error" && (
          <div className="vsAvatarAutoplayOverlay">
            <Volume2 size={32} color="#60a5fa" />
            <div style={{ color: "#f8fafc", fontSize: 13, fontWeight: 500 }}>
              {t("音视频暂时无法播放", "Playback needs attention")}
            </div>
            <button
              type="button"
              className="vsAvatarAutoplayBtn"
              onClick={handleRecoverPlay}
            >
              <Play size={14} fill="currentColor" />
              <span>{t("点击开启音视频", "Click to enable playback")}</span>
            </button>
          </div>
        )}

      </div>
        {/* Live captions use a single area below the portrait.
            No aria-live: token-streamed text would flood screen readers, and the
            chat transcript already serves as the accessible record. */}
        {showCaptions && (
          <div className="vsAvatarCaptions">
            {/* The user's live interim wins during barge-in: voiceChatReply
                lingers until turn finalize, so an active interim transcript is
                the only reliable signal that the user is speaking right now. */}
            <div className={`vsAvatarCaptionLine ${caption.user ? "user" : "assistant"} ${caption.interim ? "interim" : ""}`}>
              <span className="vsAvatarCaptionSpeaker">
                {caption.user ? t("你", "You") : avatarName || "Ben"}
              </span>
              <span ref={captionRef} className="vsAvatarCaptionText" tabIndex={0}
                aria-label={t("实时转写", "Live transcript")}>{caption.text}</span>
            </div>
          </div>
        )}

        {/* Floating Bottom Control Bar */}
        <div className="vsAvatarControlsBar">
          {onToggleMute && isVoiceActive && (
            <button
              type="button"
              className={`vsAvatarControlBtn ${isMuted ? "active danger" : ""}`}
              onClick={onToggleMute}
              title={isMuted ? t("取消静音 (M)", "Unmute (M)") : t("静音麦克风 (M)", "Mute mic (M)")}
            >
              {isMuted ? <MicOff size={15} /> : <Mic size={15} />}
              <span className="vsAvatarControlLabel">{isMuted ? t("已静音", "Muted") : t("静音", "Mute")}</span>
            </button>
          )}

          {extraControls}

          {showCaptionControl && <button
            type="button"
            className={`vsAvatarControlBtn ${captionsVisible ? "active" : ""}`}
            disabled={!captionsEnabled}
            aria-pressed={captionsVisible && captionsEnabled}
            onClick={() => setCaptionsVisible((v) => !v)}
            title={!captionsEnabled ? t("字幕显示在对话记录中", "Captions are shown in conversation history") : captionsVisible ? t("隐藏实时字幕", "Hide live captions") : t("显示实时字幕", "Show live captions")}
            aria-label={t("实时字幕", "Live captions")}
          >
            {captionsVisible ? <Captions size={15} /> : <CaptionsOff size={15} />}
            <span className="vsAvatarControlLabel">{t("字幕", "CC")}</span>
          </button>}

          <button
            type="button"
            className={`vsAvatarControlBtn ${viewMode === "pip" ? "active" : ""}`}
            onClick={() => {
              const next = viewMode === "pip" ? "stage" : "pip";
              setLocalViewMode(next);
              onViewModeChange?.(next);
            }}
            title={viewMode === "pip" ? t("还原舞台", "Restore stage") : t("画中画悬浮", "Picture in picture")}
          >
            {viewMode === "pip" ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            <span className="vsAvatarControlLabel">
              {viewMode === "pip" ? t("还原", "Restore") : t("画中画", "PiP")}
            </span>
          </button>

          {onEndCall && isVoiceActive && (
            <button
              type="button"
              className="vsAvatarControlBtn danger"
              onClick={onEndCall}
              title={t("挂断实时通话", "Hang up call")}
            >
              <PhoneOff size={15} />
              <span className="vsAvatarControlLabel">{t("挂断", "Hang up")}</span>
            </button>
          )}
        </div>
      {/* Hidden status text for backwards-compatible test assertions */}
      {status !== "playing" && (
        <p role="status" style={{ display: "none" }}>
          {status === "error"
            ? t(
                "请点击播放；如果仍无法播放，请使用支持 MP4 流的桌面环境或浏览器。",
                "Click Play. If playback still fails, use a desktop runtime or browser supporting MP4 streaming."
              )
            : t("通话开始后，分身视频会显示在这里。", "Avatar video will appear here when the conversation starts.")}
        </p>
      )}
    </div>
  );
}
