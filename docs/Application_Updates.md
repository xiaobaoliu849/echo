# In-app Windows updates

## User experience

Echo's installed Electron/NSIS Windows application checks the existing public
GitHub release feed 30 seconds after startup, then every six hours. It never
downloads automatically and never installs just because the user quits.

Update controls live in **Settings → System → Application updates**. There is
no update icon or button on the main sidebar. When a release is available (or
ready to install), a small dismissible notice links directly to the System
settings page. Dismissing a version is remembered; a different release can show
another notice. The notice is hidden while Settings is open.

The settings card shows installed/new versions, plain-text release notes,
download progress and **Restart and install** when verification finishes.
Closing Settings does not stop downloads or lose state. Installation requires
a separate confirmation, defaulting to Later, reminding users to save work and
end calls, recordings and generation.

Web and PyWebView are not Electron installers and do not expose these controls.
Electron development builds explain that installed Windows builds are required.

## Implementation

- `electron/update-controller.js` owns revisioned snapshots in the main process,
  serializes operations, guards download/install states and handles updater errors.
- `main.js` permits update IPC only from the application's main frame. The feed
  remains the builder-generated configuration for `xiaobaoliu849/echo`; renderers
  cannot supply update URLs or installer paths.
- `preload.js` gives each subscriber its own cleanup function. React subscribes
  before requesting a snapshot and rejects older revisions, including on remount.
- Stable releases only; no downgrades or NSIS web installers. `electron-updater`
  verifies the manifest checksum and, when a publisher is configured, the Windows
  Authenticode signature. Release notes are text, not remote HTML.
- An offline/failed check can be retried. A failed download must be checked and
  downloaded again before installation. The updater cache can reuse verified
  bytes on a subsequent launch; UI state is reconstructed by checking the feed.
- There is no claim of atomic rollback after Windows starts the NSIS installer.
  Keep the previous verified installer for recovery. User data stays outside the
  installation directory in the existing Electron profile.

## Release procedure

1. Update `electron/package.json` and both root version entries in its lockfile.
   This implementation prepares **1.0.2**; published **1.0.1** predates it.
2. Configure a real Windows signing identity in the secure build environment
   using electron-builder's supported signing configuration. Do not commit
   certificates, passwords or GitHub tokens. The generated `app-update.yml` must
   contain the matching `publisherName`. Use `forceCodeSigning: true` for release
   builds so a missing certificate fails the build.
3. Run `scripts/build_desktop.ps1` with Python 3.12. It runs tests, freezes the
   backend, builds the desktop frontend and NSIS installer and smoke-tests it.
   New installers use `Echo-Setup-<version>.exe` on disk and in the feed, so
   manually uploaded assets do not need renaming.
4. Run `node scripts/verify_update_release.cjs`. This deliberately refuses
   unsigned releases, stale metadata, mismatched checksum/size or publisher.
5. In an isolated Windows test account/VM, install the previous version, create
   disposable settings/history, and update through its existing Settings →
   System controls. Verify the new installed version, preserved data, backend
   shutdown/restart, cancel/Later behavior and uninstall behavior. Never use a
   developer's real profile or installed copy for destructive release testing.
6. Once approved for publication, publish a stable GitHub release tagged with
   the same version and release notes. Upload the installer, its `.blockmap`,
   and **latest.yml from the same build** as one complete release. A draft can
   stage all assets before publication. Do not overwrite an existing version's
   assets. No GitHub token is needed in the desktop application for this public
   repository.
7. Validate the actual public feed from an older installed application, including
   download, explicit restart, new version, preserved data and a second check
   reporting up to date. Complete this before declaring end-to-end verification.

Old 1.0.1 installations require a manual check in Settings → System to receive
this first release. They cannot acquire the new background checks and notices until
they install the version containing it.

## Evidence and remaining gates

On 2026-09-20 the public repository had stable v1.0.1 with an installer,
blockmap and latest.yml. The local 1.0.1 installer was **NotSigned**, and its
generated updater configuration had no publisher. HTTPS plus a checksum is
not independent publisher authentication. Do not describe that release as signed.

Tests cover state transitions, concurrent commands, retry, confirmation cancel,
scheduler cleanup, sender validation, multi-subscriber/remount state, stale
snapshots, safe release-note rendering and IPC failure. Local HTTP integration
tests use the real updater to reject corrupt payloads, same/older versions and
unsigned data when a signing publisher is configured. They do not execute a real
installer. The desktop smoke test checks packaged preload/state/version and opens
Settings → System, saving `output/electron-update-settings.png`.

Remaining release gates: a real signing identity, a signed candidate, publication
approval, and a real installed-version upgrade with data preservation. No release
is automatically published by this work.

Reference: [electron-builder v26 update documentation](https://www.electron.build/v26/docs/features/auto-update/).
Implementation behavior is checked against the locally installed electron-updater
6.8.9; newer major versions have different installation-control APIs.
