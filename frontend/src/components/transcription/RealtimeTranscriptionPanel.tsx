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

type ViewMode = "transcript" | "timeline" | "teleprompter";

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
  onSwitchToLibrary?: () => void;
};

const LANGUAGE_OPTIONS: { value: string; hints?: string[]; zh: string; en: string }[] = [
  { value: "auto", zh: "自动检测 (85+ 语种)", en: "Auto detect (85+ languages)" },
  { value: "zh", hints: ["zh"], zh: "中文 (普通话)", en: "Chinese (Mandarin)" },
  { value: "en", hints: ["en"], zh: "英语 (English)", en: "English" },
  { value: "zh-en", hints: ["zh", "en"], zh: "中英混合 (Bilingual)", en: "Chinese + English" },
  { value: "ja", hints: ["ja"], zh: "日语 (日本語)", en: "Japanese" },
  { value: "ko", hints: ["ko"], zh: "韩语 (한국어)", en: "Korean" },
  { value: "yue", hints: ["yue"], zh: "粤语 (Cantonese)", en: "Cantonese" },
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

export function RealtimeTranscriptionPanel({ onComplete, onSwitchToLibrary }: Props) {
  const { t } = useI18n();

  const [phase, setPhase] = useState<Phase>("idle");
  const [language, setLanguage] = useState("auto");
  const [model, setModel] = useState(REALTIME_ASR_MODELS[0].id);
  const [viewMode, setViewMode] = useState<ViewMode>("teleprompter");
  const [fontSizeLevel, setFontSizeLevel] = useState<"normal" | "large" | "xlarge">("large");

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
  const teleprompterBoxRef = useRef<HTMLDivElement | null>(null);
  const teleprompterActiveRef = useRef<HTMLDivElement | null>(null);
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

  // Auto-scroll transcript & teleprompter boxes
  useEffect(() => {
    const box = transcriptBoxRef.current;
    if (box) {
      box.scrollTop = box.scrollHeight;
    }
    const tBox = timelineBoxRef.current;
    if (tBox) {
      tBox.scrollTop = tBox.scrollHeight;
    }
    const teleBox = teleprompterBoxRef.current;
    if (teleBox) {
      if (typeof teleBox.scrollTo === "function") {
        teleBox.scrollTo({
          top: teleBox.scrollHeight,
          behavior: "smooth",
        });
      } else {
        teleBox.scrollTop = teleBox.scrollHeight;
      }
    }
  }, [finalized, interim, segments, viewMode]);

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
    md += `- **识别引擎**：${modelName}\n`;
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

      const now = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      const timeTag = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
      const recName = t(`实时录音_${timeTag}`, `Realtime_${timeTag}`);

      const job = await saveTranscriptionText(
        text,
        recName,
        finalWords
      );
      onComplete(job, finalWords);
      setInfo(t("已成功存入转写历史库！", "Saved to transcription library!"));
      setTimeout(() => setInfo(""), 3500);
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

  const getFontSizePx = () => {
    switch (fontSizeLevel) {
      case "normal":
        return "18px";
      case "large":
        return "24px";
      case "xlarge":
        return "30px";
      default:
        return "24px";
    }
  };

  const statusText = (() => {
    switch (phase) {
      case "connecting":
        return t("正在建立流式连接…", "Connecting…");
      case "listening":
        return t("正在实时收音，请开始说话…", "Listening live, start speaking…");
      case "finishing":
        return t("正在整理最后的内容…", "Wrapping up…");
      case "done":
        return t("录音转写已完成", "Session completed");
      default:
        return t("准备就绪", "Ready");
    }
  })();

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "14px",
        width: "100%",
        height: "100%",
        boxSizing: "border-box",
      }}
    >
      {/* Top Controls Ribbon */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "12px",
          padding: "12px 16px",
          background: "var(--bg-card)",
          border: "1px solid var(--border-color)",
          borderRadius: "14px",
        }}
      >
        {/* Left: Model & Language Selectors */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
              {t("模型", "Model")}:
            </span>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={running}
              className="vsSelect"
              style={{ height: "34px", padding: "0 10px", borderRadius: "8px", fontSize: "13px" }}
            >
              {REALTIME_ASR_MODELS.map((option) => (
                <option key={option.id} value={option.id}>
                  {t(option.zh, option.en)}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
              {t("语种", "Lang")}:
            </span>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={running}
              className="vsSelect"
              style={{ height: "34px", padding: "0 10px", borderRadius: "8px", fontSize: "13px" }}
            >
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.zh, option.en)}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Center: View Switcher Tabs */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            background: "var(--bg-subtle, rgba(0,0,0,0.04))",
            padding: "3px",
            borderRadius: "8px",
            gap: "2px",
          }}
        >
          <button
            type="button"
            onClick={() => setViewMode("teleprompter")}
            style={{
              padding: "5px 12px",
              borderRadius: "6px",
              fontSize: "12px",
              fontWeight: viewMode === "teleprompter" ? 600 : 500,
              background: viewMode === "teleprompter" ? "var(--bg-card, #fff)" : "transparent",
              color: viewMode === "teleprompter" ? "var(--primary, #6366f1)" : "var(--muted)",
              boxShadow: viewMode === "teleprompter" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            📺 {t("大字提词器", "Teleprompter")}
          </button>
          <button
            type="button"
            onClick={() => setViewMode("transcript")}
            style={{
              padding: "5px 12px",
              borderRadius: "6px",
              fontSize: "12px",
              fontWeight: viewMode === "transcript" ? 600 : 500,
              background: viewMode === "transcript" ? "var(--bg-card, #fff)" : "transparent",
              color: viewMode === "transcript" ? "var(--primary, #6366f1)" : "var(--muted)",
              boxShadow: viewMode === "transcript" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            📝 {t("文稿模式", "Transcript")}
          </button>
          <button
            type="button"
            onClick={() => setViewMode("timeline")}
            style={{
              padding: "5px 12px",
              borderRadius: "6px",
              fontSize: "12px",
              fontWeight: viewMode === "timeline" ? 600 : 500,
              background: viewMode === "timeline" ? "var(--bg-card, #fff)" : "transparent",
              color: viewMode === "timeline" ? "var(--primary, #6366f1)" : "var(--muted)",
              boxShadow: viewMode === "timeline" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            ⏱️ {t("字幕时间轴", "Timeline Cues")}
          </button>
        </div>

        {/* Right: Teleprompter Font Size & Live Stats */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          {viewMode === "teleprompter" && (
            <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              <span style={{ fontSize: "11px", color: "var(--muted)" }}>{t("字号", "Size")}:</span>
              {(["normal", "large", "xlarge"] as const).map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => setFontSizeLevel(lvl)}
                  style={{
                    padding: "2px 6px",
                    borderRadius: "4px",
                    fontSize: lvl === "normal" ? "11px" : lvl === "large" ? "13px" : "15px",
                    fontWeight: fontSizeLevel === lvl ? 700 : 400,
                    background: fontSizeLevel === lvl ? "var(--primary-bg, rgba(99,102,241,0.12))" : "transparent",
                    color: fontSizeLevel === lvl ? "var(--primary, #6366f1)" : "var(--muted)",
                    border: "none",
                    cursor: "pointer",
                  }}
                >
                  A{lvl === "normal" ? "" : lvl === "large" ? "+" : "++"}
                </button>
              ))}
            </div>
          )}

          {/* Audio level indicator */}
          {phase === "listening" && (
            <div style={{ display: "flex", alignItems: "center", gap: "3px", height: "14px" }}>
              {[0.2, 0.6, 0.9, 0.7, 0.4].map((factor, idx) => {
                const h = Math.max(3, Math.min(14, audioLevel * factor * 22));
                return (
                  <div
                    key={idx}
                    style={{
                      width: "3px",
                      height: `${h}px`,
                      borderRadius: "2px",
                      background: "#e5484d",
                      transition: "height 0.08s ease",
                    }}
                  />
                );
              })}
            </div>
          )}

          {/* Status Badge */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "4px 10px",
              borderRadius: "999px",
              fontSize: "12px",
              fontWeight: 600,
              background: phase === "listening" ? "rgba(229, 72, 77, 0.1)" : "var(--bg-subtle, rgba(0,0,0,0.04))",
              color: phase === "listening" ? "#e5484d" : "var(--muted)",
            }}
          >
            {phase === "listening" && (
              <span
                style={{
                  width: "7px",
                  height: "7px",
                  borderRadius: "50%",
                  background: "#e5484d",
                  display: "inline-block",
                }}
              />
            )}
            <span>{phase === "listening" ? "LIVE ON AIR" : statusText}</span>
            <span style={{ fontFamily: "monospace" }}>{formatElapsed(elapsed)}</span>
          </div>

          {onSwitchToLibrary && (
            <button
              type="button"
              onClick={onSwitchToLibrary}
              className="vsBtnGhost"
              style={{
                height: "32px",
                padding: "0 10px",
                fontSize: "12px",
                borderRadius: "8px",
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
              }}
              title={t("切换至转写历史库", "Switch to Transcription Library")}
            >
              📚 {t("历史库", "Library")}
            </button>
          )}
        </div>
      </div>

      {/* Main Workspace */}
      <div
        style={{
          flex: 1,
          minHeight: "340px",
          background: "var(--bg-card)",
          border: "1px solid var(--border-color)",
          borderRadius: "16px",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          position: "relative",
        }}
      >
        {/* VIEW 1: Teleprompter Mode (上下平滑滚动与高亮聚焦) */}
        {viewMode === "teleprompter" && (
          <div
            ref={teleprompterBoxRef}
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "28px 32px",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
              scrollBehavior: "smooth",
            }}
          >
            {segments.length === 0 && !interim ? (
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--muted)",
                  gap: "8px",
                  padding: "40px 0",
                }}
              >
                <div style={{ fontSize: "36px" }}>🎙️</div>
                <div style={{ fontSize: "16px", fontWeight: 600 }}>
                  {t("大字提词器已准备就绪", "Teleprompter Ready")}
                </div>
                <div style={{ fontSize: "13px", opacity: 0.8 }}>
                  {t("点击下方按钮开始说话，文字将随着您的语速自动向上平滑滚动…", "Start speaking below. Sentences will smoothly scroll up as you talk…")}
                </div>
              </div>
            ) : (
              <>
                {/* Past finalized sentences (subdued, elegant) */}
                {segments.map((seg, idx) => (
                  <div
                    key={seg.id || idx}
                    style={{
                      fontSize: `calc(${getFontSizePx()} * 0.82)`,
                      lineHeight: 1.6,
                      color: "var(--text)",
                      opacity: 0.65,
                      transition: "all 0.2s ease",
                    }}
                  >
                    <span style={{ fontSize: "12px", color: "var(--muted)", marginRight: "8px", fontFamily: "monospace" }}>
                      [{formatTimestampDisplay(seg.startSec)}]
                    </span>
                    {seg.text}
                  </div>
                ))}

                {/* Current speaking sentence (Large, High-Contrast, Focused) */}
                {interim && (
                  <div
                    ref={teleprompterActiveRef}
                    style={{
                      fontSize: getFontSizePx(),
                      fontWeight: 600,
                      lineHeight: 1.5,
                      color: "var(--primary, #6366f1)",
                      background: "var(--primary-bg, rgba(99,102,241,0.06))",
                      padding: "12px 16px",
                      borderRadius: "12px",
                      borderLeft: "4px solid var(--primary, #6366f1)",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: "8px",
                      boxShadow: "0 4px 16px rgba(99,102,241,0.08)",
                      animation: "fadeIn 0.2s ease",
                    }}
                  >
                    <span style={{ flex: 1 }}>{interim}</span>
                    <span
                      style={{
                        display: "inline-block",
                        width: "3px",
                        height: "1.2em",
                        background: "var(--primary, #6366f1)",
                        animation: "pulse 1s infinite",
                        marginLeft: "4px",
                      }}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* VIEW 2: Transcript Mode (整篇连贯文稿) */}
        {viewMode === "transcript" && (
          <div
            ref={transcriptBoxRef}
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "24px 28px",
              fontSize: "16px",
              lineHeight: 1.8,
              color: "var(--text)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {displayTranscript ? (
              <>
                <span>{finalizedText}</span>
                {interim && <span style={{ color: "var(--primary, #6366f1)", fontWeight: 600 }}>{interimPart}</span>}
              </>
            ) : (
              <span style={{ color: "var(--muted)" }}>
                {t("转写文稿将实时流式呈现在此…", "Streaming transcript will appear here in real-time…")}
              </span>
            )}
          </div>
        )}

        {/* VIEW 3: Timeline Cues Mode (时间轴字幕分段卡片) */}
        {viewMode === "timeline" && (
          <div
            ref={timelineBoxRef}
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "16px 20px",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
            }}
          >
            {segments.length === 0 && !interim ? (
              <span style={{ color: "var(--muted)", padding: "16px", fontSize: "14px" }}>
                {t("暂无字幕段落，开始说话后将自动按时间切分生成字幕条…", "No timeline cues yet. Speak to generate timestamped segments…")}
              </span>
            ) : (
              <>
                {segments.map((seg, idx) => (
                  <div
                    key={seg.id || idx}
                    style={{
                      padding: "10px 14px",
                      borderRadius: "10px",
                      background: "var(--bg-subtle, rgba(0,0,0,0.02))",
                      border: "1px solid var(--border-color)",
                      display: "flex",
                      flexDirection: "column",
                      gap: "4px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "var(--muted)" }}>
                      <span style={{ fontFamily: "monospace", fontWeight: 600 }}>
                        #{idx + 1} [{formatTimestampDisplay(seg.startSec)} ➔ {formatTimestampDisplay(seg.endSec)}]
                      </span>
                    </div>
                    <div style={{ fontSize: "15px", color: "var(--text)", lineHeight: 1.5 }}>
                      {seg.text}
                    </div>
                  </div>
                ))}
                {interim && (
                  <div
                    style={{
                      padding: "10px 14px",
                      borderRadius: "10px",
                      background: "var(--primary-bg, rgba(99,102,241,0.08))",
                      border: "1px dashed var(--primary, #6366f1)",
                      display: "flex",
                      flexDirection: "column",
                      gap: "4px",
                    }}
                  >
                    <div style={{ fontSize: "12px", color: "var(--primary, #6366f1)", fontWeight: 600 }}>
                      {t("正在说话…", "Speaking now…")} [{formatTimestampDisplay(interimStartSecRef.current)} ➔ {formatTimestampDisplay(elapsed)}]
                    </div>
                    <div style={{ fontSize: "15px", color: "var(--primary, #6366f1)", fontWeight: 600, lineHeight: 1.5 }}>
                      {interim}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Live Metrics Bottom Footer Bar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 18px",
            background: "var(--bg-subtle, rgba(0,0,0,0.02))",
            borderTop: "1px solid var(--border-color)",
            fontSize: "12px",
            color: "var(--muted)",
          }}
        >
          <div style={{ display: "flex", gap: "16px" }}>
            <span>{t(`字数统计: ${wordCount}`, `Words/Chars: ${wordCount}`)}</span>
            <span>{t(`分段句子: ${segments.length + (interim ? 1 : 0)}`, `Segments: ${segments.length + (interim ? 1 : 0)}`)}</span>
          </div>
          <div>
            <span>{t(`录制时长: ${formatElapsed(elapsed)}`, `Duration: ${formatElapsed(elapsed)}`)}</span>
          </div>
        </div>
      </div>

      {/* Bottom Action Controls Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "12px",
          justifyContent: "space-between",
          padding: "4px 0",
        }}
      >
        {phase === "done" ? (
          <div style={{ display: "flex", gap: "10px", width: "100%", position: "relative" }}>
            {/* Save to Library */}
            <button
              onClick={handleSave}
              disabled={!displayTranscript.trim() || saving}
              className="vsBtnPrimary"
              style={{
                flex: 2,
                height: "46px",
                fontSize: "15px",
                borderRadius: "12px",
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
              }}
            >
              {saving ? (
                <>
                  <span className="spinner-mini" /> {t("保存中…", "Saving…")}
                </>
              ) : (
                <>💾 {t("存入转写历史库", "Save to Library")}</>
              )}
            </button>

            {/* Export Dropdown */}
            <div style={{ position: "relative", flex: 1.2 }}>
              <button
                type="button"
                onClick={() => {
                  setShowExportMenu(!showExportMenu);
                  setShowCopyMenu(false);
                }}
                disabled={!displayTranscript.trim()}
                className="vsBtnSecondary"
                style={{
                  width: "100%",
                  height: "46px",
                  fontSize: "14px",
                  borderRadius: "12px",
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "6px",
                }}
              >
                🎬 {t("导出字幕/文稿 ▼", "Export ▼")}
              </button>

              {showExportMenu && (
                <div
                  style={{
                    position: "absolute",
                    bottom: "54px",
                    left: 0,
                    right: 0,
                    minWidth: "180px",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "10px",
                    boxShadow: "0 8px 24px rgba(0,0,0,0.14)",
                    zIndex: 30,
                    display: "flex",
                    flexDirection: "column",
                    padding: "6px",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => handleExport("srt")}
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    🎬 {t("导出 SRT 字幕 (.srt)", "Export SRT Subtitles")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExport("vtt")}
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    🌐 {t("导出 WebVTT 字幕 (.vtt)", "Export WebVTT")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExport("txt")}
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    📄 {t("导出纯文本 (.txt)", "Export Text (.txt)")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExport("md")}
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    📝 {t("导出 Markdown 纪要 (.md)", "Export Markdown (.md)")}
                  </button>
                </div>
              )}
            </div>

            {/* Copy Dropdown */}
            <div style={{ position: "relative", flex: 1 }}>
              <button
                type="button"
                onClick={() => {
                  setShowCopyMenu(!showCopyMenu);
                  setShowExportMenu(false);
                }}
                disabled={!displayTranscript.trim()}
                className="vsBtnSecondary"
                style={{
                  width: "100%",
                  height: "46px",
                  fontSize: "14px",
                  borderRadius: "12px",
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "6px",
                }}
              >
                📋 {t("复制 ▼", "Copy ▼")}
              </button>

              {showCopyMenu && (
                <div
                  style={{
                    position: "absolute",
                    bottom: "54px",
                    left: 0,
                    right: 0,
                    minWidth: "160px",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "10px",
                    boxShadow: "0 8px 24px rgba(0,0,0,0.14)",
                    zIndex: 30,
                    display: "flex",
                    flexDirection: "column",
                    padding: "6px",
                  }}
                >
                  <button
                    type="button"
                    onClick={handleCopyPlainText}
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    📄 {t("复制纯文字文稿", "Copy Plain Text")}
                  </button>
                  <button
                    type="button"
                    onClick={handleCopyTimelineText}
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      border: "none",
                      background: "transparent",
                      fontSize: "13px",
                      color: "var(--text)",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    ⏱️ {t("复制带时间轴字幕", "Copy Timestamped Cues")}
                  </button>
                </div>
              )}
            </div>

            {/* Restart */}
            <button
              type="button"
              onClick={reset}
              className="vsBtnGhost"
              style={{
                height: "46px",
                padding: "0 18px",
                fontSize: "14px",
                borderRadius: "12px",
                fontWeight: 600,
              }}
            >
              🔄 {t("重新开始", "New Session")}
            </button>
          </div>
        ) : (
          <button
            onClick={phase === "idle" ? start : stop}
            disabled={phase === "connecting" || phase === "finishing"}
            className="vsBtnPrimary"
            style={{
              width: "100%",
              height: "48px",
              fontSize: "15px",
              borderRadius: "12px",
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "8px",
              background: phase === "listening" ? "#e5484d" : undefined,
              borderColor: phase === "listening" ? "#e5484d" : undefined,
            }}
          >
            {phase === "connecting" && (
              <>
                <span className="spinner-mini" /> {t("正在建立实时连接…", "Connecting…")}
              </>
            )}
            {phase === "listening" && (
              <>
                <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#fff", display: "inline-block" }} />
                {t("结束实时录音并整理", "Stop Recording & Finish")}
              </>
            )}
            {phase === "finishing" && (
              <>
                <span className="spinner-mini" /> {t("正在整理最后的内容…", "Wrapping up…")}
              </>
            )}
            {phase === "idle" && (
              <>
                <span>🔴</span> {t("开始实时流式转写", "Start Realtime Transcription")}
              </>
            )}
          </button>
        )}
      </div>

      {info && (
        <span style={{ fontSize: "13px", color: "var(--primary, #6366f1)", textAlign: "center", fontWeight: 500 }}>
          {info}
        </span>
      )}
      {error && <ErrorNotice message={error.message || String(error)} scope="Transcription" />}
    </div>
  );
}

export default RealtimeTranscriptionPanel;

