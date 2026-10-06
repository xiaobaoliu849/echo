import { useEffect, useRef } from "react";

export type CallVisualState = "connecting" | "idle" | "user" | "thinking" | "replying" | "muted";

type Props = {
  state: CallVisualState;
  micAnalyser: AnalyserNode | null;
  assistantAnalyser: AnalyserNode | null;
};

const BAR_COUNT = 11;
const CENTER = (BAR_COUNT - 1) / 2;
const MIN_PX = 4;
const MAX_PX = 22;
// Below this mean bin energy (0-255) a source counts as silent.
const SILENCE = 6;

/** Mean energy of the voice band plus per-band shape (skips the DC bin). */
function readVoice(analyser: AnalyserNode, buffer: Uint8Array<ArrayBuffer>, bands: Float32Array): number {
  analyser.getByteFrequencyData(buffer);
  // fftSize 64 gives ~375-750 Hz per bin, so bins 1..6 cover speech.
  let sum = 0;
  for (let i = 0; i < bands.length; i += 1) {
    const value = buffer[Math.min(i + 1, buffer.length - 1)] ?? 0;
    bands[i] = value / 255;
    sum += value;
  }
  return sum / bands.length;
}

/**
 * Mirrored bar waveform for a live call. The loudest speech band sits in the
 * middle and tapers outward, so the shape reads as "a voice" rather than a
 * spectrum. Whoever is audible drives it (assistant wins over the mic); the
 * state only picks the colour and the idle motion. Heights are written
 * straight to the DOM from one rAF loop to avoid re-rendering React per frame.
 */
export default function CallWaveform({ state, micAnalyser, assistantAnalyser }: Props) {
  const rootRef = useRef<HTMLSpanElement>(null);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof requestAnimationFrame !== "function") return;
    const bars = Array.from(root.querySelectorAll<HTMLElement>(".vsCallWaveBar"));
    const reduceMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const micBuffer = micAnalyser ? new Uint8Array(micAnalyser.frequencyBinCount) : null;
    const assistantBuffer = assistantAnalyser ? new Uint8Array(assistantAnalyser.frequencyBinCount) : null;
    const bandCount = CENTER + 1;
    const micBands = new Float32Array(bandCount);
    const assistantBands = new Float32Array(bandCount);
    const heights = new Float32Array(BAR_COUNT).fill(MIN_PX);
    let level = 0;
    let frame = 0;

    const tick = (now: number) => {
      const current = stateRef.current;
      const assistantLevel = assistantAnalyser && assistantBuffer
        ? readVoice(assistantAnalyser, assistantBuffer, assistantBands) : 0;
      const micLevel = current !== "muted" && micAnalyser && micBuffer
        ? readVoice(micAnalyser, micBuffer, micBands) : 0;
      const useAssistant = assistantLevel >= SILENCE && assistantLevel >= micLevel;
      const sourceLevel = useAssistant ? assistantLevel : micLevel;
      const bands = useAssistant ? assistantBands : micBands;
      const audible = sourceLevel >= SILENCE;
      // Perceptual curve so quiet speech still moves the bars visibly.
      const targetLevel = audible ? Math.min(1, Math.sqrt((sourceLevel - SILENCE) / 90)) : 0;
      level += (targetLevel - level) * (targetLevel > level ? 0.5 : 0.12);
      const time = now / 1000;

      for (let i = 0; i < BAR_COUNT; i += 1) {
        const distance = Math.abs(i - CENTER);
        let amount = 0;
        if (audible) {
          // Bell envelope keeps the centre tallest; the band adds texture.
          // Muting only silences the mic, so the assistant still animates.
          const envelope = Math.exp(-(distance * distance) / 10);
          const band = bands[Math.round(distance)] ?? 0;
          amount = level * envelope * (0.55 + 0.45 * Math.min(1, band * 1.6));
        } else if (current === "muted") {
          amount = 0;
        } else if (!reduceMotion && current === "thinking") {
          // A soft pulse travelling outward from the centre.
          amount = 0.18 + 0.22 * Math.max(0, Math.sin(time * 5 - distance * 0.9));
        } else if (!reduceMotion && current === "connecting") {
          amount = 0.1 + 0.12 * (0.5 + 0.5 * Math.sin(time * 3));
        } else if (!reduceMotion) {
          // Idle breathing so a connected call never looks frozen.
          amount = 0.06 * (0.5 + 0.5 * Math.sin(time * 2.2 - i * 0.55));
        }
        const target = MIN_PX + (MAX_PX - MIN_PX) * Math.min(1, amount);
        const previous = heights[i] ?? MIN_PX;
        const next = previous + (target - previous) * (target > previous ? 0.45 : 0.18);
        heights[i] = next;
        const bar = bars[i];
        if (bar) bar.style.height = `${next.toFixed(1)}px`;
      }
      root.style.setProperty("--call-level", level.toFixed(3));
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [micAnalyser, assistantAnalyser]);

  return (
    <span ref={rootRef} className="vsCallWave" aria-hidden="true">
      {Array.from({ length: BAR_COUNT }, (_, i) => <span key={i} className="vsCallWaveBar" />)}
    </span>
  );
}
