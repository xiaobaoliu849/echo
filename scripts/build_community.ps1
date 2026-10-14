<#
.SYNOPSIS
  Build the community installer: a thin Electron window onto a hosted Echo server.

.DESCRIPTION
  Writes electron/remote-config.json (gitignored) with the server URL and the
  pinned certificate fingerprint, then packages electron-builder.community.yml.
  Get the fingerprint on the server with:

    echo -n sha256/; openssl x509 -in /etc/nginx/echo/cert.pem -outform DER | openssl dgst -sha256 -binary | base64

  The installer contains no backend, keys or frontend bundle; the server
  serves the UI, so server updates reach every installed copy.

.EXAMPLE
  ./scripts/build_community.ps1 -ServerUrl https://203.0.113.5:8443/app/ -CertFingerprint sha256/AbC...=
#>
param(
  [Parameter(Mandatory = $true)][string]$ServerUrl,
  [Parameter(Mandatory = $true)][string]$CertFingerprint
)

$ErrorActionPreference = "Stop"
$electronDir = Join-Path $PSScriptRoot "..\electron" | Resolve-Path

if (-not $ServerUrl.StartsWith("https://")) { throw "ServerUrl must start with https://" }
if ($CertFingerprint -notmatch '^sha256/[A-Za-z0-9+/]{43}=$') { throw "CertFingerprint must look like sha256/<base64>" }

$config = @{ url = $ServerUrl; certFingerprint = $CertFingerprint } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $electronDir "remote-config.json"), $config, (New-Object System.Text.UTF8Encoding $false))

Push-Location $electronDir
try {
  if (-not (Test-Path node_modules)) { npm ci }
  npx electron-builder --config electron-builder.community.yml --win nsis --publish never
  if ($LASTEXITCODE -ne 0) { throw "electron-builder failed ($LASTEXITCODE)" }
  Get-ChildItem dist-community -Filter "*.exe" | Select-Object Name, @{ n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
}
finally {
  Pop-Location
}
