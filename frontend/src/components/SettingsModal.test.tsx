import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SettingsModal from "./SettingsModal";
import { createSettingsController } from "../test/factories";

// Keep the lazy-loaded settings page out of these lifecycle tests.
vi.mock("../pages/SettingsPage", async () => {
  const React = await import("react");
  return {
    __esModule: true,
    default: ({ onClose }: { onClose?: () => void }) =>
      React.createElement(
        "div",
        { "data-testid": "settings-page-stub" },
        React.createElement("button", { onClick: onClose }, "返回工作区")
      ),
  };
});

const settings = createSettingsController();

describe("SettingsModal desktop workspace", () => {
  it("renders the settings workspace when open", () => {
    render(<SettingsModal open onClose={() => {}} settings={settings} />);

    expect(screen.getByTestId("settings-page-stub")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
  });

  it("dismisses the settings workspace when clicking the backdrop", () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} settings={settings} />);

    const shell = document.querySelector(".vsSettingsModalShell");
    fireEvent.click(shell!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("dismisses the settings workspace on Escape key", () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} settings={settings} />);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("wires the back action from the settings page to onClose", () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} settings={settings} />);

    fireEvent.click(screen.getByRole("button", { name: "返回工作区" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
