// Community build: the bundled backend runs in community-client mode, deferring
// accounts, minutes and call authorisation to the operator's hosted server
// while the call audio goes straight from this machine to the provider.
//
// scripts/build_community.ps1 writes these files next to main.js (both are
// gitignored because they name the operator's server):
//   community-config.json  { "server": "https://203.0.113.5:8443" }
//   community-server.pem   the server's self-signed certificate (public part)

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
  return { server: url.origin };
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

module.exports = { loadCommunityConfig, parseCommunityConfig, communityBackendEnv };
