const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { installScreenSharing, chooseDisplaySource } = require('./screen-sharing');

function harness(overrides = {}) {
  let handler;
  const frame = { url: 'http://127.0.0.1:8000/app/' };
  const window = { isDestroyed: () => false, webContents: {
    mainFrame: frame, getURL: () => frame.url,
    session: { setDisplayMediaRequestHandler: value => { handler = value; } },
  } };
  const selected = { id: 'window:2', name: 'Lesson' };
  let enumerated = 0;
  const dependencies = {
    appUrl: frame.url,
    desktopCapturer: { getSources: async options => { enumerated++; assert.deepEqual(options.types, ['screen', 'window']); return [selected]; } },
    pickSource: async sources => sources[0],
    ...overrides,
  };
  installScreenSharing(window, dependencies);
  const request = { frame, securityOrigin: new URL(frame.url).origin, userGesture: true, videoRequested: true, audioRequested: false };
  return { window, frame, selected, dependencies, request, run: async changes => {
    let result;
    await handler({ ...request, ...changes }, streams => { result = streams; });
    return result;
  }, get enumerated() { return enumerated; } };
}

test('grants only an explicitly chosen source, without system audio', async () => {
  const h = harness();
  assert.deepEqual(await h.run(), { video: h.selected });
  assert.equal(h.enumerated, 1);
});

test('rejects external pages, subframes, no gesture, and system-audio requests before enumeration', async () => {
  const h = harness();
  for (const changes of [{ securityOrigin: 'https://example.com' }, { frame: { url: h.frame.url } }, { userGesture: false }, { videoRequested: false }, { audioRequested: true }]) {
    assert.deepEqual(await h.run(changes), {});
  }
  assert.equal(h.enumerated, 0);
});

test('cancellation and unavailable sources never select a default screen', async () => {
  const h = harness({ pickSource: async () => null });
  assert.deepEqual(await h.run(), {});
  h.dependencies.desktopCapturer.getSources = async () => [];
  assert.deepEqual(await h.run(), {});
  h.dependencies.desktopCapturer.getSources = async () => { throw Error('unavailable'); };
  assert.deepEqual(await h.run(), {});
});

test('closing or navigating the requesting frame while choosing denies capture', async () => {
  const h = harness({ pickSource: async () => {
    h.frame.url = 'https://example.com';
    return h.selected;
  } });
  assert.deepEqual(await h.run(), {});
});

test('denies concurrent capture requests while the picker is open', async () => {
  let resolve;
  const h = harness({ pickSource: async () => new Promise(r => { resolve = r; }) });
  const first = h.run();
  await new Promise(r => setImmediate(r));
  assert.deepEqual(await h.run(), {});
  resolve(h.selected);
  assert.deepEqual(await first, { video: h.selected });
});

function pickerHarness() {
  const ipcMain = new EventEmitter();
  const parent = new EventEmitter();
  parent.isDestroyed = () => false;
  let picker;
  class BrowserWindow extends EventEmitter {
    constructor(options) {
      super();
      picker = this;
      this.options = options;
      this.destroyed = false;
      this.webContents = new EventEmitter();
      this.webContents.mainFrame = {};
      this.webContents.setWindowOpenHandler = callback => { this.openHandler = callback; };
      this.webContents.send = (channel, sources) => { this.sent = { channel, sources }; };
    }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; this.emit('closed'); }
    show() { this.shown = true; }
    async loadFile() { this.webContents.emit('did-finish-load'); }
  }
  const sources = Array.from({ length: 8 }, (_, i) => ({ id: `window:${i}`, name: `Lesson ${i}`, thumbnail: { toDataURL: () => 'data:image/png;base64,test' } }));
  const result = chooseDisplaySource(parent, sources, { BrowserWindow, ipcMain });
  return { ipcMain, parent, picker, sources, result, select: id => ipcMain.emit('echo-screen-share:select', { sender: picker.webContents, senderFrame: picker.webContents.mainFrame }, id) };
}

test('thumbnail picker renders every source in a sandbox and only accepts its own main frame', async () => {
  const h = pickerHarness();
  assert.equal(h.picker.sent.sources.length, 8);
  assert.equal(h.picker.options.webPreferences.sandbox, true);
  assert.equal(h.picker.options.webPreferences.nodeIntegration, false);
  assert.deepEqual(h.picker.openHandler(), { action: 'deny' });
  h.ipcMain.emit('echo-screen-share:select', { sender: {}, senderFrame: {} }, h.sources[0].id);
  assert.equal(h.picker.destroyed, false);
  h.ipcMain.emit('echo-screen-share:select', { sender: h.picker.webContents, senderFrame: {} }, h.sources[0].id);
  assert.equal(h.picker.destroyed, false);
  h.select(h.sources[7].id);
  assert.equal(await h.result, h.sources[7]);
  assert.equal(h.ipcMain.listenerCount('echo-screen-share:select'), 0);
  assert.equal(h.parent.listenerCount('closed'), 0);
});

test('picker cancel, unknown source, and parent shutdown clean up all IPC listeners', async () => {
  for (const action of ['cancel', 'unknown', 'closed']) {
    const h = pickerHarness();
    if (action === 'closed') h.parent.emit('closed');
    else h.select(action === 'cancel' ? null : 'unknown');
    assert.equal(await h.result, null);
    assert.equal(h.picker.destroyed, true);
    assert.equal(h.ipcMain.listenerCount('echo-screen-share:select'), 0);
  }
});
