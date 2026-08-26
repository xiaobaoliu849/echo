import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SettingsPage from "./SettingsPage";
import { createSettingsController } from "../test/factories";

describe("SettingsPage", () => {
  it("renders provider settings by default", () => {
    render(<SettingsPage settings={createSettingsController()} errorRuntimeContext={{}} />);

    expect(screen.getByPlaceholderText("搜索供应商...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /手动编辑可用模型/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/WorkspaceId/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
  });

  it("switches between provider, memory, transcription, and desktop categories", () => {
    render(<SettingsPage settings={createSettingsController()} errorRuntimeContext={{}} />);

    fireEvent.click(screen.getByRole("button", { name: /提供商/i }));
    expect(screen.getByPlaceholderText("搜索供应商...")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /记忆/i }));
    expect(screen.getByText("EverMem 长期记忆中心")).toBeInTheDocument();
    expect(screen.getByText("启用长期记忆支持")).toBeInTheDocument();
    expect(screen.getByText("Echo × EverMind")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /转写/i }));
    expect(screen.getByText("文件转写与上传配置")).toBeInTheDocument();
    expect(screen.getByText("文件上传模式")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /系统/i }));
    expect(screen.getByText("系统与运行时状态")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "显示系统运行时日志" })).toBeInTheDocument();
    expect(screen.getByText("桌面偏好")).toBeInTheDocument();
    expect(screen.getByText("唤醒快捷键")).toBeInTheDocument();
    expect(screen.getByText("最近一次桌面预检")).toBeInTheDocument();
  });

  it("wires desktop runtime actions to settings handlers", () => {
    const settings = createSettingsController();
    render(<SettingsPage settings={settings} errorRuntimeContext={{}} />);

    fireEvent.click(screen.getByRole("button", { name: /系统/i }));
    fireEvent.click(screen.getByRole("button", { name: "显示系统运行时日志" }));
    fireEvent.click(screen.getByRole("button", { name: "复制运行时信息" }));

    expect(settings.onToggleRuntimeOpen).toHaveBeenCalledTimes(1);
    expect(settings.onCopyBackendRuntime).toHaveBeenCalledTimes(1);
  });

  it("shows recovery hints for the latest desktop launch error", () => {
    const base = createSettingsController();
    render(
      <SettingsPage
        settings={createSettingsController({
          desktopSection: {
            ...base.desktopSection,
            latestError: {
              available: true,
              timestamp: "2026-03-10T22:46:00+0800",
              error_type: "RuntimeError",
              message: "Backend is up, but /app is not reachable.",
              recovery_hints: [
                "确认 backend/main.py 仍挂载了 /app 和 /assets",
                "必要时清理桌面缓存：python run_web_desktop.py --clear-webview"
              ]
            }
          }
        })}
        errorRuntimeContext={{}}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /系统/i }));

    expect(screen.getByText("恢复建议")).toBeInTheDocument();
    expect(screen.getByText("确认 backend/main.py 仍挂载了 /app 和 /assets")).toBeInTheDocument();
    expect(screen.getByText("必要时清理桌面缓存：python run_web_desktop.py --clear-webview")).toBeInTheDocument();
  });

  it("wires desktop preference controls to settings handlers", () => {
    const settings = createSettingsController();
    render(<SettingsPage settings={settings} errorRuntimeContext={{}} />);

    fireEvent.click(screen.getByRole("button", { name: /系统/i }));
    fireEvent.click(screen.getByText("记住窗口位置"));
    fireEvent.click(screen.getByText("显示托盘图标"));
    fireEvent.change(screen.getByDisplayValue("Alt+Shift+S"), {
      target: { value: "Ctrl+Alt+V" }
    });

    expect(settings.onDesktopRememberWindowPositionChange).toHaveBeenCalledWith(false);
    expect(settings.onDesktopShowTrayIconChange).toHaveBeenCalledWith(true);
    expect(settings.onDesktopWakeShortcutChange).toHaveBeenCalledWith("Ctrl+Alt+V");
  });

  it("submits the settings form through the primary action", () => {
    const settings = createSettingsController();
    render(<SettingsPage settings={settings} errorRuntimeContext={{}} />);

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(settings.onSubmit).toHaveBeenCalledTimes(1);
    expect(settings.onSubmit).toHaveBeenCalledWith(expect.any(Object));
  });
});
