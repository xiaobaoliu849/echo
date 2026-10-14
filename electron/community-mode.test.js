const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { loadCommunityConfig, parseCommunityConfig, communityBackendEnv } = require('./community-mode');

function tempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'echo-community-'));
}

test('regular build has no community config', () => {
  const dir = tempDir();
  assert.strictEqual(loadCommunityConfig({ resourcesPath: dir, appDir: dir }), null);
});

test('community config and certificate are read from resources', () => {
  const dir = tempDir();
  fs.writeFileSync(path.join(dir, 'community-config.json'), JSON.stringify({ server: 'https://203.0.113.5:8443/app/' }));
  fs.writeFileSync(path.join(dir, 'community-server.pem'), '-----BEGIN CERTIFICATE-----\n');
  const config = loadCommunityConfig({ resourcesPath: dir, appDir: undefined });
  assert.strictEqual(config.server, 'https://203.0.113.5:8443');
  assert.deepStrictEqual(communityBackendEnv(config), {
    ECHO_COMMUNITY_SERVER: 'https://203.0.113.5:8443',
    ECHO_COMMUNITY_CA: path.join(dir, 'community-server.pem'),
  });
});

test('a config without the pinned certificate is refused', () => {
  const dir = tempDir();
  fs.writeFileSync(path.join(dir, 'community-config.json'), JSON.stringify({ server: 'https://203.0.113.5:8443' }));
  assert.throws(() => loadCommunityConfig({ resourcesPath: dir }), /community-server.pem/);
});

test('plain http servers are refused', () => {
  assert.throws(() => parseCommunityConfig(JSON.stringify({ server: 'http://203.0.113.5:8443' })), /https/);
});
