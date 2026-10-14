// Community (hosted) build: the window shows the operator's server instead of
// a bundled backend. `remote-config.json` is generated at build time by
// scripts/build_community.ps1 and is never committed (it names the server).
//
//   { "url": "https://203.0.113.5:8443/app/", "certFingerprint": "sha256/<base64>" }
//
// The server uses a self-signed certificate, so trust is pinned to exactly
// that certificate's fingerprint for exactly that host; every other host keeps
// Chromium's normal verification.

const fs = require('fs');
const path = require('path');

const CONFIG_NAME = 'remote-config.json';
const FINGERPRINT_RE = /^sha256\/[A-Za-z0-9+/]{43}=$/;

function parseRemoteConfig(raw) {
  const data = JSON.parse(raw);
  const url = new URL(String(data.url || ''));
  if (url.protocol !== 'https:') {
    throw new Error('remote-config.json: url must be https');
  }
  const certFingerprint = String(data.certFingerprint || '');
  if (!FINGERPRINT_RE.test(certFingerprint)) {
    throw new Error('remote-config.json: certFingerprint must look like sha256/<base64>');
  }
  return { url: url.toString(), origin: url.origin, hostname: url.hostname, certFingerprint };
}

/** Returns the remote config, or null for the normal local-backend build. */
function loadRemoteConfig({ resourcesPath, appDir }) {
  const candidates = [
    resourcesPath && path.join(resourcesPath, CONFIG_NAME),
    appDir && path.join(appDir, CONFIG_NAME),
  ].filter(Boolean);
  for (const file of candidates) {
    if (fs.existsSync(file)) {
      return parseRemoteConfig(fs.readFileSync(file, 'utf-8'));
    }
  }
  return null;
}

/**
 * Chromium verify-proc result codes: 0 = trust, -2 = reject,
 * -3 = use Chromium's own verdict.
 */
function makeCertificateVerifier(config) {
  return (request, callback) => {
    if (request.hostname !== config.hostname) {
      callback(-3);
      return;
    }
    callback(request.certificate && request.certificate.fingerprint === config.certFingerprint ? 0 : -2);
  };
}

function isRemoteOrigin(config, url) {
  try {
    return new URL(url).origin === config.origin;
  } catch {
    return false;
  }
}

module.exports = { loadRemoteConfig, parseRemoteConfig, makeCertificateVerifier, isRemoteOrigin };
