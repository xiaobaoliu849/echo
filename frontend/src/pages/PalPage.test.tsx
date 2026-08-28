import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PalPage from "./PalPage";
import {
  createTavusConversation,
  endTavusConversation,
  listTavusPals
} from "../api";

const dailyMocks = vi.hoisted(() => ({
  createFrame: vi.fn()
}));

vi.mock("../api", () => ({
  getPersistedTavusApiKey: vi.fn(() => ""),
  getPersistedTavusPalId: vi.fn(() => ""),
  persistTavusApiKey: vi.fn(),
  persistTavusPalId: vi.fn(),
  listTavusPals: vi.fn(),
  createTavusConversation: vi.fn(),
  endTavusConversation: vi.fn()
}));

vi.mock("@daily-co/daily-js", () => ({
  default: {
    createFrame: dailyMocks.createFrame
  }
}));

function createCallMock() {
  return {
    join: vi.fn().mockResolvedValue({}),
    leave: vi.fn().mockResolvedValue(undefined),
    destroy: vi.fn(),
    on: vi.fn(),
    participants: vi.fn(() => ({}))
  };
}

function renderPage() {
  return render(
    <PalPage
      formatErrorMessage={(error) => (error instanceof Error ? error.message : String(error))}
      errorRuntimeContext={{}}
    />
  );
}

describe("PalPage", () => {
  beforeEach(() => {
    vi.mocked(listTavusPals).mockReset();
    vi.mocked(createTavusConversation).mockReset();
    vi.mocked(endTavusConversation).mockReset();
    vi.mocked(endTavusConversation).mockResolvedValue(undefined);
    dailyMocks.createFrame.mockReset();
  });

  it("renders the configuration panel", () => {
    renderPage();
    expect(screen.getByText("AI 视频分身")).toBeInTheDocument();
    expect(screen.getByTestId("pal-api-key-input")).toBeInTheDocument();
    expect(screen.getByTestId("pal-id-input")).toBeInTheDocument();
    expect(screen.getByTestId("pal-start-button")).toBeInTheDocument();
  });

  it("starts a conversation with the entered API key and PAL id", async () => {
    vi.mocked(listTavusPals).mockRejectedValue(new Error("not configured"));
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-1",
      conversation_url: "https://tavus.daily.co/room?t=token"
    });
    dailyMocks.createFrame.mockReturnValue(createCallMock());

    renderPage();

    fireEvent.change(screen.getByTestId("pal-api-key-input"), {
      target: { value: "key-1" }
    });
    fireEvent.change(screen.getByTestId("pal-id-input"), {
      target: { value: "pal-9" }
    });
    fireEvent.click(screen.getByTestId("pal-start-button"));

    await waitFor(() => {
      expect(screen.getByTestId("pal-leave-button")).toBeInTheDocument();
    });
    expect(createTavusConversation).toHaveBeenCalledWith({
      palId: "pal-9",
      conversationName: undefined
    });
    expect(screen.getByText("通话中")).toBeInTheDocument();
  });

  it("offers PALs from the account and starts with the selected one", async () => {
    vi.mocked(listTavusPals).mockResolvedValue({
      pals: [
        { pal_id: "pal-1", pal_name: "Mia" },
        { pal_id: "pal-2", pal_name: "Noah" }
      ]
    });
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-2",
      conversation_url: "https://tavus.daily.co/room?t=token"
    });
    dailyMocks.createFrame.mockReturnValue(createCallMock());

    renderPage();

    fireEvent.change(screen.getByTestId("pal-api-key-input"), {
      target: { value: "key-1" }
    });
    await waitFor(() => {
      expect(screen.getByTestId("pal-select")).toBeInTheDocument();
    });
    expect(screen.getByText("Mia")).toBeInTheDocument();
    expect(screen.queryByTestId("pal-id-input")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("pal-api-key-input"), {
      target: { value: "key-1" }
    });
    fireEvent.change(screen.getByTestId("pal-select"), {
      target: { value: "pal-2" }
    });
    fireEvent.click(screen.getByTestId("pal-start-button"));

    await waitFor(() => {
      expect(createTavusConversation).toHaveBeenCalledWith({
        palId: "pal-2",
        conversationName: undefined
      });
    });
  });

  it("returns to the configuration panel after leaving the call", async () => {
    vi.mocked(listTavusPals).mockRejectedValue(new Error("not configured"));
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-3",
      conversation_url: "https://tavus.daily.co/room?t=token"
    });
    dailyMocks.createFrame.mockReturnValue(createCallMock());

    renderPage();

    fireEvent.change(screen.getByTestId("pal-api-key-input"), {
      target: { value: "key-1" }
    });
    fireEvent.click(screen.getByTestId("pal-start-button"));

    await waitFor(() => {
      expect(screen.getByTestId("pal-leave-button")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("pal-leave-button"));

    await waitFor(() => {
      expect(screen.getByTestId("pal-start-button")).toBeInTheDocument();
    });
    expect(endTavusConversation).toHaveBeenCalledWith("conv-3");
    expect(screen.getByText("上一场通话已结束。")).toBeInTheDocument();
  });

  it("shows the failure message when the conversation cannot be created", async () => {
    vi.mocked(listTavusPals).mockRejectedValue(new Error("not configured"));
    vi.mocked(createTavusConversation).mockRejectedValue(new Error("boom"));

    renderPage();

    fireEvent.change(screen.getByTestId("pal-api-key-input"), {
      target: { value: "key-1" }
    });
    fireEvent.click(screen.getByTestId("pal-start-button"));

    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
    expect(screen.getByTestId("pal-start-button")).toBeInTheDocument();
  });
});
