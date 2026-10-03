const path = require('node:path');

// This sandboxed modal alone receives native source IDs. Nothing is granted
// until the user chooses a source, and parent shutdown cancels the request.
async function chooseDisplaySource(parent, sources, { BrowserWindow, ipcMain }) {
  if (!sources.length || parent.isDestroyed()) return null;
  const picker = new BrowserWindow({
    parent, modal: true, show: false, width: 680, height: 550,
    title: '共享屏幕 / Share screen', autoHideMenuBar: true, backgroundColor: '#f2efe6',
    webPreferences: {
      preload: path.join(__dirname, 'screen-sharing-preload.js'),
      contextIsolation: true, sandbox: true, nodeIntegration: false,
      partition: 'echo-screen-picker',
    },
  });
  picker.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  picker.webContents.on('will-navigate', event => event.preventDefault());
  return new Promise(resolve => {
    let settled = false;
    const finish = source => {
      if (settled) return;
      settled = true;
      ipcMain.removeListener('echo-screen-share:select', selection);
      parent.removeListener('closed', parentClosed);
      if (!picker.isDestroyed()) picker.destroy();
      resolve(source);
    };
    const parentClosed = () => finish(null);
    const selection = (event, id) => {
      if (event.sender !== picker.webContents || event.senderFrame !== picker.webContents.mainFrame) return;
      finish(sources.find(source => source.id === id) || null);
    };
    ipcMain.on('echo-screen-share:select', selection);
    parent.once('closed', parentClosed);
    picker.once('closed', () => finish(null));
    picker.webContents.once('did-finish-load', () => {
      if (settled || picker.isDestroyed()) return;
      picker.webContents.send('echo-screen-share:sources', sources.map(source => ({
        id: source.id, name: source.name, thumbnail: source.thumbnail?.toDataURL() || '',
      })));
      picker.show();
    });
    picker.loadFile(path.join(__dirname, 'screen-sharing-picker.html')).catch(() => finish(null));
  });
}

function installScreenSharing(window, dependencies) {
  const { desktopCapturer, appUrl } = dependencies;
  const pickSource = dependencies.pickSource || (sources => chooseDisplaySource(window, sources, dependencies));
  let choosing = false;
  const appOrigin = new URL(appUrl).origin;
  const trusted = request => !window.isDestroyed() && request.frame === window.webContents.mainFrame &&
    request.securityOrigin === appOrigin && new URL(request.frame.url).origin === appOrigin &&
    request.frame.url === window.webContents.getURL();
  window.webContents.session.setDisplayMediaRequestHandler(async (request, callback) => {
    let streams = {};
    try {
      if (!choosing && trusted(request) && request.userGesture && request.videoRequested && !request.audioRequested) {
        const requestedUrl = request.frame.url;
        choosing = true;
        try {
          const sources = await desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 320, height: 180 } });
          const selected = await pickSource(sources);
          if (selected && sources.includes(selected) && trusted(request) && request.frame.url === requestedUrl) streams = { video: selected };
        } finally { choosing = false; }
      }
    } catch {
      // Failed enumeration, canceled pickers, and closing windows deny capture.
    }
    try { callback(streams); } catch { /* Requesting frame may have been destroyed. */ }
  });
}

module.exports = { installScreenSharing, chooseDisplaySource };
