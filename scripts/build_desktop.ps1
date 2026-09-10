param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}

# The spec deliberately targets Python 3.12 (pydub still uses audioop).
Invoke-Checked $Python @("-c", "import sys; assert sys.version_info[:2] == (3, 12), 'Use Python 3.12 for desktop packaging'")
$buildPython = Join-Path $repoRoot ".packaging-venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $buildPython)) {
    Invoke-Checked $Python @("-m", "venv", ".packaging-venv")
}
Invoke-Checked $buildPython @("-m", "pip", "install", "-r", "backend/requirements-packaging.lock")
Invoke-Checked $buildPython @("-m", "pip", "check")
Invoke-Checked $buildPython @("-c", "import importlib.util,sys; assert sys.prefix != sys.base_prefix; assert not any(importlib.util.find_spec(n) for n in ['torch','gradio','transformers','PySide6','PyQt5']), 'Use a clean .packaging-venv'")
Invoke-Checked "npm.cmd" @("--prefix", "frontend", "ci")
Invoke-Checked "npm.cmd" @("--prefix", "electron", "ci")

# Test and build processes must never inherit developer API keys or profiles.
$testProfile = Join-Path ([IO.Path]::GetTempPath()) ("echo-build-" + [guid]::NewGuid())
$savedEnvironment = @{}
$overrides = @{
    ECHO_DATA_DIR = $testProfile
    VOICESPIRIT_DATA_DIR = $testProfile
    VITE_API_URL = "http://127.0.0.1:8000"
    VITE_API_TOKEN = ""
    VITE_API_ADMIN_TOKEN = ""
    VITE_APP_VERSION = (Get-Content electron/package.json -Raw | ConvertFrom-Json).version
}
foreach ($name in $overrides.Keys) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    [Environment]::SetEnvironmentVariable($name, $overrides[$name], "Process")
}
try {
    Invoke-Checked "npm.cmd" @("--prefix", "electron", "test")
    Invoke-Checked "npm.cmd" @("--prefix", "frontend", "run", "test:run", "--", "--maxWorkers=4")
    Push-Location backend
    try { Invoke-Checked $buildPython @("-m", "pytest", "-q") } finally { Pop-Location }
    Invoke-Checked "npm.cmd" @("--prefix", "frontend", "run", "build", "--", "--mode", "desktop")
    Push-Location backend
    try {
        Invoke-Checked $buildPython @("-m", "PyInstaller", "--noconfirm", "--clean", "voicespirit-backend.spec")
    } finally { Pop-Location }
    Invoke-Checked "npm.cmd" @("--prefix", "electron", "run", "pack")
    Invoke-Checked $buildPython @("scripts/smoke_desktop.py")
    Invoke-Checked $buildPython @("scripts/smoke_desktop.py", "--electron", "electron/dist/win-unpacked/Echo.exe")
    Invoke-Checked "npm.cmd" @("--prefix", "electron", "run", "dist")
    $version = (Get-Content electron/package.json -Raw | ConvertFrom-Json).version
    Invoke-Checked $buildPython @("scripts/verify_installer.py", "electron/dist/Echo Setup $version.exe")
    Write-Host "Verified installer created in electron/dist. Nothing has been published."
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
    }
}
