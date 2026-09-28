import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import VoiceTrajectoryHeatmap from "./VoiceTrajectoryHeatmap";
import * as api from "../api";

describe("VoiceTrajectoryHeatmap", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders trajectory stats and streak information", async () => {
    vi.spyOn(api, "fetchVoiceAgentTrajectory").mockResolvedValue({
      current_streak: 5,
      longest_streak: 14,
      total_seconds: 3600,
      total_turns: 48,
      total_sessions: 6,
      active_days: 12,
      peak_day: {
        date: "2026-09-28",
        duration_seconds: 1800,
        turn_count: 24,
      },
      daily_activity: {
        "2026-09-28": {
          date: "2026-09-28",
          duration_seconds: 1800,
          turn_count: 24,
          session_count: 2,
          user_words: 300,
          assistant_words: 450,
          level: 4,
        },
      },
    });

    const onClose = vi.fn();
    render(<VoiceTrajectoryHeatmap onClose={onClose} />);

    // Wait for data load
    await waitFor(() => {
      expect(screen.getByText("5")).toBeInTheDocument(); // current streak
      expect(screen.getByText("14")).toBeInTheDocument(); // longest streak
      expect(screen.getByText("48")).toBeInTheDocument(); // turns
      expect(screen.getByText("12")).toBeInTheDocument(); // active days
    });

    // Check title
    expect(screen.getByText(/语音练习足迹|Voice Practice Trajectory/)).toBeInTheDocument();

    // Check close button
    const closeBtn = screen.getByRole("button", { name: "Close" });
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("switches range when range button is clicked", async () => {
    const spy = vi.spyOn(api, "fetchVoiceAgentTrajectory").mockResolvedValue({
      current_streak: 0,
      longest_streak: 0,
      total_seconds: 0,
      total_turns: 0,
      total_sessions: 0,
      active_days: 0,
      peak_day: null,
      daily_activity: {},
    });

    render(<VoiceTrajectoryHeatmap initialDays={180} />);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(180);
    });

    // Switch to 90 days
    const btn90 = screen.getByRole("button", { name: /近3个月|3 Months/ });
    fireEvent.click(btn90);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(90);
    });
  });
});
