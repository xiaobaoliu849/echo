// The main process owns update state so closing Settings or reloading React
// cannot lose a download or a ready-to-install update.
class UpdateController {
  constructor({ updater, version, supported, publish, confirmInstall, setQuitting = () => {} }) {
    this.updater = updater;
    this.publish = publish;
    this.confirmInstall = confirmInstall;
    this.setQuitting = setQuitting;
    this.busy = false;
    this.state = {
      revision: 0, phase: supported ? 'idle' : 'unsupported', appVersion: version,
      updateInfo: null, progress: null, errorMessage: null, lastChecked: null,
    };
    updater.autoDownload = false;
    updater.autoInstallOnAppQuit = false;
    updater.allowPrerelease = false;
    updater.allowDowngrade = false;
    updater.disableWebInstaller = true;
    updater.on('checking-for-update', () => this.patch({ phase: 'checking', errorMessage: null }));
    updater.on('update-available', info => this.patch({ phase: 'available', updateInfo: this.info(info), lastChecked: Date.now() }));
    updater.on('update-not-available', () => this.patch({ phase: 'up-to-date', updateInfo: null, lastChecked: Date.now() }));
    updater.on('download-progress', progress => this.patch({
      phase: 'downloading', progress: {
        percent: Math.max(0, Math.min(100, Number(progress.percent) || 0)),
        transferred: progress.transferred, total: progress.total, bytesPerSecond: progress.bytesPerSecond,
      },
    }));
    updater.on('update-downloaded', info => this.patch({ phase: 'ready', updateInfo: this.info(info), progress: null, errorMessage: null }));
    updater.on('error', error => this.fail(error));
  }

  info(info) {
    const notes = info.releaseNotes;
    return {
      version: info.version,
      // Render release notes as text, never executable remote HTML.
      releaseNotes: typeof notes === 'string' ? notes : Array.isArray(notes)
        ? notes.map(note => `${note.version}\n${note.note || ''}`).join('\n\n') : '',
    };
  }

  patch(change) {
    this.state = { ...this.state, ...change, revision: this.state.revision + 1 };
    this.publish(this.state);
  }

  fail(error) {
    // A background check must never undo the user's ordinary Quit action.
    if (this.state.phase === 'installing') this.setQuitting(false);
    this.patch({ phase: 'error', progress: null, errorMessage: error?.message || String(error) });
    return { success: false, error: this.state.errorMessage };
  }

  async check() {
    if (this.state.phase === 'unsupported') return { success: false, error: 'Updates require an installed Windows build.' };
    if (this.busy || ['available', 'downloading', 'ready', 'installing'].includes(this.state.phase)) return { success: true };
    this.busy = true;
    this.patch({ phase: 'checking', errorMessage: null, updateInfo: null, progress: null });
    try {
      const result = await this.updater.checkForUpdates();
      if (!result) throw new Error('The update service is unavailable for this build.');
      return { success: true };
    } catch (error) {
      return this.fail(error);
    } finally { this.busy = false; }
  }

  async download() {
    if (this.busy || this.state.phase !== 'available') return { success: false, error: 'Check for an available update first.' };
    this.busy = true;
    this.patch({ phase: 'downloading', progress: null, errorMessage: null });
    try {
      await this.updater.downloadUpdate();
      if (this.state.phase !== 'ready') throw new Error('The download did not produce a verified installer. Please retry.');
      return { success: true };
    } catch (error) {
      return this.fail(error);
    } finally { this.busy = false; }
  }

  async install() {
    if (this.busy || this.state.phase !== 'ready') return { success: false, error: 'Download and verify the update first.' };
    this.busy = true;
    try {
      if (!await this.confirmInstall()) return { success: true, cancelled: true };
      if (this.state.phase !== 'ready') return { success: false, error: 'The update is no longer ready.' };
      this.patch({ phase: 'installing', errorMessage: null });
      this.setQuitting(true);
      this.updater.quitAndInstall(false, true);
      return { success: this.state.phase !== 'error', error: this.state.errorMessage };
    } catch (error) {
      return this.fail(error);
    } finally { this.busy = false; }
  }

  start() {
    if (this.state.phase === 'unsupported' || this.startTimer) return;
    this.startTimer = setTimeout(() => void this.check(), 30_000);
    this.interval = setInterval(() => void this.check(), 6 * 60 * 60 * 1000);
    this.startTimer.unref?.();
    this.interval.unref?.();
  }

  stop() {
    clearTimeout(this.startTimer);
    clearInterval(this.interval);
    this.startTimer = null;
  }
}

function isTrustedUpdateSender(event, window, frontendUrl) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) return false;
  try {
    const source = new URL(event.senderFrame.url);
    const expected = new URL(frontendUrl);
    return source.origin === expected.origin && source.pathname.startsWith(expected.pathname);
  } catch { return false; }
}

module.exports = { UpdateController, isTrustedUpdateSender };
