const { app, BrowserWindow, ipcMain, dialog, Tray, Menu, globalShortcut, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { BackendRuntime } = require('./backend-runtime');
const { autoUpdater } = require('electron-updater');

// Allows smoke tests and portable profiles to avoid the installed user's data.
if (process.env.ECHO_DESKTOP_USER_DATA_DIR) {
  const profile = path.resolve(process.env.ECHO_DESKTOP_USER_DATA_DIR);
  fs.mkdirSync(profile, { recursive: true });
  app.setPath('userData', profile);
}

// Check DEV_MODE
const DEV_MODE = !app.isPackaged;

function getFrontendUrl() {
  if (DEV_MODE) {
    return 'http://localhost:5173';
  }
  return 'http://127.0.0.1:8000/app/';
}

// Configure BACKEND_PATH
const BACKEND_PATH = path.join(__dirname, '../backend');

let mainWindow = null;
let tray = null;
let backendRuntime = null;
app.isQuiting = false;

// Shortcut settings management
const shortcutSettingsPath = path.join(app.getPath('userData'), 'shortcut-settings.json');

function loadShortcutSettings() {
  try {
    if (fs.existsSync(shortcutSettingsPath)) {
      const data = fs.readFileSync(shortcutSettingsPath, 'utf8');
      const settings = JSON.parse(data);
      if (settings && typeof settings.shortcut === 'string') return settings;
    }
  } catch (err) {
    console.error('Error loading shortcut settings:', err);
  }
  return { shortcut: 'Ctrl+Alt+KeyV' };
}

function saveShortcutSettings(settings) {
  try {
    const dir = path.dirname(shortcutSettingsPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(shortcutSettingsPath, JSON.stringify(settings, null, 2), 'utf8');
  } catch (err) {
    console.error('Error saving shortcut settings:', err);
  }
}

function translateShortcutToAccelerator(shortcutStr) {
  if (!shortcutStr) return '';
  // Translate e.g., "Ctrl+Alt+KeyV" -> "CommandOrControl+Alt+V"
  return shortcutStr
    .replace(/\bKey([A-Z0-9])\b/gi, '$1')
    .replace(/\bControl\b/gi, 'CommandOrControl')
    .replace(/\bCtrl\b/gi, 'CommandOrControl');
}

function registerGlobalShortcut(accelerator) {
  globalShortcut.unregisterAll();
  if (!accelerator) return;

  try {
    const registered = globalShortcut.register(accelerator, () => {
      console.log(`Global shortcut ${accelerator} triggered`);
      if (mainWindow) {
        if (mainWindow.isVisible()) {
          mainWindow.hide();
        } else {
          mainWindow.show();
          mainWindow.focus();
        }
        mainWindow.webContents.send('global-shortcut-triggered', accelerator);
      }
    });

    if (registered) {
      console.log(`Successfully registered global shortcut: ${accelerator}`);
    } else {
      console.warn(`Failed to register global shortcut: ${accelerator}`);
    }
  } catch (err) {
    console.error(`Error registering shortcut ${accelerator}:`, err);
  }
}

// Spawns Python backend
async function startBackend() {
  const env = {
    ...process.env,
    ECHO_DATA_DIR: app.getPath('userData'),
    VOICESPIRIT_DATA_DIR: app.getPath('userData'),
    VOICESPIRIT_FRONTEND_DIST: DEV_MODE
      ? path.join(__dirname, '../frontend/dist')
      : path.join(process.resourcesPath, 'frontend', 'dist')
  };

  if (DEV_MODE) {
    console.log(`Starting backend in development mode from: ${BACKEND_PATH}`);
    const pythonCandidates = process.platform === 'win32'
      ? [
          path.join(__dirname, '../backend/.venv/Scripts/python.exe'),
          path.join(__dirname, '../backend/.venv-win/Scripts/python.exe'),
          path.join(__dirname, '../venv/Scripts/python.exe'),
          'python'
        ]
      : [
          path.join(__dirname, '../backend/.venv/bin/python'),
          path.join(__dirname, '../venv/bin/python'),
          'python3'
        ];
    const pythonCmd = pythonCandidates.find((candidate) => candidate === 'python' || candidate === 'python3' || fs.existsSync(candidate));
    await backendRuntime.start(pythonCmd, ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], { cwd: BACKEND_PATH, env });
  } else {
    // Production: spawn path.join(process.resourcesPath, 'backend-dist', 'voicespirit-backend.exe')
    const prodBackendExe = path.join(process.resourcesPath, 'backend-dist', 'voicespirit-backend.exe');
    // pydub and transcription subprocesses must work without a system ffmpeg.
    // Windows environment names are case-insensitive; remove Path/PATH aliases.
    const pathKey = Object.keys(env).find((key) => key.toLowerCase() === 'path');
    const inheritedPath = pathKey ? env[pathKey] : '';
    for (const key of Object.keys(env)) {
      if (key.toLowerCase() === 'path') delete env[key];
    }
    env.PATH = `${path.join(process.resourcesPath, 'media-tools')}${path.delimiter}${inheritedPath}`;
    console.log(`Starting backend in production mode: ${prodBackendExe}`);
    await backendRuntime.start(prodBackendExe, [], { cwd: app.getPath('userData'), env });
  }

}

async function waitForBackend(timeoutMs = 20000) {
  await backendRuntime.waitUntilReady(timeoutMs);
}

function killBackend() {
  backendRuntime?.stop();
}

// Tray management
function createTray() {
  const iconPath = DEV_MODE
    ? path.join(__dirname, '../resources/icons/logo.ico')
    : path.join(process.resourcesPath, 'resources/icons/logo.ico');
  let trayIcon;
  if (fs.existsSync(iconPath)) {
    trayIcon = nativeImage.createFromPath(iconPath);
  } else {
    trayIcon = nativeImage.createEmpty();
  }

  tray = new Tray(trayIcon);
  tray.setToolTip('Echo');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show Echo',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        app.isQuiting = true;
        app.quit();
      }
    }
  ]);

  tray.setContextMenu(contextMenu);

  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// Window creation
