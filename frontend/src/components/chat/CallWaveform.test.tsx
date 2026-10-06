import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CallWaveform from "./CallWaveform";

function analyser(level: number): AnalyserNode {
  return {
    frequencyBinCount: 32,
    getByteFrequencyData: (buffer: Uint8Array) => buffer.fill(level),
  } as unknown as AnalyserNode;
}

function runFrames(count: number) {
  const callbacks: FrameRequestCallback[] = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    callbacks.push(cb);
    return callbacks.length;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  return () => {
    for (let i = 0; i < count; i += 1) callbacks.shift()?.(i * 16);
  };
}

const heights = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLElement>(".vsCallWaveBar")).map((bar) => parseFloat(bar.style.height));

describe("CallWaveform", () => {
  afterEach(() => vi.restoreAllMocks());

  it("grows a centre-weighted, mirrored shape from live audio", () => {
    const flush = runFrames(30);
    const { container } = render(<CallWaveform state="user" micAnalyser={analyser(200)} assistantAnalyser={null} />);
    flush();
    const bars = heights(container);
    expect(bars).toHaveLength(11);
    const centre = bars[5];
    expect(centre).toBeGreaterThan(15);
    expect(centre).toBeGreaterThan(bars[0]);
    expect(bars[1]).toBeCloseTo(bars[9], 5);
  });

  it("ignores the microphone while muted", () => {
    const flush = runFrames(30);
    const { container } = render(<CallWaveform state="muted" micAnalyser={analyser(200)} assistantAnalyser={null} />);
    flush();
    expect(Math.max(...heights(container))).toBeLessThan(5);
  });

  it("still shows the assistant's voice while the mic is muted", () => {
    const flush = runFrames(30);
    const { container } = render(<CallWaveform state="muted" micAnalyser={analyser(0)} assistantAnalyser={analyser(200)} />);
    flush();
    expect(Math.max(...heights(container))).toBeGreaterThan(15);
  });
});
