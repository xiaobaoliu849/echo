// Release gate: run after building the NSIS installer, before publishing assets.
// Signed releases are the default; --allow-unsigned explicitly permits a
// release without a publisher, while retaining all artifact integrity checks.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const yaml = require('../electron/node_modules/js-yaml');

async function main() {
  const args = process.argv.slice(2);
  if (args.some(arg => arg !== '--allow-unsigned')) throw new Error('Usage: node scripts/verify_update_release.cjs [--allow-unsigned]');
  const allowUnsigned = args.includes('--allow-unsigned');
  const root = path.resolve(__dirname, '..');
  const dist = path.join(root, 'electron', 'dist');
  const version = require('../electron/package.json').version;
  const metadata = yaml.load(fs.readFileSync(path.join(dist, 'latest.yml'), 'utf8'));
  if (metadata.version !== version) throw new Error('latest.yml does not match the application version.');
  if (!Array.isArray(metadata.files) || metadata.files.length !== 1) throw new Error('Expected one Windows x64 installer.');
  const entry = metadata.files[0];
  const filename = decodeURIComponent(entry.url);
  if (filename !== path.basename(filename) || !filename.endsWith('.exe')) throw new Error('Expected a local installer filename.');
  if (metadata.path !== entry.url || metadata.sha512 !== entry.sha512) throw new Error('Legacy updater metadata does not match the installer entry.');
  const installer = path.join(dist, filename);
  const hash = crypto.createHash('sha512');
  for await (const chunk of fs.createReadStream(installer)) hash.update(chunk);
  if (hash.digest('base64') !== entry.sha512) throw new Error('Installer SHA512 does not match latest.yml.');
  if (fs.statSync(installer).size !== entry.size) throw new Error('Installer size does not match latest.yml.');
  if (!fs.existsSync(`${installer}.blockmap`)) throw new Error('Installer blockmap is missing.');
  const config = yaml.load(fs.readFileSync(path.join(dist, 'win-unpacked', 'resources', 'app-update.yml'), 'utf8'));
  if (config.provider !== 'github' || config.owner !== 'xiaobaoliu849' || config.repo !== 'echo') throw new Error('Unexpected release destination.');
  const publishers = Array.isArray(config.publisherName) ? config.publisherName : [config.publisherName].filter(Boolean);
  if (!publishers.length && !allowUnsigned) throw new Error('Release blocked: app-update.yml has no signing publisher. Configure Windows code signing and rebuild, or explicitly approve an unsigned release and use --allow-unsigned.');
  if (process.platform !== 'win32') throw new Error('Run the release signature check on Windows.');
  // Pass the path through the child environment, never interpolate it into code.
  const signature = JSON.parse(execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    '$ErrorActionPreference = "Stop"; Import-Module "$PSHOME/Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1"; $s = Get-AuthenticodeSignature -LiteralPath $env:ECHO_RELEASE_INSTALLER; $p = if ($s.SignerCertificate) { $s.SignerCertificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) } else { "" }; @{ status = $s.Status.ToString(); publisher = $p } | ConvertTo-Json -Compress'],
    { encoding: 'utf8', windowsHide: true, env: { ...process.env, ECHO_RELEASE_INSTALLER: installer } }));
  if (!publishers.length && allowUnsigned && signature.status === 'NotSigned') {
    console.log(`PASS: explicitly unsigned ${version} installer, release metadata, size and checksum match. Windows may display an unknown publisher warning. Nothing published.`);
    return;
  }
  if (signature.status !== 'Valid' || !publishers.includes(signature.publisher)) throw new Error('Release blocked: installer signature is invalid or its publisher does not match app-update.yml.');
  console.log(`PASS: signed ${version} installer, release metadata, size, checksum and publisher match. Nothing published.`);
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
