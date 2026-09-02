import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LiveCaptionDrawer from "./LiveCaptionDrawer";
import { createVoiceChatController } from "../../test/factories";
import * as api from "../../api";

vi.mock("../../api", async () => {
  const actual = await vi.importActual("../../api");
  return {
    ...actual,
    translateText: vi.fn(),
  };
});

describe("LiveCaptionDrawer", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not render when isOpen is false", () => {
    const voiceChat = createVoiceChatController();
    const { container } = render(
      <LiveCaptionDrawer voiceChat={voiceChat} isOpen={false} onToggle={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders empty notice when there are no messages or active stream", () => {
    const voiceChat = createVoiceChatController({
      sessionSummary: [],
      voiceChatTranscript: "",
      voiceChatReply: "",
    });
    render(
      <LiveCaptionDrawer voiceChat={voiceChat} isOpen={true} onToggle={vi.fn()} />
    );

    expect(screen.getByText(/等待语音输入中/)).toBeInTheDocument();
    expect(screen.getByText("实时双语字幕")).toBeInTheDocument();
  });

  it("renders live streaming user transcript and assistant reply", () => {
    const voiceChat = createVoiceChatController({
      voiceChatTranscript: "I want to improve my speaking score",
      voiceChatReply: "Practice talking about varied topics every day",
    });

    const { container } = render(
      <LiveCaptionDrawer voiceChat={voiceChat} isOpen={true} onToggle={vi.fn()} />
    );

    expect(screen.getByText("我 (正在说...)")).toBeInTheDocument();
    expect(container).toHaveTextContent("I want to improve my speaking score");
    expect(screen.getByText("Echo (正在回复...)")).toBeInTheDocument();
    expect(container).toHaveTextContent("Practice talking about varied topics every day");
  });

  it("toggles font size when clicking font size button", () => {
    const voiceChat = createVoiceChatController({
      voiceChatTranscript: "Testing font size",
    });

    const { container } = render(
      <LiveCaptionDrawer voiceChat={voiceChat} isOpen={true} onToggle={vi.fn()} />
    );

    const drawer = container.querySelector(".vsLiveCaptionDrawer");
    expect(drawer).not.toHaveClass("vsFontLarge");

    const fontBtn = screen.getByLabelText("字幕字号切换");
    fireEvent.click(fontBtn);

    expect(drawer).toHaveClass("vsFontLarge");

    fireEvent.click(fontBtn);
    expect(drawer).not.toHaveClass("vsFontLarge");
  });

  it("calls onToggle when clicking close button", () => {
    const onToggle = vi.fn();
    const voiceChat = createVoiceChatController();

    render(
      <LiveCaptionDrawer voiceChat={voiceChat} isOpen={true} onToggle={onToggle} />
    );

    const closeBtn = screen.getByLabelText("收起字幕");
    fireEvent.click(closeBtn);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("triggers word lookup when clicking on an interactive word", async () => {
    vi.mocked(api.translateText).mockResolvedValueOnce({
      translated_text: "提高，改善",
      provider: "DashScope",
      model: "test-model",
    });

    const voiceChat = createVoiceChatController({
      voiceChatTranscript: "I want to improve my speaking",
    });

    render(
      <LiveCaptionDrawer voiceChat={voiceChat} isOpen={true} onToggle={vi.fn()} />
    );

    const wordEl = screen.getByText("improve");
    fireEvent.click(wordEl);

    expect(screen.getByText("正在查询释义...")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("提高，改善")).toBeInTheDocument();
    });
  });

  it("renders past session messages with translate action", async () => {
    vi.mocked(api.translateText).mockResolvedValueOnce({
      translated_text: "今天天气很好",
      provider: "DashScope",
      model: "test-model",
    });

    const voiceChat = createVoiceChatController({
      sessionSummary: [
        { role: "assistant", content: "The weather is very nice today." },
      ],
      voiceChatTranscript: "",
      voiceChatReply: "",
    });

    const { container } = render(
      <LiveCaptionDrawer voiceChat={voiceChat} isOpen={true} onToggle={vi.fn()} />
    );

    expect(screen.getByText("Echo")).toBeInTheDocument();
    expect(container).toHaveTextContent("The weather is very nice today.");

    const translateBtn = screen.getByTitle("翻译整句");
    fireEvent.click(translateBtn);

    await waitFor(() => {
      expect(screen.getByText("今天天气很好")).toBeInTheDocument();
    });
  });
});
