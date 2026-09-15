import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PalPage, { getRollingSubtitleText } from "./PalPage";
import {
  createTavusConversation,
  endTavusConversation,
  getPersistedTavusPalId,
  listTavusFaces,
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
  listTavusFaces: vi.fn(),
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
    vi.mocked(getPersistedTavusPalId).mockReturnValue("");
    vi.mocked(listTavusPals).mockReset();
    vi.mocked(listTavusPals).mockResolvedValue({ pals: [] });
    vi.mocked(listTavusFaces).mockReset();
    vi.mocked(listTavusFaces).mockResolvedValue({ faces: [] });
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

  it("passes the selected Phoenix 4.5 face into the conversation", async () => {
    vi.mocked(listTavusFaces).mockResolvedValue({ faces: [
      { face_id: "old", face_name: "Old", model_name: "phoenix-3", status: "completed" },
      { face_id: "face45", face_name: "Brooke", model_name: "phoenix-4.5", status: "completed" },
      { face_id: "training", face_name: "Training", model_name: "phoenix-4.5", status: "started" },
    ] });
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "new-model", conversation_url: "https://tavus.daily.co/room",
    });
    dailyMocks.createFrame.mockReturnValue(createCallMock());
    renderPage();
    await screen.findByRole("option", { name: "Brooke · Phoenix 4.5" });
    const select = screen.getByTestId("pal-face-select") as HTMLSelectElement;
    expect(select.options[1].value).toBe("face45");
    expect(screen.getByRole("option", { name: "Training · Phoenix 4.5 (started)" })).toBeDisabled();
    fireEvent.change(screen.getByTestId("pal-id-input"), { target: { value: "pal" } });
    fireEvent.change(select, { target: { value: "face45" } });
    fireEvent.click(screen.getByTestId("pal-start-button"));
    await waitFor(() => expect(createTavusConversation).toHaveBeenCalledWith({
      palId: "pal", faceId: "face45", conversationName: undefined,
    }));
  });

  it("allows manual Face ID when listing fails", async () => {
    vi.mocked(listTavusFaces).mockRejectedValue(new Error("upstream unavailable"));
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "manual", conversation_url: "https://tavus.daily.co/room",
    });
    dailyMocks.createFrame.mockReturnValue(createCallMock());
    renderPage();
    await screen.findByRole("alert");
    fireEvent.change(screen.getByTestId("pal-face-select"), { target: { value: "__manual_face__" } });
    fireEvent.change(screen.getByTestId("pal-face-id-input"), { target: { value: " face45 " } });
    fireEvent.click(screen.getByTestId("pal-start-button"));
    await waitFor(() => expect(createTavusConversation).toHaveBeenCalledWith({
      palId: undefined, faceId: "face45", conversationName: undefined,
    }));
  });

  it("restores the selected PAL instead of replacing it with the first result", async () => {
    vi.mocked(getPersistedTavusPalId).mockReturnValue("saved");
    vi.mocked(listTavusPals).mockResolvedValue({ pals: [
      { pal_id: "first", pal_name: "First" }, { pal_id: "saved", pal_name: "Saved" },
    ] });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("pal-select")).toHaveValue("saved"));
  });

  it("shows all Phoenix versions and resolves the PAL default without upgrading it", async () => {
    vi.mocked(listTavusPals).mockResolvedValue({ pals: [
      { pal_id: "gloria", pal_name: "Gloria", default_face_id: "face4" },
    ] });
    vi.mocked(listTavusFaces).mockResolvedValue({ faces: [
      { face_id: "face3", face_name: "Classic", model_name: "phoenix-3", status: "completed" },
      { face_id: "face4", face_name: "Gloria - Studio", model_name: "phoenix-4", status: "completed" },
      { face_id: "face45", face_name: "Brooke", model_name: "phoenix-4.5", status: "completed" },
    ] });
    vi.mocked(createTavusConversation).mockResolvedValue({ conversation_id: "default", conversation_url: "https://tavus.daily.co/room" });
    dailyMocks.createFrame.mockReturnValue(createCallMock());
    renderPage();
    await waitFor(() => expect(screen.getByTestId("pal-effective-face")).toHaveTextContent("Gloria - Studio · Phoenix 4"));
    for (const version of ["3", "4", "4.5"]) {
      expect(screen.getByRole("group", { name: `Phoenix ${version} · 1` })).toBeInTheDocument();
    }
    expect(screen.getByTestId("pal-face-select")).toHaveValue("");
    fireEvent.click(screen.getByTestId("pal-start-button"));
    await waitFor(() => expect(createTavusConversation).toHaveBeenCalledWith({
      palId: "gloria", faceId: undefined, conversationName: undefined,
    }));
  });

  it.each(["phoenix-3", "phoenix-4", "phoenix-4.5"])("starts with an explicitly selected %s face", async (model) => {
    vi.mocked(listTavusFaces).mockResolvedValue({ faces: [
      { face_id: "selected-face", face_name: "Selected", model_name: model, status: "completed" },
    ] });
    vi.mocked(createTavusConversation).mockResolvedValue({ conversation_id: "id", conversation_url: "https://tavus.daily.co/room" });
    dailyMocks.createFrame.mockReturnValue(createCallMock());
    renderPage();
    await screen.findByRole("option", { name: `Selected · ${model.replace("phoenix-", "Phoenix ")}` });
    fireEvent.change(screen.getByTestId("pal-face-select"), { target: { value: "selected-face" } });
    expect(screen.getByTestId("pal-effective-face")).toHaveTextContent(model.replace("phoenix-", "Phoenix "));
    fireEvent.click(screen.getByTestId("pal-start-button"));
    await waitFor(() => expect(createTavusConversation).toHaveBeenCalledWith({
      palId: undefined, faceId: "selected-face", conversationName: undefined,
    }));
  });

  it("does not label an unknown default as Phoenix 4.5", async () => {
    renderPage();
    expect(screen.getByTestId("pal-effective-face")).toHaveTextContent("模型尚未确认");
  });

  it("blocks an unready default face and allows a ready override", async () => {
    vi.mocked(listTavusPals).mockResolvedValue({ pals: [
      { pal_id: "pal", pal_name: "Role", default_face_id: "training" },
    ] });
    vi.mocked(listTavusFaces).mockResolvedValue({ faces: [
      { face_id: "training", face_name: "Training", model_name: "phoenix-4.5", status: "started" },
      { face_id: "ready", face_name: "Ready", model_name: "phoenix-4", status: "completed" },
    ] });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("pal-start-button")).toBeDisabled());
    fireEvent.change(screen.getByTestId("pal-face-select"), { target: { value: "ready" } });
    expect(screen.getByTestId("pal-start-button")).toBeEnabled();
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

  it("supports subtitles toggle and opening the transcript drawer during a call", async () => {
    vi.mocked(listTavusPals).mockRejectedValue(new Error("not configured"));
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-live",
      conversation_url: "https://tavus.daily.co/room?t=token"
    });
    const call = createCallMock();
    dailyMocks.createFrame.mockReturnValue(call);

    renderPage();

    fireEvent.change(screen.getByTestId("pal-api-key-input"), {
      target: { value: "key-1" }
    });
    fireEvent.click(screen.getByTestId("pal-start-button"));

    await waitFor(() => {
      expect(screen.getByTestId("pal-toggle-subtitles-button")).toBeInTheDocument();
    });

    // Toggle subtitles button
    fireEvent.click(screen.getByTestId("pal-toggle-subtitles-button"));
    expect(screen.getByTestId("pal-toggle-subtitles-button")).toHaveAttribute("aria-label", "开启字幕");

    // Open transcript drawer
    expect(screen.getByTestId("pal-toggle-drawer-button")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("pal-toggle-drawer-button"));

    expect(screen.getByText(/实时速记/)).toBeInTheDocument();
  });

  it("shows post-call summary and allows dismissing via Back to Setup and Close buttons", async () => {
    vi.mocked(listTavusPals).mockRejectedValue(new Error("not configured"));
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-summary-test",
      conversation_url: "https://tavus.daily.co/room?t=token"
    });
    const call = createCallMock();
    dailyMocks.createFrame.mockReturnValue(call);

    renderPage();

    fireEvent.change(screen.getByTestId("pal-api-key-input"), {
      target: { value: "key-1" }
    });
    fireEvent.click(screen.getByTestId("pal-start-button"));

    await waitFor(() => {
      expect(screen.getByTestId("pal-leave-button")).toBeInTheDocument();
    });

    // Simulate incoming speech transcript
    const appMessageHandler = call.on.mock.calls.find(([name]) => name === "app-message")?.[1];
    expect(appMessageHandler).toBeDefined();
    appMessageHandler?.({
      data: {
        event_type: "conversation.utterance",
        properties: { text: "Hello from Tavus AI", role: "assistant" }
      }
    });

    // Hang up call
    fireEvent.click(screen.getByTestId("pal-leave-button"));

    // Verify summary card appears with messages
    await waitFor(() => {
      expect(screen.getByText("通话已结束")).toBeInTheDocument();
      expect(screen.getByText("Hello from Tavus AI")).toBeInTheDocument();
      expect(screen.getByTestId("pal-close-summary-button")).toBeInTheDocument();
      expect(screen.getByTestId("pal-dismiss-summary-button")).toBeInTheDocument();
    });

    // Verify close button contains svg icon and has Esc title
    const closeBtn = screen.getByTestId("pal-close-summary-button");
    expect(closeBtn.querySelector("svg")).toBeInTheDocument();
    expect(closeBtn).toHaveAttribute("title", "关闭 (Esc)");

    // Dismiss summary via Close button
    fireEvent.click(closeBtn);

    // Verify returning to configuration panel
    await waitFor(() => {
      expect(screen.queryByText("通话已结束")).not.toBeInTheDocument();
      expect(screen.getByTestId("pal-start-button")).toBeInTheDocument();
    });
  });

  it("dismisses post-call summary when pressing Escape key", async () => {
    vi.mocked(listTavusPals).mockRejectedValue(new Error("not configured"));
    vi.mocked(createTavusConversation).mockResolvedValue({
      conversation_id: "conv-esc-test",
      conversation_url: "https://tavus.daily.co/room?t=token"
    });
    const call = createCallMock();
    dailyMocks.createFrame.mockReturnValue(call);

    renderPage();

    fireEvent.change(screen.getByTestId("pal-api-key-input"), {
      target: { value: "key-1" }
    });
    fireEvent.click(screen.getByTestId("pal-start-button"));

    await waitFor(() => {
      expect(screen.getByTestId("pal-leave-button")).toBeInTheDocument();
    });

    const appMessageHandler = call.on.mock.calls.find(([name]) => name === "app-message")?.[1];
    appMessageHandler?.({
      data: {
        event_type: "conversation.utterance",
        properties: { text: "Escape test speech", role: "assistant" }
      }
    });

    fireEvent.click(screen.getByTestId("pal-leave-button"));

    await waitFor(() => {
      expect(screen.getByText("通话已结束")).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByText("通话已结束")).not.toBeInTheDocument();
      expect(screen.getByTestId("pal-start-button")).toBeInTheDocument();
    });
  });
});

describe("getRollingSubtitleText", () => {
  it("returns empty string when given empty input", () => {
    expect(getRollingSubtitleText("")).toBe("");
  });

  it("returns short text directly without modification", () => {
    expect(getRollingSubtitleText("Hello world!")).toBe("Hello world!");
    expect(getRollingSubtitleText("你好世界！")).toBe("你好世界！");
  });

  it("rolls Latin text exceeding latinMax characters with leading ellipsis", () => {
    const longEnglish = "The quick brown fox jumps over the lazy dog repeatedly until the sentence becomes extremely long and exceeds limits.";
    const result = getRollingSubtitleText(longEnglish, 40);
    expect(result.startsWith("… ")).toBe(true);
    expect(result.length).toBeLessThanOrEqual(45);
  });

  it("rolls CJK text exceeding cjkMax characters with leading ellipsis", () => {
    const longChinese = "这是一段非常长的中文实时对话转录文本，当用户连续不断地说了很多话的时候，字幕不能停滞卡死，而是应该平滑地滚动显示最新的一句话。";
    const result = getRollingSubtitleText(longChinese, 120, 25);
    expect(result.startsWith("… ")).toBe(true);
    expect(result.length).toBeLessThanOrEqual(28);
  });
});

