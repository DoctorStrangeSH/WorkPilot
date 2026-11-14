# Malenia Desktop 0.3.0

React + Vite frontend and Tauri 2 host for the local Python Agent Runtime.

## Current capabilities

- Dark Russian-language desktop dashboard.
- Start and stop the Python agent from the Tauri shell.
- Resource snapshot: physical RAM, sampled CPU utilization and logical processor count.
- List and filter queued tasks.
- Create and cancel pending tasks.
- Recent local activity events.
- Browser page shows only tabs explicitly shared by the user through the Browser Bridge preview.

Tasks are persisted in SQLite by the Python runtime. **They are queued only; this version does not execute them.**

## Windows prerequisites

- Windows 10/11.
- Python 3.11+ available as `python` on PATH.
- Node.js 20+.
- Rust stable toolchain.
- Microsoft C++ Build Tools and the WebView2 Runtime.
- Tauri 2 Windows development prerequisites.

## Run in development

From the repository root:

```powershell
cd desktop
npm install
npm run tauri dev
```

The Tauri host starts the Python agent on `127.0.0.1:8765`. It injects a random per-run API token through the child process environment; the token is not displayed in the UI, command-line arguments, or persisted to disk.

If Python is installed outside PATH, set `MALENIA_PYTHON` to the Python executable path before starting Tauri. If the agent source directory is not at the repository's expected `agent` path, set `MALENIA_AGENT_DIR`.

## Build Windows installer in CI

Push to `feat/desktop-shell` or manually run the **Windows installer** workflow. It packages the Python agent and Native Messaging host with PyInstaller `onedir`, smoke-tests the native host, builds the NSIS installer, and uploads both `malenia-windows-installer` and `malenia-browser-extension` for 14 days.

## Browser Bridge preview

The extension source is in `browser-extension/`. It requests only `activeTab` and `nativeMessaging`, and sends the active tab only after the user clicks its button. The Native Messaging host is packaged at `resources/malenia-native-host/malenia-native-host.exe`. See `browser-extension/README.md` for local sideloading and the per-user registration script. Compatibility must be tested on the exact Yandex Browser version before treating the bridge as supported.

## Build frontend

```powershell
cd desktop
npm install
npm run build
```

The desktop CI validates the frontend, Tauri Rust host and Python tests on Windows. The PyInstaller `onedir` executable at `resources/malenia-agent/malenia-agent.exe` passes a Windows `--help` smoke test. The release-mode Rust host resolves and launches that executable from the onedir folder; debug mode continues to launch Python from the repository. The installer workflow is `.github/workflows/windows-installer.yml`. A downloadable installer is considered ready only after the current NSIS workflow completes successfully and the artifact is inspected.

## Security notes

- The agent binds to loopback only.
- Tauri commands proxy authenticated requests; the bearer token is held in Rust process memory.
- The current browser profile is not read by this application.
- Browser cookies, passwords and tokens are not extracted.
- Stopping the agent terminates only the child process started by this Malenia window.
- The UI does not claim that unimplemented browser/AI/image-search modules are available.

## Malenia 0.3 identity and startup

The Python package is `malenia`, the bundled executables are `malenia-agent.exe` and `malenia-native-host.exe`, the desktop binary is `Malenia.exe`, and the app identifier is `com.malenia.desktop`. Runtime configuration uses `MALENIA_PYTHON`, `MALENIA_AGENT_DIR`, and `MALENIA_API_TOKEN`. Data is stored in the new `Malenia/malenia.sqlite3` namespace, with no migration of previous product data.

The single-instance plugin brings the existing Malenia window forward on a second launch. An independently started agent or unrelated process can still occupy port 8765; the app reports that conflict without terminating or attaching to it. The agent acquires an exclusive listener on Windows before announcing readiness. Windows installer CI exercises duplicate starts of both the frozen agent and the actual desktop executable; these checks are distinct from compilation.
