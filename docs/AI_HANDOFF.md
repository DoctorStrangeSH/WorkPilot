## CI update — 2026-11-12 — Excel batch checks

- Code head `e3af7541a7cafb282354e916f73b0b6485fec79f`: Python matrix run 43254104757 succeeded on 3.11/3.12/3.13. Previous code run 43253695476 executed **172 tests per version** successfully.
- Desktop run 43253695499 passed frontend build, browser bridge, permissions, AI, navigation UI tests; Tauri host still running at last check. Latest Desktop run 43254104791 has begun frontend dependency installation.
- Windows installer run 43254104814 is building; previous 43253695610 was cancelled by the later UI improvement commit. Do not claim installer green or ready for user download until latest CI completes.
- UI source validation now explicitly rejects a scan timestamp if SC ID or scan result is absent; it no longer defaults to OK/SC 101366. Unknown Asgard status is passed through to evaluator and leads to manual review. Displayed batch reason labels are localized in Russian.
- No OAuth setup request; user explicitly deferred it.

## 2026-11-12 — batch order preview and Excel copy

- User asked to continue improving Malenia, without setting up personal Gmail OAuth now.
- Feature branch: `feat/desktop-shell`, head at this handoff: `7c015267494e6ad64211436c80c9ffe12967921a`. PR #2 remains draft. `main` unchanged.
- Implemented `agent/malenia/order_batch.py`: pure bounded `preview_batch(rows)`, max 100 rows and 100 scans per row, no persistence or external fetch, uses existing confirmed `evaluate_order` rules. All occurrences of duplicate cargo_place + inventory_date are manually reviewed, rather than trusting either duplicate.
- Local API `POST /v1/orders/batch-preview` is authenticated and limited to 128KiB JSON. Tauri command `preview_order_batch` exposes this only to local UI.
- Added `desktop/src/OrderBatchPage.tsx` and nav item «Список заказов». The user pastes 2–9 TAB-delimited columns copied from Excel (cargo-place, inventory date, scan time, SC ID, scan result, Asgard status, box ID, history confirmed, issued in history). Scan with a timestamp requires **explicit SC ID and result**; no inferred OK. Unknown Asgard statuses are manually reviewed. Dates accept ISO or DD.MM.YYYY, scan times include HH:MM. Supports 100 rows, synthetic examples.
- After processing, shows status counts and per-row proposals. «Скопировать для Excel» copies a TSV report to clipboard on user action only. `safeCell` prevents spreadsheet formula injection by text-escaping cells beginning with =,+,-,@. Data never goes to SQLite or corporate services and never modifies the user's Excel/ИНВента. Data resides only in the current UI memory until copied.
- Added unit tests `tests/test_order_batch.py`, authenticated API tests in `tests/test_server.py`, UI tests in `tests/navigation_ui.test.cjs`.
- On code commit `b148b7c`, Python CI passed (run `43253546201`). On preceding commit `b148b7c`, frontend build and Node regression tests passed in Desktop run `43253545944`, while Tauri host check continued. Latest code commit `7c015267494e6ad64211436c80c9ffe12967921a` hardens UI validation so scan date without SC ID/result fails closed. CI for latest code still pending; do not claim final installer complete until passing Desktop/Windows runs.
- Google OAuth setup remains deferred. DataLens/Asgard browser access and automatic writeback are NOT implemented. Next safety check: verify latest CI and Windows installer, then consider optional import from local XLSX/CSV (only if user wants) and a real persistent result-history feature only with explicit privacy design.
- Documentation details: `docs/ROADMAP.md` stage 10. PR #2 must remain draft/unmerged until user review.

## 2026-11-12 — OAuth postponed, offline order workbench started

- User said: «Давай попозже это сделаем:) Продолжай улучшать программу». **Do not ask them to configure Google Cloud or OAuth now.**
- Current coding branch remains `feat/desktop-shell`, PR #2 draft; `main` unchanged.
- Added `POST /v1/orders/preview` in `agent/malenia/server.py`: authenticated localhost-only request; strict bounded JSON, max 100 scans; delegates to existing deterministic `evaluate_order()`. Never writes to database, Google Sheets, DataLens or Asgard.
- Added Tauri command `preview_order` and a visible sidebar page `OrderCheckPage.tsx` («Проверка заказа»), with manual inputs for cargo place, inventory date, last successful DataLens scan (SC ID/result), Asgard status, box ID and extended history.
- UI shows only proposed status/comment/color and reason. No persisted order data; source marked manual_input. Unknown evidence goes to manual review.
- Added regression tests to `tests/test_server.py` and `tests/navigation_ui.test.cjs`; latest Python matrix passed (run `43251748924`). The latest Desktop checks `43251749051` passed the frontend build and Node tests; Rust/Tauri and installer `43251749393` are still in progress. An initial navigation test mistakenly asserted the dynamic `2 ШК Выдан` value was a literal in the UI; fixed it to verify rendering of the backend-proposed comment instead.
- Added synthetic «Тестовый пример» action using fake ID `TEST-BOX-001`, plus `order_preview` runtime capability. No real order data is bundled.
- Explicit limitation: preview only takes manually selected latest scan, not full scan history; the user must check they selected the right cargo place, SC and latest successful scan.
- Later: OAuth on the user's initiative, then read-only Google Sheets import, browser permission review for DataLens and Asgard, followed by evidence-backed batch dry-run report. No sheet writeback until separately authorized.
- Baseline before this work: Python, Desktop checks and Windows installer runs all passed on code commit `05c65c3` (43239645452, 43239645705, 43239645740). Latest feature code requires new CI verification.

## Personal Gmail OAuth decision — 2026-11-12

- User explicitly selected a **personal Gmail**, not corporate Workspace, for Malenia Google Sheets OAuth.
- Recommended Cloud setup: separate project `Malenia Personal`, External audience, In production publishing status, personal-use exception from required verification (possible unverified warning and up to 100 users), one Desktop OAuth client, Sheets API enabled, ONLY `spreadsheets.readonly` scope. Do not leave in Testing: Sheets refresh token then expires after 7 days. Production removes this specific 7-day limit but not other token invalidation.
- Complete account-owner checklist, Google documentation, and caveats: `docs/ORDER_CHECKING.md` section «Настройка личного Gmail для постоянной работы».
- Latest code baseline `05c65c3`: Python run 43239645452, Desktop run 43239645705, Windows installer run 43239645740 all completed successfully. Subsequent changes to docs are [skip ci]. PR #2 remains draft and unmerged; main unchanged.
- Owner action required: create Google Cloud project/client and publish OAuth audience, then enter Client ID in installed Malenia, approve in system browser, read selected ИНВента spreadsheet/range. Never request a refresh token in chat; real account authorization has not yet happened.
- Next coding step only after real selected spreadsheet/range is validated: map ИНВента columns and create evidence-backed dry-run order results. Keep DataLens/Asgard disconnected pending their permission review.

## Latest continuation — 2026-11-12 — Google Sheets read-only connector

- Current branch HEAD before this handoff update: `05c65c3fac162d34ecb0090ffe4fa14cb7f00d39`.
- PR #2 remains draft/open/unmerged; PR #1 remains open. `main` is unchanged. Never merge without explicit user approval.
- The user confirmed Malenia 0.6.0 is installed and the app works on their PC. The current feature-branch UX/Google Sheets changes have not been installed on the user's PC.
- Order rules: `docs/ORDER_CHECKING.md`, pure evaluator `agent/malenia/order_check.py`. It uses only supplied source snapshots and always returns `write_enabled: false`. DataLens rules and exact Asgard mappings are recorded there.
- OAuth protocol: `agent/malenia/google_oauth.py` — Desktop Client ID validation, PKCE S256, random one-use state, loopback redirect validation, callback parsing, exact scope and token-response validation. It supports an optional Client Secret but does not treat it as confidential.
- Google Sheets connector: `agent/malenia/google_sheets.py` — local callback listener bound only to 127.0.0.1, Google callback query/fragment bridge (static same-origin script, no external resources), code exchange/refresh, and GET-only Sheets values API with response limits.
- Secrets: `agent/malenia/secret_store.py` — Windows Credential Manager. Refresh token, client ID and optional client secret are stored there; access token is memory-only. No SQLite/config/log/frontend token storage or plaintext fallback.
- API: `agent/malenia/server.py` exposes authenticated status/connect/read/disconnect routes. Tauri commands in `desktop/src-tauri/src/main.rs` open the system browser and proxy only read operations. UI in `desktop/src/App.tsx` asks for Client ID, optional Client Secret, spreadsheet ID and A1 range.
- Only scope requested: `https://www.googleapis.com/auth/spreadsheets.readonly`. It is read-only but grants visibility to all spreadsheets accessible to the Google account. Malenia itself only issues GET for the explicitly entered ID/range. No Google Drive scope, Sheets write scope, or write endpoint.
- UI reports «Авторизация сохранена» after OAuth, and «Подключён» only after the selected range is successfully read. Changing the spreadsheet/range clears the previous preview. Disconnect removes local credentials; the Google grant must be revoked separately in Google Account settings.
- Google OAuth setup: create an OAuth Desktop client, enable Sheets API, configure consent screen/Test users, enter Client ID in Malenia and approve in the system browser. Client Secret is optional; if a particular project requires it, enter it only in the local UI. Never paste Client Secret or refresh token into chat.
- DataLens and Asgard remain disconnected pending separate read-only permission review. Browser Bridge still sends only manually shared title and sanitized URL; no DOM/screenshots/cookies/history.
- CI for code head `05c65c3`: Python run `43239645452` passed 162 tests on Python 3.11/3.12/3.13, including compileall, PKCE, query/fragment callback bridge, optional Client Secret, disconnect race, invalid_grant reauthorization, read-only API and vault tests. Desktop checks `43239645705` passed frontend build and Node regression tests; Tauri host/Rust check is still running. Windows installer `43239645740` passed PyInstaller agent packaging and bundled-agent smoke/duplicate-start checks; Native Messaging host packaging is running, followed by NSIS/install/upgrade checks. The earlier bytes-literal syntax failure was fixed by UTF-8 encoding; explicit PyInstaller hidden imports remain. Do not claim all checks green until Desktop and Windows installer finish.
- Next: verify CI including the Windows Credential Manager integration test; then ask user to configure OAuth Client ID and test a real selected ИНВента spreadsheet/range. Confirm column mapping with the user before connecting `evaluate_order()` to a dry-run report. No writes to ИНВента, DataLens, or Asgard.

## Secure secret vault follow-up — 2026-11-12

- Current branch HEAD before this note: `1dea9eb0bcaf31bfb441fd1f6099a2b4031faf38`.
- Added `agent/malenia/secret_store.py`: `WindowsCredentialStore` stores named UTF-8 secrets as Windows Credential Manager Generic Credentials for the current user. It has no plaintext fallback on non-Windows.
- Added `tests/test_secret_store.py`: fake-backend tests for validation/round-trip/replacement/delete; a real Windows Credential Manager integration test is skipped on non-Windows and runs in the Windows Desktop checks.
- Documented the boundary in `docs/SECURITY.md`, `docs/ORDER_CHECKING.md`, and `docs/ROADMAP.md`.
- Python tests passed on Linux matrix after adding the secret store test (run `43233799550`); the latest docs-only Python run also passed (run `43233820885`). Windows Desktop checks `43233799547` still needs to complete to verify the native Credential Manager integration test.
- This vault is only infrastructure. No Google OAuth flow, client ID, refresh token, Sheets API call, or UI connection action exists yet.
- Google OAuth implementation must use a Desktop OAuth client, PKCE S256, a random one-use state, a loopback listener bound only to 127.0.0.1, and the exact read-only Sheets scope. Desktop client secret is optional and must not be treated as a protected secret. Official references are linked in `docs/ORDER_CHECKING.md`.
- Do not mark Google Sheets as connected until a user explicitly authorizes the OAuth consent screen and Malenia successfully reads a user-selected spreadsheet/range with GET only.

