import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ProviderSettingsSection from "./ProviderSettingsSection";
import { createSettingsController } from "../../test/factories";

describe("ProviderSettingsSection", () => {
  it("opens and closes the custom provider modal properly", () => {
    const settings = createSettingsController();
    render(<ProviderSettingsSection settings={settings} />);

    // Modal is initially not present
    expect(screen.queryByText("添加自定义 OpenAI 兼容服务商")).not.toBeInTheDocument();

    // Click to open modal
    fireEvent.click(screen.getByRole("button", { name: /添加自定义服务商/i }));
    expect(screen.getByText("添加自定义 OpenAI 兼容服务商")).toBeInTheDocument();

    // Close via cancel button
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByText("添加自定义 OpenAI 兼容服务商")).not.toBeInTheDocument();

    // Reopen and close via close icon button
    fireEvent.click(screen.getByRole("button", { name: /添加自定义服务商/i }));
    expect(screen.getByText("添加自定义 OpenAI 兼容服务商")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByText("添加自定义 OpenAI 兼容服务商")).not.toBeInTheDocument();

    // Reopen and close via Escape key
    fireEvent.click(screen.getByRole("button", { name: /添加自定义服务商/i }));
    expect(screen.getByText("添加自定义 OpenAI 兼容服务商")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("添加自定义 OpenAI 兼容服务商")).not.toBeInTheDocument();

    // Reopen and close via backdrop click
    fireEvent.click(screen.getByRole("button", { name: /添加自定义服务商/i }));
    const overlay = document.querySelector(".vsModalOverlay");
    expect(overlay).toBeInTheDocument();
    fireEvent.click(overlay!);
    expect(screen.queryByText("添加自定义 OpenAI 兼容服务商")).not.toBeInTheDocument();
  });

  it("validates required fields and submits valid custom provider", async () => {
    const onAddCustomProvider = vi.fn();
    const settings = createSettingsController({ onAddCustomProvider });
    render(<ProviderSettingsSection settings={settings} />);

    fireEvent.click(screen.getByRole("button", { name: /添加自定义服务商/i }));

    // Submit with empty name
    fireEvent.click(screen.getByRole("button", { name: "确认添加" }));
    expect(screen.getByText("请输入服务商名称")).toBeInTheDocument();
    expect(onAddCustomProvider).not.toHaveBeenCalled();

    // Fill name but omit base url
    fireEvent.change(screen.getByPlaceholderText("例如: MyLocalOllama"), {
      target: { value: "MyOllama" }
    });
    fireEvent.click(screen.getByRole("button", { name: "确认添加" }));
    expect(screen.getByText("请输入 Base URL")).toBeInTheDocument();

    // Fill invalid headers JSON
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "http://localhost:11434/v1" }
    });
    fireEvent.change(screen.getByPlaceholderText('{"User-Agent": "CustomApp/1.0"}'), {
      target: { value: "{bad-json" }
    });
    fireEvent.click(screen.getByRole("button", { name: "确认添加" }));
    expect(screen.getByText("请求头 JSON 格式无效")).toBeInTheDocument();

    // Fix JSON and submit
    fireEvent.change(screen.getByPlaceholderText('{"User-Agent": "CustomApp/1.0"}'), {
      target: { value: '{"X-Custom": "1"}' }
    });
    fireEvent.change(screen.getByPlaceholderText("输入 API Key (若无需可留空)"), {
      target: { value: "ollama-key" }
    });
    fireEvent.click(screen.getByLabelText(/max_completion_tokens/i));
    fireEvent.click(screen.getByRole("button", { name: "确认添加" }));

    expect(onAddCustomProvider).toHaveBeenCalledWith(
      "MyOllama",
      "http://localhost:11434/v1",
      "ollama-key",
      true,
      '{"X-Custom": "1"}'
    );
    expect(screen.queryByText("添加自定义 OpenAI 兼容服务商")).not.toBeInTheDocument();
  });
});
