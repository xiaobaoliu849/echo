import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ErrorNotice from "./ErrorNotice";

const BASE_ERROR = "AUTH_TOKEN_INVALID: Invalid token (request_id: req_test_001)";

function setClipboardWriteText(writeText: (value: string) => Promise<void>) {
  Object.defineProperty(globalThis.navigator, "clipboard", {
    value: { writeText },
    configurable: true
  });
}

describe("ErrorNotice", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it("renders null for empty message", () => {
    const { container } = render(<ErrorNotice message="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders code and request_id meta", () => {
    render(<ErrorNotice message={BASE_ERROR} scope="chat" />);
    expect(screen.getByText("code: AUTH_TOKEN_INVALID")).toBeInTheDocument();
    expect(screen.getByText("request_id: req_test_001")).toBeInTheDocument();
  });

  it("shows provider configuration hints for missing TTS API keys", () => {
    render(
      <ErrorNotice
        message="TTS_SPEAK_DEPENDENCY_ERROR: Xiaomi API Key is not configured. (request_id: req_tts_001)"
        scope="tts"
      />
    );

    expect(screen.getByText("Open Settings and fill the API Key for the selected TTS provider.")).toBeInTheDocument();
    expect(screen.getByText("Save settings, then retry synthesis with the same voice.")).toBeInTheDocument();
  });

  it("renders request_id as log link when log url is configured", () => {
    vi.stubEnv("VITE_LOG_SEARCH_BASE_URL", "https://logs.example/search");
    render(<ErrorNotice message={BASE_ERROR} scope="chat" />);

    const link = screen.getByRole("link", { name: "request_id: req_test_001" });
    expect(link).toHaveAttribute("href", "https://logs.example/search?request_id=req_test_001");
  });

  it("copies request_id and resets button label after timeout", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboardWriteText(writeText);

    render(<ErrorNotice message={BASE_ERROR} scope="chat" />);
    const button = screen.getByRole("button", { name: "复制请求 ID" });
    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
    });

    expect(writeText).toHaveBeenCalledWith("req_test_001");
    expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("请求 ID 已复制。");

    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(screen.getByRole("button", { name: "复制请求 ID" })).toBeInTheDocument();
  });

  it("shows fallback text when clipboard copy fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    setClipboardWriteText(writeText);

    render(<ErrorNotice message={BASE_ERROR} scope="chat" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "复制请求 ID" }));
      await Promise.resolve();
    });

    expect(screen.getByRole("status")).toHaveTextContent("复制失败，请手动复制。");
  });

  it("copies diagnostics payload", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-05T13:14:15.000Z"));
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboardWriteText(writeText);

    render(
      <ErrorNotice
        message={BASE_ERROR}
        scope="chat"
        context={{
          provider: "DashScope",
          model: "qwen-plus",
          backend_auth_enabled: false
        }}
      />
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "复制诊断信息" }));
      await Promise.resolve();
    });

    expect(writeText).toHaveBeenCalledTimes(1);
    const payload = writeText.mock.calls[0][0] as string;
    expect(payload).toContain("scope=chat");
    expect(payload).toContain("path=/");
    expect(payload).toMatch(/frontend_version=\S+/);
    expect(payload).toContain("user_agent=");
    expect(payload).toContain("code=AUTH_TOKEN_INVALID");
    expect(payload).toContain("request_id=req_test_001");
    expect(payload).toContain("log_search_url=N/A");
    expect(payload).toContain("context.model=qwen-plus");
    expect(payload).toContain("context.provider=DashScope");
    expect(payload).toContain("context.backend_auth_enabled=false");
    expect(payload).toContain("generated_at=2026-03-05T13:14:15.000Z");
    expect(screen.getByRole("status")).toHaveTextContent("诊断信息已复制。");
  });

  it("toggles diagnostic details panel", async () => {
    render(<ErrorNotice message={BASE_ERROR} scope="chat" />);
    expect(screen.queryByText("诊断信息")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    });
    expect(screen.getByText("诊断信息")).toBeInTheDocument();
    expect(screen.getByText(/code=AUTH_TOKEN_INVALID/)).toBeInTheDocument();
    expect(screen.getByText(/scope=chat/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "隐藏详情" })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "隐藏详情" }));
    });
    expect(screen.queryByText("诊断信息")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看详情" })).toBeInTheDocument();
  });

  it("copies markdown issue template payload", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-05T15:16:17.000Z"));
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboardWriteText(writeText);

    render(
      <ErrorNotice
        message={BASE_ERROR}
        scope="chat"
        context={{
          provider: "DashScope",
          model: "qwen-plus",
          backend_auth_enabled: false
        }}
      />
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "复制问题模板" }));
      await Promise.resolve();
    });

    expect(writeText).toHaveBeenCalledTimes(1);
    const payload = writeText.mock.calls[0][0] as string;
    expect(payload).toContain("## Echo 错误报告");
    expect(payload).toContain("- 生成时间: 2026-03-05T15:16:17.000Z");
    expect(payload).toContain("- 模块: chat");
    expect(payload).toContain("- 页面路径: /");
    expect(payload).toMatch(/- 前端版本: \S+/);
    expect(payload).toContain("- 浏览器信息: ");
    expect(payload).toContain("- 错误代码: AUTH_TOKEN_INVALID");
    expect(payload).toContain("- 请求 ID: req_test_001");
    expect(payload).toContain("### 上下文");
    expect(payload).toContain("- model=qwen-plus");
    expect(payload).toContain("- backend_auth_enabled=false");
    expect(payload).toContain("- provider=DashScope");
    expect(payload).toContain("### 建议处理方式");
    expect(screen.getByRole("status")).toHaveTextContent("问题模板已复制。");
  });
});