## Latest continuation — 2026-11-12 — deterministic order rules

- Current feature branch: `feat/desktop-shell`; HEAD at the time of this note: `b9a277defc91ae4bff4b08c3835db8b566a1450a`.
- `main` remains unchanged. PR #1 and PR #2 remain open; PR #2 is draft. Do not merge or mark ready without the user's explicit approval.
- The user previously taught the order-checking rules. They were recovered from prior conversation and formalized in `docs/ORDER_CHECKING.md`.
- Added `agent/malenia/order_check.py`: pure deterministic `evaluate_order()` over caller-supplied source snapshots. It has no HTTP client, browser access, credentials, or write operations.
- Added `tests/test_order_check.py` covering the exact DataLens and Asgard rules, source filtering, strict date boundary, missing/unknown evidence, and fail-closed behavior.
- DataLens rule: match `cargo-place` to `main_partner_code_original`; only СЦ МК Дзержинский КГТ (`SC ID 101366`); only successful `result=OK` scans; use the latest successful scan. A scan date strictly later than inventory date proposes «Найден» (green). Same calendar date is not treated as later because inventory date has no time component.
- If no qualifying post-inventory scan exists, check Asgard «Обратный поток» → «Штрихкод коробки». «Принят на ФФ» proposes «В работе» + comment «Принят на ФФ» (orange); main status «Выдан» proposes «В работе» + comment «Выдан» (orange); «В пути» requires box ID and extended history containing «Выдан», then proposes «В работе» + comment «2 ШК Выдан» (orange). Unknown/incomplete cases require human review.
- All results have `write_enabled: false`. The rule engine only proposes outcomes; it cannot change ИНВента, DataLens, or Asgard.
- Python tests passed on code commit `180cafc` (workflow `43233142074`). Desktop checks for code/docs and Windows installer were still running on the latest check at the time; see workflows `43233289458`, `43233142318`, and `43233142056`. Do not claim all CI green until the latest runs complete.
- Google Sheets OAuth is not implemented. Before coding it, use a Google OAuth Desktop client with PKCE and only `https://www.googleapis.com/auth/spreadsheets.readonly`; Google classifies that scope as sensitive. Store refresh tokens in Windows Credential Manager, never SQLite, frontend, logs, or Git. Do not use the client secret as a security boundary: installed desktop clients are public clients.
- DataLens and Asgard are not connected. Browser Bridge still transmits only title and sanitized URL after a manual share; it does not read DOM or page contents.
- Next: verify current CI; then design the OAuth onboarding/settings UX and secure token vault, with explicit consent. User must create/provide a local OAuth Client ID; do not invent credentials or ask for refresh tokens. Start with read-only access to one explicitly selected spreadsheet/range. Only after source snapshots are user-validated should the order engine be connected to a dry-run report.

## Follow-up UX update — 7c02d82

- Added a dedicated «Источники» page. Google Sheets/ИНВента, DataLens and Asgard are explicitly marked not connected to Malenia; the copy explains ChatGPT connector access does not transfer to the desktop app.
- Browser Bridge card reflects the count of manually shared tabs and links to the existing Browser page. It accurately states that only title and sanitized URL are shared; no page contents/DOM/cookies/history are read.
- Removed the dead Search placeholder route from the main navigation/page type.
- Source connection hub code: commits `61d5725`, `76a37b6`; styles `4c50cf1`; tests `7dc482f`, `7c02d82`.
- Desktop CI initially caught missing Lucide icon imports in the assistant redesign; fixed in `21786c5`. It also caught a too-strict test selector for the assistant settings class; fixed in `7c02d82`. Recheck the latest Desktop checks run before calling the branch green.
- PR #2 title is now «feat: Malenia desktop workspace and assistant UX», still draft/open/unmerged.
- Branch HEAD at time of this note: `7c02d820a378a043a9a8ebaef8e1264df225af6f`.

# Latest handoff — 2026-11-12

## User-confirmed product state

- The user confirmed that Malenia 0.6.0 is installed and working on their PC (2026-11-12).
- The user wants the application to become a simple, modern, genuinely useful personal work assistant. Keep Russian UI and the existing dark/purple visual direction.
- The first business workflow is order verification: Google Sheets «ИНВента» → Yandex DataLens → Asgard. User is teaching the exact process and has paused adding new edge cases for now.
- Confirmed order rules are documented in ROADMAP.md. Do not invent additional statuses or write back to the sheet yet.

## Latest UX work on `feat/desktop-shell`

- Current branch HEAD before this handoff update: `a08b55304563822dcaa1b5e531a658f44c613d9a`.
- PR #2 remains draft/open and unmerged. PR #1 remains open. `main` must not be changed or merged without explicit user approval.
- Main navigation now exposes «Ассистент» as a first-class destination instead of hiding the chat under «ИИ-модели». Navigation is grouped into workspace, knowledge/safety, and system areas.
- Removed the separate «Поиск» navigation item because it was a placeholder; opt-in Bing search remains inside the assistant.
- Home page no longer displays empty CPU/RAM metrics while the agent is stopped. It shows clear next steps instead. When connected, the main action opens the assistant.
- Assistant page has a clearer readiness state, resource-access disclosure, collapsed advanced controls, and quick-start prompts. Quick-start prompts only populate the composer; they do not send anything.
- Task queue wording explicitly states that tasks are saved locally but are not automatically executed.
- Added UI regression coverage in `tests/ai_ui.test.cjs` and `tests/navigation_ui.test.cjs`; Desktop checks workflow runs the navigation test.
- UX commits: `6ec48ba`, `3280383`, `f98e339`, `35765c4`, `cb6e997`, `0f3f7f4`, `07f9c39`, plus roadmap update `a08b553`.

## Truthful capability boundaries

- The task queue persists requests but does not execute them.
- Browser Bridge is manual-share metadata only; it does not read page DOM, screenshots, arbitrary tabs, cookies, passwords, or browser history.
- Google Drive access in ChatGPT is not an OAuth connection for Malenia. Malenia still needs its own explicit read-only Google Sheets integration.
- DataLens and Asgard are not yet directly integrated into Malenia.
- Do not present decorative placeholders as working connectors or skills.

## Next actions

1. Wait for Desktop checks / Windows installer / Python CI on the latest branch head and fix any failures before claiming the UX refresh is verified.
2. Update PR #2 description with the UX changes and CI evidence; keep it draft.
3. Ask the user to test the refreshed build and report usability friction.
4. Then implement a read-only Google Sheets OAuth adapter for Malenia, followed by a safe, explicitly permitted read-only browser adapter for DataLens and Asgard.
5. Build the order-check workflow in dry-run mode first. No sheet edits, order status changes, ticket creation, or other write actions until separately approved.

# Malenia — AI handoff

Last updated: 2026-11-12

## Current request and decisions

- User confirmed manual tab sharing worked on the previous installed build and now requests a **complete** Malenia rename. User states there are no tabs/tasks to preserve. The prior display-only compatibility policy is superseded: no implicit import or migration of previous product data.
- Current installed desktop: 0.4.1 (release/protocol handshake); Python package metadata: 0.2.0; extension: 1.1.0. Historical milestones below describe their state at the time. All internal identifiers/resources/environment variables/package names now use Malenia.
- Python package `agent/malenia`, entry point `malenia-agent`, desktop crate `malenia-desktop`, main binary `Malenia.exe`, app ID `com.malenia.desktop`, native host `com.malenia.browser`.
- Data/config: `%LOCALAPPDATA%/Malenia`, database `malenia.sqlite3`, extension config `browser_bridge.json`, manifest `browser-bridge/com.malenia.browser.json`. Old installations/data are not read, imported or automatically deleted.
- Frozen resources: `resources/malenia-agent/malenia-agent.exe` and `resources/malenia-native-host/malenia-native-host.exe` with adjacent PyInstaller `_internal` directories. Entry scripts: `packaging/malenia_agent_entry.py` and `packaging/malenia_native_host_entry.py`.
- Runtime environment variables: `MALENIA_PYTHON`, `MALENIA_AGENT_DIR`, `MALENIA_API_TOKEN`. Native host/desktop use the same new data directory.
- Repository is still at DoctorStrangeSH/WorkPilot; GitHub repository metadata renaming is not exposed by the available connector. Do not invent a new repository URL. PR #2 must remain draft/unmerged and `main` unchanged (baseline `712d0a8e1885cca402eaa4fdda041bb09b50e397`). PR #2 depends on PR #1 / `feat/desktop-runtime-foundation`.

## Implemented capabilities

- Windows-first Tauri 2 + React + Vite desktop UI; local Python runtime and SQLite task/event/shared-tab store.
- Dashboard: sampled CPU, RAM and Normal/Economy/Emergency mode; create/list/cancel queued tasks. Tasks are not automatically executed.
- Loopback API on 127.0.0.1:8765. Random per-run bearer token stays in Rust and the child environment; it is not sent to frontend or persisted. Standalone CLI prints its temporary token only after successfully binding its endpoint.
- MV3 extension permissions remain exactly `activeTab` and `nativeMessaging`. Tab title/HTTP(S) URL path is transmitted only after an explicit Share click. Queries/fragments are stripped; embedded URL credentials are rejected. No DOM, profile, cookies, passwords, browsing history, local storage or session tokens are read.
- Native host validates the exact registered extension origin and bounded framed JSON; at most 100 shared tabs are stored.
- Popup diagnostics: manual reconnect, five-second native response timeout, actionable missing/forbidden/disconnected/invalid-host response errors. Reconnect sends only `hello`, never reads a tab and never resends a share with uncertain delivery. Late callbacks cannot override a newer state.
- Browser registration is ASCII-only for Windows PowerShell 5.1, validates the executable and `_internal` folder, writes JSON UTF-8 without BOM, and uses HKCU-only Yandex/Chromium registration. Use the current commit-pinned download block and its ASCII/SHA256/syntax checks; never rerun an older temp setup file.

## New startup protection

- `tauri-plugin-single-instance` activates/unminimizes/focuses the existing Malenia window before another shell can own a second child agent.
- Agent listener uses SO_EXCLUSIVEADDRUSE on Windows rather than SO_REUSEADDR. An occupied/unavailable endpoint fails before announcing readiness or printing a standalone API token. No existing process is terminated or adopted.
- Windows CI now runs `smoke_test_agent_instance.py` against the frozen agent and `smoke_test_desktop_instance.py` against the real built Malenia.exe. The desktop smoke test is restricted to an isolated Windows GitHub Actions runner, uses disposable WebView storage and cleans up only the processes it spawned.

## Verification state

- Local: 24 Python tests passed, nine Node popup tests passed, frontend production build passed, and Windows PowerShell 5.1 new-namespace registration/discovery checks passed with isolated fixtures.
- Full-namespace CI passed on revision `bf9cfd6f80c980ea0bb8d0353fad9317506916ed`: Windows installer `43170856310` compiled Rust, exercised the frozen agent against duplicate/foreign listeners, passed the native host and registration smoke tests, built NSIS, and passed two-launch testing of the actual `Malenia.exe` before uploading both artifacts. Desktop checks `43170856302`, Python tests `43170856214` and Windows PowerShell 5.1 registration `43170776704` also passed. This is CI runtime verification, not a claim of installation on the user's PC.
- The previously installed build's tab sharing was user-confirmed; the new full-namespace build has not been installed or end-to-end shared on the user's PC.

## Updating the user's PC

