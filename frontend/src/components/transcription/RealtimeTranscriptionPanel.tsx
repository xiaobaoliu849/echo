import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildRealtimeTranscriptionWebSocketUrl,
  saveTranscriptionText,
  type TranscriptionJobResponse,
  type WordTimestamp,
} from "../../api";
import { REALTIME_ASR_MODELS } from "../../utils/asrProviders";
import { encodePcm16k, getAudioContextCtor } from "../../hooks/useVoiceChatHelpers";
import { exportTextFile } from "../../utils/desktopFileSave";
import { formatSrtTime, formatVttTime } from "../../utils/subtitleGenerator";
import ErrorNotice from "../ErrorNotice";
import { useI18n } from "../../i18n";

type Phase = "idle" | "connecting" | "listening" | "finishing" | "done";

type ViewMode = "transcript" | "timeline" | "banner";

export type SentenceSegment = {
  id: string;
  text: string;
  startSec: number;
  endSec: number;
  words?: WordTimestamp[] | null;
};

type RealtimeServerMessage =
  | { type: "started" }
  | {
      type: "sentence";
      text: string;
      sentence_end: boolean;
      begin_ms?: number | null;
      end_ms?: number | null;
      words?: WordTimestamp[] | null;
    }
  | { type: "finished" }
  | { type: "error"; message?: string };

type Props = {
  onComplete: (job: TranscriptionJobResponse, words?: WordTimestamp[]) => void;
};

const LANGUAGE_OPTIONS: { value: string; hints?: string[]; zh: string; en: string }[] = [
  { value: "auto", zh: "自动检测 (85+ 语种)", en: "Auto detect (85+ languages)" },
  { value: "zh", hints: ["zh"], zh: "中文", en: "Chinese" },
  { value: "en", hints: ["en"], zh: "英文", en: "English" },
  { value: "zh-en", hints: ["zh", "en"], zh: "中英混合", en: "Chinese + English" },
  { value: "ja", hints: ["ja"], zh: "日语", en: "Japanese" },
  { value: "ko", hints: ["ko"], zh: "韩语", en: "Korean" },
  { value: "yue", hints: ["yue"], zh: "粤语", en: "Cantonese" },
];

function isCjk(ch: string): boolean {
  const code = ch.codePointAt(0) ?? 0;
  return (
    (code >= 0x3000 && code <= 0x30ff) ||
    (code >= 0x4e00 && code <= 0x9fff) ||
    (code >= 0xac00 && code <= 0xd7af) ||
    (code >= 0xff00 && code <= 0xffef)
  );
}

/** Join finalized sentences + live interim into one coherent transcript. */
export function joinSegments(parts: string[]): string {
  let out = "";
  for (const raw of parts) {
    const part = raw.trim();
    if (!part) continue;
    if (!out) {
      out = part;
      continue;
    }
    const last = [...out].slice(-1)[0] || "";
    const first = [...part][0] || "";
    const needsSpace = !isCjk(last) && !isCjk(first) && !/\s$/.test(out);
    out += (needsSpace ? " " : "") + part;
  }
  return out;
}

