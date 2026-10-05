import { useEffect, useRef, useState, type RefObject } from "react";

/** Activity in rendered audio, with a short silence hold to avoid syllable flicker. */
export function useAudioActivity(analyser: AnalyserNode | null | undefined, enabled: boolean, threshold = 0.01) {
  const [activity, setActivity] = useState<{ analyser: AnalyserNode; speaking: boolean } | null>(null);
  const thresholdRef = useRef(threshold);
  thresholdRef.current = threshold;
  useEffect(() => {
    if (!analyser || !enabled || typeof analyser.getFloatTimeDomainData !== "function") return;
    const samples = new Float32Array(analyser.fftSize);
    let lastSound = -Infinity;
    let speaking = false;
    const timer = window.setInterval(() => {
      let energy = 0;
      if (analyser.context.state === "running") {
        analyser.getFloatTimeDomainData(samples);
        for (const sample of samples) energy += sample * sample;
      }
      const rms = Math.sqrt(energy / samples.length);
      const now = performance.now();
      if (rms >= thresholdRef.current * (speaking ? 0.6 : 1)) lastSound = now;
      const next = analyser.context.state === "running" && now - lastSound < 320;
      if (next !== speaking) {
        speaking = next;
        setActivity({ analyser, speaking });
      }
    }, 80);
    return () => {
      window.clearInterval(timer);
      setActivity(null);
    };
  }, [analyser, enabled]);
  return Boolean(enabled && activity?.analyser === analyser && activity?.speaking);
}

type CapturableVideo = HTMLVideoElement & { captureStream?: () => MediaStream };

/** Capture a copy of the muxed audio. Never reroute or mute the native video. */
export function useAvatarAudioActivity(
  videoRef: RefObject<HTMLVideoElement | null>,
  context: AudioContext | null | undefined,
  active: boolean,
  stream: EventTarget,
) {
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  useEffect(() => {
    const video = videoRef.current as CapturableVideo | null;
    if (!video?.captureStream || !context || !active) return;
    let capture: MediaStream | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let meter: AnalyserNode | null = null;
    let silent: GainNode | null = null;
    const disconnect = () => {
      source?.disconnect();
      meter?.disconnect();
      silent?.disconnect();
      source = null;
      meter = null;
      silent = null;
      setAnalyser(null);
    };
    const connect = () => {
      disconnect();
      if (!capture?.getAudioTracks().some(track => track.readyState === "live") || context.state === "closed") return;
      try {
        source = context.createMediaStreamSource(capture);
        meter = context.createAnalyser();
        meter.fftSize = 1024;
        silent = context.createGain();
        silent.gain.value = 0;
        source.connect(meter);
        meter.connect(silent);
        silent.connect(context.destination);
        setAnalyser(meter);
      } catch { disconnect(); }
    };
    const stop = () => {
      disconnect();
      capture?.removeEventListener("addtrack", connect);
      capture?.removeEventListener("removetrack", connect);
      capture?.getTracks().forEach(track => track.stop());
      capture = null;
    };
    const start = () => {
      if (capture) return;
      try {
        capture = video.captureStream!();
        capture.addEventListener("addtrack", connect);
        capture.addEventListener("removetrack", connect);
        connect();
      } catch { stop(); }
    };
    video.addEventListener("playing", start);
    video.addEventListener("emptied", stop);
    stream.addEventListener("reset", stop);
    stream.addEventListener("interrupt", stop);
    if (!video.paused && video.readyState >= 2) start();
    return () => {
      video.removeEventListener("playing", start);
      video.removeEventListener("emptied", stop);
      stream.removeEventListener("reset", stop);
      stream.removeEventListener("interrupt", stop);
      stop();
    };
  }, [videoRef, context, active, stream]);
  return useAudioActivity(analyser, active);
}