1. Obtain the new successful Malenia installer and extension artifact. Do not install automatically, shut down the working app or delete an older installation without user authorization for those actions.
2. Install the new desktop build. Replace extension files in the original unpacked directory and reload the existing extension, preserving its ID.
3. Run the new verified registration script with the local extension ID. Do not commit the user's extension ID. Fully restart Yandex Browser and explicitly share an HTTP(S) tab.
4. New app identifier/data namespace means a fresh empty queue/shared-tab list; no old data migration is intended.

## Next milestones

- Verify full-namespace installer and startup protections, then user-machine update.
- Separately design permissions for selected-tab DOM snapshots/screenshots before implementing them. Do not broaden extension permissions silently.
- Future: desktop automation with a permission/risk gate, local/connected photo-search adapters, and an on-demand model provider measured on a 16 GB RAM machine. These are not currently implemented.

## Safety

Never read browser profiles, cookies, passwords, history or session tokens. Treat pages, OCR and files as untrusted. Do not bypass ACL/MFA/CAPTCHA, terminate unrelated apps, send external messages or execute financial/destructive actions without authorization. Never publish credentials, real work data or personal screenshots.


## Local development after 0.3.0 (not published or installed)

- User selected development only. Do not install Malenia, replace the unpacked
  extension, change native-host registration or stop running applications.
- Added internal `PermissionGate` / `BrowserAction` and additive SQLite schema.
  This is a protocol foundation, not an executable browser capability or UI.
- Exact session/tab/document/parameter binding, bounded expiry, explicit
  decisions/revocation and transactional one-shot consumption are implemented.
- 38 local Python tests pass (14 new permission tests), including concurrent
  decisions and eight competing consumers; no browser data was accessed.
- See BROWSER_PERMISSIONS.md for adapter requirements and limitations, including
  navigation races and metadata cleanup. Dual wall/monotonic deadlines prevent
  clock rollback from extending the lifetime. Address these
  before enabling real browser execution. Extension permissions are unchanged.
- Next: implement trusted request presentation and a browser document/session
  adapter, with end-to-end tests, before adding DOM/screenshot execution.
- Existing published CI evidence above belongs to the earlier 0.3.0 revision;
  it does not validate these new local changes.


## Local permission panel and decision API (next development stage)

- Added session-scoped PermissionInbox, authenticated list/decision routes,
  Tauri decision command and the desktop Permissions panel. There is no live
  request producer or browser executor. Normal runtime displays an empty panel.
- Action details are held as defensive in-memory copies; only their fingerprint
  and lifecycle metadata are persisted. Maximum 100 in-memory snapshots. Durable
  terminal metadata cleanup is still required before production browser adapters.
- Old open grants are revoked after successful socket ownership, before serving.
  A failed duplicate startup cannot revoke a running instance's grants.
- Local validation: 48 Python tests, 15 Node tests (9 existing popup checks and
  6 new React rendering checks), frontend TypeScript/production build passed.
  Native Tauri/Rust compilation and actual desktop click-through are not yet
  verified for this revision: Cargo is unavailable locally. Added rendering checks
  to the existing Windows desktop CI workflow; it has not run on these local edits.
- No publication, installation, registration change or extension replacement was
  performed. main and draft PR #2 remain untouched.
- Next: run Windows CI for these commits, then add browser-authoritative document
  identity/navigation invalidation and test real trusted request production before
  enabling page text or screenshots. Do not expose creation to arbitrary pages.


## Local selected-document lifecycle adapter

- Added BrowserPermissionSession: fresh connection identity, ordered document
  events, selected-target request creation and one-shot preparation. No real
  Native Messaging transport or executor is connected; normal UI stays empty.
- Navigation/selection/closure invalidates open inbox grants in one transaction;
  disconnect/reconnect rotates session identity. Late connection events and
  non-increasing event sequences cannot restore a prior target or permission.
- Invalidation clears selected authority before database writes, keeping dispatch
  disabled on storage failure. Tested both injected failure and SQLite-triggered
  rollback of a partially attempted batch including audit rows.
- A prepared envelope binds connection, sequence and exact action fingerprint.
  Receiving-side revalidation, tamper rejection and replay protection remain
  requirements for the real browser adapter; only a test double exists here.
- Local validation: 64 Python tests pass, including the internal request -> HTTP
  approval -> one-shot preparation path and navigation/preparation concurrency.
  UI/Rust sources were not changed in this stage; the preceding 15 Node tests
  and frontend build evidence still refer to the permission-panel stage.
- Development remains local and uninstalled. No browser profiles, page content,
  cookies, passwords or history were accessed. main and PR #2 stay untouched.
- Next: Windows CI for the accumulated local commits, bounded durable permission
  metadata cleanup, then an authenticated ordered transport and a browser-side
  identity/replay guard before enabling any DOM or screenshot capability.


## Local bounded retention and signed event protocol prototype

- PermissionGate now performs transactional expiry/retention maintenance with a
  global limit of 100 open and 100 terminal permission rows. Terminal pruning
  never removes task/shared-tab data or audit events. Audit-log retention and
  physical SQLite file-size management remain unchanged. Added a status/time index.
- Added internal BrowserEventChannel with exact extension-origin matching,
  detached HMAC-SHA256 over bounded UTF-8 body bytes, strict JSON/schema checks,
  fresh connection identity and contiguous event sequencing. No HTTP/native-host
  route, socket or production key provisioning was added. The extension and
  installed registrations were not changed.
- Unauthenticated input/replays do not mutate authority. Authenticated gaps or
  malformed events close the channel and invalidate selection. Old connections
  cannot close new ones. Operational errors close the channel without retry.
- Local validation: 80 Python tests pass, including 5 retention tests and 11
  signed-channel tests. No frontend/Rust changes in this stage; their earlier
  evidence and pending Windows CI status remain as recorded above.
- Docs: BROWSER_CHANNEL.md records protocol and remaining trust requirements.
  HMAC possession is not proof of browser identity; trusted per-connection key
  provisioning, origin acquisition, liveness/timeouts and an actual transport
  still need implementation. This is not an authenticated live browser bridge.
- All work remains local and uninstalled; main and PR #2 were not changed.
- Next: run Windows CI for accumulated commits, implement trusted transport/key
  bootstrap and browser-side identity/replay checks before enabling execution.


## User-authorized installation and reusable manual-ID setup (2026-11-12)

- User explicitly requested installation and an ID field for deploying to others.
  Installed the previously Windows-CI-verified Malenia 0.3.0 NSIS artifact from
  run 43170856310, artifact 13922905187. Verified archive SHA256 matches
  48ae00936b87eeaa3c593a406301291557e0436e43ea0752c097811e89a592a4.
  NSIS /S returned 0; application exists under LOCALAPPDATA/Malenia and was opened.
- Updated only the known extension source files in the user's supplied unpacked
  folder after backing those files up locally. No browser profile was accessed.
  Registered com.malenia.browser for the user-provided ID; installed native-host
  hello returned ok and share_active_tab. No test tab was inserted in user data.
  Browser-side extension reload/restart and explicit real tab sharing remain user
  steps; installed UI agent startup has not been clicked/verified in this turn.
- Added reusable Connect-Browser.cmd and setup_browser_bridge.ps1 with blank ID
  field, validation, automatic host discovery and optional file chooser. No user
  ID/path is embedded in these source files or the reusable distribution kit.
- Setup fails closed on non-ASCII/source hash/parser failures; accepts exactly the
  pinned registration source's LF/CRLF SHA256 values. ASCII PowerShell source
  decodes Russian UI labels at runtime. Direct -ExtensionId CLI also supported.
- Windows PowerShell 5.1 local checks passed: wizard's verified-source path,
  isolated repeated registration/discovery/data preservation/invalid host checks,
  ID validation, localized-label decoding, non-ASCII and tampered-source rejection.
- Reusable distribution outputs/Malenia-0.3.0-Windows.zip contains installer,
  extension folder, blank-ID setup, README and SHA256SUMS. docs/WINDOWS_INSTALLATION.md
  gives generic instructions. Keep the extension folder stable after loading it.
- This is the stable published 0.3.0 installer plus locally tested setup helper,
  not a newly compiled build of the accumulated permission/channel prototypes.
  New helper CI steps are prepared locally; no new GitHub publication/merge.


## Local AI milestone in progress (0.4.0)

User chose a compact local model for a first test. Added bounded Ollama client,
authenticated chat/status API, asynchronous Tauri chat command, Start Ollama and
AI chat page. No automatic context, tools or chat persistence. Default Qwen 2.5
0.5B, context 2048, one generation, output 384 tokens, keep-alive 30 seconds.
89 Python tests passed and frontend build passed before final packaging edits.
Official Ollama v0.40.16 Windows archive was verified against its GitHub asset
SHA256; CPU runtime extracted under LOCALAPPDATA/Malenia/ollama. Runtime launch
and compact-model download are being verified; installation of the new desktop
build is still pending. Do not treat source changes as delivered functionality.
See LOCAL_AI.md. main must stay unchanged and PR #2 unmerged.


## Delivered Malenia 0.4.0 first local chat (2026-11-12)

- Published source revision 3005284eb069216ea3ffe6e4ce59704c6a7b105c in
  feat/desktop-shell; all 36 changed public files were fetched and compared to
  local source. main stays at 712d0a8e1885cca402eaa4fdda041bb09b50e397 and
  PR #2 remains draft/open/unmerged. Local history merged the published revision.
- All CI succeeded: Windows installer 43190208605, Desktop checks 43190208487,
  Python 43190208614, Windows PowerShell registration 43190208789. 89 Python tests,
  15 Node tests, frontend build, Rust compilation, frozen agent/native host,
  registration and real desktop duplicate-launch smoke checks passed.
- Installer artifact 13929834613 (ZIP SHA256
  069283c07bc12b3e640d10888a7eb55d8f1333c97c787461709da28bd21e6240) was installed.
  Important upgrade finding: NSIS returned 0 and desktop was new, but installed
  resource agent was still old and returned HTTP 404 for /v1/ai/status. Cause was
  not conclusively established. Closed the exact Malenia app, verified its
  resource processes stopped, backed up old resources and copied BOTH frozen
  resource directories from the hash-verified installer. Every copied file hash
  matched. User database/config/extension registration were not removed.
- Post-repair actual installed frozen agent -> Ollama -> Qwen 0.5B chat succeeded
  against an isolated fixture DB and replied 2 + 2 = 4. Updated desktop was opened.
  User click-through of the new chat is not yet independently confirmed.
- CPU runtime is official Ollama v0.40.16, model qwen2.5:0.5b Q4_K_M (~398 MB).
  Owned CPU server was started by setup; no unrelated process was killed. Ollama
  sees one compact model, cloud tags/tools/context attachments are disabled.
- Intel Graphics experiment: OLLAMA_VULKAN=1 alone skipped iGPU; adding
  OLLAMA_IGPU_ENABLE=1 offloaded ~456 MB of shared RAM. Short 48-token test gave
  CPU 50.17 tok/s and iGPU 45.93 tok/s; CPU remains the default. No driver change.
- Model quality limitation observed: a planning prompt caused invented order
  quantity/address. Compact-model answers must not be treated as verified data.
- Next reliability work: an installed-upgrade test and resource manifest/version
  check must detect stale bundled agents even when the NSIS exit code is zero.
  Fresh-build smoke checks alone missed this upgrade problem. Preserve the
  existing user data and restrict any process stops to owned Malenia processes.


## 0.4.1 task review and upgrade safeguards (delivered)

- AI replies offer an explicit Create task button, editable title/description
  review and a separate queue confirmation. No tool execution is enabled.
