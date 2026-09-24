import React, { useEffect, useRef, useState, useCallback } from "react";
import { Mic, MicOff, Square, Pause, Play, RefreshCw, Volume2, Sparkles, BookOpen, ChevronRight, Check } from "lucide-react";
import { useI18n } from "../../i18n";
import { AudioPreviewPlayer } from "./AudioPreviewPlayer";

type VoiceRecorderProps = {
  onRecordingComplete: (file: File) => void;
  onDiscard?: () => void;
  currentFile?: File | null;
  disabled?: boolean;
};

type RecordingState = "idle" | "recording" | "paused" | "completed";

const SAMPLE_SCRIPTS = [
  {
    category: "日常叙事",
    categoryEn: "Daily Narrative",
    text: "清晨的阳光透过树叶洒在窗台，微风带来泥土与青草的气息。生活中的美好，往往就藏在这些安静而温暖的日常片段里。",
  },
  {
    category: "自然诗意",
    categoryEn: "Poetic & Gentle",
    text: "海浪轻柔地拍打着礁石，激起层层白色的浪花。远方的地平线上，夕阳将整片天空染成了温柔的橘红与淡紫。",
  },
  {
    category: "科技未来",
    categoryEn: "Tech & Vision",
    text: "人工智能正在重塑人与世界的连接方式。声音不仅是沟通的桥梁，更是情感与灵魂独特的数字化印记。",
  },
  {
    category: "English Standard",
    categoryEn: "English Standard",
    text: "The quick brown fox jumps over the lazy dog. A wonderful journey of voice cloning brings digital characters to life with warmth and authenticity.",
  },
  {
    category: "Google 授权声明",
    categoryEn: "Google Consent Phrase",
    text: "I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model.",
  },
];

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export const VoiceRecorder: React.FC<VoiceRecorderProps> = ({
  onRecordingComplete,
  onDiscard,
  currentFile,
  disabled = false,
}) => {
  const { t, language } = useI18n();

  const [recordingState, setRecordingState] = useState<RecordingState>(
    currentFile ? "completed" : "idle"
  );
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [activeScriptIndex, setActiveScriptIndex] = useState(0);
  const [copiedScript, setCopiedScript] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerIntervalRef = useRef<number | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Sync state if currentFile changes externally
  useEffect(() => {
    if (currentFile && recordingState === "idle") {
      setRecordingState("completed");
    } else if (!currentFile && recordingState === "completed") {
      setRecordingState("idle");
      setElapsedSeconds(0);
    }
  }, [currentFile, recordingState]);

  const isMountedRef = useRef(true);
  const isDiscardedRef = useRef(false);

  // Clean up resources on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      isDiscardedRef.current = true;
      cleanupMedia();
    };
  }, []);

  const cleanupMedia = useCallback(() => {
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      try {
        mediaRecorderRef.current.stop();
      } catch {
        // ignore
      }
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      try {
        audioContextRef.current.close();
      } catch {
        // ignore
      }
      audioContextRef.current = null;
    }
  }, []);

  // Visualizer loop
  const drawWaveform = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const analyser = analyserRef.current;
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width <= 0 || height <= 0) return;

    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
    }

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const drawBar = (x: number, y: number, w: number, h: number, r: number) => {
      ctx.beginPath();
      if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, w, h, r);
      } else {
        ctx.rect(x, y, w, h);
      }
      ctx.fill();
    };

    const barCount = 42;
    const barWidth = 3;
    const gap = (width - barCount * barWidth) / (barCount - 1);
    const centerY = height / 2;

    if (analyser && recordingState === "recording") {
      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      analyser.getByteFrequencyData(dataArray);

      for (let i = 0; i < barCount; i++) {
        // Sample frequency distribution
        const binIndex = Math.floor((i / barCount) * (bufferLength * 0.65));
        const value = dataArray[binIndex] || 0;
        const percent = Math.min(1, Math.max(0.08, value / 255));
        const barHeight = Math.max(4, percent * (height * 0.85));

        const x = i * (barWidth + gap);
        const y = centerY - barHeight / 2;

        // Gradient from brand teal to vibrant cyan/emerald
        const gradient = ctx.createLinearGradient(0, y, 0, y + barHeight);
        gradient.addColorStop(0, "rgba(56, 189, 248, 0.95)");
        gradient.addColorStop(0.5, "rgba(16, 185, 129, 0.9)");
        gradient.addColorStop(1, "rgba(56, 189, 248, 0.7)");

        ctx.fillStyle = gradient;
        drawBar(x, y, barWidth, barHeight, 2);
      }
    } else {
      // Idle / paused subtle breathing wave
      const time = Date.now() * 0.003;
      for (let i = 0; i < barCount; i++) {
        const offset = Math.sin(time + i * 0.25) * 0.5 + 0.5;
        const barHeight = Math.max(4, offset * 14 + 4);
        const x = i * (barWidth + gap);
        const y = centerY - barHeight / 2;

        ctx.fillStyle = "rgba(16, 185, 129, 0.25)";
        drawBar(x, y, barWidth, barHeight, 2);
      }
    }

    ctx.restore();

    if (recordingState === "recording" || recordingState === "idle" || recordingState === "paused") {
      animationFrameRef.current = requestAnimationFrame(drawWaveform);
    }
  }, [recordingState]);

  useEffect(() => {
    if (recordingState !== "completed") {
      animationFrameRef.current = requestAnimationFrame(drawWaveform);
    }
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [drawWaveform, recordingState]);

  const startRecording = async () => {
    isDiscardedRef.current = false;
    setErrorMessage("");
    audioChunksRef.current = [];

    if (!navigator.mediaDevices?.getUserMedia) {
      setErrorMessage(
        t(
          "当前浏览器或系统环境不支持录音功能，请使用文件上传模式。",
          "Audio recording is not supported in this browser. Please use file upload."
        )
      );
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      if (!isMountedRef.current || isDiscardedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      mediaStreamRef.current = stream;

      // Setup Web Audio Analyser
      const AudioContextClass =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioContextClass) {
        try {
          const audioCtx = new AudioContextClass();
          const source = audioCtx.createMediaStreamSource(stream);
          const analyser = audioCtx.createAnalyser();
          analyser.fftSize = 128;
          source.connect(analyser);
          audioContextRef.current = audioCtx;
          analyserRef.current = analyser;
        } catch {
          // Analyser setup optional, continue recording
        }
      }

      // Check supported MIME type
      const mimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
        "audio/mp4",
        "audio/wav",
      ];
      let selectedMime = "";
      if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported) {
        for (const type of mimeTypes) {
          if (MediaRecorder.isTypeSupported(type)) {
            selectedMime = type;
            break;
          }
        }
      }

      const recorder = selectedMime
        ? new MediaRecorder(stream, { mimeType: selectedMime })
        : new MediaRecorder(stream);

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        if (!isMountedRef.current || isDiscardedRef.current) {
          audioChunksRef.current = [];
          return;
        }

        const mimeType = recorder.mimeType || "audio/webm";
        const blob = new Blob(audioChunksRef.current, { type: mimeType });
        const ext = mimeType.includes("wav")
          ? "wav"
          : mimeType.includes("ogg")
          ? "ogg"
          : mimeType.includes("mp4")
          ? "mp4"
          : "webm";
        const timestamp = new Date()
          .toISOString()
          .replace(/[-:T]/g, "")
          .slice(0, 14);
        const fileName = `voice_record_${timestamp}.${ext}`;
        const file = new File([blob], fileName, { type: mimeType.split(";")[0] });

        setRecordingState("completed");
        cleanupMedia();
        onRecordingComplete(file);
      };

      recorder.start(100);
      mediaRecorderRef.current = recorder;
      setRecordingState("recording");
      setElapsedSeconds(0);

      // Start elapsed timer
      timerIntervalRef.current = window.setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } catch (err: unknown) {
      const errStr = String(err);
      if (errStr.includes("NotAllowedError") || errStr.includes("Permission")) {
        setErrorMessage(
          t(
            "麦克风权限被拒绝，请在系统或浏览器设置中允许访问麦克风。",
            "Microphone permission was denied. Please allow microphone access."
          )
        );
      } else {
        setErrorMessage(
          t("启动麦克风录音失败，请检查音频输入设备。", "Failed to start recording. Please check your microphone.")
        );
      }
      cleanupMedia();
      setRecordingState("idle");
    }
  };

  const pauseRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
      mediaRecorderRef.current.pause();
      if (timerIntervalRef.current) {
        clearInterval(timerIntervalRef.current);
        timerIntervalRef.current = null;
      }
      setRecordingState("paused");
    }
  };

  const resumeRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "paused") {
      mediaRecorderRef.current.resume();
      timerIntervalRef.current = window.setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
      setRecordingState("recording");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
  };

  const handleRetake = () => {
    isDiscardedRef.current = true;
    cleanupMedia();
    setRecordingState("idle");
    setElapsedSeconds(0);
    setErrorMessage("");
    onDiscard?.();
  };

  const handleNextScript = () => {
    setActiveScriptIndex((prev) => (prev + 1) % SAMPLE_SCRIPTS.length);
    setCopiedScript(false);
  };

  const handleCopyScript = () => {
    const currentScript = SAMPLE_SCRIPTS[activeScriptIndex];
    const textToCopy =
      language === "zh-CN" ? currentScript.text : currentScript.text;
    navigator.clipboard?.writeText(textToCopy);
    setCopiedScript(true);
    setTimeout(() => setCopiedScript(false), 2000);
  };

  // Duration guidance indicators
  const isTooShort = elapsedSeconds > 0 && elapsedSeconds < 10;
  const isOptimal = elapsedSeconds >= 10 && elapsedSeconds <= 30;
  const isSufficient = elapsedSeconds > 30;

  // Active script
  const activeScript = SAMPLE_SCRIPTS[activeScriptIndex];
  const scriptCategory =
    language === "zh-CN" ? activeScript.category : activeScript.categoryEn;

  return (
    <div className="vsVoiceRecorderContainer">
      {errorMessage && (
        <div className="vsRecorderErrorNotice">
          <MicOff size={16} />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Completed State: Audio Preview */}
      {recordingState === "completed" && currentFile ? (
        <div className="vsRecorderSuccessView">
          <div className="vsRecorderSuccessBanner">
            <span className="vsRecorderSuccessDot" />
            <span className="vsRecorderSuccessText">
              {t("录音已完成，请试听检查音质与清晰度", "Recording complete. Preview to verify clarity and quality")}
            </span>
          </div>

          <AudioPreviewPlayer
            file={currentFile}
            title={t("录制的声纹样本", "Recorded Voice Sample")}
            onReplace={handleRetake}
            onRemove={handleRetake}
          />
        </div>
      ) : (
        /* Recording / Idle Console */
        <div className="vsRecorderConsole">
          {/* Top Visualizer Canvas Area */}
          <div className={`vsRecorderWaveWrap ${recordingState}`}>
            <canvas ref={canvasRef} className="vsRecorderCanvas" />

            <div className="vsRecorderStatusOverlay">
              {recordingState === "idle" && (
                <div className="vsRecorderPill idle">
                  <Mic size={14} />
                  <span>{t("点击下方按钮开始录音", "Click below to start recording")}</span>
                </div>
              )}
              {recordingState === "recording" && (
                <div className="vsRecorderPill recording">
                  <span className="vsRecorderPulseDot" />
                  <span>{t("正在录制中...", "Recording...")}</span>
                </div>
              )}
              {recordingState === "paused" && (
                <div className="vsRecorderPill paused">
                  <Pause size={14} />
                  <span>{t("录音已暂停", "Recording paused")}</span>
                </div>
              )}
            </div>

            {/* Timer and Target Guideline */}
            <div className="vsRecorderTimerRow">
              <span className="vsRecorderTimerVal">{formatTime(elapsedSeconds)}</span>

              {recordingState !== "idle" && (
                <div className="vsRecorderGuideline">
                  {isTooShort && (
                    <span className="vsRecorderZone warning">
                      {t("⏱️ 录音偏短 (建议 10~30 秒)", "⏱️ Short (10-30s recommended)")}
                    </span>
                  )}
                  {isOptimal && (
                    <span className="vsRecorderZone optimal">
                      {t("✨ 最佳时长范围，声纹特征充足", "✨ Optimal range, rich voiceprint")}
                    </span>
                  )}
                  {isSufficient && (
                    <span className="vsRecorderZone sufficient">
                      {t("✅ 时长充足", "✅ Sufficient length")}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Controls Bar */}
          <div className="vsRecorderControls">
            {recordingState === "idle" && (
              <button
                type="button"
                className="vsRecorderMainBtn start"
                onClick={startRecording}
                disabled={disabled}
                title={t("开始录制语音", "Start recording")}
              >
                <div className="vsRecorderBtnRing" />
                <Mic size={24} />
                <span>{t("开始录音", "Record")}</span>
              </button>
            )}

            {(recordingState === "recording" || recordingState === "paused") && (
              <div className="vsRecorderActiveButtonGroup">
                {recordingState === "recording" ? (
                  <button
                    type="button"
                    className="vsRecorderSubBtn pause"
                    onClick={pauseRecording}
                    title={t("暂停录音", "Pause recording")}
                  >
                    <Pause size={18} />
                    <span>{t("暂停", "Pause")}</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    className="vsRecorderSubBtn resume"
                    onClick={resumeRecording}
                    title={t("继续录音", "Resume recording")}
                  >
                    <Play size={18} />
                    <span>{t("继续", "Resume")}</span>
                  </button>
                )}

                <button
                  type="button"
                  className="vsRecorderMainBtn stop"
                  onClick={stopRecording}
                  title={t("完成并保存录音", "Finish recording")}
                >
                  <Square size={18} fill="currentColor" />
                  <span>{t("完成录音", "Finish")}</span>
                </button>

                <button
                  type="button"
                  className="vsRecorderSubBtn cancel"
                  onClick={handleRetake}
                  title={t("取消放弃录音", "Discard recording")}
                >
                  <RefreshCw size={16} />
                  <span>{t("重置", "Reset")}</span>
                </button>
              </div>
            )}
          </div>

          {/* Reference Script Prompts Card */}
          <div className="vsRecorderScriptCard">
            <div className="vsRecorderScriptHeader">
              <div className="vsRecorderScriptTitle">
                <BookOpen size={15} />
                <span>{t("💡 朗读示例范本", "💡 Sample Reading Prompts")}</span>
                <span className="vsRecorderScriptTag">{scriptCategory}</span>
              </div>
              <div className="vsRecorderScriptActions">
                <button
                  type="button"
                  className="vsRecorderScriptBtn"
                  onClick={handleNextScript}
                  title={t("切换下一句", "Next prompt")}
                >
                  <Sparkles size={13} />
                  <span>{t("换一句", "Next")}</span>
                </button>
                <button
                  type="button"
                  className="vsRecorderScriptBtn copy"
                  onClick={handleCopyScript}
                  title={t("复制文本", "Copy prompt")}
                >
                  {copiedScript ? <Check size={13} color="#10b981" /> : <ChevronRight size={13} />}
                  <span>{copiedScript ? t("已复制", "Copied") : t("复制", "Copy")}</span>
                </button>
              </div>
            </div>

            <p className="vsRecorderScriptContent">"{activeScript.text}"</p>

            <div className="vsRecorderScriptTips">
              <Volume2 size={13} />
              <span>
                {t(
                  "建议保持稳定语速和适中音量，口齿清晰，尽量减少背景杂音与混响。",
                  "Keep a steady pace, clear pronunciation, and avoid background noise or echo."
                )}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
