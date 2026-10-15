<#
.SYNOPSIS
  Build the community installer: Echo desktop running as a client of a hosted server.

.DESCRIPTION
  The installed app logs in against the operator's hosted Echo server, which
  owns accounts and minutes and issues short-lived provider client secrets.
  Call audio goes from the user's own network straight to the provider; the
  operator's provider keys never leave the server.

  Writes electron/community-config.json and electron/community-server.pem
  (both gitignored), builds the hosted-mode frontend, freezes the backend
  with the packaging venv, and packages electron-builder.community.yml.
  Run scripts/build_desktop.ps1 once first so .packaging-venv exists.

  -Version stamps the community installer on its own (e.g. 1.0.5) without
  bumping electron/package.json, which the regular desktop release shares.

  Installed copies check an electron-updater generic feed: -UpdatesUrl, or
  <Server>/updates/ by default. The build writes latest.yml next to the
  installer and its .blockmap; upload all three to that feed to release.
  -ReleaseNotes is shown to users in Settings -> General.

.EXAMPLE
  ./scripts/build_community.ps1 -Server https://203.0.113.5:8443 -CertFile C:\path\server-cert.pem -Version 1.0.5 -ReleaseNotes "New settings page"
#>
param(
  [Parameter(Mandatory = $true)][string]$Server,
  [Parameter(Mandatory = $true)][string]$CertFile,
  [string]$Version = "",
  [string]$UpdatesUrl = "",
  [string]$ReleaseNotes = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

function Invoke-Checked {
  param([string]$Command, [string[]]$Arguments)
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}

if (-not $Server.StartsWith("https://")) { throw "Server must start with https://" }
$certText = Get-Content -LiteralPath $CertFile -Raw
if ($certText -notmatch "BEGIN CERTIFICATE" -or $certText -match "PRIVATE KEY") {
  throw "CertFile must be the server's public certificate only (no private key)."
}
$buildPython = Join-Path $repoRoot ".packaging-venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $buildPython)) { throw "Run scripts/build_desktop.ps1 first to create .packaging-venv." }

if (-not $UpdatesUrl) { $UpdatesUrl = $Server.TrimEnd("/") + "/updates/" }
if (-not $UpdatesUrl.StartsWith("https://")) { throw "UpdatesUrl must start with https://" }
if (-not $UpdatesUrl.EndsWith("/")) { $UpdatesUrl += "/" }

$utf8 = New-Object System.Text.UTF8Encoding $false
[IO.File]::WriteAllText((Join-Path $repoRoot "electron/community-config.json"), (@{ server = $Server; updates = $UpdatesUrl } | ConvertTo-Json), $utf8)
[IO.File]::WriteAllText((Join-Path $repoRoot "electron/community-server.pem"), $certText, $utf8)

if ($Version -and $Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must look like 1.0.5" }
if (-not $Version) { $Version = (Get-Content electron/package.json -Raw | ConvertFrom-Json).version }
$env:VITE_APP_VERSION = $Version
Invoke-Checked "npm.cmd" @("--prefix", "frontend", "run", "build", "--", "--mode", "hosted")
Push-Location backend
try {
  Invoke-Checked $buildPython @("-m", "pip", "install", "-q", "-r", "requirements-packaging.lock")
  Invoke-Checked $buildPython @("-m", "PyInstaller", "--noconfirm", "--clean", "voicespirit-backend.spec")
} finally { Pop-Location }

Push-Location electron
try {
  # A generic publish target makes electron-builder write latest.yml (the
  # feed manifest); --publish never keeps it from uploading anything.
  $builderArgs = @("electron-builder", "--config", "electron-builder.community.yml", "--win", "nsis", "--publish", "never",
    "-c.extraMetadata.version=$Version", "-c.publish.provider=generic", "-c.publish.url=$UpdatesUrl")
  if ($ReleaseNotes) { $builderArgs += "-c.releaseInfo.releaseNotes=$ReleaseNotes" }
  Invoke-Checked "npx.cmd" $builderArgs
  Get-ChildItem dist-community -File | Where-Object { $_.Name -like "*$Version*" -or $_.Name -eq "latest.yml" } |
    Select-Object Name, @{ n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
  Write-Host "Release: upload latest.yml, Echo-Community-Setup-$Version.exe and its .blockmap to $UpdatesUrl"
} finally { Pop-Location }
Write-Host "Community installer built in electron/dist-community. Note: frontend/dist now holds the hosted build; run build_desktop.ps1 before a regular release."