- A UUID submission key is stored transactionally with the task and event.
  Concurrent/retried submissions return the same task, including after restart
  or cancellation. Changed content for the same key is rejected with HTTP 409.
  After a save attempt the UI freezes reviewed text for identical safe retries.
  Oversized replies are shown in full and must be shortened before submission.
- Authenticated /v1/runtime advertises release 0.4.1, protocol 1 and capabilities.
  Desktop requires the exact release/protocol and task_idempotency capability;
  a mismatch stops only its own spawned agent and reports reinstall guidance.
  This is a compatibility handshake, not cryptographic resource verification.
- NSIS preinstall/preuninstall hooks test write access to the two frozen resource
  executables, without writing data, and exit 32 if locked. No process killing.
  This addresses resource locks; the original 0.4.0 cause remains unproven.
- New CI-only installed-upgrade test checks every installed resource hash against
  build output, real installed runtime/task API, locked-agent refusal, stale-exe
  repair and preservation of fixture data/task/submission key after reinstall.
  It runs only on an isolated Windows GitHub Actions runner, never on user data.
- Windows unread-body connection resets during denied POSTs were reproduced.
  Access denial now discards at most 32 KiB without parsing, with a 250 ms bound,
  before sending 401/403. This never invokes chat or task creation.
- Local: 94 Python tests, 16 Node tests and production frontend build passed.
  Rust/NSIS build and installed-upgrade execution subsequently passed Windows CI.
  Installed version 0.4.1 was verified as recorded below.
- main baseline and draft/unmerged PR #2 were checked unchanged before publication.


## Verified 0.4.1 delivery (2026-11-12)

- Published implementation 6d04ea98f31798db3b0faef03bad85fe5ba68f52; all 18
  changed files fetched and compared. First installed-upgrade CI failed because
  the test's 2-second HTTP timeout was shorter than Ollama status's 3-second
  timeout. Fixed only the test to allow 10 seconds in source revision
  ba8aced1180bc28ad95695a9e325773bb0513b7f; fetched and compared that file too.
- Successful Windows installer run 43196940816; Desktop checks 43196940746;
  Python tests 43196940748. PS5.1 registration passed 43195638724 on unchanged
  registration source. 94 Python / 16 Node tests, frontend, Rust, frozen agent,
  native host, registration and real desktop single-instance checks passed.
- CI installed-upgrade test passed: initial hashes match, running agent causes
  nonzero setup exit without killing it, stopped-agent reinstall restores a
  deliberately stale executable, and fixture task/key/data survive. No user
  database or browser profile is involved in this test.
- Installer artifact 13934495192 ZIP SHA256:
  a422038b12b48aeba9aa9a5bfc24dbb7a02feddbae0c87b3938632cc25e8364e.
  Verified before extraction/install. Installed with /S /UPDATE /NS after
  confirming no processes from the installed Malenia directory were running.
  Setup returned zero; all 125 installed resource files AND desktop executable
  matched the extracted verified payload. Desktop file version is 0.4.1.
- Actual installed frozen agent passed /v1/runtime release/capability check and
  duplicate-task submission check using an isolated temporary database. Actual
  installed agent -> existing local Ollama -> Qwen 0.5B answered 2 + 2 = 4.
  The verification-owned agent was stopped; existing model server preserved.
  User model/settings/tasks/extension registration were not removed or replaced.
- GitHub API, commit-pinned raw and cache-busted branch raw registration script
  were fetched again and are identical ASCII. SHA256 remains
  f80ece220c84267ba9f0bb5ebdbaa47e8e43046cb674a552983187a2275a7392.
- Task creation queues only reviewed text. No automatic execution, browser DOM
  access or automatic context was added. User click-through remains a user test.
- main must remain 712d0a8e1885cca402eaa4fdda041bb09b50e397; PR #2 draft/unmerged.


## 0.5.0 Sherlock and explicit knowledge (verified target-PC kit)

- User approved continuing model/memory/knowledge work, then requested Sherlock
  branding and a stronger model for a DIFFERENT 32 GB NVIDIA PC. Exact GPU/VRAM
  is unknown. App name remains Malenia. Technical model provenance stays in docs;
  no claim of original training. main and PR #2 must remain unchanged/unmerged.
- Added explicit remembered-user-text review, visible/deletable SQLite knowledge,
  bounded selected-folder Markdown snapshots and lexical retrieval with excerpts.
  No existing Obsidian path was supplied; prepare a separate sample folder in the
  output kit. Do not search user directories for a vault or read browser profiles.
- UI supports main/light/extended Sherlock downloads after an explicit click,
  with free-RAM guard. Target main is Qwen3 8B. No large model downloaded/loaded on
  the development PC; its 0.4.1 installed app has not been upgraded in this stage.
- Downloaded only Qwen3 0.6B for an actual small-model comparison. It also answered
  Japan's capital incorrectly. It is an experimental fallback, not a quality fix.
  No actual 8B model inference or NVIDIA offload verified on the second PC.
- Local validation so far: 104 Python tests, 18 Node tests, frontend build. Windows
  Rust/NSIS and frozen knowledge/upgrade checks must pass before distributing.
- See LOCAL_AI.md for limits/architecture and THIRD_PARTY_MODELS.md for actual IDs
  and upstream license links. Next: Windows CI, verified target-PC kit, then actual
  user-machine quality/performance evaluation before claiming an improvement.


## Verified Sherlock 0.5.0 target-PC distribution (2026-11-12)

- Final code revision 5fa2711472516e35b10462d8c184aa5fa47cac1c. Published 19
  changed files were fetched and compared; final preference-prompt change also
  fetched and compared. Confirmed memory preferences are distinguished from note
  data; neither grants tool/action/file permissions.
- Successful CI: Windows installer 43202735277, Desktop checks 43202733579,
  Python matrix 43202733675. 104 Python and 18 Node tests, frontend/Rust, frozen
  agent/native host, Windows PowerShell 5.1 registration, desktop single instance
  and installed-upgrade hash/lock/repair/preserved-task-and-knowledge tests passed.
- Installer artifact 13935179133; artifact ZIP SHA256
  91a1bd4a7654bd5e54dc3fffb5829f202247f7e7162d1ef28ed9445fc34aa2cf.
  Download verified before extracting. Packaged desktop reports 0.5.0. Downloaded
  frozen agent was separately started on an ephemeral port with temporary data:
  runtime capability/version, idempotent confirmed memory, sample Markdown import,
  persistence after restart and deletion all passed. Only fixture processes stopped.
- Prepared outputs/Malenia-0.5.0-Sherlock-Windows.zip with verified installer,
  Russian start guide, sample Obsidian folder, optional generic Browser Bridge
  setup/extension and SHA256 manifest. No personal extension ID or user directory.
  Full official local runtime and large model weights are downloaded on target PC,
  not embedded. Official model manifests confirmed 8B ~4.87 GiB, 4B ~2.33 GiB,
  14B ~8.64 GiB. No 8B/14B weights were downloaded on the development PC.
- Current computer's installed 0.4.1 was NOT replaced. Target second-PC installation,
  actual 8B quality/latency and NVIDIA offload remain unverified and require that PC.
  Do not describe this kit as an already installed/benchmarked stronger model.
- Internet fact search and autonomous actions remain unimplemented. This iteration
  adds setup, explicit persistent memory and bounded local reference retrieval.


## 0.5.1 source-constrained knowledge work (verified kit)

- User requested continued project improvements. Focus: exact order-code retrieval,
  relevant long-note passages, explicit search without inference, and opt-in answers
  only from matching saved knowledge. No new browser permissions/tools/internet.
- Codes such as AB-17 no longer collide with AB-170. Retrieved snippets include
  snapshot offsets. General code-free preferences remain available as context;
  strict mode and search preview exclude unrelated preferences.
- knowledge_only returns a fixed refusal without any model/status call if no match.
  With matches it sends only the current question/context and requests structured
  output. Unknown/duplicate/missing citations and malformed output are rejected.
  Citation validation does NOT verify factual entailment; do not overclaim safety.
- Chat source metadata is now preserved on screen over subsequent messages while
  excluded from model history. Search results arriving after disconnect are ignored.
- Local: 114 Python and 20 Node tests, production frontend build passed. Actual
  compact-model fixture probe answered AB-17 with Tokyo, using only its matching
  note; unknown AB-19 returned generated=false. Target 8B/NVIDIA still untested.
- Installed current-PC app remains 0.4.1. Prepare a new verified kit for the other
  32 GB NVIDIA machine; do not claim remote installation or download heavy models.
- Next: publish feature code, run Windows CI including installed-upgrade fixture
  search/preservation, verify artifact, build 0.5.1 kit and update handoff evidence.
  Keep main at 712d0a8e1885cca402eaa4fdda041bb09b50e397 and PR #2 draft/unmerged.


## Verified 0.5.1 distribution (2026-11-12)

- Code revision 611b58023aa56edcc21ca8ffdac6210f3175f4c3, all 18 published paths
  fetched and compared to local source. No merges to main; PR #2 remains draft.
- All CI passed: Windows installer 43206566134, Desktop checks 43206566165,
  Python matrix 43206566115. 114 Python / 20 Node tests, frontend, Rust, frozen
  agent/host, Windows PowerShell 5.1 registration and real desktop single-instance
  checks passed. Installed-upgrade test now also verifies AB-17 vs AB-170 search,
  no-generation response for unknown AB-19, and note preservation after reinstall.
- Artifact 13938586944 ZIP SHA256:
  8f36f2ed094857dc74fac54ae95ae5aa92d03a9e27f684809edcb51f07185740.
  Download verified; extracted desktop version is 0.5.1. Actual downloaded frozen
  agent passed exact-ID retrieval, snapshot offsets, no-generation strict refusal,
  and persistent search after restart on an ephemeral port/temporary fixture DB.
- Actual local compact-model source probe: AB-17 answered Tokyo with only its
  matching note/citation; AB-19 generated=false with no sources; missing phone
  yielded the fixed insufficient-information reply after model sufficient=false.
  This is a tiny fictional smoke probe, not an 8B/NVIDIA accuracy benchmark.
- Prepared outputs/Malenia-0.5.1-Sherlock-Windows.zip: verified installer, updated
  Russian instructions, explicitly fictional AB-17/AB-170 examples, original sample
  Obsidian notes, generic manual-ID Browser Bridge and per-file SHA256 manifest.
  ZIP contents/hash tested; no personal extension ID/directory. Setup scripts are
  ASCII and registration hash still matches pinned approved source.
- The agent did not replace the current PC installation (last verified 0.4.1); no model download/installation was run
  for the remote 32 GB PC. Its actual deployment and 8B/GPU evaluation remain user
  steps. Main must stay 712d0a8e1885cca402eaa4fdda041bb09b50e397, PR #2 unmerged.
- Citation checks only establish that cited IDs were supplied; they do not prove
  answers follow from source text. No autonomous actions or internet lookup added.


## 0.6.0 — runtime setup and explicit public search (implemented; see verified delivery below)

- User requests in-app Ollama installation and internet access; publication to feat/desktop-shell is authorized. main and draft PR #2 stay unchanged/unmerged.
- Added pinned official full portable runtime with size/SHA256 checks before extraction, safe ZIP paths, symlink/size bounds, unique staging, free-space preflight, download progress and async shell start. Existing healthy server or standard Ollama reused. No administrator/startup/driver changes. Model download first prepares runtime.
- Added opt-in fixed-endpoint Bing RSS search: current question only; no saved knowledge/history/tasks sent externally. Only snippets, not page fetches; bounded results, redirect rejection, safe displayed links, grounded structured responses and known citation IDs. No browser profile/cookie/password/history access.
- Runtime source/schema release 0.6.0; public_search capability required by shell. Installed current-PC version remains 0.4.1 until actual verified installation. Target 32GB/NVIDIA PC is separate; exact GPU still unknown. No heavy model downloaded here.
- Windows CI includes Rust archive verification tests and a separate real official-runtime download/hash/extract/version/start test on an isolated loopback port without model weights.
- Local checks and Windows CI delivery evidence will be appended after completion. This section describes code, not an installed update.


