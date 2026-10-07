import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CoachFeedback } from "../../api";
import { coachTextKey, readStoredCoachConfig, writeStoredCoachConfig } from "../../utils/speakingCoach";
import CoachFeedbackCard from "./CoachFeedbackCard";

const t = (_zh: string, en: string) => en;

const IMPROVE: CoachFeedback = {
  id: 7,
  verdict: "improve",
  user_text: "I go to the park yesterday",
  corrected: "I went to the park yesterday.",
  issues: [{ type: "grammar", original: "I go", suggestion: "I went", explanation: "Past tense" }],
  vocabulary: [{ term: "stroll", meaning: "a relaxed walk" }],
  tip: "Mind your tenses.",
};

describe("CoachFeedbackCard", () => {
  it("shows the correction and expands into details with a dismiss action", () => {
    const onDismiss = vi.fn();
    render(<CoachFeedbackCard feedback={IMPROVE} t={t} onDismiss={onDismiss} />);

    expect(screen.getByText("I went to the park yesterday.")).toBeTruthy();
    expect(screen.queryByText("Past tense")).toBeNull();

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText("Past tense")).toBeTruthy();
    expect(screen.getByText("stroll")).toBeTruthy();

    fireEvent.click(screen.getByText("Misheard or wrong — remove"));
    expect(onDismiss).toHaveBeenCalledWith(7);
  });

  it("renders a compact positive note for good utterances", () => {
    render(
      <CoachFeedbackCard
        feedback={{ ...IMPROVE, verdict: "good", corrected: "", issues: [], vocabulary: [], tip: "" }}
        t={t}
      />
    );
    expect(screen.getByText("✓ Natural")).toBeTruthy();
    expect(screen.getByText("Well said")).toBeTruthy();
  });
});

describe("speakingCoach utils", () => {
  afterEach(() => localStorage.clear());

  it("matches utterances regardless of case and punctuation", () => {
    expect(coachTextKey("I went, to the park!")).toBe(coachTextKey("i went to the park"));
    expect(coachTextKey("  ")).toBe("");
  });

  it("round-trips stored config and rejects invalid levels", () => {
    expect(readStoredCoachConfig().enabled).toBe(false);
    writeStoredCoachConfig({ enabled: true, target_language: "Japanese", native_language: "Chinese", level: "ielts" });
    expect(readStoredCoachConfig()).toEqual({
      enabled: true,
      target_language: "Japanese",
      native_language: "Chinese",
      level: "ielts",
    });
    localStorage.setItem("vs_speaking_coach", JSON.stringify({ enabled: true, level: "guru" }));
    expect(readStoredCoachConfig().level).toBe("intermediate");
  });
});
