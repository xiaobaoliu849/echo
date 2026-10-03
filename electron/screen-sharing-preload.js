const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('echoScreenPicker', {
  onSources: callback => {
    ipcRenderer.once('echo-screen-share:sources', (_event, sources) => callback(sources));
  },
  select: id => ipcRenderer.send('echo-screen-share:select', typeof id === 'string' ? id : null),
});
