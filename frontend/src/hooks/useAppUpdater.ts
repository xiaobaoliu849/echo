import { useCallback, useEffect, useState } from "react";

export type UpdatePhase = "idle" | "unsupported" | "checking" | "up-to-date" | "available" | "downloading" | "ready" | "installing" | "error";
export interface UpdateInfo { version: string; releaseNotes: string }
export interface DownloadProgress { percent: number; transferred: number; total: number; bytesPerSecond: number }
export interface AppUpdaterState {
  revision: number;
  phase: UpdatePhase;
  appVersion: string;
  updateInfo: UpdateInfo | null;
  progress: DownloadProgress | null;
  errorMessage: string | null;
  lastChecked: number | null;
}
interface UpdateResult { success: boolean; error?: string; cancelled?: boolean }
interface ElectronAPI {
  checkForUpdates: () => Promise<UpdateResult>;
  downloadUpdate: () => Promise<UpdateResult>;
  installUpdate: () => Promise<UpdateResult>;
  getAppVersion: () => Promise<string>;
  getUpdateState: () => Promise<AppUpdaterState>;
  onUpdateState: (callback: (state: AppUpdaterState) => void) => () => void;
}
declare global {
  interface Window { isElectron?: boolean; electronAPI?: ElectronAPI }
}
const initialState: AppUpdaterState = {
  revision: -1, phase: "idle", appVersion: "", updateInfo: null,
  progress: null, errorMessage: null, lastChecked: null,
};

export function useAppUpdater() {
  const isElectron = typeof window !== "undefined" && window.isElectron === true;
  const [state, setState] = useState(initialState);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  useEffect(() => {
    const api = window.electronAPI;
    if (!isElectron || !api) return;
    let active = true;
    const receive = (next: AppUpdaterState) => {
      if (!active) return;
      setConnectionError(null);
      setState(previous => next.revision >= previous.revision ? next : previous);
    };
    // Subscribe before reading; revisions reject snapshots overtaken by events.
    const unsubscribe = api.onUpdateState(receive);
    void api.getUpdateState().then(receive).catch(error => {
      if (active) setConnectionError(String(error));
    });
    return () => { active = false; unsubscribe(); };
  }, [isElectron]);

  const invoke = useCallback(async (action: "checkForUpdates" | "downloadUpdate" | "installUpdate") => {
    const api = window.electronAPI;
    if (!api) return;
    try {
      setConnectionError(null);
      const result = await api[action]();
      const next = await api.getUpdateState();
      setState(previous => next.revision >= previous.revision ? next : previous);
      if (!result.success) setConnectionError(result.error || "Update action failed.");
    } catch (error) { setConnectionError(String(error)); }
  }, []);

  return {
    ...state, isElectron, connectionError,
    checkForUpdates: () => invoke("checkForUpdates"),
    downloadUpdate: () => invoke("downloadUpdate"),
    installNow: () => invoke("installUpdate"),
  };
}
export type UseAppUpdaterResult = ReturnType<typeof useAppUpdater>;
