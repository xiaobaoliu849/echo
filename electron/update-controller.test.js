const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { UpdateController, isTrustedUpdateSender } = require('./update-controller');

function fixture(options = {}) {
  const updater = new EventEmitter();
  const states = [];
  const quitting = [];
  let checks = 0;
  let downloads = 0;
  let installs = 0;
  updater.checkForUpdates = async () => {
    checks++;
    updater.emit('update-available', { version: '1.0.2', releaseNotes: [{ version: '1.0.2', note: 'Fixes' }] });
    return { updateInfo: { version: '1.0.2' } };
  };
  updater.downloadUpdate = async () => {
    downloads++;
    updater.emit('download-progress', { percent: 125, transferred: 10, total: 10 });
    updater.emit('update-downloaded', { version: '1.0.2' });
  };
  updater.quitAndInstall = () => { installs++; };
  const controller = new UpdateController({ updater, version: '1.0.1', supported: true,
    publish: state => states.push(state), confirmInstall: async () => true,
    setQuitting: value => quitting.push(value), ...options });
  return { updater, controller, states, quitting, counts: () => ({ checks, downloads, installs }) };
}

test('check, download, explicit install; repeat checks preserve pending updates', async () => {
  const f = fixture();
  assert.equal(f.updater.autoDownload, false);
  assert.equal(f.updater.autoInstallOnAppQuit, false);
  assert.equal(f.updater.allowDowngrade, false);
  assert.equal(f.updater.allowPrerelease, false);
  assert.equal((await f.controller.install()).success, false);
  await f.controller.check();
  assert.equal(f.controller.state.updateInfo.releaseNotes, '1.0.2\nFixes');
  await f.controller.check();
  await f.controller.download();
  await f.controller.check();
  assert.equal(f.controller.state.phase, 'ready');
  assert.equal(f.states.find(s => s.progress)?.progress.percent, 100);
  assert.equal(f.counts().checks, 1);
  assert.equal(f.counts().installs, 0);
  await f.controller.install();
  assert.equal(f.counts().installs, 1);
  assert.deepEqual(f.quitting, [true]);
  assert.ok(f.states.every((s, i) => s.revision === i + 1));
});

test('cancel restart keeps verified download and does not quit', async () => {
  const f = fixture({ confirmInstall: async () => false });
  await f.controller.check();
  await f.controller.download();
  assert.equal((await f.controller.install()).cancelled, true);
  assert.equal(f.controller.state.phase, 'ready');
  assert.equal(f.counts().installs, 0);
  assert.deepEqual(f.quitting, []);
});

test('failed download or integrity check cannot be installed and can be retried', async () => {
  const f = fixture();
  const download = f.updater.downloadUpdate;
  f.updater.downloadUpdate = async () => { throw new Error('SHA512 mismatch'); };
  await f.controller.check();
  assert.equal((await f.controller.download()).success, false);
  assert.equal(f.controller.state.phase, 'error');
  assert.equal((await f.controller.install()).success, false);
  f.updater.downloadUpdate = download;
  await f.controller.check();
  await f.controller.download();
  assert.equal(f.controller.state.phase, 'ready');
});

test('network rejection and disabled service leave checking state', async () => {
  const f = fixture();
  f.updater.checkForUpdates = async () => { throw new Error('offline'); };
  await f.controller.check();
  assert.equal(f.controller.state.errorMessage, 'offline');
  assert.deepEqual(f.quitting, []);
  f.updater.checkForUpdates = async () => null;
  await f.controller.check();
  assert.equal(f.controller.state.phase, 'error');
});

test('concurrent actions are serialized and emitted install failure restores normal quit behavior', async () => {
  let finish;
  const f = fixture({ confirmInstall: () => new Promise(resolve => { finish = resolve; }) });
  await f.controller.check();
  await f.controller.download();
  const pending = f.controller.install();
  assert.equal((await f.controller.install()).success, false);
  f.updater.quitAndInstall = () => f.updater.emit('error', new Error('installer failed'));
  finish(true);
  assert.equal((await pending).success, false);
  assert.equal(f.controller.state.phase, 'error');
  assert.deepEqual(f.quitting, [true, false]);
});

test('development builds do not start background checks', async () => {
  const f = fixture({ supported: false });
  f.controller.start();
  assert.equal(f.controller.startTimer, undefined);
  assert.equal((await f.controller.check()).success, false);
  assert.equal(f.counts().checks, 0);
});

test('background scheduler checks at startup and six-hour intervals, then stops', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  const f = fixture();
  f.updater.checkForUpdates = async () => {
    f.updater.emit('update-not-available', {});
    return {};
  };
  f.controller.start();
  t.mock.timers.tick(30_000);
  await Promise.resolve();
  assert.equal(f.controller.state.phase, 'up-to-date');
  const revision = f.controller.state.revision;
  t.mock.timers.tick(6 * 60 * 60 * 1000);
  await Promise.resolve();
  assert.ok(f.controller.state.revision > revision);
  f.controller.stop();
  const stopped = f.controller.state.revision;
  t.mock.timers.tick(12 * 60 * 60 * 1000);
  assert.equal(f.controller.state.revision, stopped);
});

test('update IPC rejects foreign windows, subframes and external pages', () => {
  const frame = { url: 'http://127.0.0.1:8000/app/' };
  const window = { webContents: { mainFrame: frame } };
  const event = { sender: window.webContents, senderFrame: frame };
  const trusted = () => isTrustedUpdateSender(event, window, 'http://127.0.0.1:8000/app/');
  assert.equal(trusted(), true);
  event.senderFrame = { ...frame };
  assert.equal(trusted(), false);
  event.senderFrame = frame;
  frame.url = 'https://untrusted.example/app/';
  assert.equal(trusted(), false);
  frame.url = 'http://127.0.0.1:8000/api/';
  assert.equal(trusted(), false);
  event.sender = {};
  assert.equal(trusted(), false);
});
