import { useCallback, useEffect, useRef, useState } from "react";
import { createInlineTranslator, type UiLanguage } from "../i18n";
import { SCREEN_FRAME_INTERVAL_MS, SCREEN_FRAME_MAX_BYTES, SCREEN_FRAME_MAX_DIMENSION } from "../utils/liveScreenShare";

type Options = {
  enabled: boolean;
  getConnection: () => WebSocket | null;
  language: UiLanguage;
};

/** Capture belongs to one connection; pending pickers and frames cannot outlive it. */
export default function useLiveScreenShare({ enabled, getConnection, language }: Options) {
  const [sharing, setSharing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [source, setSource] = useState("");
  const generationRef = useRef(0);
  const pendingRef = useRef(false);
  const cleanupRef = useRef<(() => void) | null>(null);
  const optionsRef = useRef({ enabled, getConnection, language });
  optionsRef.current = { enabled, getConnection, language };
  const supported = typeof navigator.mediaDevices?.getDisplayMedia === "function";

  const stop = useCallback(() => {
    generationRef.current += 1;
    cleanupRef.current?.();
    cleanupRef.current = null;
    pendingRef.current = false;
    setSharing(false);
    setPending(false);
    setError("");
    setStream(null);
    setSource("");
  }, []);

  const start = useCallback(async () => {
    const options = optionsRef.current;
    const connection = options.getConnection();
    if (!options.enabled || !connection || connection.readyState !== WebSocket.OPEN || pendingRef.current || cleanupRef.current) return;
    const t = createInlineTranslator(options.language);
    setError("");
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setError(t("此运行环境不支持屏幕共享，请使用 Chrome、Edge 或 Electron 桌面版。", "Screen sharing is unavailable here. Use Chrome, Edge, or the Electron desktop app."));
      return;
    }
    const generation = ++generationRef.current;
    const current = () => generation === generationRef.current && optionsRef.current.enabled &&
      optionsRef.current.getConnection() === connection && connection.readyState === WebSocket.OPEN;
    pendingRef.current = true;
    setPending(true);
    let captured: MediaStream | null = null;
    try {
      // Invoke directly from the click, before any await, to preserve user activation.
      captured = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { ideal: 1, max: 1 } }, audio: false });
      if (!current()) {
        captured.getTracks().forEach(track => track.stop());
        return;
      }
      const track = captured.getVideoTracks()[0];
      if (!track || track.readyState === "ended") throw new Error("No live display track");
      const video = document.createElement("video");
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Canvas unavailable");
      video.muted = true;
      video.playsInline = true;
      video.srcObject = captured;
      let timer: ReturnType<typeof setTimeout> | null = null;
      const ended = () => stop();
      track.addEventListener("ended", ended);
      cleanupRef.current = () => {
        if (timer !== null) clearTimeout(timer);
        try {
          if (optionsRef.current.getConnection() === connection && connection.readyState === WebSocket.OPEN) {
            connection.send(JSON.stringify({ type: "screen_share_stopped" }));
          }
        } catch { /* A closing connection must not prevent capture cleanup. */ }
        track.removeEventListener("ended", ended);
        captured?.getTracks().forEach(item => item.stop());
        video.pause();
        video.srcObject = null;
        canvas.width = canvas.height = 0;
      };
      await video.play();
      if (!current()) {
        if (generation === generationRef.current) stop();
        return;
      }
      pendingRef.current = false;
      setPending(false);
      setSharing(true);
      setStream(captured);
      setSource(track.label || t("所选屏幕或窗口", "Selected screen or window"));

      const capture = () => {
        if (!current()) { stop(); return; }
        try {
          // Drop frames under backpressure; never queue screenshots behind speech.
          if (video.videoWidth && video.videoHeight && connection.bufferedAmount < 128 * 1024) {
            const scale = Math.min(1, SCREEN_FRAME_MAX_DIMENSION / Math.max(video.videoWidth, video.videoHeight));
            canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
            canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            let data = canvas.toDataURL("image/jpeg", 0.7).split(",")[1] || "";
            if (data.length > SCREEN_FRAME_MAX_BYTES * 4 / 3) data = canvas.toDataURL("image/jpeg", 0.4).split(",")[1] || "";
            if (data && data.length <= SCREEN_FRAME_MAX_BYTES * 4 / 3 && current()) {
              connection.send(JSON.stringify({ type: "screen_frame", mime_type: "image/jpeg", data }));
            }
          }
          timer = setTimeout(capture, SCREEN_FRAME_INTERVAL_MS);
        } catch {
          stop();
          setError(t("屏幕共享已停止，请重新选择窗口。", "Screen sharing stopped. Select a window again."));
        }
      };
      capture();
    } catch (err) {
      captured?.getTracks().forEach(track => track.stop());
      if (generation === generationRef.current) {
        stop();
        const name = err && typeof err === "object" && "name" in err ? String(err.name) : "";
        if (name !== "NotAllowedError" && name !== "AbortError") {
          setError(t("无法共享屏幕，请检查屏幕录制权限，或使用 Chrome、Edge、Electron 桌面版。", "Could not share the screen. Check screen recording permissions, or use Chrome, Edge, or the Electron desktop app."));
        }
      }
    } finally {
      if (generation === generationRef.current) {
        pendingRef.current = false;
        setPending(false);
      }
    }
  }, [stop]);

  useEffect(() => { if (!enabled) stop(); }, [enabled, stop]);
  useEffect(() => () => stop(), [stop]);
  const reject = useCallback((message: string) => { stop(); setError(message); }, [stop]);
  return { sharing, pending, error, stream, source, supported, start, stop, reject };
}
