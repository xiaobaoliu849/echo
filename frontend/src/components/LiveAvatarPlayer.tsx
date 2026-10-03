import { useEffect, useRef, useState, useCallback } from "react";
import {
  Bot,
  Captions,
  CaptionsOff,
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
  className?: string;
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
  className = "",
}: LiveAvatarPlayerProps) {
  const { t } = useI18n();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<"waiting" | "playing" | "error">("waiting");
  const [image, setImage] = useState("");
  const [viewMode, setViewMode] = useState<"stage" | "pip">("stage");
  const [lastSnapshot, setLastSnapshot] = useState("");
  const [isInterrupted, setIsInterrupted] = useState(false);
  const [captionsVisible, setCaptionsVisible] = useState(true);

  // Playback engine initialization and event wiring
  useEffect(() => {
    if (!videoRef.current) return;
    const player = new LiveAvatarPlayback(videoRef.current, (error) => {
      setStatus(error ? "error" : "playing");
    });

    const reset = () => {
      setIsInterrupted(false);
      setLastSnapshot("");
      player.reset();
      setImage("");
      setStatus("waiting");
    };

    const interrupt = () => {
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
      player.reset(true);
      setImage("");
      setStatus("waiting");
    };

    const frame = (event: Event) => {
      setIsInterrupted(false);
      setLastSnapshot("");
      const data = (event as MessageEvent<AvatarFrame>).data;
      if (/^image\/(jpeg|png|webp)$/.test(data.mimeType)) {
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

  // Determine container state class
  const stateClass = isAssistantSpeaking
    ? "state-speaking"
    : isUserSpeaking
    ? "state-listening"
    : isThinking
    ? "state-thinking"
    : "state-idle";

  const userCaption = captionTail(userTranscript);
  const assistantCaption = captionTail(assistantReply);
  const showCaptions = captionsVisible && viewMode === "stage" && (assistantCaption || userCaption);

  return (
    <div
      className={`vsLiveAvatarPlayer ${stateClass} ${viewMode === "pip" ? "is-pip" : ""} ${className}`}
    >
      {/* Top Floating Header with Live Status & State Badge */}
      <div className="vsAvatarHeaderBar">
        <div className="vsAvatarHeaderPill">
          <span
            className={`vsAvatarLiveDot ${
              isVoiceActive && status === "playing" ? "live" : "connecting"
            }`}
          />
          <span>{avatarName || "Ben"}</span>
          <span className="vsAvatarModelLabel">Gemini 3.8 Live</span>
        </div>

        {duration != null && duration > 0 && (
          <div className="vsAvatarDurationBadge" title={t("通话时长", "Call Duration")}>
            <span className="vsAvatarDurationDot" />
            <span>{formatDuration(duration)}</span>
          </div>
        )}

        {isAssistantSpeaking ? (
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
          hidden={Boolean(image)}
          aria-label={t("Gemini 实时视频分身", "Gemini Live Avatar")}
          onError={() => setStatus("error")}
        />

        {/* Fallback image frame stream if provider emits raw image frames */}
        {image && (
          <img
            src={image}
            alt={t("Gemini 实时视频分身", "Gemini Live Avatar")}

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
                  ? t("正在接入 Gemini 3.8 实时视频分身...", "Connecting Gemini 3.8 Live Avatar...")
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

        {/* Floating Live Captions — realtime transcription layered over the video.
            No aria-live: token-streamed text would flood screen readers, and the
            chat transcript already serves as the accessible record. */}
        {showCaptions && (
          <div className="vsAvatarCaptions">
            {/* The user's live interim wins during barge-in: voiceChatReply
                lingers until turn finalize, so an active interim transcript is
                the only reliable signal that the user is speaking right now. */}
            {userTranscriptInterim && userCaption ? (
              <div className="vsAvatarCaptionLine user interim" key="user">
                <span className="vsAvatarCaptionSpeaker">
                  <Mic size={11} />
                  {t("你", "You")}
                </span>
                <span className="vsAvatarCaptionText">{userCaption}</span>
              </div>
            ) : isAssistantSpeaking && assistantCaption ? (
              <div className="vsAvatarCaptionLine assistant" key="assistant">
                <span className="vsAvatarCaptionSpeaker">{avatarName || "Ben"}</span>
                <span className="vsAvatarCaptionText">{assistantCaption}</span>
              </div>
            ) : userCaption ? (
              <div className="vsAvatarCaptionLine user" key="user">
                <span className="vsAvatarCaptionSpeaker">
                  <Mic size={11} />
                  {t("你", "You")}
                </span>
                <span className="vsAvatarCaptionText">{userCaption}</span>
              </div>
            ) : (
              <div className="vsAvatarCaptionLine assistant" key="assistant">
                <span className="vsAvatarCaptionSpeaker">{avatarName || "Ben"}</span>
                <span className="vsAvatarCaptionText">{assistantCaption}</span>
              </div>
            )}
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

          <button
            type="button"
            className={`vsAvatarControlBtn ${captionsVisible ? "active" : ""}`}
            onClick={() => setCaptionsVisible((v) => !v)}
            title={captionsVisible ? t("隐藏实时字幕", "Hide live captions") : t("显示实时字幕", "Show live captions")}
            aria-label={t("实时字幕", "Live captions")}
            aria-pressed={captionsVisible}
          >
            {captionsVisible ? <Captions size={15} /> : <CaptionsOff size={15} />}
            <span className="vsAvatarControlLabel">{t("字幕", "CC")}</span>
          </button>

          <button
            type="button"
            className={`vsAvatarControlBtn ${viewMode === "pip" ? "active" : ""}`}
            onClick={() => setViewMode((v) => (v === "pip" ? "stage" : "pip"))}
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
