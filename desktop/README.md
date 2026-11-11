# WorkPilot Desktop 0.2.0

React + Vite frontend and Tauri 2 host for the local Python Agent Runtime.

## Current capabilities

- Dark Russian-language desktop dashboard.
- Start and stop the Python agent from the Tauri shell.
- Resource snapshot: physical RAM, sampled CPU utilization and logical processor count.
- List and filter queued tasks.
- Create and cancel pending tasks.
- Recent local activity events.
- Browser, image search and model pages clearly marked as not yet connected.

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

If Python is installed outside PATH, set `WORKPILOT_PYTHON` to the Python executable path before starting Tauri. If the agent source directory is not at the repository's expected `agent` path, set `WORKPILOT_AGENT_DIR`.

## Build Windows installer in CI

Push to `feat/desktop-shell` or manually run the **Windows installer** workflow. It packages the Python agent with PyInstaller, runs `tauri build --bundles nsis`, and uploads `workpilot-windows-installer` for 14 days.

## Build frontend

```powershell
cd desktop
npm install
npm run build
```

The desktop CI validates the frontend and checks Rust compilation on Windows. The Windows NSIS bundle now includes a PyInstaller `onedir` output at `resources/workpilot-agent/workpilot-agent.exe`. The release-mode Rust host resolves and launches that executable from the onedir folder; debug mode continues to launch Python from the repository. The installer workflow is `.github/workflows/windows-installer.yml`. A downloadable installer is considered ready only after that workflow completes successfully and the artifact is inspected.

## Security notes

- The agent binds to loopback only.
- Tauri commands proxy authenticated requests; the bearer token is held in Rust process memory.
- The current browser profile is not read by this application.
- Browser cookies, passwords and tokens are not extracted.
- Stopping the agent terminates only the child process started by this WorkPilot window.
- The UI does not claim that unimplemented browser/AI/image-search modules are available.
