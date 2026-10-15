// Community build: the bundled backend runs in community-client mode, deferring
// accounts, minutes and call authorisation to the operator's hosted server
// while the call audio goes straight from this machine to the provider.
//
// scripts/build_community.ps1 writes these files next to main.js (both are
// gitignored because they name the operator's server):
//   community-config.json  { "server": "https://203.0.113.5:8443",
//                            "updates": "https://.../echo-updates/" (optional) }
//   community-server.pem   the server's self-signed certificate (public part)
//
// Updates come from a generic electron-updater feed (latest.yml + installer +
// blockmap): `updates` when set, else <server>/updates/. On the server's own
// host only the pinned certificate is accepted.

const fs = require('fs');
const path = require('path');

const CONFIG_NAME = 'community-config.json';
const CERT_NAME = 'community-server.pem';

function parseCommunityConfig(raw) {
  const data = JSON.parse(raw);
  const url = new URL(String(data.server || ''));
  if (url.protocol !== 'https:') {
    throw new Error('community-config.json: server must be https');
  }
  const updates = new URL(String(data.updates || `${url.origin}/updates/`));
  if (updates.protocol !== 'https:') {
    throw new Error('community-config.json: updates must be https');
  }
  if (!updates.pathname.endsWith('/')) updates.pathname += '/';
  return { server: url.origin, updatesUrl: updates.href };
}

/** Returns { server, caPath } for a community build, or null otherwise. */
function loadCommunityConfig({ resourcesPath, appDir }) {
  const dirs = [resourcesPath, appDir].filter(Boolean);
  for (const dir of dirs) {
    const configPath = path.join(dir, CONFIG_NAME);
    if (!fs.existsSync(configPath)) continue;
    const caPath = path.join(dir, CERT_NAME);
    if (!fs.existsSync(caPath)) {
      throw new Error(`${CONFIG_NAME} found without ${CERT_NAME}`);
    }
    return { ...parseCommunityConfig(fs.readFileSync(configPath, 'utf-8')), caPath };
  }
  return null;
}

/** Environment the bundled backend needs to run as a community client. */
function communityBackendEnv(config) {
  return { ECHO_COMMUNITY_SERVER: config.server, ECHO_COMMUNITY_CA: config.caPath };
}

function normalisePem(pem) {
  return String(pem || '').replace(/\r/g, '').trim();
}

/**
 * certificate-verify proc for the updater's session: the operator's host is
 * trusted only with the pinned certificate; every other host (e.g. an object
 * storage bucket) keeps Chromium's normal verification (-3).
 */
function pinnedCertificateVerifier(config, pem) {
  const host = new URL(config.server).hostname;
  const expected = normalisePem(pem);
  return (request, callback) => {
    if (request.hostname !== host) return callback(-3);
    callback(normalisePem(request.certificate && request.certificate.data) === expected ? 0 : -2);
  };
}

module.exports = { loadCommunityConfig, parseCommunityConfig, communityBackendEnv, pinnedCertificateVerifier };
