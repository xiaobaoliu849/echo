const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { loadCommunityConfig, parseCommunityConfig, communityBackendEnv, pinnedCertificateVerifier } = require('./community-mode');

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

test('updates default to the server and may point elsewhere over https', () => {
  assert.strictEqual(parseCommunityConfig(JSON.stringify({ server: 'https://203.0.113.5:8443' })).updatesUrl, 'https://203.0.113.5:8443/updates/');
  assert.strictEqual(
    parseCommunityConfig(JSON.stringify({ server: 'https://203.0.113.5:8443', updates: 'https://cdn.example.com/echo' })).updatesUrl,
    'https://cdn.example.com/echo/',
  );
  assert.throws(() => parseCommunityConfig(JSON.stringify({ server: 'https://203.0.113.5:8443', updates: 'http://cdn.example.com/' })), /updates must be https/);
});

test('the pinned certificate is required on the server host only', () => {
  const config = parseCommunityConfig(JSON.stringify({ server: 'https://203.0.113.5:8443' }));
  const verify = pinnedCertificateVerifier(config, '-----BEGIN CERTIFICATE-----\r\nAAA\r\n-----END CERTIFICATE-----\r\n');
  const result = (hostname, data) => {
    let code;
    verify({ hostname, certificate: { data } }, (value) => { code = value; });
    return code;
  };
  assert.strictEqual(result('203.0.113.5', '-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----'), 0);
  assert.strictEqual(result('203.0.113.5', '-----BEGIN CERTIFICATE-----\nBBB\n-----END CERTIFICATE-----'), -2);
  assert.strictEqual(result('cdn.example.com', 'anything'), -3);
});