## Verified 0.6.0 delivery (2026-11-12)

- Final executable code revision: `1ce83249358a4904cc025a616632623dc34cc234` on feat/desktop-shell. Initial actual Windows install test caught a stack overflow in nested 1MiB stack buffers; fixed with heap-backed 64KiB streaming buffers. Do not distribute the earlier 9c2ec92 build.
- Python matrix: successful run `43211292056`; local Python 120 tests and Node 22 tests passed, frontend build and diff whitespace checks passed.
- Windows desktop checks `43211292311` / job `131159270187`: cargo check, archive hash/size and traversal unit tests, and REAL official 1.6GB runtime download + SHA256 + full CUDA extraction + version + serve/readiness on isolated loopback port all passed. Official runtime smoke took 89.02s; no model weights downloaded there.
- Windows installer `43211292109` / job `131159271354`: Windows PowerShell 5.1 ASCII/parse checks and actual registration/re-registration/data-preservation path passed; frozen/native-host/single-instance checks passed; actual NSIS install/resource-hash/locked-agent refusal/reinstall/preserved task-and-knowledge tests passed.
- Installer artifact `13940079950`, ZIP SHA256 `9d0b491299f309465b3ea175d2a4c9cd8deda5f91bc177ec32dabff8294b9317`, verified before extraction. Installer ProductVersion confirmed 0.6.0.
- Extracted frozen agent was started with temporary app data, random bearer and ephemeral port. Live public query «столица Японии» via web mode returned «Токио», four snippets and three valid cited IDs. Empty local knowledge mode returned deterministic refusal without generation; combining web/knowledge-only rejected with 422. Temporary process/data cleaned up; no working install/registration changed.
- Prepared `outputs/Malenia-0.6.0-Sherlock-Windows.zip`, 11119309 bytes, 19 files, outer SHA256 `a91bc6aa55be55698211f130522f255fb1775b8df49ea64be5415f4a97a488ec`. Includes verified installer, in-app runtime/search guide, sample notes, generic extension-ID setup and UTF-8 per-file SHA256 manifest; all ZIP CRCs and manifest hashes verified. Contains no engine/model weights or personal extension ID/path.
- Current-PC existing installation was not upgraded; this is a prepared/tested kit for the separate target PC. Actual target GPU/VRAM and 8B model quality/performance still require testing there. Search uses snippets, not full-page browsing; validated citations do not prove factual truth. main stays at `712d0a8e1885cca402eaa4fdda041bb09b50e397`, PR #2 stays draft/open/unmerged.


## 2026-11-12 — Batch paste evidence integrity follow-up

- Work continues on PR #2 (`feat/desktop-shell`), not `main`; PR #2 remains draft and PR #1 is its prerequisite. Do not merge without user approval.
- Commit `767e6b5` tightened `desktop/src/OrderBatchPage.tsx`: scan timestamp, SC ID, and result must be supplied together; incomplete partial scan metadata is rejected with a row-specific error rather than silently omitted. Asgard box ID/history fields are rejected without an Asgard status and are valid only when status is `В пути`.
- Commit `6b7a162` added UI regression assertions in `tests/navigation_ui.test.cjs` to keep those guards in place.
- This is still *manual data, read-only preview only*. No DataLens/Asgard automation, no ИНВента writes, and no implied company-system permissions. Google OAuth setup is postponed by user's request.
- GitHub Actions were pending at the time of writing: Desktop checks `43270731201`, Python tests `43270730767`, Windows installer `43270730529`. Check the exact latest SHA before reporting a passing build.
- Next valuable step after CI: improve pasted evidence auditability and source mapping without inventing access to corporate tools; continue toward separately approved read-only integrations.


## 2026-11-12 — Explicit live-site reading foundation

The user clarified that ИНВента, DataLens and Asgard are **websites**, not downloadable files, and wants Malenia eventually to navigate/read these authenticated resources herself.

Implemented on `feat/desktop-shell`:
- Browser Bridge manifest now requests `scripting` alongside `activeTab` and `nativeMessaging`.
- Popup has a separate explicit **«Прочитать страницу»** button. Upon a user click, `chrome.scripting.executeScript` reads up to 16,000 characters of `document.body.innerText` from the currently selected HTTP(S) tab and sends the URL without query/fragment plus that bounded text to the registered local native host. It does not inspect input values, cookies, browser profile, unrelated tabs or hidden DOM. Note: rendered text **can** contain sensitive corporate information; consent UI discloses that.
- The native host validates the page snapshot and returns only a character count and `persisted: false`; it intentionally does **not** persist or expose raw page text via the agent/API. There is **no automatic navigation, site parsing, cross-site reconciliation, background automation or write capability** at this milestone. Do not advertise this as full autonomous site access.
- Added UI and Python regression tests; pending CI check at latest head: Desktop `43271474063`, Python `43271473560`, Installer `43271473767`. Recheck current SHA before asserting success.
- PR #2 remains draft; main unchanged. Browser Bridge extension must be reloaded and the latest installer/native host deployed before on-device use. Earlier installer does not understand `inspect_active_page`.
- Future phases: named resource adapters with explicit host allowlist, scoped permission, user-verified DOM/table mapping, read-only multi-page navigation and provenance, then deterministic order reconciliation. Any status write requires a separate explicit permission/confirmation flow. Site automation must respect organizational access policy and must never bypass MFA/CAPTCHA or access restrictions.


## 2026-11-12 — Scoped autonomous three-site read-only traversal

User requirement: Malenia should perform the full ИНВента → DataLens → Asgard order-checking job, not ask the user to copy Excel or manually visit every page. Do not misrepresent a three-page read as complete order reconciliation.

Implemented in PR #2 branch `feat/desktop-shell`:
- `browser-extension/automation.js`: bounded 3-role (`inventory`, `datalens`, `asgard`) page visit engine. User-configured HTTPS URL paths only (no query/fragment/credentials, no local targets or custom ports); Chrome requests optional per-origin host permission from a direct user gesture. Opens each URL in an inactive tab, waits up to 20 seconds, validates final origin in browser metadata **and at script execution**, captures up to 16k rendered characters, sends to local native host, and closes only the tab it created. Redirects, timeouts, empty pages, host rejection and permission failures fail closed to `needs_attention`.
- `browser-extension/background.js`: MV3 service worker task runs independent of popup using persistent Native Messaging `connectNative` port for task lifetime; one outstanding request at a time, request IDs matched, five-second response deadline. It stores only sanitized role/progress/character-count metadata in `chrome.storage.session`. Port is closed after run; no autonomous task runs on startup.
- Popup version 1.3.0 exposes three resource HTTPS URL fields and one-button automatic read-only audit, after Chrome's exact-origin permission prompt. Sanitized resource URL paths are retained in extension local storage for the next run. No credentials or page text are saved.
- Native host already supports `inspect_active_page`, validates bounded text, reports characters and `persisted: false`, but does **not** forward text to the local AI agent or correlate orders. Thus the current result is a 3-site read success/failure summary, not an actual business workflow output.
- Desktop Browser/Sources privacy messages corrected for new opt-in rendered-text reading. `browser-extension/README.md` explains capability and setup. `tests/browser_automation.test.cjs` tests URL restrictions, sequential traversal, cleanup, redirect block, host failure. CI desktop-checks workflow runs it; existing popup mock and navigation privacy tests were adapted.
- Latest relevant fixes: `b374095c` browser popup test mock; `85f3064b` privacy UI assertion update. Older desktop CI runs failed on stale test assertions, not on a proven packaged-browser failure. Check latest SHA Actions results before reporting success.
- **Still missing before fulfilling user's objective:** actual authenticated target site URLs, per-site DOM/table/SPA mapping, search and pagination navigation, resilient site-specific adapters, structured data transfer through an authenticated ephemeral channel to Malenia agent, joining the three sources per cargo-place and inventory date using `evaluate_order`, user-visible job progress and report in the DESKTOP app, and separately permitted status edits. Do not invent source selectors, rely on screenshots from unrelated pages, or claim unattended business-data edits.
- No site-write capability; no credentials/cookies/history/form-value extraction, MFA/CAPTCHA bypass, persistent browser session scraping, or unreviewed automatic record changes. Do not widen permissions without explicit approved task scope.
- PR #2 remains draft; main unchanged. Latest installed binaries may predate `inspect_active_page`; new installer plus unpacked extension reload required to test this on the user's machine.


## 2026-11-12 — First ephemeral site-table reconciliation bridge

Continued PR #2 `feat/desktop-shell`. The user insists on autonomous order-checking rather than Excel paste or manual per-page clicks.

New implementation:
- `agent/malenia/site_reconciliation.py` parses bounded structured HTML table rows passed by the extension, requiring exact column names. It joins inventory cargo-place/date to DataLens exact cargo key + SC ID 101366 + result OK, and falls back to Asgard accepted/issued states using existing `preview_batch` + `evaluate_order`. Returns **only aggregate counts**, with read_only=true and write_enabled=false; no data persistence. Duplicate inventory/Asgard identities fail closed. Status `В пути` remains manual, because visible generic table text is not verified extended box history.
- `agent/malenia/native_messaging.py` supports `reconcile_site_tables`: validates snapshots using the new module, returns `site_tables_reconciled` summary or a generic mapping error, never exports cargo identifiers or source text in its response.
- `browser-extension/automation.js` now attempts strict-header HTML table extraction for the three configured pages, sends a single ephemeral reconciliation request after all three pages are read, and stores only outcome counts in extension session progress. It does not search/paginate the remote apps or read inputs. No page text or cargo code is saved. The popup shows explicit distinction between `reconciled` and merely `read_only`.
- Tests: `tests/test_site_reconciliation.py`, `tests/test_native_messaging.py`, `tests/browser_automation.test.cjs` now cover deterministic matching, duplicate records, unavailable mappings, no write mode, and no identifiers in progress. `browser-extension/README.md` documents the exact provisional field names and the critical limitation: they are **not verified to match any real company website**.
- A JavaScript source corruption caused an `Illegal continue statement` in CI; fixed in commit `474963fc`. Earlier Python CI was green as of `a9914851`, while browser desktop CI needed the syntax fix. Check latest SHA and workflow state before asserting successful browser tests or installer.
- Do not claim live ИНВента/DataLens/Asgard functional integration yet. Current code tries to match only visible standard HTML tables with literal internal field labels, and only up to 100 rendered rows. Actual resource UIs, selectors, SPA state, search forms, pagination and approved mutation capabilities still must be mapped and tested in the user's authorized environment.
- Next: actual read-only adapters per site with proof of current document/site identity, query-by-cargo, pagination and source provenance, coupled to user-visible desktop job/results. Need explicit authorization for any write task. Never bypass MFA, CAPTCHA or organizational policy.


## 2026-11-12 — Read-only automatic pagination