export function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatTimestampDisplay(sec: number): string {
  const minutes = Math.floor(sec / 60);
  const seconds = Math.floor(sec % 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function RealtimeTranscriptionPanel({ onComplete }: Props) {
  const { t } = useI18n();

  const [phase, setPhase] = useState<Phase>("idle");
  const [language, setLanguage] = useState("auto");
  const [model, setModel] = useState(REALTIME_ASR_MODELS[0].id);
  const [viewMode, setViewMode] = useState<ViewMode>("transcript");

  const [segments, setSegments] = useState<SentenceSegment[]>([]);
  const [finalized, setFinalized] = useState<string[]>([]);
  const [interim, setInterim] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [audioLevel, setAudioLevel] = useState(0);

  const [error, setError] = useState<Error | null>(null);
  const [info, setInfo] = useState("");
  const [saving, setSaving] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showCopyMenu, setShowCopyMenu] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const muteGainRef = useRef<GainNode | null>(null);

  const segmentsRef = useRef<SentenceSegment[]>([]);
  const finalizedRef = useRef<string[]>([]);
  const interimRef = useRef("");
  const interimStartSecRef = useRef(0);
  const wordsRef = useRef<WordTimestamp[]>([]);
  const elapsedRef = useRef(0);

  const languageRef = useRef(language);
  const modelRef = useRef(model);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const finishTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const transcriptBoxRef = useRef<HTMLDivElement | null>(null);
  const timelineBoxRef = useRef<HTMLDivElement | null>(null);
  const aliveRef = useRef(true);

  languageRef.current = language;
  modelRef.current = model;
  interimRef.current = interim;
  elapsedRef.current = elapsed;

  const displayTranscript = joinSegments([...finalized, interim]);
  const finalizedText = joinSegments(finalized);
  let interimPart = interim;
  if (finalizedText && interim) {
    const last = [...finalizedText].slice(-1)[0] || "";
    const first = [...interim][0] || "";
    const needsSpace = !isCjk(last) && !isCjk(first) && !/\s$/.test(finalizedText);
    interimPart = (needsSpace ? " " : "") + interim;
  }

  const wordCount = displayTranscript.replace(/\s+/g, "").length;

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startTimer = useCallback(() => {
    stopTimer();
    setElapsed(0);
    elapsedRef.current = 0;
    timerRef.current = setInterval(() => {
      setElapsed((value) => {
        const next = value + 1;
        elapsedRef.current = next;
        return next;
      });
    }, 1000);
  }, [stopTimer]);

  const clearFinishTimeout = useCallback(() => {
    if (finishTimeoutRef.current !== null) {
      clearTimeout(finishTimeoutRef.current);
      finishTimeoutRef.current = null;
    }
  }, []);

  const cleanupAudio = useCallback(() => {
    if (animFrameRef.current !== null) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    setAudioLevel(0);
    processorRef.current?.disconnect();
    sourceRef.current?.disconnect();
    muteGainRef.current?.disconnect();
    analyserRef.current?.disconnect();

    processorRef.current = null;
    sourceRef.current = null;
    muteGainRef.current = null;
    analyserRef.current = null;

    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;

    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context) {
      void context.close().catch(() => {});
    }
  }, []);

  /** Commit any pending in-flight interim text into the finalized segments list. */
  const flushInterimToFinalized = useCallback(() => {
    const pendingText = interimRef.current.trim();
    if (!pendingText) return;

    const currentSec = elapsedRef.current;
    const startSec = interimStartSecRef.current || Math.max(0, currentSec - 2);
    const endSec = Math.max(startSec + 1, currentSec);

    const seg: SentenceSegment = {
      id: `seg_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      text: pendingText,
      startSec,
      endSec,
    };

    segmentsRef.current = [...segmentsRef.current, seg];
    setSegments(segmentsRef.current);

    finalizedRef.current = [...finalizedRef.current, pendingText];
    setFinalized(finalizedRef.current);

    setInterim("");
    interimRef.current = "";
  }, []);

  const handleServerMessage = useCallback(
    (data: RealtimeServerMessage) => {
      switch (data.type) {
        case "started":
          setPhase("listening");
          break;
        case "sentence":
          if (data.sentence_end) {
            const sentenceText = (data.text || "").trim();
            if (sentenceText) {
              const currentSec = elapsedRef.current;
              const startSec = data.begin_ms != null ? data.begin_ms / 1000 : interimStartSecRef.current || Math.max(0, currentSec - 3);
              const endSec = data.end_ms != null ? data.end_ms / 1000 : Math.max(startSec + 1, currentSec);

              const newSeg: SentenceSegment = {
                id: `seg_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
                text: sentenceText,
                startSec,
                endSec,
                words: data.words || null,
              };

              segmentsRef.current = [...segmentsRef.current, newSeg];
              setSegments(segmentsRef.current);

              finalizedRef.current = [...finalizedRef.current, sentenceText];
              setFinalized(finalizedRef.current);
            }
            setInterim("");
            interimRef.current = "";
            interimStartSecRef.current = elapsedRef.current;
            if (data.words && data.words.length) {
              wordsRef.current = [...wordsRef.current, ...data.words];
            }
          } else {
            if (!interimRef.current) {
              interimStartSecRef.current = elapsedRef.current;
            }
            setInterim(data.text);
            interimRef.current = data.text;
          }
          break;
        case "finished":
          clearFinishTimeout();
          stopTimer();
          flushInterimToFinalized();
          setPhase("done");
          break;
        case "error":
          clearFinishTimeout();
          stopTimer();
          flushInterimToFinalized();
          setError(
            new Error(data.message || t("实时转写出错。", "Realtime transcription error."))
          );
          setPhase("done");
          break;
        default:
          break;
      }
    },
    [clearFinishTimeout, stopTimer, flushInterimToFinalized, t]
  );

  // Auto-scroll transcript box
  useEffect(() => {
    const box = transcriptBoxRef.current;
    if (box) {
      box.scrollTop = box.scrollHeight;
    }
    const tBox = timelineBoxRef.current;
    if (tBox) {
      tBox.scrollTop = tBox.scrollHeight;
    }
  }, [finalized, interim, segments]);

  // Audio level monitoring
  const updateAudioVisualizer = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);

    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      sum += dataArray[i];
    }
    const avg = sum / dataArray.length;
    setAudioLevel(Math.min(1, avg / 128));

    animFrameRef.current = requestAnimationFrame(updateAudioVisualizer);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      stopTimer();
      clearFinishTimeout();
      cleanupAudio();
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        try {
          ws.close();
        } catch {
          // Ignore
        }
      }
    };
  }, [stopTimer, clearFinishTimeout, cleanupAudio]);

  async function start() {
    setError(null);
    setInfo("");
    setInterim("");
    interimRef.current = "";
    segmentsRef.current = [];
    finalizedRef.current = [];
    setSegments([]);
    setFinalized([]);
    wordsRef.current = [];

    const AudioContextCtor = getAudioContextCtor();
    if (!navigator.mediaDevices?.getUserMedia || typeof WebSocket === "undefined" || !AudioContextCtor) {
      setError(
        new Error(t("当前环境不支持实时转写。", "Realtime transcription is not supported in this environment."))
      );
      return;
    }

    setPhase("connecting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;
      if (!aliveRef.current) {
        cleanupAudio();
        return;
      }

      const audioContext = new AudioContextCtor();
      audioContextRef.current = audioContext;
      await audioContext.resume();
      if (!aliveRef.current) {
        cleanupAudio();
        return;
      }

      const ws = new WebSocket(buildRealtimeTranscriptionWebSocketUrl());
      if (!aliveRef.current) {
        cleanupAudio();
        try {
          ws.close();
        } catch {
          // Ignore
        }
        return;
      }
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        if (wsRef.current !== ws) return;
        const hints = LANGUAGE_OPTIONS.find((option) => option.value === languageRef.current)?.hints;
        ws.send(
          JSON.stringify({
            type: "config",
            model: modelRef.current,
            ...(hints ? { language_hints: hints } : {}),
          })
        );

        const source = audioContext.createMediaStreamSource(stream);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 64;
        analyserRef.current = analyser;

        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        const muteGain = audioContext.createGain();
        muteGain.gain.value = 0;

        processor.onaudioprocess = (audioEvent) => {
          if (ws.readyState !== WebSocket.OPEN) return;
          const input = audioEvent.inputBuffer.getChannelData(0);
          const pcm = encodePcm16k(input, audioContext.sampleRate);
          if (pcm.byteLength > 0) {
            ws.send(pcm);
          }
        };

        source.connect(analyser);
        analyser.connect(processor);
        processor.connect(muteGain);
        muteGain.connect(audioContext.destination);

        sourceRef.current = source;
        processorRef.current = processor;
        muteGainRef.current = muteGain;

        updateAudioVisualizer();
      };

      ws.onmessage = (message) => {
        if (wsRef.current !== ws || typeof message.data !== "string") return;
        try {
          handleServerMessage(JSON.parse(message.data) as RealtimeServerMessage);
        } catch {
          // Ignore malformed frames
        }
      };

      ws.onerror = () => {
        if (wsRef.current !== ws) return;
        setError(
          new Error(
            t(
              "实时转写连接失败。请确认后端正在运行，并已在设置中配置对应的 API Key。",
              "Realtime connection failed. Please confirm the backend is running and the required API key is configured."
            )
          )
        );
      };

      ws.onclose = () => {
        cleanupAudio();
        stopTimer();
        clearFinishTimeout();
        flushInterimToFinalized();
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        setPhase((current) => (current === "done" ? current : finalizedRef.current.length > 0 ? "done" : "idle"));
      };

      startTimer();
    } catch (err) {
      cleanupAudio();
      stopTimer();
      setPhase("idle");
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }

  function stop() {
    cleanupAudio();
    stopTimer();
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      setPhase("finishing");
      try {
        ws.send(JSON.stringify({ type: "finish" }));
      } catch {
        // Ignore
      }
      clearFinishTimeout();
      finishTimeoutRef.current = setTimeout(() => {
        finishTimeoutRef.current = null;
        flushInterimToFinalized();
        setPhase("done");
        try {
          ws.close();
        } catch {
          // Ignore
        }
      }, 10000);
    } else {
      flushInterimToFinalized();
      setPhase("done");
    }
  }

  function reset() {
    setPhase("idle");
    setInterim("");
    interimRef.current = "";
    segmentsRef.current = [];
    finalizedRef.current = [];
    setSegments([]);
    setFinalized([]);
    wordsRef.current = [];
    setElapsed(0);
    elapsedRef.current = 0;
    setError(null);
    setInfo("");
  }

  /** Build subtitle timestamps string for SRT/VTT export from recorded segments. */
  function buildSrtContent(): string {
    const segList = segmentsRef.current.length > 0 ? segmentsRef.current : (finalizedRef.current.length > 0 ? [{
      id: "seg_1",
      text: finalizedRef.current.join(" "),
      startSec: 0,
      endSec: Math.max(1, elapsedRef.current),
    }] : []);

    let srt = "\uFEFF"; // UTF-8 BOM for Windows compatibility
    segList.forEach((seg, i) => {
      srt += `${i + 1}\n${formatSrtTime(seg.startSec)} --> ${formatSrtTime(seg.endSec)}\n${seg.text}\n\n`;
    });
    return srt.trim();
  }

  function buildVttContent(): string {
    const segList = segmentsRef.current.length > 0 ? segmentsRef.current : (finalizedRef.current.length > 0 ? [{
      id: "seg_1",
      text: finalizedRef.current.join(" "),
      startSec: 0,
      endSec: Math.max(1, elapsedRef.current),
    }] : []);

    let vtt = "WEBVTT\n\n";
    segList.forEach((seg, i) => {
      vtt += `${i + 1}\n${formatVttTime(seg.startSec)} --> ${formatVttTime(seg.endSec)}\n${seg.text}\n\n`;
    });
    return vtt.trim();
  }

  function buildMarkdownSummary(): string {
    const dateStr = new Date().toLocaleString();
    const durationStr = formatElapsed(elapsedRef.current);
    const modelItem = REALTIME_ASR_MODELS.find((m) => m.id === model);
    const modelName = modelItem ? modelItem.zh : model;

    let md = `# 实时转写纪要\n\n`;
    md += `- **录制时间**：${dateStr}\n`;
    md += `- **转写时长**：${durationStr}\n`;
    md += `- **识别模型**：${modelName}\n`;
    md += `- **总字数**：${wordCount} 字\n\n`;
    md += `## 完整文稿\n\n${displayTranscript}\n\n`;

    if (segments.length > 0) {
      md += `## 时间轴对齐记录\n\n`;
      segments.forEach((seg) => {
        md += `- \`[${formatTimestampDisplay(seg.startSec)} - ${formatTimestampDisplay(seg.endSec)}]\` ${seg.text}\n`;
      });
    }

    return md;
  }

  async function handleExport(format: "srt" | "vtt" | "txt" | "md") {
    flushInterimToFinalized();
    const text = displayTranscript.trim();
    if (!text) return;

    const baseName = `realtime_transcript_${new Date().toISOString().slice(0, 10)}_${Date.now().toString().slice(-4)}`;
    let content = "";
    let mimeType = "text/plain";
    const extension = format;

    if (format === "srt") {
      content = buildSrtContent();
    } else if (format === "vtt") {
      content = buildVttContent();
      mimeType = "text/vtt";
    } else if (format === "txt") {
      content = text;
    } else if (format === "md") {
      content = buildMarkdownSummary();
      mimeType = "text/markdown";
    }

    setShowExportMenu(false);

    try {
      const outcome = await exportTextFile(`${baseName}.${extension}`, content, mimeType);
      if (outcome.kind === "saved-desktop") {
        setInfo(outcome.path ? t(`已成功导出: ${outcome.path}`, `Exported: ${outcome.path}`) : t("文件已导出。", "File exported."));
      } else if (outcome.kind === "downloaded-browser") {
        setInfo(t("文件已开始下载。", "Download started."));
      } else if (outcome.kind === "failed") {
        setError(new Error(t(`导出失败: ${outcome.message}`, `Export failed: ${outcome.message}`)));
      }
      setTimeout(() => setInfo(""), 4000);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }

  async function handleSave() {
    flushInterimToFinalized();
    const text = displayTranscript.trim();
    if (!text) return;
    setSaving(true);
    setError(null);
    try {
      let finalWords = wordsRef.current;
      if (!finalWords.length && segmentsRef.current.length) {
        finalWords = segmentsRef.current.map((seg) => ({
          text: seg.text,
          start: seg.startSec,
          end: seg.endSec,
        }));
      }

      const job = await saveTranscriptionText(
        text,
        t(`实时转写_${new Date().toLocaleTimeString()}`, `Realtime_${new Date().toLocaleTimeString()}`),
        finalWords
      );
      onComplete(job, finalWords);
      setInfo(t("已成功保存至转写库！", "Saved to transcription library!"));
      setTimeout(() => setInfo(""), 3000);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setSaving(false);
    }
  }

  function handleCopyPlainText() {
    flushInterimToFinalized();
    const text = displayTranscript.trim();
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      setInfo(t("全文文稿已复制到剪贴板", "Transcript copied to clipboard."));
      setShowCopyMenu(false);
      setTimeout(() => setInfo(""), 3000);
    });
  }

  function handleCopyTimelineText() {
    flushInterimToFinalized();
    const segList = segmentsRef.current.length > 0 ? segmentsRef.current : [{
      id: "1",
      text: displayTranscript.trim(),
      startSec: 0,
      endSec: elapsedRef.current,
    }];
    const text = segList
      .map((s) => `[${formatTimestampDisplay(s.startSec)} - ${formatTimestampDisplay(s.endSec)}] ${s.text}`)
      .join("\n");

    navigator.clipboard.writeText(text).then(() => {
      setInfo(t("带时间戳字幕已复制到剪贴板", "Timestamped cues copied to clipboard."));
      setShowCopyMenu(false);
      setTimeout(() => setInfo(""), 3000);
    });
  }

  const running = phase === "connecting" || phase === "listening" || phase === "finishing";

  const statusText = (() => {
    switch (phase) {
      case "connecting":
        return t("正在连接模型服务…", "Connecting to recognition model…");
      case "listening":
        return t("正在实时收音，请开始说话…", "Listening in real-time, start speaking…");
      case "finishing":
        return t("正在处理并整理剩余语音…", "Finalizing remaining speech…");
      case "done":
        return t("转写已完成，你可以复制、导出字幕或存入转写库。", "Completed. You can copy, export subtitles, or save to library.");
      default:
        return t("点击下方按钮开启实时流式转写。", "Click start to begin streaming speech-to-text.");
    }
  })();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* Model & Language Controls */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
        <div className="vsField" style={{ gap: "6px" }}>
          <label className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>
            {t("识别引擎", "ASR Model")}
          </label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={running}
            className="vsSelect"
            style={{ width: "100%", height: "40px", borderRadius: "8px", fontSize: "13px" }}
          >
            {REALTIME_ASR_MODELS.map((option) => (
              <option key={option.id} value={option.id}>
                {t(option.zh, option.en)}
              </option>
            ))}
          </select>
        </div>

        <div className="vsField" style={{ gap: "6px" }}>
          <label className="vsFieldLabel" style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>
            {t("识别语种", "Language")}
          </label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            disabled={running}
            className="vsSelect"
            style={{ width: "100%", height: "40px", borderRadius: "8px", fontSize: "13px" }}
          >
            {LANGUAGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.zh, option.en)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Model Note */}
      <div style={{ marginTop: "-8px" }}>
        <span style={{ fontSize: "12px", color: "var(--muted)", lineHeight: 1.4 }}>
          {(() => {
            const selected = REALTIME_ASR_MODELS.find((option) => option.id === model);
            return selected ? t(selected.noteZh, selected.noteEn) : "";
          })()}
        </span>
      </div>

      {/* View Switcher Tabs & Live Stats Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingBottom: "4px",
          borderBottom: "1px solid var(--border-color)",
        }}
      >
        <div style={{ display: "flex", gap: "6px" }}>
          <button
            type="button"
            onClick={() => setViewMode("transcript")}
            style={{
              padding: "4px 10px",
              borderRadius: "6px",
              fontSize: "12px",
              fontWeight: viewMode === "transcript" ? 600 : 400,
              background: viewMode === "transcript" ? "var(--primary-bg, rgba(99,102,241,0.12))" : "transparent",
              color: viewMode === "transcript" ? "var(--primary, #6366f1)" : "var(--muted)",
              border: "none",
              cursor: "pointer",
            }}
          >
            {t("文稿模式", "Transcript")}
          </button>
          <button
            type="button"
            onClick={() => setViewMode("timeline")}
            style={{
              padding: "4px 10px",
              borderRadius: "6px",
              fontSize: "12px",
              fontWeight: viewMode === "timeline" ? 600 : 400,
              background: viewMode === "timeline" ? "var(--primary-bg, rgba(99,102,241,0.12))" : "transparent",
              color: viewMode === "timeline" ? "var(--primary, #6366f1)" : "var(--muted)",
              border: "none",
              cursor: "pointer",
            }}
          >
            {t("字幕时间轴", "Timeline Cues")}
          </button>
          <button
            type="button"
            onClick={() => setViewMode("banner")}
            style={{
              padding: "4px 10px",
              borderRadius: "6px",
              fontSize: "12px",
              fontWeight: viewMode === "banner" ? 600 : 400,
              background: viewMode === "banner" ? "var(--primary-bg, rgba(99,102,241,0.12))" : "transparent",
              color: viewMode === "banner" ? "var(--primary, #6366f1)" : "var(--muted)",
              border: "none",
              cursor: "pointer",
            }}
          >
            {t("大字实时字幕", "Live Subtitle")}
          </button>
        </div>

        {/* Live Counters */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: "12px", color: "var(--muted)" }}>
          <span>{t(`字数: ${wordCount}`, `Chars: ${wordCount}`)}</span>
          <span>{t(`句子: ${segments.length + (interim ? 1 : 0)}`, `Segments: ${segments.length + (interim ? 1 : 0)}`)}</span>
          <span>{formatElapsed(elapsed)}</span>
        </div>
      </div>

      {/* Main Content Area Based on View Mode */}
      {viewMode === "transcript" && (
        <div
          ref={transcriptBoxRef}
          style={{
            minHeight: "180px",
            maxHeight: "280px",
            overflowY: "auto",
            padding: "14px",
            borderRadius: "12px",
            border: "1px solid var(--border-color)",
            background: "var(--bg-card)",
            fontSize: "15px",
            lineHeight: 1.7,
            color: "var(--text)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {displayTranscript ? (
            <>
              <span>{finalizedText}</span>
              {interim && <span style={{ color: "var(--primary, #6366f1)", fontWeight: 500 }}>{interimPart}</span>}
            </>
          ) : (
            <span style={{ color: "var(--muted)" }}>
              {t("转写文字将在此实时呈现…", "Live streaming transcript will appear here…")}
            </span>
          )}
        </div>
      )}

      {viewMode === "timeline" && (
        <div
          ref={timelineBoxRef}
          style={{
            minHeight: "180px",
            maxHeight: "280px",
            overflowY: "auto",
            padding: "10px",
            borderRadius: "12px",
            border: "1px solid var(--border-color)",
            background: "var(--bg-card)",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          {segments.length === 0 && !interim ? (
            <span style={{ color: "var(--muted)", padding: "8px", fontSize: "13px" }}>
              {t("暂无字幕段落，开始说话后将按时间生成分段…", "No timeline cues yet. Speak to generate timestamped segments…")}
            </span>
          ) : (
            <>
              {segments.map((seg, idx) => (
                <div
                  key={seg.id || idx}
                  style={{
                    padding: "8px 10px",
                    borderRadius: "8px",
                    background: "var(--bg-subtle, rgba(0,0,0,0.03))",
                    border: "1px solid var(--border-color)",
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--muted)" }}>
                    <span style={{ fontFamily: "monospace" }}>
                      #{idx + 1} [{formatTimestampDisplay(seg.startSec)} - {formatTimestampDisplay(seg.endSec)}]
                    </span>
                  </div>
                  <div style={{ fontSize: "14px", color: "var(--text)", lineHeight: 1.5 }}>
                    {seg.text}
                  </div>
                </div>
              ))}
              {interim && (
                <div
                  style={{
                    padding: "8px 10px",
                    borderRadius: "8px",
                    background: "var(--primary-bg, rgba(99,102,241,0.08))",
                    border: "1px dashed var(--primary, #6366f1)",
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                  }}
                >
                  <div style={{ fontSize: "11px", color: "var(--primary, #6366f1)", fontWeight: 600 }}>
                    {t("正在说话…", "Speaking now…")} [{formatTimestampDisplay(interimStartSecRef.current)} - {formatTimestampDisplay(elapsed)}]
                  </div>
                  <div style={{ fontSize: "14px", color: "var(--primary, #6366f1)", fontWeight: 500, lineHeight: 1.5 }}>
                    {interim}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {viewMode === "banner" && (
        <div
          style={{
            minHeight: "180px",
            maxHeight: "280px",
            borderRadius: "12px",
            border: "1px solid var(--border-color)",
            background: "linear-gradient(180deg, var(--bg-card) 0%, var(--bg-subtle, rgba(0,0,0,0.02)) 100%)",
            padding: "20px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
            textAlign: "center",
            gap: "12px",
          }}
        >
          <div style={{ fontSize: "12px", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "1px" }}>
            {t("实时大字字幕提词", "Live Subtitle Banner")}
          </div>
          <div
            style={{
              fontSize: "20px",
              fontWeight: 600,
              color: interim ? "var(--primary, #6366f1)" : "var(--text)",
              lineHeight: 1.5,
              maxWidth: "90%",
              minHeight: "60px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {interim || (segments.length > 0 ? segments[segments.length - 1].text : t("等待说话输入…", "Waiting for speech…"))}
          </div>
          {phase === "listening" && (
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "#e5484d" }}>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#e5484d", display: "inline-block" }} />
              <span>LIVE ON AIR</span>
            </div>
          )}
        </div>
      )}

      {/* Audio Waveform & Status Indicator */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: "13px",
          color: "var(--muted)",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
          {phase === "listening" && (
            <span
              style={{
                width: "9px",
                height: "9px",
                borderRadius: "50%",
                background: "#e5484d",
                display: "inline-block",
              }}
            />
          )}
          {statusText}
        </span>

        {/* Dynamic Voice Level Visualizer */}
        {phase === "listening" && (
          <div style={{ display: "flex", alignItems: "center", gap: "3px", height: "16px" }}>
            {[0.2, 0.5, 0.8, 0.6, 0.3].map((factor, idx) => {
              const h = Math.max(3, Math.min(16, audioLevel * factor * 24));
              return (
                <div
                  key={idx}
                  style={{
                    width: "3px",
                    height: `${h}px`,
                    borderRadius: "2px",
                    background: "var(--primary, #6366f1)",
                    transition: "height 0.08s ease",
                  }}
                />
              );
            })}
          </div>
        )}
      </div>

      {/* Action Controls */}
      {phase === "done" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          <div style={{ display: "flex", gap: "8px", position: "relative" }}>
            {/* Save to Library */}
            <button
              onClick={handleSave}
              disabled={!displayTranscript.trim() || saving}
              className="vsBtnPrimary"
              style={{ flex: 2, height: "42px", fontSize: "14px", borderRadius: "8px", fontWeight: 600 }}
            >
              {saving ? (
                <>
                  <span className="spinner-mini" /> {t("保存中…", "Saving…")}
                </>
              ) : (
                t("保存到转写库", "Save to library")
              )}
            </button>

            {/* Export Menu Dropdown */}
            <div style={{ position: "relative", flex: 1 }}>
              <button
                type="button"
                onClick={() => {
                  setShowExportMenu(!showExportMenu);
                  setShowCopyMenu(false);
                }}
                disabled={!displayTranscript.trim()}
                className="vsBtnSecondary"
                style={{ width: "100%", height: "42px", fontSize: "14px", borderRadius: "8px", fontWeight: 600 }}
              >
                {t("导出 ▼", "Export ▼")}
              </button>

              {showExportMenu && (
                <div
                  style={{
                    position: "absolute",
                    bottom: "48px",
                    left: 0,
                    right: 0,
                    minWidth: "160px",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "8px",
                    boxShadow: "0 6px 18px rgba(0,0,0,0.12)",
                    zIndex: 20,
                    display: "flex",
                    flexDirection: "column",
                    padding: "4px",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => handleExport("srt")}
                    style={{
                      padding: "8px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    🎬 {t("导出 SRT 字幕文件", "Export SRT Subtitle")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExport("vtt")}
                    style={{
                      padding: "8px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    🌐 {t("导出 WebVTT 字幕", "Export WebVTT")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExport("txt")}
                    style={{
                      padding: "8px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    📄 {t("导出纯文本 TXT", "Export Text (.txt)")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExport("md")}
                    style={{
                      padding: "8px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    📝 {t("导出 Markdown 纪要", "Export Markdown (.md)")}
                  </button>
                </div>
              )}
            </div>

            {/* Copy Menu Dropdown */}
            <div style={{ position: "relative", flex: 1 }}>
              <button
                type="button"
                onClick={() => {
                  setShowCopyMenu(!showCopyMenu);
                  setShowExportMenu(false);
                }}
                disabled={!displayTranscript.trim()}
                className="vsBtnSecondary"
                style={{ width: "100%", height: "42px", fontSize: "14px", borderRadius: "8px", fontWeight: 600 }}
              >
                {t("复制 ▼", "Copy ▼")}
              </button>

              {showCopyMenu && (
                <div
                  style={{
                    position: "absolute",
                    bottom: "48px",
                    left: 0,
                    right: 0,
                    minWidth: "150px",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "8px",
                    boxShadow: "0 6px 18px rgba(0,0,0,0.12)",
                    zIndex: 20,
                    display: "flex",
                    flexDirection: "column",
                    padding: "4px",
                  }}
                >
                  <button
                    type="button"
                    onClick={handleCopyPlainText}
                    style={{
                      padding: "8px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    📋 {t("复制纯文字文稿", "Copy Plain Text")}
                  </button>
                  <button
                    type="button"
                    onClick={handleCopyTimelineText}
                    style={{
                      padding: "8px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    ⏱️ {t("复制带时间轴字幕", "Copy Timestamped")}
                  </button>
                </div>
              )}
            </div>

            {/* Restart */}
            <button
              type="button"
              onClick={reset}
              className="vsBtnGhost"
              style={{ height: "42px", padding: "0 14px", fontSize: "13px", borderRadius: "8px" }}
            >
              {t("重开", "Reset")}
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={phase === "idle" ? start : stop}
          disabled={phase === "connecting" || phase === "finishing"}
          className="vsBtnPrimary"
          style={{ width: "100%", height: "44px", fontSize: "14px", borderRadius: "10px", fontWeight: 600 }}
        >
          {phase === "connecting" && (
            <>
              <span className="spinner-mini" /> {t("连接中…", "Connecting…")}
            </>
          )}
          {phase === "listening" && t("结束录音并整理", "Stop Recording & Finish")}
          {phase === "finishing" && (
            <>
              <span className="spinner-mini" /> {t("正在整理…", "Wrapping up…")}
            </>
          )}
          {phase === "idle" && t("开始实时流式转写", "Start Realtime Transcription")}
        </button>
      )}

      {info && (
        <span style={{ fontSize: "12px", color: "var(--primary, #6366f1)", textAlign: "center", fontWeight: 500 }}>
          {info}
        </span>
      )}
      {error && <ErrorNotice message={error.message || String(error)} scope="Transcription" />}
    </div>
  );
}

export default RealtimeTranscriptionPanel;
