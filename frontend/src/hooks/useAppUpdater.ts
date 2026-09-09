import { useCallback, useEffect, useRef, useState } from "react";

// ── Types ──────────────────────────────────────────────────────────────────

export type UpdatePhase =
  | "idle"
  | "checking"
  | "up-to-date"
  | "available"
  | "downloading"
  | "ready"
  | "error";

export interface UpdateInfo {
  version?: string;
  releaseNotes?: string;
}

export interface DownloadProgress {
  percent: number;
  transferred: number;
  total: number;
  bytesPerSecond: number;
}

export interface AppUpdaterState {
  phase: UpdatePhase;
  appVersion: string;
  updateInfo: UpdateInfo | null;
  progress: DownloadProgress | null;
  errorMessage: string | null;
}

export interface UseAppUpdaterResult extends AppUpdaterState {
  isElectron: boolean;
  checkForUpdates: () => Promise<void>;
  downloadUpdate: () => Promise<void>;
  installNow: () => void;
}

// ── Electron API type shim (populated by preload.js) ──────────────────────

interface ElectronAPI {
  checkForUpdates: () => Promise<{ success: boolean; error?: string }>;
  downloadUpdate: () => Promise<{ success: boolean; error?: string }>;
  installUpdate: () => Promise<{ success: boolean; error?: string }>;
  getAppVersion: () => Promise<string>;
  onUpdateStatus: (
    cb: (status: string, data: unknown) => void
  ) => unknown;
  removeUpdateStatusListener: () => void;
}

declare global {
  interface Window {
    isElectron?: boolean;
    electronAPI?: ElectronAPI;
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────

export function useAppUpdater(): UseAppUpdaterResult {
  const isElectron =
    typeof window !== "undefined" && window.isElectron === true;

  const [state, setState] = useState<AppUpdaterState>({
    phase: "idle",
    appVersion: "",
    updateInfo: null,
    progress: null,
    errorMessage: null,
  });

  // Guard: only set state when component is still mounted
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const safeSetState = useCallback(
    (updater: (prev: AppUpdaterState) => AppUpdaterState) => {
      if (mounted.current) setState(updater);
    },
    []
  );

  // ── Fetch app version on mount ───────────────────────────────────────────
  useEffect(() => {
    if (!isElectron || !window.electronAPI) return;
    void window.electronAPI.getAppVersion().then((v) => {
      if (v) safeSetState((prev) => ({ ...prev, appVersion: v }));
    });
  }, [isElectron, safeSetState]);

  // ── Subscribe to push events from main process ───────────────────────────
  useEffect(() => {
    if (!isElectron || !window.electronAPI) return;

    window.electronAPI.onUpdateStatus((status: string, data: unknown) => {
      safeSetState((prev) => {
        switch (status) {
          case "checking-for-update":
            return { ...prev, phase: "checking", errorMessage: null };

          case "available": {
            const info = data as UpdateInfo | null;
            return {
              ...prev,
              phase: "available",
              updateInfo: info ?? null,
              errorMessage: null,
            };
          }

          case "not-available":
            return {
              ...prev,
              phase: "up-to-date",
              updateInfo: null,
              errorMessage: null,
            };

          case "downloading": {
            const progress = data as DownloadProgress | null;
            return {
              ...prev,
              phase: "downloading",
              progress: progress ?? null,
            };
          }

          case "downloaded":
            return {
              ...prev,
              phase: "ready",
              progress: null,
              errorMessage: null,
            };

          case "error": {
            const msg = typeof data === "string" ? data : "更新出错";
            return { ...prev, phase: "error", errorMessage: msg };
          }

          default:
            return prev;
        }
      });
    });

    return () => {
      window.electronAPI?.removeUpdateStatusListener();
    };
  }, [isElectron, safeSetState]);

  // ── Actions ──────────────────────────────────────────────────────────────

  const checkForUpdates = useCallback(async () => {
    if (!window.electronAPI) return;
    safeSetState((prev) => ({
      ...prev,
      phase: "checking",
      errorMessage: null,
    }));
    const res = await window.electronAPI.checkForUpdates();
    if (!res.success && res.error) {
      safeSetState((prev) => ({
        ...prev,
        phase: "error",
        errorMessage: res.error ?? "检查更新失败",
      }));
    }
  }, [safeSetState]);

  const downloadUpdate = useCallback(async () => {
    if (!window.electronAPI) return;
    safeSetState((prev) => ({
      ...prev,
      phase: "downloading",
      progress: null,
      errorMessage: null,
    }));
    const res = await window.electronAPI.downloadUpdate();
    if (!res.success && res.error) {
      safeSetState((prev) => ({
        ...prev,
        phase: "error",
        errorMessage: res.error ?? "下载失败",
      }));
    }
  }, [safeSetState]);

  const installNow = useCallback(() => {
    void window.electronAPI?.installUpdate();
  }, []);

  return {
    ...state,
    isElectron,
    checkForUpdates,
    downloadUpdate,
    installNow,
  };
}
