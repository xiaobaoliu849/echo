import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SettingsModal from "./SettingsModal";
import { createSettingsController } from "../test/factories";

// Keep the lazy-loaded settings page out of these window-control tests.
vi.mock("../pages/SettingsPage", async () => {
  const React = await import("react");
  return {
    __esModule: true,
    default: () => React.createElement("div", { "data-testid": "settings-page-stub" }, "stub"),
  };
});

const settings = createSettingsController();

describe("SettingsModal window controls", () => {
  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).pywebview;
  });

  it("hides minimize/maximize buttons outside the desktop shell", () => {
    render(<SettingsModal open onClose={() => {}} settings={settings} />);

    expect(screen.queryByRole("button", { name: "最小化" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "最大化" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭" })).toBeInTheDocument();
  });

  it("wires minimize/maximize to the desktop bridge in desktop mode", () => {
    const minimizeWindow = vi.fn().mockResolvedValue({ ok: true });
    const toggleMaximizeWindow = vi.fn().mockResolvedValue({ ok: true });
    Object.defineProperty(window, "pywebview", {
      configurable: true,
      value: { api: { minimize_window: minimizeWindow, toggle_maximize_window: toggleMaximizeWindow } },
    });

    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} settings={settings} />);

    fireEvent.click(screen.getByRole("button", { name: "最小化" }));
    expect(minimizeWindow).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "最大化" }));
    expect(toggleMaximizeWindow).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps close working in desktop mode", () => {
    Object.defineProperty(window, "pywebview", {
      configurable: true,
      value: { api: {} },
    });

    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} settings={settings} />);

    expect(screen.getByRole("button", { name: "最小化" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "最大化" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("is a no-op when the desktop bridge is missing a method", () => {
    Object.defineProperty(window, "pywebview", {
      configurable: true,
      value: { api: {} },
    });

    render(<SettingsModal open onClose={() => {}} settings={settings} />);

    expect(() => {
      fireEvent.click(screen.getByRole("button", { name: "最小化" }));
      fireEvent.click(screen.getByRole("button", { name: "最大化" }));
    }).not.toThrow();
  });
});