- The user reiterated autonomous execution: Malenia must navigate sources herself, not require per-page manual assistance. Continue on PR #2 in `feat/desktop-shell`, not `main`.
- `browser-extension/automation.js` now follows an explicit HTML `a[rel~='next'][href]` link for up to 5 pages **per resource**, only within the originally approved HTTPS origin. Cross-origin redirects, credentials, fragments, custom ports, repeated URLs, table schema changes and more than 100 total rows fail closed. The extension aggregates matching rows before sending one ephemeral `reconcile_site_tables` request to the local native host, closes its inactive tab on completion/failure and retains only per-resource reading counts and page count in session progress. No site record changes are possible.
- `browser-extension/popup.js` reports the number of pages read per resource.
- `tests/browser_automation.test.cjs` adds multi-page merging, restriction on next-page URL, and pagination cycle coverage. CI workflow already includes this test. Desktop run `43276041134` has passed frontend, Browser Bridge, autonomous browser traversal, permission panel, AI and navigation Node checks; Rust checks were still running at last observation. Python run `43276041170` passed. Recheck the latest head and installer before claiming all checks green.
- `browser-extension/README.md` describes the exact rel-next behavior and limitations. The actual user's corporate sites may use JavaScript virtualized grids/search; no verified site-specific adapters exist yet. This milestone does not meet the full end-to-end requirement, and **reconciled visible tables do not prove complete corporate data coverage**. Next work should target site-specific dynamic navigation/search and reliable completeness/provenance signals; do not invent selector names or claim live business-site access.


## 2026-11-12 — Accessible dynamic table read support

- Continued the existing PR #2 `feat/desktop-shell`; do not merge the draft without explicit approval. `main` unchanged.
- `browser-extension/automation.js` can now read a fully-rendered **ARIA grid/table** (roles grid/table, row, columnheader, gridcell/cell), using the same exact source field names as the existing HTML table adapter. Extraction is read-only, bounded, same-origin and excludes form values/cookies.
- An ARIA grid is eligible only when `aria-rowcount` exists and equals its rendered row count, including the header; otherwise `incomplete=true` aborts that source and suppresses all aggregate reconciliation. Missing columns, malformed data and more than 100 rows also fail closed. This prevents false positives on virtualized lists where only a viewport's rows are in the DOM.
- `tests/browser_automation.test.cjs` includes synthetic incomplete-grid suppression and source checks for extractor guards. Browser Bridge/desktop CI results for the current head still need verification; latest green Python on commit `19e2caf0` (CI run `43276661779`). Do not claim that the actual three company websites have been tested.
- `browser-extension/README.md` documents the generic ARIA compatibility and restrictions.
- **Next critical gap:** source-specific search flows, SPA navigation/button pagination and completeness/provenance validation for actual ИНВента, DataLens and Asgard. Their layouts are unknown to this repository; do not invent CSS selectors or imply that autonomous real-order processing already works. Work toward opt-in per-site adapters inspected in the user's authorized session. No site mutations implemented, no MFA/CAPTCHA bypass.


## 2026-11-12 — Opt-in autonomous exact-GET cargo searching

The user reiterates that Malenia must perform the operator's job, not require manual copy/paste or tab-by-tab clicks. Continued code in draft PR #2 branch `feat/desktop-shell` (do NOT merge without approval).

Implementation:
- `browser-extension/automation.js` adds `exactGetSearch()` and an optional `run(...,{exactGetSearch:true})` mode. It first reads the inventory cargo codes, validates at most 20 unique conservative ASCII cargo identifiers, then for each code independently opens DataLens and Asgard tabs. On these sites it recognizes **exactly one** native HTML GET form with one plain named text/search input: DataLens `main_partner_code_original`, Asgard `cargo_place`. Forms with hidden/password inputs, additional named inputs, existing query strings, ambiguous matches, arbitrary POST or unapproved origins are rejected. It constructs a single-parameter same-origin URL (without executing form submission/clicks), visits its own inactive tab, reads the result, and requires every returned row to contain the exact searched cargo code. On any source failure, no aggregate reconciliation is emitted.
- `browser-extension/popup.html` has an opt-in search checkbox; `popup.js` forwards its value, and remembers this choice locally after a successful start. `background.js` enables the mode only on an explicit `true` flag.
- New tests in `tests/browser_automation.test.cjs` cover two-cargo multi-site queries, mismatched result identities, GET-only guards, and simulated DOM form selection. A test fixture syntax error was fixed in commit `47b4fe04`. Syntax compilation for `automation.js`, `popup.js`, `background.js`, and the test file passed via V8. Recheck current CI before asserting new tests pass.
- `browser-extension/README.md` documents the precise opt-in contract and strict limitations. Query URLs contain cargo identifiers and can appear in site/server logs, but are not stored in extension progress or returned to the local host.
- This is **not yet verified with actual corporate websites**: whether their forms are native GET with expected field names is unknown. JavaScript search, button interaction, SPA custom filters, virtualized pagination and Asgard extended box history still need approved, tested adapters. This does not perform any status writes. The desired final UX remains one user command, autonomous execution under explicitly approved resource permissions.


## 2026-11-12 — Privacy-safe browser diagnostics and automatic search default

User keeps requesting autonomous browser tasks, not repetitive manual operations. Continued draft PR #2 `feat/desktop-shell`; do **not** merge without user authorization.

- `browser-extension/automation.js` now maps only a **fixed allowlist of internal browser failure codes** to task progress. Browser exception strings, sensitive URLs, cargo identifiers, form contents and source text are never persisted as diagnostic messages. Unknown errors become `site_or_browser_error`. Known codes include cross-origin redirects, malformed/incomplete grids, pagination errors, exact search-result mismatch and local host rejection.
- Native GET search introspection distinguishes `unsupported_search_form` from `dynamic_search_ui` (non-form search widget) and `unmapped_search_form` (no suitable match). It does NOT interact with unknown JavaScript controls or infer site-specific selectors; no corporate write actions.
- `browser-extension/popup.js` displays actionable Russian descriptions for the safe codes, and the optional read-only per-cargo search mode is now **enabled by default** on first configuration (user can uncheck and saved explicit `false` persists). The browser's origin-permission prompt and direct start action still apply.
- `tests/browser_automation.test.cjs` covers secret-bearing browser errors, login redirects, simulated native form mismatch and a dynamic search widget. `browser-extension/README.md` documents classification and limitations.
- Prior CI for full head `36cd7be1` passed Python and Desktop; Windows installer succeeded on `47b4fe04`. For the new diagnostics commits, recheck latest Actions `Desktop checks` and Windows installer before claiming verified success.
- Critical remaining obstacle: we still have **no verified URL/DOM contract for real ИНВента, DataLens, Asgard**. Only a conservative native GET search implementation is active. Dynamic search detection helps discover why an adapter is needed but does not make JS searches work. Next implementation should be a scoped and tested site-specific read-only search adapter from verified markup/authorized session, then desktop-initiated jobs and progress/report UI, then separate explicit permission for any status write. Do not claim corporate login access, full autonomous order checking or site edits.


## 2026-11-12 — Conservative autonomous reactive search

