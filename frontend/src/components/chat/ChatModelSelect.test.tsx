import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ChatModelSelect from "./ChatModelSelect";
import { createChatController } from "../../test/factories";

const t = (zh: string, _en: string) => zh;

const SEP = "";

const CHOICES = [
  { provider: "DashScope", model: "qwen3.5-plus", label: "DashScope / qwen3.5-plus", value: `DashScope${SEP}qwen3.5-plus` },
  { provider: "DashScope", model: "qwen3.5-livetranslate-flash-realtime", label: "DashScope / qwen3.5-livetranslate-flash-realtime", value: `DashScope${SEP}qwen3.5-livetranslate-flash-realtime` },
  { provider: "DashScope", model: "qwen3.5-flash", label: "DashScope / qwen3.5-flash", value: `DashScope${SEP}qwen3.5-flash` },
  { provider: "DashScope", model: "qwen3.5-omni-plus-realtime", label: "DashScope / qwen3.5-omni-plus-realtime", value: `DashScope${SEP}qwen3.5-omni-plus-realtime` },
  { provider: "Google", model: "gemini-3.5-flash", label: "Google / gemini-3.5-flash", value: `Google${SEP}gemini-3.5-flash` },
  { provider: "Google", model: "gemini-3.1-flash-live-preview", label: "Google / gemini-3.1-flash-live-preview", value: `Google${SEP}gemini-3.1-flash-live-preview` },
];

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, "innerHeight", { writable: true, configurable: true, value: 768 });
});

function renderSelect(overrides: Parameters<typeof createChatController>[0] = {}, onOpenSettings?: () => void) {
  const chat = createChatController({
    chatProvider: "DashScope",
    chatModel: "qwen3.5-plus",
    chatModelChoiceValue: `DashScope${SEP}qwen3.5-plus`,
    chatModelChoices: CHOICES,
    ...overrides,
  });
  render(<ChatModelSelect chat={chat} t={t} onOpenSettings={onOpenSettings} />);
  return chat;
}

function openPanel() {
  fireEvent.click(screen.getByTitle("切换模型"));
  return screen.getByRole("dialog", { name: "切换模型" });
}

describe("ChatModelSelect", () => {
  it("shows the current provider and model in the summary pill", () => {
    renderSelect();
    const summary = screen.getByTitle("切换模型");
    expect(summary).toHaveTextContent("DashScope / qwen3.5-plus");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a placeholder when no model is selected", () => {
    renderSelect({ chatModel: "", chatModelChoiceValue: "" });
    expect(screen.getByTitle("切换模型")).toHaveTextContent("选择模型");
  });

  it("opens only the provider list first, then flies out models on provider hover", () => {
    renderSelect();
    openPanel();
    // Level 1 only: providers visible, no models yet
    expect(screen.getByText("DashScope")).toBeInTheDocument();
    expect(screen.getByText("Google")).toBeInTheDocument();
    expect(screen.queryByText("qwen3.5-plus")).not.toBeInTheDocument();

    // Hover Level 1 provider to open Level 2 model flyout
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    expect(screen.getByText("qwen3.5-plus")).toBeInTheDocument();
    expect(screen.getByText("qwen3.5-flash")).toBeInTheDocument();
    // Google models stay hidden until Google is hovered
    expect(screen.queryByText("gemini-3.5-flash")).not.toBeInTheDocument();

    fireEvent.mouseEnter(screen.getByText("Google"));
    expect(screen.getByText("gemini-3.5-flash")).toBeInTheDocument();
    expect(screen.queryByText("qwen3.5-plus")).not.toBeInTheDocument();
  });

  it("marks the current provider and current model as selected", () => {
    renderSelect();
    openPanel();
    expect(screen.getByText("DashScope").closest("button")).toHaveClass("selected");
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    const currentModel = screen.getByText("qwen3.5-plus").closest("button");
    expect(currentModel).toHaveClass("selected");
    expect(currentModel).toHaveAttribute("aria-current", "true");
  });

  it("shows realtime hints only for realtime-capable models", () => {
    renderSelect();
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    expect(screen.getByText("实时翻译")).toBeInTheDocument();
    expect(screen.getByText("全模态实时")).toBeInTheDocument();
    // Plain text models have no hint
    expect(screen.getByText("qwen3.5-plus").closest("button")).not.toHaveTextContent("实时");
    expect(screen.getByText("qwen3.5-flash").closest("button")).not.toHaveTextContent("实时");
  });

  it("calls onModelChoiceChange with the choice value and closes the panel", () => {
    const chat = renderSelect();
    openPanel();
    fireEvent.mouseEnter(screen.getByText("Google"));
    fireEvent.click(screen.getByText("gemini-3.5-flash"));
    expect(chat.onModelChoiceChange).toHaveBeenCalledWith(`Google${SEP}gemini-3.5-flash`);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens model management from the footer and closes the panel", () => {
    const onOpenSettings = vi.fn();
    renderSelect({}, onOpenSettings);
    openPanel();
    fireEvent.click(screen.getByText("管理模型"));
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("always shows a Done button in the footer that closes the panel", () => {
    renderSelect();
    openPanel();
    fireEvent.click(screen.getByText("完成"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on Escape and on outside pointer down", () => {
    renderSelect();
    openPanel();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    openPanel();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("aligns the model flyout with the hovered provider row, not the panel top", () => {
    // jsdom has no layout engine; simulate row offsets so the alignment can be asserted.
    vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockImplementation(function (this: HTMLElement) {
      const text = this.textContent || "";
      if (text.includes("Google")) return 48;
      if (text.includes("DashScope")) return 6;
      return 0;
    });
    renderSelect();
    openPanel();

    fireEvent.mouseEnter(screen.getByText("DashScope"));
    expect(screen.getByText("qwen3.5-plus").closest(".vsModelFlyout")).toHaveStyle("top: 6px");

    fireEvent.mouseEnter(screen.getByText("Google"));
    expect(screen.getByText("gemini-3.5-flash").closest(".vsModelFlyout")).toHaveStyle("top: 48px");
  });

  it("resets hover state when reopened so only Level 1 shows", () => {
    renderSelect();
    openPanel();
    fireEvent.mouseEnter(screen.getByText("DashScope"));
    expect(screen.getByText("qwen3.5-plus")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    openPanel();
    expect(screen.queryByText("qwen3.5-plus")).not.toBeInTheDocument();
  });
});
