# Windows installer: build and troubleshooting

The Windows installer uses Electron (`electron/main.js`) and the PyInstaller
backend. `run_web_desktop.py` remains a separate PyWebView development launcher.
Both load FastAPI's `http://127.0.0.1:8000/app/` frontend. Do not use `file://` or
relax CORS to allow the `null` origin.

## Reproducible build

Use Windows x64, Python 3.12 and Node.js 22 or newer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1
# Or select an installed Python 3.12 explicitly:
./scripts/build_desktop.ps1 -Python C:/Python312/python.exe
```

The script installs the exact Windows build/test dependencies from
`backend/requirements-packaging.lock` into `.packaging-venv`, installs both npm
lockfiles, runs all tests, builds the frontend in `desktop` mode, freezes the
backend and builds Electron. It runs the real frozen executable and Electron
before producing `electron/dist/Echo Setup <version>.exe`. It then extracts the
NSIS application payload and runs that copy as well. Any failing stage stops
the build. Nothing is automatically published to GitHub Releases.

Do not freeze the backend from a global Conda/ML environment. Do not manually
delete DLLs or package directories to reduce installer size. The tracked spec
excludes GUI/model-training stacks and explicitly collects Azure Speech's
native DLLs. `ffmpeg` and `ffprobe` are supplied under `resources/media-tools`,
with their upstream license notices. They are separate executables with their
own licenses; the project MIT license does not replace those notices.

`desktop` Vite builds ignore local dotenv files and ambient `VITE_*` values,
except the explicit build version. The API URL is fixed to the local backend;
API tokens must be supplied by the installed user's configuration. Backend
configuration, databases, logs and audio caches are never build inputs.

## Verification and data isolation

```powershell
./.packaging-venv/Scripts/python.exe scripts/smoke_desktop.py
./.packaging-venv/Scripts/python.exe scripts/smoke_desktop.py --electron electron/dist/win-unpacked/Echo.exe
./.packaging-venv/Scripts/python.exe scripts/verify_installer.py 'electron/dist/Echo Setup 1.0.1.exe'
```

Smoke checks use fresh profiles and working directories containing Chinese
characters and spaces. PATH contains only Windows and bundled media tools, so
the application cannot accidentally rely on a developer's Python or FFmpeg.
Checks cover backend identity, HTTP assets, settings access, WebSocket
handshake, FFmpeg encoding/FFprobe inspection, React chat rendering, preload
IPC and normal application shutdown with port release. Installation resource
files must remain unchanged. Screenshots and logs go to ignored `output/`.

The NSIS payload is extracted rather than silently replacing the user's
installed copy and uninstall registry entry. This verifies the actual files
the installer deploys, including launch from an unrelated directory. It does
not claim an interactive installer/uninstaller or clean-VM SmartScreen test.
Cloud synthesis, transcription and model calls still need the user's valid
provider credentials/network; these checks do not exercise paid services.
In-process ChatTTS/faster-whisper model runtimes are not bundled. Externally
hosted local-model integrations remain separate services.

## Startup failures

The Electron profile defaults to `%APPDATA%/echo-desktop`. Startup diagnostics
are written to `logs/desktop-startup.log` under that profile. The error dialog
shows the exact path. `ECHO_DESKTOP_USER_DATA_DIR` can select an isolated profile
for testing; it should not point inside an installation directory.

- Port 8000 occupied: close the other Echo/backend instance first. The app
  deliberately refuses to attach to an unrelated process or terminate it.
- Missing backend/DLL/front-end resources: reinstall a verified complete
  installer; inspect the startup log for the exact missing file.
- Unexpected backend exit: the shell reports the failure and exits, rather
  than leaving an apparently functional window connected to a dead backend.
- Cloud API configuration errors: configure the relevant provider in Settings.
  These are distinct from a backend startup failure.

## Audit findings (2026-09-10)

The original `Echo Setup 1.0.0.exe` was 400,759,200 bytes. Running its bundled
backend from an unrelated working directory reproduced exit code 1 before
FastAPI startup:

```text
FileNotFoundError: Tcl data directory .../_internal/_tcl_data not found.
Failed to execute script 'pyi_rth__tkinter'
```

The old bundle collected unrelated ML/GUI packages from the build machine.
After isolating the build, executable testing exposed another missing
dependency: `Microsoft.CognitiveServices.Speech.core.dll`, loaded dynamically
by Azure Speech. The new spec explicitly includes the SDK's native libraries.

Additional fixes address `file://`/CORS mismatch, uncaught spawn errors, missing
startup logs, unbounded readiness requests, accidental adoption of a different
backend on port 8000, backend/audio subprocess cleanup, writing TTS cache into
installation resources, and stale diagnostics from the PyWebView profile.
The backend spec is now version-controlled instead of being discarded by the
global `*.spec` ignore rule. Electron and electron-builder are pinned and the
npm manifest/lockfile identity is consistent. The installer version is 1.0.1.

Reference for isolated freezing and exclusions:
[PyInstaller usage documentation](https://pyinstaller.org/en/stable/usage.html).
