const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { loadRemoteConfig, parseRemoteConfig, makeCertificateVerifier, isRemoteOrigin } = require('./remote-mode');

const FINGERPRINT = `sha256/${'A'.repeat(43)}=`;
const CONFIG = JSON.stringify({ url: 'https://203.0.113.5:8443/app/', certFingerprint: FINGERPRINT });

function verify(config, request) {
  let result;
  makeCertificateVerifier(config)(request, (code) => { result = code; });
  return result;
}

test('local build has no remote config', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'echo-remote-'));
  assert.strictEqual(loadRemoteConfig({ resourcesPath: dir, appDir: dir }), null);
});

test('remote config is read from the resources directory', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'echo-remote-'));
  fs.writeFileSync(path.join(dir, 'remote-config.json'), CONFIG);
  const config = loadRemoteConfig({ resourcesPath: dir, appDir: undefined });
  assert.strictEqual(config.url, 'https://203.0.113.5:8443/app/');
  assert.strictEqual(config.hostname, '203.0.113.5');
});

test('plain http and malformed fingerprints are refused', () => {
  assert.throws(() => parseRemoteConfig(JSON.stringify({ url: 'http://203.0.113.5/app/', certFingerprint: FINGERPRINT })));
  assert.throws(() => parseRemoteConfig(JSON.stringify({ url: 'https://203.0.113.5/app/', certFingerprint: 'abc' })));
});

test('only the pinned certificate is trusted for the server host', () => {
  const config = parseRemoteConfig(CONFIG);
  assert.strictEqual(verify(config, { hostname: '203.0.113.5', certificate: { fingerprint: FINGERPRINT } }), 0);
  assert.strictEqual(
    verify(config, { hostname: '203.0.113.5', certificate: { fingerprint: `sha256/${'B'.repeat(43)}=` } }),
    -2,
  );
});

test('other hosts keep normal certificate verification', () => {
  const config = parseRemoteConfig(CONFIG);
  assert.strictEqual(verify(config, { hostname: 'example.com', certificate: { fingerprint: FINGERPRINT } }), -3);
});

test('navigation is limited to the server origin', () => {
  const config = parseRemoteConfig(CONFIG);
  assert.ok(isRemoteOrigin(config, 'https://203.0.113.5:8443/app/#x'));
  assert.ok(!isRemoteOrigin(config, 'https://203.0.113.5/app/'));
  assert.ok(!isRemoteOrigin(config, 'https://evil.example/'));
  assert.ok(!isRemoteOrigin(config, 'not a url'));
});
