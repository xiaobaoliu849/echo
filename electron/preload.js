const { contextBridge, ipcRenderer } = require('electron');

function saveAudioFile(payloadOrBase64, filename) {
  if (payloadOrBase64 && typeof payloadOrBase64 === 'object') {
    return ipcRenderer.invoke('save-audio-file', payloadOrBase64);
  }
  return ipcRenderer.invoke('save-audio-file', {
    data_base64: payloadOrBase64,
    filename: filename || 'audio.mp3'
  });
}

function onUpdateStatus(callback) {
  const listener = (event, payload) => {
    if (payload && typeof payload === 'object' && 'status' in payload) {
      callback(payload.status, payload.data);
      return;
    }
    callback('unknown', payload);
  };
  ipcRenderer.on('update-status', listener);
  return listener;
}

let updateStatusListener = null;

const electronAPI = {
  platform: process.platform,
  onNavigate: () => {},
  saveAudioFile,
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  downloadUpdate: () => ipcRenderer.invoke('download-update'),
  installUpdate: () => ipcRenderer.invoke('install-update'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  getShortcutSettings: () => ipcRenderer.invoke('get-shortcut-settings'),
  updateGlobalShortcut: (shortcut) => ipcRenderer.invoke('update-global-shortcut', shortcut),
  onUpdateStatus: (callback) => {
    updateStatusListener = onUpdateStatus(callback);
  },
  removeUpdateStatusListener: () => {
    if (updateStatusListener) {
      ipcRenderer.removeListener('update-status', updateStatusListener);
      updateStatusListener = null;
    }
  }
};

try {
  contextBridge.exposeInMainWorld('isElectron', true);
  contextBridge.exposeInMainWorld('electronAPI', electronAPI);
  contextBridge.exposeInMainWorld('saveAudioFile', saveAudioFile);
  contextBridge.exposeInMainWorld('checkForUpdates', electronAPI.checkForUpdates);
  contextBridge.exposeInMainWorld('downloadUpdate', electronAPI.downloadUpdate);
  contextBridge.exposeInMainWorld('installUpdate', electronAPI.installUpdate);
  contextBridge.exposeInMainWorld('getAppVersion', electronAPI.getAppVersion);
  contextBridge.exposeInMainWorld('getShortcutSettings', electronAPI.getShortcutSettings);
  contextBridge.exposeInMainWorld('updateGlobalShortcut', electronAPI.updateGlobalShortcut);
  contextBridge.exposeInMainWorld('onUpdateStatus', onUpdateStatus);
  contextBridge.exposeInMainWorld('removeUpdateStatusListener', (listener) => {
    ipcRenderer.removeListener('update-status', listener);
  });
} catch (e) {
  console.warn('Failed to use contextBridge to expose APIs, falling back to window object:', e);
  window.isElectron = true;
  window.electronAPI = electronAPI;
  window.saveAudioFile = saveAudioFile;
  window.checkForUpdates = electronAPI.checkForUpdates;
  window.downloadUpdate = electronAPI.downloadUpdate;
  window.installUpdate = electronAPI.installUpdate;
  window.getAppVersion = electronAPI.getAppVersion;
  window.getShortcutSettings = electronAPI.getShortcutSettings;
  window.updateGlobalShortcut = electronAPI.updateGlobalShortcut;
  window.onUpdateStatus = onUpdateStatus;
  window.removeUpdateStatusListener = (listener) => {
    ipcRenderer.removeListener('update-status', listener);
  };
}
