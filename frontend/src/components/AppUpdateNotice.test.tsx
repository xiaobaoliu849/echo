import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { AppUpdaterState } from "../hooks/useAppUpdater";
import AppUpdateNotice from "./AppUpdateNotice";
import UpdateCard from "./UpdateCard";

let state: AppUpdaterState;
let listeners: Set<(state: AppUpdaterState) => void>;
beforeEach(() => {
  localStorage.clear();
  state = { revision: 1, phase: "available", appVersion: "1.0.1", updateInfo: { version: "1.0.2", releaseNotes: "A useful fix\n<script>bad()</script>" }, progress: null, errorMessage: null, lastChecked: 1234567 };
  listeners = new Set();
  window.isElectron = true;
  window.electronAPI = {
    getUpdateState: vi.fn(async () => state),
    onUpdateState: cb => { listeners.add(cb); return () => { listeners.delete(cb); }; },
    getAppVersion: vi.fn(async () => "1.0.1"),
    checkForUpdates: vi.fn(async () => ({ success: true })),
    downloadUpdate: vi.fn(async () => ({ success: true })),
    installUpdate: vi.fn(async () => ({ success: true, cancelled: true })),
  };
});
afterEach(() => { delete window.isElectron; delete window.electronAPI; });
function push(patch: Partial<AppUpdaterState>) {
  state = { ...state, ...patch, revision: state.revision + 1 };
  act(() => listeners.forEach(cb => cb(state)));
}
function renderNotice() {
  return render(<I18nProvider language="en-US"><AppUpdateNotice onOpenUpdates={() => {}} /></I18nProvider>);
}

it("only shows a dismissible notice for a new release and routes to Settings", async () => {
  const onOpenUpdates = vi.fn();
  const view = render(<I18nProvider language="en-US"><AppUpdateNotice onOpenUpdates={onOpenUpdates} /></I18nProvider>);
  expect(await screen.findByRole("status", { name: "Update notification" })).toHaveTextContent("1.0.2");
  fireEvent.click(screen.getByRole("button", { name: "View in Settings" }));
  expect(onOpenUpdates).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Dismiss this version" }));
  expect(screen.queryByRole("status")).toBeNull();
  view.unmount();
  renderNotice();
  await act(async () => {});
  expect(screen.queryByRole("status")).toBeNull();
  push({ updateInfo: { version: "1.0.3", releaseNotes: "Newer" } });
  expect(screen.getByRole("status")).toHaveTextContent("1.0.3");
  push({ phase: "up-to-date" });
  expect(screen.queryByRole("status")).toBeNull();
});

it("settings card displays safe notes, download progress and explicit install", async () => {
  render(<I18nProvider language="en-US"><UpdateCard /></I18nProvider>);
  expect(await screen.findByText(/A useful fix/)).toHaveTextContent("<script>bad()</script>");
  expect(document.querySelector("section script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Download update" }));
  await waitFor(() => expect(window.electronAPI?.downloadUpdate).toHaveBeenCalledOnce());
  push({ phase: "downloading", progress: null });
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
  push({ phase: "downloading", progress: { percent: 42, transferred: 42, total: 100, bytesPerSecond: 1 } });
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "42");
  push({ phase: "ready", progress: null });
  expect(screen.getByText(/Save your work/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Restart and install" }));
  await waitFor(() => expect(window.electronAPI?.installUpdate).toHaveBeenCalledOnce());
  expect(screen.getByRole("button", { name: "Restart and install" })).toBeVisible();
});

it("late initial snapshot cannot overwrite a newer pushed state", async () => {
  let resolve!: (state: AppUpdaterState) => void;
  const stale = state;
  window.electronAPI!.getUpdateState = vi.fn(() => new Promise<AppUpdaterState>(r => { resolve = r; }));
  render(<UpdateCard />);
  push({ phase: "ready" });
  await act(async () => resolve(stale));
  expect(screen.getByRole("button", { name: "重启并安装" })).toBeVisible();
});

it("multiple consumers survive closing one, and reopening restores main-process state", async () => {
  const first = render(<UpdateCard />);
  const second = render(<UpdateCard />);
  await waitFor(() => expect(listeners.size).toBe(2));
  first.unmount();
  expect(listeners.size).toBe(1);
  push({ phase: "ready" });
  expect(await screen.findByRole("button", { name: "重启并安装" })).toBeVisible();
  second.unmount();
  render(<UpdateCard />);
  expect(await screen.findByRole("button", { name: "重启并安装" })).toBeVisible();
});

it("renders IPC rejection as a recoverable error", async () => {
  state.phase = "idle";
  window.electronAPI!.checkForUpdates = vi.fn(async () => { throw new Error("IPC unavailable"); });
  render(<UpdateCard />);
  fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("IPC unavailable");
  expect(screen.getByRole("button", { name: "检查更新" })).toBeEnabled();
});

it("hides controls on web and explains unsupported desktop builds", async () => {
  window.isElectron = false;
  const view = renderNotice();
  expect(screen.queryByRole("button")).toBeNull();
  view.unmount();
  window.isElectron = true;
  state.phase = "unsupported";
  render(<UpdateCard />);
  expect(await screen.findByText(/开发模式不检查更新/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "检查更新" })).toBeNull();
});
