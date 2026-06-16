/// <reference types="vite/client" />

declare const __APP_VERSION__: string;

interface ElectronAPI {
  platform: string;
  onNavigate: (callback: (route: string) => void) => void;
  checkForUpdates: () => Promise<any>;
  downloadUpdate: () => Promise<any>;
  installUpdate: () => void;
  getAppVersion: () => Promise<string>;
  getShortcutSettings: () => Promise<{ globalToggleWindow: string }>;
  updateGlobalShortcut: (binding: string) => Promise<{ ok: boolean; binding: string; error?: string }>;
  onUpdateStatus: (callback: (status: string, data: any) => void) => void;
  removeUpdateStatusListener: () => void;
  saveAudioFile: (payload: { filename: string; mime_type: string; data_base64: string }) => Promise<{ ok: boolean; cancelled: boolean; message?: string }>;
}

interface Window {
  isElectron?: boolean;
  electronAPI?: ElectronAPI;
}

