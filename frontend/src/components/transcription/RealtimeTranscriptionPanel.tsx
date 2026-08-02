import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildRealtimeTranscriptionWebSocketUrl,
  saveTranscriptionText,
  type TranscriptionJobResponse,
  type WordTimestamp,
} from "../../api";
import { REALTIME_ASR_MODELS } from "../../utils/asrProviders";
import { encodePcm16k, getAudioContextCtor } from "../../hooks/useVoiceChatHelpers";
import ErrorNotice from "../ErrorNotice";
import { useI18n } from "../../i18n";

type Phase = "idle" | "connecting" | "listening" | "finishing" | "done";

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
  { value: "auto", zh: "自动检测", en: "Auto detect" },
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

/** Join finalized sentences + the live interim into one transcript. CJK
 * boundaries get no separator; Latin boundaries get a single space. */
function joinSegments(parts: string[]): string {
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

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function RealtimeTranscriptionPanel({ onComplete }: Props) {
  const { t } = useI18n();

  const [phase, setPhase] = useState<Phase>("idle");
  const [language, setLanguage] = useState("auto");
  const [model, setModel] = useState(REALTIME_ASR_MODELS[0].id);
  const [finalized, setFinalized] = useState<string[]>([]);
  const [interim, setInterim] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<Error | null>(null);
  const [info, setInfo] = useState("");
  const [saving, setSaving] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const muteGainRef = useRef<GainNode | null>(null);
  const finalizedRef = useRef<string[]>([]);
  const wordsRef = useRef<WordTimestamp[]>([]);
  const languageRef = useRef(language);
  const modelRef = useRef(model);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const finishTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const transcriptBoxRef = useRef<HTMLDivElement | null>(null);
  const aliveRef = useRef(true);

  languageRef.current = language;
  modelRef.current = model;

  const displayTranscript = joinSegments([...finalized, interim]);
  const finalizedText = joinSegments(finalized);
  let interimPart = interim;
  if (finalizedText && interim) {
    const last = [...finalizedText].slice(-1)[0] || "";
    const first = [...interim][0] || "";
    const needsSpace = !isCjk(last) && !isCjk(first) && !/\s$/.test(finalizedText);
    interimPart = (needsSpace ? " " : "") + interim;
  }

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startTimer = useCallback(() => {
    stopTimer();
    setElapsed(0);
    timerRef.current = setInterval(() => setElapsed((value) => value + 1), 1000);
  }, [stopTimer]);

  const clearFinishTimeout = useCallback(() => {
    if (finishTimeoutRef.current !== null) {
      clearTimeout(finishTimeoutRef.current);
      finishTimeoutRef.current = null;
    }
  }, []);

  const cleanupAudio = useCallback(() => {
    processorRef.current?.disconnect();
    sourceRef.current?.disconnect();
    muteGainRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current = null;
    muteGainRef.current = null;

    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;

    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context) {
      void context.close().catch(() => {});
    }
  }, []);

  const handleServerMessage = useCallback(
    (data: RealtimeServerMessage) => {
      switch (data.type) {
        case "started":
          setPhase("listening");
          break;
        case "sentence":
          if (data.sentence_end) {
            finalizedRef.current = [...finalizedRef.current, data.text];
            setFinalized(finalizedRef.current);
            setInterim("");
            // Only final results carry stable per-word timestamps; interim
            // sentences are partial and get overwritten. Accumulate so the
            // saved job can drive precise SRT/VTT export.
            if (data.words && data.words.length) {
              wordsRef.current = [...wordsRef.current, ...data.words];
            }
          } else {
            setInterim(data.text);
          }
          break;
        case "finished":
          clearFinishTimeout();
          stopTimer();
          setInterim("");
          setPhase("done");
          break;
        case "error":
          clearFinishTimeout();
          stopTimer();
          setError(
            new Error(data.message || t("实时转写出错。", "Realtime transcription error."))
          );
          setPhase("idle");
          break;
        default:
          break;
      }
    },
    [clearFinishTimeout, stopTimer, t]
  );

  // Auto-scroll the transcript to the newest text.
  useEffect(() => {
    const box = transcriptBoxRef.current;
    if (box) {
      box.scrollTop = box.scrollHeight;
    }
  }, [finalized, interim]);

  // Tear everything down on unmount.
  useEffect(() => {
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
          // Ignore close failures during teardown.
        }
      }
    };
  }, [stopTimer, clearFinishTimeout, cleanupAudio]);

  async function start() {
    setError(null);
    setInfo("");
    setInterim("");
    finalizedRef.current = [];
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
          // Ignore close failures during teardown.
        }
        return;
      }
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        if (wsRef.current !== ws) return;
        const hints = LANGUAGE_OPTIONS.find((option) => option.value === languageRef.current)?.hints;
        ws.send(JSON.stringify({ type: "config", model: modelRef.current, ...(hints ? { language_hints: hints } : {}) }));

        const source = audioContext.createMediaStreamSource(stream);
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

        source.connect(processor);
        processor.connect(muteGain);
        muteGain.connect(audioContext.destination);
        sourceRef.current = source;
        processorRef.current = processor;
        muteGainRef.current = muteGain;
      };

      ws.onmessage = (message) => {
        if (wsRef.current !== ws || typeof message.data !== "string") return;
        try {
          handleServerMessage(JSON.parse(message.data) as RealtimeServerMessage);
        } catch {
          // Ignore malformed frames.
        }
      };

      ws.onerror = () => {
        if (wsRef.current !== ws) return;
        setError(
          new Error(
            t(
              "实时转写连接失败。请确认后端正在运行，并且已配置 DashScope API Key。",
              "Realtime transcription connection failed. Confirm the backend is running and the DashScope API key is set."
            )
          )
        );
      };

      ws.onclose = () => {
        cleanupAudio();
        stopTimer();
        clearFinishTimeout();
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        setPhase((current) => (current === "done" ? current : "idle"));
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
    // Stop capturing immediately; keep the socket open to drain final results.
    cleanupAudio();
    stopTimer();
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      setPhase("finishing");
      ws.send(JSON.stringify({ type: "finish" }));
      clearFinishTimeout();
      finishTimeoutRef.current = setTimeout(() => {
        finishTimeoutRef.current = null;
        setInterim("");
        setPhase("done");
        try {
          ws.close();
        } catch {
          // Ignore.
        }
      }, 15000);
    } else {
      setPhase("done");
    }
  }

  function reset() {
    setPhase("idle");
    setInterim("");
    finalizedRef.current = [];
    setFinalized([]);
    wordsRef.current = [];
    setElapsed(0);
    setError(null);
    setInfo("");
  }

  async function handleSave() {
    const text = displayTranscript.trim();
    if (!text) return;
    setSaving(true);
    setError(null);
    try {
      const savedWords = wordsRef.current;
      const job = await saveTranscriptionText(
        text,
        t("实时转写", "Realtime transcription"),
        savedWords
      );
      onComplete(job, savedWords);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setSaving(false);
    }
  }

  function handleCopy() {
    const text = displayTranscript.trim();
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      setInfo(t("文稿已复制到剪贴板", "Transcript copied to clipboard."));
      setTimeout(() => setInfo(""), 3000);
    });
  }

  const running = phase === "connecting" || phase === "listening" || phase === "finishing";

  const statusText = (() => {
    switch (phase) {
      case "connecting":
        return t("正在连接…", "Connecting…");
      case "listening":
        return t("正在聆听，开始说话吧…", "Listening, start speaking…");
      case "finishing":
        return t("正在整理最后的内容…", "Wrapping up the last words…");
      case "done":
        return t("本次实时转写已结束。", "This realtime session has ended.");
      default:
        return t("点击下方按钮开始实时转写。", "Click below to start realtime transcription.");
    }
  })();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <div className="vsField" style={{ gap: "8px" }}>
        <label
          className="vsFieldLabel"
          style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}
        >
          {t("识别模型", "Recognition model")}
        </label>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={running}
          className="vsSelect"
          style={{ width: "100%", height: "44px", borderRadius: "10px", fontSize: "14px" }}
        >
          {REALTIME_ASR_MODELS.map((option) => (
            <option key={option.id} value={option.id}>
              {t(option.zh, option.en)}
            </option>
          ))}
        </select>
        <span style={{ fontSize: "12px", color: "var(--muted)", lineHeight: 1.4 }}>
          {(() => {
            const selected = REALTIME_ASR_MODELS.find((option) => option.id === model);
            return selected ? t(selected.noteZh, selected.noteEn) : "";
          })()}
        </span>
      </div>

      <div className="vsField" style={{ gap: "8px" }}>
        <label
          className="vsFieldLabel"
          style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}
        >
          {t("识别语言", "Recognition language")}
        </label>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          disabled={running}
          className="vsSelect"
          style={{ width: "100%", height: "44px", borderRadius: "10px", fontSize: "14px" }}
        >
          {LANGUAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.zh, option.en)}
            </option>
          ))}
        </select>
      </div>

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
            {interim && <span style={{ color: "var(--muted)" }}>{interimPart}</span>}
          </>
        ) : (
          <span style={{ color: "var(--muted)" }}>
            {t(
              "转写结果会实时显示在这里…",
              "Live transcription will appear here…"
            )}
          </span>
        )}
      </div>

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
        {running || phase === "done" ? <span>{formatElapsed(elapsed)}</span> : null}
      </div>

      {phase === "done" ? (
        <div style={{ display: "flex", gap: "10px" }}>
          <button
            onClick={handleSave}
            disabled={!displayTranscript.trim() || saving}
            className="vsBtnPrimary"
            style={{ flex: 1, height: "44px", fontSize: "14px", borderRadius: "10px", fontWeight: 600 }}
          >
            {saving ? (
              <>
                <span className="spinner-mini" /> {t("保存中…", "Saving…")}
              </>
            ) : (
              t("保存到转写库", "Save to library")
            )}
          </button>
          <button
            onClick={handleCopy}
            disabled={!displayTranscript.trim()}
            className="vsBtnSecondary"
            style={{ height: "44px", padding: "0 16px", fontSize: "14px", borderRadius: "10px", fontWeight: 600 }}
          >
            {t("复制", "Copy")}
          </button>
          <button
            onClick={reset}
            className="vsBtnGhost"
            style={{ height: "44px", padding: "0 16px", fontSize: "14px", borderRadius: "10px", fontWeight: 600 }}
          >
            {t("重新开始", "Restart")}
          </button>
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
          {phase === "listening" && t("结束录音", "Stop recording")}
          {phase === "finishing" && (
            <>
              <span className="spinner-mini" /> {t("整理中…", "Wrapping up…")}
            </>
          )}
          {phase === "idle" && t("开始实时转写", "Start realtime transcription")}
        </button>
      )}

      {info && (
        <span style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>{info}</span>
      )}
      {error && <ErrorNotice message={error.message || String(error)} scope="Transcription" />}
    </div>
  );
}

export default RealtimeTranscriptionPanel;
