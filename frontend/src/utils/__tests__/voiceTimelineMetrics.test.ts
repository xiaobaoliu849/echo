import { describe, expect, it } from "vitest";
import type { VoiceAgentTimelineEventHistory } from "../../api";
import { buildVoiceTimelineMetrics } from "../voiceTimelineMetrics";

describe("voiceTimelineMetrics", () => {
  it("returns all nulls and zero count for empty timeline", () => {
    const metrics = buildVoiceTimelineMetrics([]);
    expect(metrics).toEqual({
      firstAudioMs: null,
      interruptionDecisionMs: null,
      decisionCount: 0,
      falseInterruptionRate: null,
    });
  });

  it("calculates firstAudioMs average from assistant_audio_started events", () => {
    const timeline = [
      {
        id: "1",
        session_id: "s1",
        event_type: "assistant_audio_started",
        source: "assistant",
        payload: { first_audio_ms: 300 },
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "2",
        session_id: "s1",
        event_type: "assistant_audio_started",
        source: "assistant",
        payload: { elapsed_ms: 500 }, // fallback to elapsed_ms
        created_at: "2026-01-01T00:00:01Z",
      },
    ] as unknown as VoiceAgentTimelineEventHistory[];

    const metrics = buildVoiceTimelineMetrics(timeline);
    expect(metrics.firstAudioMs).toBe(400); // (300 + 500) / 2
    expect(metrics.decisionCount).toBe(0);
    expect(metrics.interruptionDecisionMs).toBeNull();
    expect(metrics.falseInterruptionRate).toBeNull();
  });

  it("calculates interruption metrics, decision count, and false interruption rate", () => {
    const timeline = [
      {
        id: "1",
        session_id: "s1",
        event_type: "interruption_decision",
        source: "system",
        payload: { classification: "TRUE_BARGE_IN", decision_latency_ms: 120 },
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "2",
        session_id: "s1",
        event_type: "interruption_decision",
        source: "system",
        payload: { classification: "FALSE_ALARM", decision_latency_ms: 180 },
        created_at: "2026-01-01T00:00:01Z",
      },
      {
        id: "3",
        session_id: "s1",
        event_type: "interruption_decision",
        source: "system",
        payload: { classification: "BACKCHANNEL", elapsed_ms: 240 },
        created_at: "2026-01-01T00:00:02Z",
      },
      {
        id: "4",
        session_id: "s1",
        event_type: "interruption_decision",
        source: "system",
        payload: { classification: "TRUE_BARGE_IN", decision_latency_ms: 100 },
        created_at: "2026-01-01T00:00:03Z",
      },
    ] as unknown as VoiceAgentTimelineEventHistory[];

    const metrics = buildVoiceTimelineMetrics(timeline);
    expect(metrics.decisionCount).toBe(4);
    // (120 + 180 + 240 + 100) / 4 = 640 / 4 = 160
    expect(metrics.interruptionDecisionMs).toBe(160);
    // 2 non-TRUE_BARGE_IN out of 4 decisions = 0.5
    expect(metrics.falseInterruptionRate).toBe(0.5);
  });

  it("handles non-finite or missing numeric fields gracefully", () => {
    const timeline = [
      {
        id: "1",
        session_id: "s1",
        event_type: "assistant_audio_started",
        source: "assistant",
        payload: { first_audio_ms: "invalid" as unknown as number },
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "2",
        session_id: "s1",
        event_type: "interruption_decision",
        source: "system",
        payload: { classification: "TRUE_BARGE_IN", decision_latency_ms: NaN },
        created_at: "2026-01-01T00:00:01Z",
      },
    ] as unknown as VoiceAgentTimelineEventHistory[];

    const metrics = buildVoiceTimelineMetrics(timeline);
    expect(metrics.firstAudioMs).toBeNull();
    expect(metrics.interruptionDecisionMs).toBeNull();
    expect(metrics.decisionCount).toBe(1);
    expect(metrics.falseInterruptionRate).toBe(0);
  });
});
