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
    const stored = {
      enabled: true,
      target_language: "Japanese",
      native_language: "Chinese",
      level: "ielts",
      tutor: true,
      scenario: "travel",
    } as const;
    writeStoredCoachConfig(stored);
    expect(readStoredCoachConfig()).toEqual(stored);
    localStorage.setItem("vs_speaking_coach", JSON.stringify({ enabled: true, level: "guru", scenario: "mars" }));
    expect(readStoredCoachConfig().level).toBe("intermediate");
    expect(readStoredCoachConfig().scenario).toBe("free_talk");
    expect(readStoredCoachConfig().tutor).toBe(false);
  });
});

describe("buildVoiceChatWebSocketUrl tutor params", () => {
  it("adds tutor query params only when tutor mode is requested", async () => {
    const { buildVoiceChatWebSocketUrl } = await import("../../api");
    const plain = new URL(buildVoiceChatWebSocketUrl({ provider: "DashScope" }));
    expect(plain.searchParams.has("tutor")).toBe(false);

    const tutored = new URL(
      buildVoiceChatWebSocketUrl({
        provider: "DashScope",
        tutor: { targetLanguage: "English", nativeLanguage: "Chinese", level: "ielts", scenario: "ielts" },
      })
    );
    expect(tutored.searchParams.get("tutor")).toBe("true");
    expect(tutored.searchParams.get("tutor_level")).toBe("ielts");
    expect(tutored.searchParams.get("tutor_scenario")).toBe("ielts");
    expect(tutored.searchParams.get("tutor_language")).toBe("English");
  });
});

describe("CoachFeedbackCard saving", () => {
  it("saves the corrected sentence and a phrase once each", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<CoachFeedbackCard feedback={IMPROVE} t={t} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { expanded: false }));

    fireEvent.click(screen.getByRole("button", { name: "Save this correction for review" }));
    fireEvent.click(screen.getByRole("button", { name: 'Save "stroll"' }));

    expect(onSave).toHaveBeenCalledWith({
      text: "I went to the park yesterday.",
      kind: "sentence",
      context: "I go to the park yesterday",
      sourceFeedbackId: 7,
    });
    expect(onSave).toHaveBeenCalledWith({
      text: "stroll",
      kind: "phrase",
      meaning: "a relaxed walk",
      context: "I went to the park yesterday.",
      sourceFeedbackId: 7,
    });
    expect(await screen.findAllByText("✓ Saved")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: 'Save "stroll"' }));
    expect(onSave).toHaveBeenCalledTimes(2);
  });
});