Continued `feat/desktop-shell` (draft PR #2, not merged). The user repeatedly requests actual autonomous work, rather than manually browsing/copying results.

- `browser-extension/automation.js` adds `reactiveSearch(chromeApi,tabId,role,cargo,origin)`. After the first attempt at strict native GET search fails specifically as `dynamic_search_ui`, the agent tries a bounded search-as-you-type interaction. It only uses **one** visible, enabled, standalone `input[type=search]` or `input[role=searchbox]` outside forms, exactly labelled `main_partner_code_original` for DataLens or `cargo_place` for Asgard. It sets the value with the native input setter and sends one `input` event. No Enter, clicks, form submissions, API calls, DOM arbitrary script execution or status writes.
- For acceptance, the injected logic must find a unique table/grid with the exact expected column headers and observe a mutation **inside that results container**, then wait for a 400-ms quiet interval (max 6s) before reading. Existing origin, exact row identity, bounded pagination, source table validation and cross-site reconciliation protections still apply. A missing/ambiguous field, missing/ambiguous table or no update fails closed with `unsupported_dynamic_search` or `dynamic_search_no_result_update`, shown in Russian in the popup.
- `tests/browser_automation.test.cjs` adds synthetic DOM tests for unique reactive input, rejecting a form-owned control and rejecting a foreign origin; the previous dynamic-search diagnostic mock was adjusted to supply an actual labelled standalone input in commit `eac1c22e`. CI should be checked for current-head browser tests before claiming pass; previous CI head `3e984464` failed only because the old simulated input omitted the exact label/DOM APIs.
- `browser-extension/README.md` documents the new mode. **Crucial**: no verified live DOM/URLs for actual ИНВента/DataLens/Asgard; the current generic adapter will not run arbitrary JS search controls or inspect Asgard box history. Additional work requires confirmed site-specific selectors/flows and authorized real-browser testing. No company record updates implemented.


## 2026-11-12 — Reject stale dynamic-search results

- Continued draft PR #2 / `feat/desktop-shell`; do not merge without explicit approval.
- Found a false-positive risk in `browser-extension/automation.js`: `reactiveSearch()` previously treated any mutation inside a result table as evidence that its contents had updated. This can be a spinner/loading repaint, not a new query result.
- New code records the bounded rendered `innerText` of exactly one matching table before typing, waits for table mutation plus 400-ms quiet interval (6s bound), and requires the text to actually differ. If a mutation occurs but content is identical, `dynamic_search_unchanged_table` is returned and that source fails closed. No status proposals are produced from stale rows. If the content cannot safely be inspected or exceeds 16k characters, the adapter refuses.
- `tests/browser_automation.test.cjs` updates the successful reactive UI mock with changing table content and adds a regression test where a mutation occurs but visible rows remain unchanged. `popup.js` shows a Russian diagnostic; `browser-extension/README.md` documents tradeoffs.
- Python tests succeeded on commit `e57967c5` (run `43285247714`). Desktop tests for the updated test fixture on commit `7077deba` and subsequent heads were still in progress at last check. Recheck CI and do not claim full green yet. Latest source changes in this step: `e57967c5`, `7077deba`, `8e828220`, `4537ed94`.
- The corporate sites' actual markup has not been inspected. Generic search still does not prove complete page coverage and does not handle Asgard extended box history, custom JS search or status writes. Next work should prioritize real-site, permission-reviewed adapters and a usable in-app job/report flow, not superficial polishing.


## 2026-11-12 — Browser audit aggregate now visible in desktop UI

Continued draft PR #2 in `feat/desktop-shell` (do not merge without explicit approval). Previous autonomous browser audit ran entirely inside extension and Native Messaging with only local popup progress; the desktop had no result surface.

Implemented a narrow, privacy-preserving bridge for **completed summaries**:
- `agent/malenia/store.py` adds singleton SQLite `browser_audit_summary` with exact fields `checked_at,total,found,in_progress,manual_review`. `record_browser_audit_summary` accepts only integer totals from 0 to 100 with three nonnegative matching bounded counts adding up to total; `latest_browser_audit_summary` returns these counts only. No source rows, cargo identifiers, URLs or scan details are written.
- `agent/malenia/native_messaging.py` after successful `reconcile_site_tables` writes aggregate counts only and returns `aggregate_persisted:true`; existing `persisted:false` continues to describe source records, which remain ephemeral. On aggregate storage error, the native host reports a safe failure and does not claim success.
- `agent/malenia/server.py` exposes authenticated `GET /v1/browser/audit-summary`; read-only count response includes `source_records_persisted:false`. No unauthenticated endpoint and no write endpoint were added.
- `desktop/src-tauri/src/main.rs` retrieves the summary in `get_dashboard`; `desktop/src/App.tsx` renders a new `Последняя автоматическая сверка` card in the `Браузер` page: four counts and completion timestamp, explicitly marked as read-only preview. The page does not trigger a browser audit yet.
- `tests/test_native_messaging.py`, `tests/test_server.py`, and `tests/navigation_ui.test.cjs` cover sanitized storage, authenticated API, and desktop surface. One Python test initially failed because it checked the literal substring `rows` which occurs within `browser_tables`; commit `b610350d` corrected it to exact response shape assertion. Python CI on `b610350d` passed (run `43287030840`). Desktop/installer tests on later heads were still running at last observation.
- `browser-extension/README.md` documents the latest-completed-only semantics: historical/partial audits are not stored, and there is no per-cargo report yet.
- Important limitations: No verified direct interaction with actual corporate sites, no Asgard extended box history, no status writes, no desktop-to-extension launch. This step only makes already-completed **aggregate reports** available to desktop. Next: review CI, implement authorized desktop-triggered browser task transport with local user consent / confirmation, and a better evidence-completeness model.


## 2026-11-12 — Desktop-origin read-only browser audits

User requested further autonomy. The desktop Browser page now has a **real launch button** rather than relying on opening the extension manually. Continued on `feat/desktop-shell` (draft PR #2; do NOT merge without permission).

Implemented one-shot local dispatch with bounded expiry:
- `agent/malenia/store.py`: a singleton SQLite `browser_audit_job` table stores only random job ID, pending/running/completed/failed/expired status, creation/update times. One active job max. `request_browser_audit`, atomic `claim_browser_audit`, `finish_browser_audit` (one-shot; no retry), and expiration (pending 15m, running 30m since creation). No source URLs, cargo IDs or record contents are stored in the job.
- `agent/malenia/server.py`: authenticated loopback `POST /v1/browser/audit-request` with empty payload queues job (409 on active duplicate); `GET /v1/browser/audit-job` exposes job state only. No external or unauthenticated access.
- `agent/malenia/native_messaging.py`: registered extension can `claim_browser_audit` and `finish_browser_audit`; capability list extended. Only the previously registered Chrome extension can use this Native Messaging host.
- `browser-extension/manifest.json` v1.4.0: includes `alarms` permission, no cookies/webRequest. `background.js` installs a one-minute polling alarm. It checks its own previously configured three HTTPS targets and existing optional host permissions **before claiming** an audit; if the local host is available, it claims one job and runs the existing read-only multi-source audit, reports outcome, closes the native session, and prevents parallel runs. Browser must be running and extension installed. No corporate writes; no CAPTCHA/login bypass. Does not auto-retry a consumed claim on crash.
- `desktop/src-tauri/src/main.rs`: `request_browser_audit` Tauri command and dashboard job state; `desktop/src/App.tsx`: desktop Browser page launch button, status text, and latest aggregate-only result. It refuses duplicate launch from UI while pending/running.
- Tests: `tests/test_store.py` covers concurrency, expiration, claim and no replay; `tests/test_native_messaging.py` covers job protocol; `tests/test_server.py` covers authenticated request/status and rejection; `tests/navigation_ui.test.cjs` covers desktop command; `tests/browser_desktop_dispatch.test.cjs` checks extension polling contract, wired in `.github/workflows/desktop-checks.yml`. `browser-extension/README.md` documents initial setup and expiry behavior.
- Python CI has passed commit `d481d7ed` (run `43289916666`). Desktop checks on `8e9eef46` (run `43289784267`) already passed frontend, existing browser tests and navigation UI; long Rust stages still running. New browser dispatch tests on `d3aff07c` pending/ongoing when last checked. Do not claim entire pipeline green without fresh status.
- **Remaining limitations:** needs user to configure the three sites and grant browser origin permissions via popup once; desktop launch is polled about once/minute, not immediate; real ИНВента/DataLens/Asgard DOM and Asgard box extended history still unverified; reports are aggregate only, statuses are proposals, no corporate writes. Next work: integration test alarm/native dispatch with mock Chrome MV3 APIs, test actual authorized sites and adapters, improve live job progress, and investigate live Windows Browser Bridge installation.


## 2026-11-12 — Source-level live browser job progress in desktop

Continuing user-requested autonomous Malenia browser workflow. Changes are on `feat/desktop-shell`, draft PR #2; do not merge without explicit approval.

- Last confirmed baseline `567ee20f` had **all 3 GitHub workflows green**: Python, Desktop checks, Windows installer.
- `agent/malenia/store.py`: new singleton `browser_audit_progress` SQLite table, holding only `job_id, current_role, completed_sources, attention_sources, failed_role, updated_at`. Automatically reset when a new job is requested, left join with current audit job on query; previous database schema is extended through `CREATE TABLE IF NOT EXISTS`. `update_browser_audit_progress` only accepts the currently claimed running job, fixed source enums or null, bounded integer counters 0–3, nondecreasing completed/error counters, no raw identifiers. No source data is persisted.
- `agent/malenia/native_messaging.py`: new `update_browser_audit_progress` capability + strict message key set, delegates validation to store. Registered Chrome extension may post limited progress on already-claimed desktop job.
- `browser-extension/background.js`: desktop-triggered audit wraps the existing progress callback to send counters and safe role names to Native Messaging in addition to updating the popup's session storage. On local progress transport rejection, the audit fails closed.
- `desktop/src/App.tsx`: Browser page displays processed source count, needs-attention count, last current role, last failed role during/after the job. Corrected privacy wording: extension can interact with one narrowly approved search input, but never reads cookies/passwords/history.
- Added regression tests: `tests/test_store.py` tests wrong job ID, active-only updates, backwards counters, invalid roles/bools, reset; `tests/test_native_messaging.py` validates strict progress shape and capability; `tests/navigation_ui.test.cjs` and `tests/browser_desktop_dispatch.test.cjs` inspect safe display and dispatch. `browser-extension/README.md` explains.
- One intermediate Python CI run on `d24ad963` failed because the hello capability test had the old list. Fixed in `f6f2e90d`. Check CI on current head before claiming green. Current code changes: `9d7e3c4b`, `b070db12`, `1aba2b6e`, `72cf5f51`, `d24ad963`, `f6f2e90d`, `bf99beaa`, `2bf27718`, `0218a7c9`, `b8e8ff52`.
- Still unverified on live corporate sites (ИНВента, DataLens, Asgard); no Asgard extended box history, per-order persisted reports, corporate status writes or bypass of login; browser background polling requires browser running plus preapproved HTTPS target origins. A robust next task is a full simulated Chrome MV3 alarm/native host integration test and per-site adapter calibration from an authorized browser session.


## 2026-11-12 — General-purpose Sherlock skill architecture + learning from ratings

User clarified Malenia is a **general-purpose autonomous assistant**, not an inventory-only tool. Sherlock is locally served via Ollama/Qwen, and user wants extensible skills, durable database, intelligence and experience-driven improvements. This entry supersedes any inventory-specific scope assumptions. Current working branch `feat/desktop-shell`, draft PR #2, do NOT merge without explicit permission.

Implemented in this turn:
- `agent/malenia/skills.py`: local SQLite `assistant_skills` registry, four built-in **instruction-only** recipes: orders, research, planning and data analysis. Custom skills have title, description, instructions, search terms, `draft`/`approved` status, UUID request identity, bounded content and 100-entry cap. Only approved skills are eligible for retrieval; drafts require explicit user approval. Skill recipes are not executable scripts and never grant browser/file permissions.
- Retrieval uses the existing keyword/exact-code matching functions to select up to 2 relevant approved recipes, without importing all skills into the context. `assistant_skill_feedback` stores only UUID, skill ID, helpful Boolean and timestamp (no raw chat text) and supplies a **small bounded tie-break** to improve matching on later similar requests. No training or modification of Qwen model weights, no automatic unreviewed knowledge promotion. Skill records survive agent restarts.
- `agent/malenia/ai.py`: `OllamaClient.skills` optional registry; ordinary chat adds selected approved skill instructions to system context, explicitly marked as guidance, not source facts/permissions. Web and strict knowledge-only modes do not use skills as evidence. Response adds `skill_ids`; still returns `tools_enabled:false`, no tool execution, no fabricated completed actions.
- `agent/malenia/server.py`: authenticated GET `/v1/skills`, POST `/v1/skills/draft`, `/approve`, `/delete`, `/feedback`, narrow payload validation; `reviewed_skills` runtime capability. `desktop/src-tauri/src/main.rs`: `get_skills` and `skill_action` commands. `desktop/src/SkillsPage.tsx`: catalog, draft form, explicit approval/deletion, local-only explanation. `desktop/src/App.tsx`: first-class “Навыки” navigation. `desktop/src/AiPage.tsx`: shows applied skill IDs and “Полезен / Не помог” rating actions per response; ratings update retrieval preferences without storing the conversation.
- New `tests/test_skills.py` validates builtins, draft/approve, durable persistence, idempotent feedback, and Qwen context. `tests/test_server.py` tests authenticated skill API. `tests/navigation_ui.test.cjs` covers new page and feedback UI.
- CI: Python tests passed through code commit `afb8868c` (run `43295864689`). Later CI runs for new tests and UI updates were ongoing at last check; recheck fresh head, do not claim complete green until verified. Latest code `c0cda4c6` (UI feedback rating keyed per response).
- Next phases: (1) review CI and fix; (2) optional AI-assisted **draft skill proposals** based on explicit task review / correction, never autoapprove instructions from external sources; (3) auditable executor/capability bus for browser/data/calendar/files with user-granted scoped access, task outcomes as verified training signals; (4) measured quality evals and optional offline adapter/LoRA fine-tuning on curated consented samples, never silent training of confidential data. User wants intelligence and agency; generic chat+skills alone is not equivalent to autonomous execution.


## 2026-11-12 — Local Qwen proposes draft skills; adaptive thinking depth

Continued universal AI/skills direction in `feat/desktop-shell` (draft PR #2; do NOT merge without explicit approval).

New functionality on top of the reviewed skills registry:
- `agent/malenia/ai.py` adds `OllamaClient.suggest_skill`: after a deliberate UI action, calls the already configured **local** Qwen with bounded current request+assistant response and strict JSON schema for `title,description,instructions,terms`. It validates field lengths using `SkillRegistry._validate`, returns `saved:false,approved:false,tools_enabled:false`, and **does not write it to the DB**. Generated recipe text is only a suggestion, never an authorization or executable tool. Any model/JSON failure fails closed. Runs under existing generation mutex.
- Authenticated local `POST /v1/skills/suggest` and Tauri `suggest_skill` command added. `desktop/src/AiPage.tsx`: “Сделать навык из ответа” button for assistant messages, editable review of all fields, explicit “Сохранить на проверку” (writes a `draft`); actual activation still requires separate “Утвердить” in the **Навыки** page.
- Qwen reasoning improvement: `OllamaClient.chat` accepts optional `reasoning_mode` (fast/auto/deep); in **general chat only**, Qwen3 gets `think:true` for explicit deep mode, or auto when query is long or has analysis/planning-related terms; context increases to 8192 and generation budget to 768, timeout 180s. Strict knowledge-only and public-search grounded answers remain deterministic under source verification. Server-side defaults to `fast` for legacy callers. Desktop selects `auto` by default with user-facing fast/deep options; Tauri forwards mode. Deep reasoning changes inference effort, not Qwen's weights or permissions.
- New tests in `tests/test_skills.py` verify proposed drafts remain unsaved and malformed output fails; `tests/test_server.py` tests authenticated proposal endpoint; `tests/test_ai.py` tests adaptive thinking; `tests/navigation_ui.test.cjs` checks review and thinking UI. `docs/ROADMAP.md` stage 11 is the general-purpose agent roadmap, explicitly superseding inventory-only scope.
- At last observed check, Python tests passed through code commit `72ecd07d` (run `43297092831`), including prior skill registry tests. Desktop build and Node navigation tests for `45b129a8` were already green, long Rust step still running. Tests for latest reasoning UI and proposals were queued or in progress; recheck current Actions before claiming all green.
- Future priority: typed capability bus/agent execution loop across approved apps; verified outcomes and evals; optional consented LoRA training only on cleaned curated examples. Existing feedback changes retrieval rankings, not model weights. Do not imply “the AI trains itself” in a neural-weight sense or that general skills automatically operate a site.


## 2026-11-12 — Test readiness for 13 November (user testing Windows tomorrow)

User said they will test Malenia tomorrow and hope it works. Prioritize reliability, installer artifacts and clear expectation setting over another large feature. Continued draft PR #2 on `feat/desktop-shell` (do NOT merge without explicit approval).

- Previous full code head `59f982b6` passed both Python and Desktop checks. Windows installer passed at prior commit `de207499`, but it predates last docs-only commits.
- Added `packaging/smoke_test_packaged_skills.py`: tests the actual **frozen Windows malenia-agent.exe**, not only source. Starts it on a random loopback port with a disposable `LOCALAPPDATA` directory and random bearer token; checks built-in skill catalogue, draft, approval, catalog persistence and separate SQLite database; terminates the process without touching user's real data. Wired it to `.github/workflows/windows-installer.yml` immediately after the frozen agent smoke test.
- New Windows Installer run `43299558601` on `a19d71fa`: at last checked, **package agent**, **verify agent**, **smoke-test packaged Sherlock skills and SQLite** all PASSED; bundled host/NSIS build/upload still in progress. Python and browser registration workflows passed. Don't claim installer ready until this run finishes successfully.
- Created `docs/TESTING_2026-11-13.md` with safe, actionable Windows checklist: use latest successful Windows installer artifacts, pair extension from same workflow run, start agent, install local Qwen if necessary, test chat and reasoning, notes and skills review/approval, Sherlock-generated draft, explicit feedback and optional Browser Bridge. Calls out features not implemented and sensitive-data protection.
- Updated top-level `README.md` (commit `0da57e6d`) to remove stale blanket statement that local LLM/browser automation are unimplemented, clearly distinguish experimental features and outstanding capabilities, and link guide. Documentation-only commits don't retrigger the installer; use the verified newer installer run with same preceding code.
- Next step: confirm installer `43299558601` success, verify actual uploaded artifact, report exact workflow URL and avoid sending an old installer. If CI fails, inspect job logs and fix in the same branch. User will test tomorrow, so be explicit about limitations and what details to provide for a bug report.


## 2026-11-13 — INVenta auto-detection, analysis and editor approval groundwork

User provided the exact editor URL for the INVenta spreadsheet:
`https://docs.google.com/spreadsheets/d/1zPgIA_Au6J8_NEAPsTZo1TLkfFJYUTYKxtIwUWRHS30/edit?usp=sharing`
and explicitly clarified that Malenia should be able to **edit**, not merely read. No concrete cell edit has been approved, so do not write to the real spreadsheet in this milestone.

Implemented in `feat/desktop-shell`:
- Added `agent/malenia/inventa.py`: deterministic read-only analyzer with Russian/English header aliases; detects header row within first 12 rows; extracts column mapping; reports row counts, exact status counts, top groupings, missing required fields, duplicate order IDs with row numbers, invalid date/cost rows, missing ticket rows, and anomaly-like status rows. Does not mutate or guess values.
- `GoogleSheetsConnector.read_active_sheet(url,gid=None)` validates exact `https://docs.google.com/spreadsheets/d/<id>/edit` URL, resolves a specific `gid` through Sheets metadata when present, otherwise checks up to 20 non-archive-first tabs for a recognized INVenta header signature, then reads the used grid `A:Z`. Increased bounded read limits to 5,000 rows / 100,000 cells to handle full live worksheets. For the provided screenshot, header labels include `Id заказа`, `main_partner_code_original`, `Стоимость`, `Наименование`, `Комментарий`, `Тикет`, `Статус`, `Группировка заказов`.
- Added authenticated `POST /v1/integrations/google-sheets/analyze-active` and Tauri `analyze_active_inventa`; `desktop/src/App.tsx` Sources panel now has “Найти ИНВенту и проанализировать”, uses a shared Google Sheets browser tab URL when available, otherwise the user's supplied spreadsheet URL; no manual spreadsheet ID/range required for this path. It renders summary status counts and data quality counts.
- Changed OAuth requested scope from `spreadsheets.readonly` to `spreadsheets` so explicit edits are technically possible. **Important security/privacy disclosure:** this Google scope allows reading and writing all spreadsheets available to the Google account, not only INVenta. App workflow targets the selected INVenta spreadsheet, but the OAuth grant is broader. Consider migrating to `drive.file` plus Google Picker/user-selected file authorization in a future hardening step. Do not describe scope as least-privilege.
- Added bounded `GoogleSheetsConnector.write_values` using PUT with `valueInputOption=RAW`; rejects formulas, oversized values, and large matrices. Added API `edit-preview` and one-time `edit-approve` routes: preview captures before/after exact range, approval re-reads and rejects if source changed, consumes approval token once, writes, then re-reads and verifies. This is backend groundwork only; there is not yet a complete UI for AI-generated cell diffs/review/approval. Do not call the edit UX finished.
- Added tests `tests/test_inventa.py`, extensions to `tests/test_google_sheets.py` for write/read-active URL, and `tests/test_server.py` for auto-analysis and one-time approval. Existing OAuth scope tests updated to editor scope.
- Some early commits in this sequence temporarily broke Python syntax due to misplaced insertion; those were corrected. Latest observed head `d754a467` Actions Python run `43389208217` and Desktop run `43389208450` were still running at last check. Windows installer run for earlier head `bd6d540e` was cancelled after a newer push; latest head needs its own successful installer validation. Do not claim CI green until fresh head succeeds.
- Important remaining work: add UI to review and approve proposed changes (exact sheet/tab/row/column/old/new/reason), implement audit history and expiry/size bounds on pending approval tokens, protect formula/validation cells by reading userEnteredValue before writes, auto-detect active tab `gid` through Browser Bridge (current shared-tab sanitization may strip query parameters; fallback tab scan currently chooses recognized header among up to 20 tabs and may not equal the browser's active tab), improve auto-range to avoid irrelevant columns, verify analysis with real sheet after user OAuth setup, update stale README/docs that still call this read-only, and run full Windows installer on current final commit.
- No Google OAuth has been completed in the user's local Malenia by this code. Existing app still requires their Google OAuth Desktop Client ID setup in Settings/Источники. Do not imply the ChatGPT Google Drive connector grants Malenia access. Do not ask user to paste secrets in chat.


## 2026-11-13 — Corrected Asgard decision rules (user clarification)

The user reiterated that Malenia's job is to investigate orders across INVenta → DataLens → Asgard, not to "fix errors" in the source spreadsheet. Never write back to INVenta/DataLens/Asgard as part of the investigation. Produce an evidence-backed classification/report only.

Corrected `agent/malenia/order_check.py`:
- Asgard primary status `Выдан` now maps to proposed result `Выдан` (previous code incorrectly mapped it to `В работе`).
- Explicit pair `statuses == ["В работе", "В работе"]` maps to `В работе`; incomplete/other pairs remain manual review.
- Existing rule for `В пути` plus extended history containing `Выдан` remains a `В работе` outcome with comment `2 ШК Выдан`.
- Added regression tests in `tests/test_order_check.py` for issued, both statuses in progress, and an unconfirmed pair.
- Updated `docs/ORDER_CHECKING.md` with the corrected user-confirmed rules.
- Commits: `cf88d1c61c4f9e0cb514dfc79a7d5909dd44c53e` (rule fix), `44a86298421fb0a13c385d61499b1ee055222de7` (tests), `326626a71474cf38417a52f35676befe3d9e0bcf` (docs).

Current limitations found while inspecting actual code:
- `browser-extension/automation.js` is still a generic read-only site traversal. It opens three configured URLs in inactive tabs, expects exact HTML table headers (`cargo_place/inventory_date`, `main_partner_code_original/sc_id/result/scanned_at`, `cargo_place/status`), searches exact GET/standalone search input names, and cannot reliably parse the user's actual Google Sheets UI or arbitrary DataLens/Asgard SPAs. It does not yet implement a full live order-by-order investigation for the user's real pages.
- `docs/ORDER_CHECKING.md` confirms DataLens/Asgard adapters do not yet exist. Existing `order_batch.py` is a manually supplied snapshot dry-run, not connected to live resources.
- `browser_channel.py` explicitly says its signed lifecycle channel is a protocol prototype and no real transport is wired.
- The browser bridge's README explicitly says three-site traversal does not yet correlate live order IDs or update statuses. Do not overstate runtime readiness.
- Latest Actions triggered by head `44a86298`: Python `43394803417`, Desktop `43394803312`, Windows installer `43394803408` were queued/pending at last check; earlier head runs were in progress. Verify these before reporting.
- Next high-value work: bridge actual INVenta source using Google Sheets API (the local Malenia OAuth connection must be set up separately; ChatGPT connector auth is not shared); add explicit row/column mapping for the known sheet header; determine the real DataLens search schema and Asgard reverse-flow/box-history UI from authorized live browser pages, not guessed selectors; build adapter contract + fixtures; integrate per-order orchestration and evidence records. User wants no manual spreadsheet ID/range and no Excel downloads. For browser sites, use the user's already open/authorized Yandex tabs or explicit shared tabs, never scrape cookies or bypass authentication.


## 2026-11-13 — desktop compile cleanup and investigation-only permissions

- Fixed obsolete manual Google Sheets state and `readSheet` handler that TypeScript strict noUnusedLocals rejected after the UI moved to automatic INVenta resolution. Commit: `3329eca8`.
- The subsequent CI for `30c51b4e` showed desktop failure was not JSX anymore but three unused declarations; Windows installer failed only because its frontend build step invokes the same failing npm build.
- Removed unused state and obsolete manual reader. Commit: `3329eca8`.
- Revisited product direction: Malenia investigates orders; it does not repair the INVenta sheet. Restored least-privilege `spreadsheets.readonly` OAuth scope and corrected Sources UI copy to explicitly say read-only. Commits: `d01fbed5`, `efb82362`, `4edb759d`.
- Current Actions for `4edb759d`: Desktop `43395746349`, Python `43395746356`, Windows installer `43395746357` queued/pending at time of handoff. Do not claim green until all three complete on same SHA.
- Important reality check: Browser extension currently polls a queued audit every minute and opens three configured URLs in background tabs. It performs generic table extraction and exact-form / narrowly labelled reactive search only. The current site reconciliation expects exact synthetic column names and currently cannot prove that those are the user's real DataLens/Asgard schemas. Asgard box-history adapter is not implemented; it deliberately withholds the "2 ШК Выдан" evidence. Do not label the full live workflow as working.
- Next implementation task: obtain safe page capability snapshots from explicitly shared active Yandex tabs (origin, title, visible table headers, search controls, ARIA grid completeness) without persisting raw page text or cookies; expose a diagnostic panel that clearly reports each source as accessible / unsupported schema / login required. Then implement reviewed mappings for actual page structure before attempting per-order search. Preserve user sessions; no cookie extraction, credential scraping, or bypass.


## 2026-11-13 — removed stale manual Sheets UI references

- CI for `624fa735` confirmed Python tests passed but Desktop still failed: stale `spreadsheetId`/`range` references remained in a derived status label after removing the manual reader. The previous `4edb759d` CI failure is documented; do not report the build as fixed until new CI passes.
- Removed the stale verification key/status logic and orphaned sheet preview state. Sources UI now reflects only the actual OAuth authorization state and does not imply that a manually selected range was verified.
- Commit: `f7683b1a`.
- User expectation remains: one-click, automatic investigation; no manual order IDs, spreadsheet ranges, Excel downloads, or edits to source tables.
