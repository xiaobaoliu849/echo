const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { BackendRuntime, assertPortAvailable } = require('./backend-runtime');

function harness(t, overrides = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'echo-runtime-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const child = new EventEmitter();
  Object.assign(child, { pid: 123, exitCode: null, stdout: new EventEmitter(), stderr: new EventEmitter() });
  let kills = 0;
  child.kill = () => { kills++; };
  let options;
  const runtime = new BackendRuntime({
    logPath: path.join(dir, 'startup.log'), pollMs: 1, checkPort: async () => {},
    terminateProcess: (process) => process.kill(),
    spawnProcess: (cmd, args, opts) => { options = opts; return child; },
    ...overrides
  });
  return { runtime, child, get options() { return options; }, get kills() { return kills; } };
}

test('starts without a shell, logs stderr, and handles missing executable', async (t) => {
  const h = harness(t);
  await h.runtime.start('C:/Program Files/Echo/backend.exe', [], { cwd: os.tmpdir(), env: {} });
  assert.equal(h.options.shell, false);
  assert.equal(h.options.windowsHide, true);
  assert.equal(h.options.env.ECHO_DESKTOP_INSTANCE_ID, h.runtime.instanceId);
  h.child.stderr.emit('data', Buffer.from('Tcl data directory missing'));
  h.child.emit('error', new Error('spawn ENOENT'));
  await assert.rejects(h.runtime.waitUntilReady(), /ENOENT/);
  assert.match(fs.readFileSync(h.runtime.logPath, 'utf8'), /Tcl data directory missing/);
});

test('early process exit fails immediately instead of waiting for timeout', async (t) => {
  const h = harness(t);
  await h.runtime.start('backend', [], { env: {} });
  h.child.emit('exit', 1, null);
  await assert.rejects(h.runtime.waitUntilReady(), /code 1/);
  h.runtime.stop();
  assert.equal(h.kills, 0);
});

test('never adopts an unrelated or older backend on port 8000', async (t) => {
  const h = harness(t, { fetchUrl: async () => ({ ok: true, json: async () => ({ name: 'Echo API' }) }) });
  await h.runtime.start('backend', [], { env: {} });
  await assert.rejects(h.runtime.waitUntilReady(), /Another service/);
});

test('checks frontend availability before declaring ready', async (t) => {
  const h = harness(t);
  h.runtime.fetchUrl = async (url) => url.endsWith('/app/')
    ? { ok: false, text: async () => 'Not Found' }
    : { ok: true, json: async () => ({ desktop_instance_id: h.runtime.instanceId }) };
  await h.runtime.start('backend', [], { env: {} });
  await assert.rejects(h.runtime.waitUntilReady(), /Frontend resources/);
});

test('ready runtime reports later crashes and only kills its owned child once', async (t) => {
  let error;
  const h = harness(t, { onUnexpectedExit: (message) => { error = message; } });
  h.runtime.fetchUrl = async (url) => url.endsWith('/app/')
    ? { ok: true, text: async () => '<div id="root"></div>' }
    : { ok: true, json: async () => ({ desktop_instance_id: h.runtime.instanceId }) };
  await h.runtime.start('backend', [], { env: {} });
  await h.runtime.waitUntilReady();
  h.child.emit('exit', 2, null);
  assert.match(error, /code 2/);
  h.runtime.stop();
  assert.equal(h.kills, 0);
  const other = harness(t);
  await other.runtime.start('backend', [], { env: {} });
  other.runtime.stop();
  other.runtime.stop();
  assert.equal(other.kills, 1);
});

test('unreachable backend has a bounded startup deadline', async (t) => {
  const h = harness(t, { fetchUrl: async () => { throw new Error('ECONNREFUSED'); } });
  await h.runtime.start('backend', [], { env: {} });
  await assert.rejects(h.runtime.waitUntilReady(10), /timed out/);
});

test('busy port fails without spawning another backend', async (t) => {
  const server = net.createServer();
  const alreadyOccupied = await new Promise((resolve) => {
    server.once('error', () => resolve(true));
    server.listen(8000, '127.0.0.1', () => resolve(false));
  });
  if (alreadyOccupied) {
    // A dev backend or installed Echo is running; the busy-port behavior
    // cannot be exercised without a free port, so skip instead of failing.
    t.skip('port 8000 is already in use');
    return;
  }
  t.after(() => new Promise((resolve) => server.close(resolve)));
  await assert.rejects(assertPortAvailable(), /8000/);
});