async function createWindow() {
  const windowIconPath = DEV_MODE
    ? path.join(__dirname, '../resources/icons/logo.ico')
    : path.join(process.resourcesPath, 'resources/icons/logo.ico');

  mainWindow = new BrowserWindow({
    title: 'Echo · 回声',
    icon: fs.existsSync(windowIconPath) ? windowIconPath : undefined,
    width: 1200,
    height: 800,
    minWidth: 920,
    minHeight: 620,
    // Match the warm app canvas instead of flashing a dark frame on startup.
    backgroundColor: '#F2EFE6',
    autoHideMenuBar: true,
    show: false,
    // Windows: the native title bar follows the system accent color and
    // clashes with the sage brand. Draw caption buttons over app colors;
    // the sidebar is the drag surface (see -webkit-app-region in styles.css).
    ...(process.platform === 'win32' ? {
      titleBarStyle: 'hidden',
      titleBarOverlay: { color: '#FAF8F2', symbolColor: '#43544B', height: 40 }
    } : {}),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.once('ready-to-show', () => {
    if (process.argv.includes('--smoke-test')) return;
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.on('close', (event) => {
    if (!app.isQuiting) {
      event.preventDefault();
      mainWindow.hide();
    }
    return false;
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Set up context menu
  mainWindow.webContents.on('context-menu', (e, params) => {
    const contextMenu = Menu.buildFromTemplate([
      { role: 'cut', enabled: params.editFlags.canCut },
      { role: 'copy', enabled: params.editFlags.canCopy },
      { role: 'paste', enabled: params.editFlags.canPaste },
      { type: 'separator' },
      { role: 'selectAll', enabled: params.editFlags.canSelectAll }
    ]);
    contextMenu.popup();
  });
  await mainWindow.loadURL(getFrontendUrl());
}

// Menu setup
function setupMenus() {
  const template = [
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { role: 'close' }
      ]
    },
    {
      role: 'help',
      submenu: [
        {
          label: 'Learn More',
          click: async () => {
            const { shell } = require('electron');
            await shell.openExternal('https://github.com/xiaobaoliu849/echo');
          }
        }
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

// IPC Handlers
function setupIpcHandlers() {
  ipcMain.handle('save-audio-file', async (event, payloadOrBase64, defaultFilename) => {
    const payload = payloadOrBase64 && typeof payloadOrBase64 === 'object'
      ? payloadOrBase64
      : { data_base64: payloadOrBase64, filename: defaultFilename };
    const filename = payload.filename || defaultFilename || 'audio.mp3';

    const { filePath } = await dialog.showSaveDialog(mainWindow, {
      defaultPath: filename,
      filters: [
        { name: 'Audio Files', extensions: ['mp3', 'wav', 'ogg', 'aac', 'm4a'] },
        { name: 'All Files', extensions: ['*'] }
      ]
    });

    if (filePath) {
      try {
        const base64Data = String(payload.data_base64 || payload.base64Data || '');
        const cleanBase64 = base64Data.replace(/^data:audio\/\w+;base64,/, '');
        const buffer = Buffer.from(cleanBase64, 'base64');
        await fs.promises.writeFile(filePath, buffer);
        return { ok: true, success: true, filePath, path: filePath, cancelled: false };
      } catch (err) {
        console.error('Failed to save audio file:', err);
        return { ok: false, success: false, error: err.message, message: err.message, cancelled: false };
      }
    }
    return { ok: false, success: false, error: 'Cancelled', message: 'Cancelled', cancelled: true };
  });

  // Auto-updater handlers
  ipcMain.handle('check-for-updates', async () => {
    try {
      const result = await autoUpdater.checkForUpdates();
      return { success: true, result: result ? { updateInfo: result.updateInfo } : null };
    } catch (err) {
      console.error('Check for updates error:', err);
      return { success: false, error: err.message };
    }
  });

  ipcMain.handle('download-update', async () => {
    try {
      const result = await autoUpdater.downloadUpdate();
      return { success: true, result };
    } catch (err) {
      console.error('Download update error:', err);
      return { success: false, error: err.message };
    }
  });

  ipcMain.handle('install-update', () => {
    try {
      autoUpdater.quitAndInstall();
      return { success: true };
    } catch (err) {
      console.error('Install update error:', err);
      return { success: false, error: err.message };
    }
  });

  ipcMain.handle('get-app-version', () => {
    return app.getVersion();
  });

  // Shortcut handlers
  ipcMain.handle('get-shortcut-settings', () => {
    const settings = loadShortcutSettings();
    return {
      ...settings,
      globalToggleWindow: settings.shortcut
    };
  });

  ipcMain.handle('update-global-shortcut', (event, shortcutStr) => {
    const accelerator = translateShortcutToAccelerator(shortcutStr);
    console.log(`Updating global shortcut: ${shortcutStr} -> ${accelerator}`);
    
    registerGlobalShortcut(accelerator);
    saveShortcutSettings({ shortcut: shortcutStr });
    
    return { ok: true, success: true, binding: shortcutStr };
  });
}

// Auto-updater event registration
function setupAutoUpdaterEvents() {
  autoUpdater.autoDownload = false;

  const sendUpdateStatus = (status, data = null) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('update-status', { status, data });
    }
  };

  autoUpdater.on('checking-for-update', () => {
    sendUpdateStatus('checking-for-update');
  });

  autoUpdater.on('update-available', (info) => {
    sendUpdateStatus('available', info);
  });

  autoUpdater.on('update-not-available', (info) => {
    sendUpdateStatus('not-available', info);
  });

  autoUpdater.on('error', (err) => {
    sendUpdateStatus('error', err ? err.message : 'Unknown error');
  });

  autoUpdater.on('download-progress', (progressObj) => {
    sendUpdateStatus('downloading', progressObj);
  });

  autoUpdater.on('update-downloaded', (info) => {
    sendUpdateStatus('downloaded', info);
  });
}

// Single instance lock
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  // App lifecycle
  app.whenReady().then(async () => {
    backendRuntime = new BackendRuntime({
      logPath: path.join(app.getPath('userData'), 'logs', 'desktop-startup.log'),
      onUnexpectedExit: (message) => {
        if (!app.isQuiting) {
          dialog.showErrorBox('Echo 后端已停止 / Backend stopped', message);
          app.quit();
        }
      }
    });
    try {
      await startBackend();
      await waitForBackend(60000);
      setupIpcHandlers();
      setupAutoUpdaterEvents();
      await createWindow();
      createTray();
      setupMenus();
    } catch (err) {
      const message = err && err.message ? err.message : String(err);
      console.error('Backend startup failed:', message);
      dialog.showErrorBox('Echo 启动失败 / Startup failed', `${message}\n\n日志 / Log: ${backendRuntime.logPath}`);
      app.isQuiting = true;
      app.quit();
      return;
    }

    // Load and register configured global shortcut
    const settings = loadShortcutSettings();
    const accelerator = translateShortcutToAccelerator(settings.shortcut);
    registerGlobalShortcut(accelerator);

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow().catch((err) => {
          dialog.showErrorBox('Echo 页面加载失败 / Page failed to load', err.message);
          app.quit();
        });
      }
    });
  });
}

app.on('before-quit', () => {
  app.isQuiting = true;
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  killBackend();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
