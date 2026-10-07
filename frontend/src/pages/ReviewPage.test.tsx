import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LearningItem, LearningStats } from "../api";
import { deleteLearningItem, fetchDueReviews, fetchLearningItems, submitReview } from "../api";
import ReviewPage from "./ReviewPage";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchDueReviews: vi.fn(),
    fetchLearningItems: vi.fn(),
    submitReview: vi.fn(),
    deleteLearningItem: vi.fn(),
    fetchSpeakAudio: vi.fn(),
  };
});

function makeItem(overrides: Partial<LearningItem>): LearningItem {
  return {
    id: 1,
    language: "English",
    kind: "phrase",
    text: "thoroughly enjoyed",
    meaning: "非常享受",
    context: "We thoroughly enjoyed the film.",
    source_feedback_id: null,
    review_step: 0,
    review_count: 0,
    lapse_count: 0,
    due_at: "2026-10-07T00:00:00Z",
    last_reviewed_at: "",
    created_at: "2026-10-07T00:00:00Z",
    ...overrides,
  };
}

const STATS: LearningStats = { total_items: 2, due_now: 2, learned_items: 0, reviewed_today: 0, recalled_today: 0 };

describe("ReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("walks the due queue: prompt → reveal → grade, then shows done state", async () => {
    const phrase = makeItem({ id: 1 });
    const sentence = makeItem({
      id: 2,
      kind: "sentence",
      text: "I went to the park yesterday.",
      meaning: "",
      context: "I go to the park yesterday",
    });
    vi.mocked(fetchDueReviews).mockResolvedValue({ items: [phrase, sentence], stats: STATS });
    vi.mocked(fetchLearningItems).mockResolvedValue([phrase, sentence]);
    vi.mocked(submitReview)
      .mockResolvedValueOnce({ item: { ...phrase, review_step: 1 }, stats: { ...STATS, due_now: 1, reviewed_today: 1 } })
      .mockResolvedValueOnce({ item: { ...sentence, review_step: 0 }, stats: { ...STATS, due_now: 0, reviewed_today: 2 } });

    render(<ReviewPage />);

    // Phrase card prompts with the native-language meaning, answer hidden.
    expect(await screen.findByText("非常享受")).toBeTruthy();
    expect(screen.queryByText("thoroughly enjoyed")).toBeNull();

    fireEvent.keyDown(window, { key: " " });
    expect(screen.getByText("thoroughly enjoyed")).toBeTruthy();
    fireEvent.keyDown(window, { key: "2" });
    await waitFor(() => expect(submitReview).toHaveBeenCalledWith(1, "good"));

    // Sentence card prompts with the learner's original mistake.
    expect(await screen.findByText("I go to the park yesterday")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Show answer|显示答案/ }));
    fireEvent.click(screen.getByRole("button", { name: /Again|没记住/ }));
    await waitFor(() => expect(submitReview).toHaveBeenCalledWith(2, "again"));

    expect(await screen.findByText(/All caught up|今天的复习都完成了/)).toBeTruthy();
  });

  it("shows onboarding hint when nothing is saved and deletes from the list", async () => {
    vi.mocked(fetchDueReviews).mockResolvedValue({
      items: [],
      stats: { ...STATS, total_items: 0, due_now: 0 },
    });
    vi.mocked(fetchLearningItems).mockResolvedValue([]);
    render(<ReviewPage />);
    expect(await screen.findByText(/Nothing saved yet|还没有收藏/)).toBeTruthy();
  });

  it("deletes a saved item from the full list", async () => {
    const item = makeItem({ id: 5, due_at: "2099-01-01T00:00:00Z" });
    vi.mocked(fetchDueReviews).mockResolvedValue({ items: [], stats: { ...STATS, total_items: 1, due_now: 0 } });
    vi.mocked(fetchLearningItems).mockResolvedValue([item]);
    vi.mocked(deleteLearningItem).mockResolvedValue();
    render(<ReviewPage />);

    fireEvent.click(await screen.findByRole("button", { name: /All saved|全部收藏/ }));
    fireEvent.click(screen.getByRole("button", { name: /Delete "thoroughly enjoyed"|删除「thoroughly enjoyed」/ }));
    await waitFor(() => expect(deleteLearningItem).toHaveBeenCalledWith(5));
    await waitFor(() => expect(screen.queryByText("thoroughly enjoyed")).toBeNull());
  });
});
