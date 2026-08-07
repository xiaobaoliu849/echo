import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
  it("renders minimize, maximize, and close controls", () => {
    render(<SettingsModal open onClose={() => {}} settings={settings} />);

    expect(screen.getByRole("button", { name: "最小化" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "最大化" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭" })).toBeInTheDocument();
  });

  it("minimize hides the panel without touching the app window", () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} settings={settings} />);

    fireEvent.click(screen.getByRole("button", { name: "最小化" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("maximize expands the panel to fill the window and restores on a second click", () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} settings={settings} />);

    const stage = document.querySelector(".vsSettingsModalStage");
    const shell = document.querySelector(".vsSettingsModalShell");
    expect(stage).not.toHaveClass("maximized");
    expect(shell).not.toHaveClass("maximized");

    fireEvent.click(screen.getByRole("button", { name: "最大化" }));

    expect(stage).toHaveClass("maximized");
    expect(shell).toHaveClass("maximized");
    expect(screen.getByRole("button", { name: "还原" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "还原" }));

    expect(stage).not.toHaveClass("maximized");
    expect(shell).not.toHaveClass("maximized");
    expect(screen.getByRole("button", { name: "最大化" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("close still dismisses the modal", () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} settings={settings} />);

    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
