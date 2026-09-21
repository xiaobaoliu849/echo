// Real electron-updater metadata parsing, version comparison, HTTP download and
// SHA512 verification. The fixture is inert data, never an executable installer.
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { NsisUpdater } = require('electron-updater');
const { ElectronHttpExecutor } = require('electron-updater/out/electronHttpExecutor');
const { NodeHttpExecutor } = require('builder-util/out/nodeHttpExecutor');
const { UpdateController } = require('./update-controller');

async function fixture(t, { corrupt = false, version = '1.0.2', signed = false } = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'echo-update-test-'));
  const payload = Buffer.from('Inert update transport test; never execute.');
  const checksum = createHash('sha512').update(payload).digest('base64');
  const server = http.createServer((req, res) => {
    if (req.url.startsWith('/latest.yml')) {
      res.end(`version: ${version}\nfiles:\n  - url: fixture.exe\n    sha512: ${checksum}\n    size: ${payload.length}\npath: fixture.exe\nsha512: ${checksum}\nreleaseDate: '2026-09-20T00:00:00Z'\n`);
    } else if (req.url.startsWith('/fixture.exe')) {
      const data = corrupt ? Buffer.from('corrupt') : payload;
      res.writeHead(200, { 'Content-Length': data.length });
      res.end(data);
    } else { res.writeHead(404); res.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    await new Promise(resolve => server.close(resolve));
    assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
    assert.ok(path.basename(root).startsWith('echo-update-test-'));
    await fs.rm(root, { recursive: true, force: true });
  });
  const config = path.join(root, 'app-update.yml');
  await fs.writeFile(config, `updaterCacheDirName: fixture-cache\n${signed ? 'publisherName: Echo Test Publisher\n' : ''}`);
  const updater = new NsisUpdater(null, {
    version: '1.0.1', name: 'echo-update-test', isPackaged: true,
    appUpdateConfigPath: config, userDataPath: root, baseCachePath: root,
    whenReady: async () => {}, onQuit: () => {},
  });
  updater.logger = { info() {}, warn() {}, error() {}, debug() {} };
  const executor = new NodeHttpExecutor();
  executor.download = ElectronHttpExecutor.prototype.download;
  updater.httpExecutor = executor;
  updater.disableDifferentialDownload = true;
  updater.setFeedURL({ provider: 'generic', url: `http://127.0.0.1:${server.address().port}/` });
  const controller = new UpdateController({ updater, version: '1.0.1', supported: true, publish() {}, confirmInstall: async () => false });
  return { controller, updater, payload };
}

test('actual updater downloads and verifies local release bytes', async t => {
  const f = await fixture(t);
  await f.controller.check();
  assert.equal(f.controller.state.phase, 'available');
  assert.equal((await f.controller.download()).success, true);
  assert.equal(f.controller.state.phase, 'ready');
  assert.deepEqual(await fs.readFile(f.updater.installerPath), f.payload);
});

test('actual updater rejects corrupt release bytes and disallows install', async t => {
  const f = await fixture(t, { corrupt: true });
  await f.controller.check();
  assert.equal((await f.controller.download()).success, false);
  assert.match(f.controller.state.errorMessage, /checksum mismatch/i);
  assert.equal(f.controller.state.phase, 'error');
  assert.equal((await f.controller.install()).success, false);
});

test('actual updater does not offer same version or downgrade', async t => {
  for (const version of ['1.0.1', '1.0.0']) {
    const f = await fixture(t, { version });
    await f.controller.check();
    assert.equal(f.controller.state.phase, 'up-to-date');
    assert.equal((await f.controller.download()).success, false);
  }
});

test('actual Windows signature verifier rejects unsigned payload when publisher is configured', { skip: process.platform !== 'win32' }, async t => {
  const f = await fixture(t, { signed: true });
  await f.controller.check();
  assert.equal((await f.controller.download()).success, false);
  assert.match(f.controller.state.errorMessage, /not signed by the application owner/i);
  assert.equal(f.controller.state.phase, 'error');
});
