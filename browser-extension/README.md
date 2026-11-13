# Malenia Browser Bridge extension preview

This is a developer-preview Manifest V3 extension for Yandex Browser builds that support Chromium extensions and Native Messaging.

## Permissions

- `activeTab`: temporary access to the selected page after a deliberate click.
- `nativeMessaging`: communicate with the registered local Malenia host.
- `scripting`: read bounded rendered text of the selected, permitted page.
- `tabs`: create and close three isolated background tabs for the explicitly started read-only audit.
- `storage`: remember user-supplied resource URL paths and non-sensitive job progress only.
- Optional host permissions: requested at runtime for **only the three HTTPS origins entered by the user**. The manifest advertises an optional HTTPS pattern but does not automatically grant that entire pattern.

There is no `history` or `cookies` permission, no persistent content script, and no automatic form submission.

## Install for local testing

1. Open `browser://extensions` in Yandex Browser.
2. Enable Developer mode.
3. Choose **Load unpacked** and select this `browser-extension` folder.
4. Copy the extension ID shown by the browser.
5. Open PowerShell (ordinary user permissions are enough). The registration script auto-detects the installed host using the running Malenia process, the per-user uninstall registry, and the bundled Tauri resource layout. It also accepts an explicit executable path if auto-detection is ambiguous.
6. From a local clone of this repository, run:

   ```powershell
   .\packaging\register_browser_bridge.ps1 -ExtensionId YOUR_32_CHARACTER_EXTENSION_ID
   ```

   Or download the verified script pinned to the full Malenia namespace commit (paste the entire block):

   ```powershell
   & {
       $ErrorActionPreference = "Stop"
       $sha = "87b63a70708115309acdb4fa9ab12d6249f38dcb"
       $expected = "f80ece220c84267ba9f0bb5ebdbaa47e8e43046cb674a552983187a2275a7392"
       $fresh = Join-Path $env:TEMP ("malenia-register-" + [guid]::NewGuid() + ".ps1")
       $url = "https://raw.githubusercontent.com/DoctorStrangeSH/WorkPilot/$sha/packaging/register_browser_bridge.ps1"
       Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $fresh -ErrorAction Stop
       $bytes = [IO.File]::ReadAllBytes($fresh)
       if ($bytes.Length -eq 0 -or @($bytes | Where-Object { $_ -gt 0x7F }).Count -gt 0) {
           throw "Downloaded script is empty or non-ASCII. Nothing executed."
       }
       $hasher = [Security.Cryptography.SHA256]::Create()
       try { $actual = [BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant() }
       finally { $hasher.Dispose() }
       if ($actual -ne $expected) {
           throw "Script SHA256 mismatch. Nothing executed."
       }
       $tokens = $null
       $parseErrors = $null
       [System.Management.Automation.Language.Parser]::ParseFile($fresh, [ref]$tokens, [ref]$parseErrors) | Out-Null
       if ($parseErrors.Count -gt 0) { throw "Script syntax check failed. Nothing executed." }
       powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fresh -ExtensionId YOUR_32_CHARACTER_EXTENSION_ID
       if ($LASTEXITCODE -ne 0) { throw "Registration failed (exit $LASTEXITCODE)." }
   }
   ```

   The block creates a unique file, stops on download/ASCII/hash/syntax failure, and only then executes that file. Never rerun the previous `$script` temp file. The commit URL avoids the mutable branch cache; the SHA256 above covers the exact 7487 downloaded bytes.

   If the host is installed in a non-standard location, add `-NativeHostPath "C:\full\path\to\malenia-native-host.exe"`.
7. Close all Yandex Browser windows (including background processes) and restart the browser.
8. Navigate to a normal HTTP(S) page, open the Malenia extension popup and click **Поделиться вкладкой**. Then start/refresh Malenia and check the Browser page.

The registration script is intentionally ASCII-only so it also parses correctly in Windows PowerShell 5.1 (`powershell.exe`), which otherwise may misread UTF-8 files without a BOM. The script writes only to the current user's `%LOCALAPPDATA%\Malenia` folder and `HKCU` registry keys; it does not require administrator rights. It verifies the host EXE and adjacent PyInstaller `_internal` folder before registering.

If the popup reports that the host is not found or access is forbidden, open `browser://policy` and inspect `NativeMessagingUserLevelHosts`, `NativeMessagingAllowlist` and `NativeMessagingBlocklist`. Yandex documents that user-level hosts are permitted when the policy is Not Configured (the default) or Enabled; Disabled blocks user-level hosts. Do not change a policy managed by an organization—ask its administrator instead.

To unregister the native host:

```powershell
.\packaging\unregister_browser_bridge.ps1
```

## Official compatibility references

- [Yandex Browser extensions](https://yandex.ru/support/browser/ru/personalization/extension)
- [Yandex NativeMessagingUserLevelHosts policy](https://browser.yandex.ru/support/browser-corporate/ru/policy/native-messaging-user-level-hosts)
- [Chromium Native Messaging protocol](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)

## Data policy

**Manual sharing:** sends the active tab title and sanitized URL after the user presses «Поделиться вкладкой».

**Manual page inspection:** separately sends up to 16,000 characters of rendered `document.body.innerText` to the local host, which validates the snapshot and does not store the text.

**Three-site automatic read-only traversal:** after the user enters the three exact HTTPS pages and approves the corresponding site permissions, pressing «Прочитать все 3 сайта автоматически» starts a background task. The task opens each configured URL in a new inactive tab, checks that the origin did not change during navigation, reads bounded rendered text and sends it to the native host, then closes its own tab. Results contain only reading status and character counts; page text is not saved in progress metadata. The supplied sanitized resource URL paths are saved locally for future runs. The task does not click page controls, type search terms, read form values, bypass sign-in, or change records. If login redirects to another origin, the relevant step needs attention. **This milestone does not yet correlate live order IDs across sites or update statuses.**

No cookie, password, browser history or browser profile file access is requested. Rendered page text may nonetheless contain sensitive corporate data; permit only authorized pages and abide by the site's usage policy.

Target browser reported by the initial tester: Yandex Browser 26.10.3.771 (64-bit). Yandex's public documentation confirms Chrome/Opera extension catalogue compatibility and documents the `NativeMessagingUserLevelHosts` policy (default: Not Configured, which permits user-level hosts). It does not specify a stable-consumer-build registry lookup contract. The setup script registers both a Yandex-specific per-user key and the Chromium per-user fallback; actual discovery and tab sharing still need to be confirmed on the target machine. See the official Yandex policy and extension docs linked below.

## Full Malenia namespace (version 1.1.0)

This release changes the native host ID to `com.malenia.browser`, the executable to `malenia-native-host.exe`, and the data/config directory to `%LOCALAPPDATA%/Malenia`. It does not import previous product data or delete a previous installation. Install Malenia 0.3.0 or newer before registering this host. Old setup downloads cannot register the new host.

Replace the files in the existing unpacked extension directory and reload that same extension to preserve its ID. Run the verified registration block with that ID after installing the new desktop build. No browser profile access is required. Version 1.3.0 adds new, explicitly prompted scoped permissions for automated browsing.

## Connection diagnostics

The popup checks the registered native host with a `hello` message. **Retry connection** sends another `hello` only; it never reads or shares a tab. Missing registration, denied access, disconnected host and invalid responses have separate guidance. Native Messaging replies time out after five seconds; late replies cannot replace a newer connection state.

If sharing times out or disconnects, the tab may already have been saved. Check Malenia before sharing again. The extension never automatically retries a share. Query/fragment data is stripped, URLs containing embedded credentials are rejected, and raw browser/native errors are not displayed.

Run `node --test tests/browser_bridge.test.cjs` from the repository root to verify popup behavior against a simulated Chrome API.

## Automatic three-site reading (1.3.0)

After installing the updated native host and reloading the unpacked extension, enter the actual HTTPS pages for ИНВента, DataLens, and Asgard. The browser will show a permission request listing those origins. Approve only if you are authorized to automate those pages. Press the automatic audit button once. You may close the popup; reopening it shows the last progress summary. The service worker may be interrupted by browser shutdown or platform lifecycle limits; an interrupted task must be started again manually. This read-only prototype is not yet an autonomous order reconciliation and does not replace the site-specific adapters.

To validate locally, run `node --test tests/browser_bridge.test.cjs tests/browser_automation.test.cjs`.


## Structured table reconciliation (new, experimental)

The background audit now attempts to extract a **single visible HTML table** for each resource with these exact header names:

- ИНВента: `cargo_place`, `inventory_date` (ISO `YYYY-MM-DD`).
- DataLens: `main_partner_code_original`, `sc_id`, `result`, `scanned_at` (ISO date + time).
- Asgard: `cargo_place`, `status` (optional `box_id`).

Up to 100 rendered table rows and 20 columns are processed per site. Tables with unknown headings, excessive rows, or missing columns are **not** silently mapped. Raw table cells are sent to the registered local native host over Native Messaging and joined using the deterministic rule engine in memory; the host returns only aggregate counts. No order IDs, status changes or source rows are written to local storage, logs, or corporate sites. `В пути` remains manual review because a generic table cannot attest that the extended history of the **correct** box was opened.

**Important limitations:** the exact headings above are an internal adapter contract, not claims about the actual user's private sites. Until a site-specific adapter is verified against its live UI, a three-site read may succeed but table reconciliation will report that mappings are unavailable. It does not search by cargo place, click filters, page through lists, or inspect virtualized rows. The summary only covers visible matched tables, not all orders on the remote systems. It cannot be considered a production audit or evidence of complete inventory reconciliation. Untrusted page text is data, never instructions to the agent.

Follow-up work: permission-reviewed site adapters for in-page search/pagination and human-verified column mapping; explicit report visibility in the desktop UI; validation of permissions/role access before any change action. Do not bypass MFA, CAPTCHA, company policy or site security controls.


## Automatic pagination (experimental)

Read-only audit now supports ordinary HTML pagination through an explicit `<a rel="next" href="...">` link. For each of the three configured resources the extension opens one inactive tab and automatically follows at most **five pages** on the exact same HTTPS origin, appending matching table rows before attempting reconciliation. The next URL is taken from the rendered page, not generated or guessed; credentials, fragments, custom ports, cross-origin redirects and circular page links are rejected. Each page remains read-only and each result is sent to the trusted local host without storing source text. The extension closes only its own tab even after an error.

If a table changes columns, contains more than 100 total rows, has malformed cells, exposes an unrecognized pagination scheme (such as JavaScript buttons), or continues beyond five pages, Malenia must not claim a complete audit. The supported link navigation is still only a **prototype for conventional HTML tables**. DataLens, ИНВента and Asgard may use SPA grids, custom pagination or internal search; those require dedicated reviewed adapters before real unattended order checking works. Reading the visible last page does not prove there are no additional records in a virtualized source. No status writes are performed.


## Accessible SPA grid reading (experimental)

The automatic read-only walker additionally recognizes visible WAI-ARIA tables/grids using `role="grid"` or `role="table"`, `role="row"`, `role="columnheader"` and `role="gridcell"`/`role="cell"`. The same strict, literal per-resource column contract applies as for HTML tables. It never reads form inputs or site credentials, and does not click controls.

To prevent false conclusions from virtual scrolling, an ARIA grid is eligible only if its **explicit `aria-rowcount` exactly matches the number of currently rendered rows (including the header)**. Missing or mismatched counts, too many rows, malformed data or unknown headings make the corresponding reading require attention rather than proposing an order status. Some genuine small grids do not expose an explicit count and are therefore intentionally unsupported until a site-specific adapter verifies completeness.

This is a generic capability, **not evidence** that actual ИНВента, DataLens or Asgard use these roles or expose compatible headings. Their concrete search/navigation logic remains unimplemented and requires inspection in the user's authorized browser session.


## Opt-in exact cargo search (experimental)

A new opt-in checkbox `Искать каждое грузоместо автоматически` enables a **read-only navigation-only** search mode. After collecting the current inventory table, the extension takes at most **20 unique cargo codes** and independently visits DataLens and Asgard once per code. It accepts only conservative identifiers containing ASCII letters/digits, dot, underscore or hyphen. Search never uses a guessed selector or executes a page-provided script.

The limited generic adapter recognizes **exactly one** native HTML form on the corresponding site with:
- `method="get"`, one named text/search input and no hidden/password inputs;
- input `name="main_partner_code_original"` on DataLens, or `name="cargo_place"` on Asgard;
- a plain action URL with the same permitted HTTPS origin and no existing query or fragment.

It constructs one single-parameter URL using the form's own action, navigates only its own inactive tab and validates the resulting table rows against the **exact requested cargo code** before accepting them. Any missing/ambiguous form, unexpected row, disallowed redirect, unsupported cargo identifier, excess results, pagination error, or failed page validation requires attention. No data-changing form is submitted, and no record writes are implemented. Search parameters (cargo identifiers) can be visible in the browser's navigation URL and site server logs; they are not stored in extension progress or passed back as a URL to the native host. This mode requires the user to opt in once in the extension; the preference is remembered locally.

**This is not a verified adapter for the actual private websites.** If they use JavaScript search buttons, POST search, arbitrary field labels or virtualized grids, this mode will refuse the action. Its purpose is to establish a safe, testable end-to-end per-cargo search path where the website exposes the stated native GET contract. Support for the real sites needs verified mappings and authorization; do not assert that live order processing works until exercised on those sites.


## Safe diagnostics for site-specific adapters

Automatic audit progress now includes one of a fixed set of **non-sensitive reason codes** when a source cannot be processed. The extension never persists raw browser exception text, a failed URL, cargo code, screenshot, page text or form values in its progress report. The popup maps codes to actionable Russian explanations.

An unsupported native HTML form is reported as `unsupported_search_form`; a page with a non-form search widget (such as `role="searchbox"`) is reported as `dynamic_search_ui`. A missing search surface is `unmapped_search_form`. Other known cases include cross-origin login redirects, virtualized/incomplete grids, a returned cargo ID that does not match the exact query, pagination limit/cycle, and host rejection. Unknown browser exceptions become the generic `site_or_browser_error` to avoid leaking private URL parameters.

These codes are diagnostic evidence for building a reviewed read-only adapter, **not permission** to click arbitrary controls, write to corporate sites, bypass login, or guess site selectors. The dynamic search widget is detected but is **not yet operated**.


## Reactive search-as-you-type (experimental)

When an explicitly started per-cargo audit cannot use the strictly validated native GET form, Malenia now attempts **one conservative reactive search** on the allowed HTTPS page. This does not click buttons, press Enter, submit a form, or write a site record. It only types the cargo-place identifier into a **unique, visible, enabled, standalone search input outside all HTML forms**, with exact `aria-label` or `name` of `main_partner_code_original` (DataLens) or `cargo_place` (Asgard). It uses the native `HTMLInputElement.value` setter and a bubbled `input` event to support common controlled UI fields.

It must also identify exactly one result table/grid with the documented exact column names and see **a mutation inside that result table**, not an unrelated notification or spinner, after the field update. The walker waits for a short quiet period before reading results, still enforces the same origin, per-cargo row identity, pagination/completeness limits, and fail-closed reconciliation. A missing/ambiguous field or table, or no observed table update, becomes a safe diagnostic code. The injected function does not return the cargo code or form values to extension progress.

**This is generic behavior, not verified live operation in ИНВента, DataLens or Asgard.** Many SPAs need a submit button, custom filter activation, or server-side paging; these are intentionally unsupported rather than guessed. In particular, the Asgard extended history of a linked box remains unverified and its status remains manual review if needed. A search can initiate ordinary server-side reads as the site's own UI does; respect organizational policies and permitted access. No status changes are implemented.


### Reactive search: stale-table protection

A DOM mutation alone no longer proves the search was applied: a site may only re-render a spinner or unrelated cells. The reactive adapter now compares the bounded visible text of the exact matching result table before and after updating its search field. It requires both a mutation within that table and changed rendered table content after the debounce period. A mutation with unchanged table content reports `dynamic_search_unchanged_table`; a missing update reports `dynamic_search_no_result_update`. Both fail closed and are shown as Russian diagnostic labels.

This intentionally may reject valid searches whose result set is exactly identical before and after filtering; it is safer than treating an unchanged or stale result as proof. A complete real-site adapter should use the website's own documented filter/query completion signals and explicit empty-results state instead of guessing.


## Aggregate results shown in the Malenia desktop app

After a **successful read-only browser table reconciliation**, the native host now saves **only** the aggregate counters (`total`, `found`, `in_progress`, `manual_review`) and a completion timestamp in the local SQLite database. The source table snapshots, cargo identifiers, page URLs and scan details are still not persisted by the audit. The native response retains `persisted:false` for source records and explicitly reports `aggregate_persisted:true`. A failed/partial reconciliation does not overwrite the previous completed summary.

The authenticated loopback endpoint `GET /v1/browser/audit-summary` exposes only this aggregate, and the Tauri desktop `Браузер` page renders the latest counts and completion time. **This is the latest completed preview, not a live status or proof that the real three corporate sites have been integrated.** The extension remains the user-triggered initiator of the audit: the desktop UI now *displays* the result but does **not yet remotely trigger** the extension. The summary is a single most-recent record (no sensitive history), not an order-by-order report; no updates to any corporate system occur.


## Start an audit from the Malenia desktop app (experimental)

The desktop **Браузер** page now includes **Запустить проверку**. Pressing it invokes a Tauri command that sends an authenticated request to the local agent, which creates **one** SQLite `browser_audit_job` with a random ID and the state `pending`. This request carries **no site URL, cargo identifier, browser command or source text**. A second request while `pending` or `running` is rejected with HTTP 409.

The Browser Bridge extension creates a local `chrome.alarms` check approximately once per minute. When running in the permitted browser session, it loads **its own previously saved** three HTTPS targets, checks all corresponding host permissions, opens a registered Native Messaging channel, and atomically claims exactly one pending job. Only then does it execute the existing read-only site walker. It reports the completion state over Native Messaging; the desktop polls authenticated `GET /v1/browser/audit-job` and displays `pending`, `running`, `completed`, `failed` or `expired`. The last completed aggregate is still shown separately. No source details are added to SQLite.

Pending jobs expire after 15 minutes, and running jobs after 30 minutes from creation. A claimed job is not automatically retried if the extension exits or crashes: the user can request a fresh audit after it expires. The extension must be installed, registered and active, the user's browser must be running, site sessions must already be authorized, the three targets must be configured from the popup once, and optional host permissions must already be granted. This does not circumvent login, browser policies, or CAPTCHA.

The **desktop launches a read-only audit**, not an authorized corporate write. It does not edit orders or automate the Asgard extended box-history path. Live compatibility with the actual ИНВента, DataLens and Asgard websites is still unverified.


## Live source-level audit progress in desktop

While a desktop-initiated audit is running, the extension now reports **only** fixed source roles (`inventory`, `datalens`, `asgard`), number of completed sources (0–3), number requiring attention (0–3), and the last source with a failed read. Progress is sent through the registered Native Messaging host, accepted only for the **matching active claimed job**, and displayed in Malenia's Browser page. New jobs reset counters, older/stale jobs cannot update newer work, and counters may never move backwards. No raw page text, URL, cargo place, source rows, or exception messages are transferred for this progress report.

The popup still shows its own more detailed but nonidentifying diagnostic reason codes. The desktop shows the most recent active source and counts, not live per-record statuses. The existing summary of the latest successfully reconciled run remains separate; a failed run does not replace that summary. This does not enable corporate writes or prove the private sites have been tested.


## Open-tab discovery (experimental, user-confirmed selection only)

The extension popup now contains a separate **Найти уже открытые рабочие вкладки**
flow. The user enters the HTTPS page URLs they recognize as ИНВента, DataLens
and Asgard. Malenia stores only each URL's origin and path prefix, discarding
query strings and fragments, then queries the current open tabs and the host
permissions already granted to the extension. It does not request new access
silently. A missing permission is reported with instructions to grant access
through the browser's extension settings.

Candidates are matched only against those explicit mappings and exact-origin
permission patterns. A duplicate match is marked ambiguous and every candidate
must be selected manually. All three roles must be selected before confirmation.
Immediately before confirmation, Malenia fetches each selected tab again and
revalidates its current URL, origin, path and host permission. A closed or
navigated tab, or revoked permission, invalidates the selection.

Confirmed tab IDs and sanitized locations are held in `chrome.storage.session`
only; the mapping origin/path prefixes are stored in local extension storage.
Session references disappear when the browser session ends. The desktop-triggered
audit now requires all three confirmed references, rechecks their current tab ID,
HTTPS origin, exact path and granted host permission before the run, and repeats
the tab/path/permission checks immediately around each DOM read. It reads only
the structured visible table cells in these selected tabs; it does not extract
or forward full page text, navigate, paginate, submit forms, or close the user's
tabs. If a selected table exposes a next-page link, the selected-tab audit stops
with an attention result rather than navigating the user's tab. Search-driven
GET/reactive queries remain available only in the legacy isolated-background-tab
runner and are deliberately disabled for selected tabs.

The audit engine sends the bounded table snapshots to the existing read-only
reconciliation endpoint. No order edits, status changes or form submissions are
implemented. If a tab is closed, navigated, loses permission, has an unsupported
table schema or requires pagination, the source fails closed. Session-only
selection expires after 30 minutes and is discarded on browser-session end.

This integration is code- and test-verified, but compatibility with the user's
actual private ИНВента, DataLens and Asgard pages is still unverified. The user
must map the correct HTTPS origins/paths, grant host access through browser
settings and keep the three source tabs open and logged in. No production-ready
claim is made until tested against those authorized live sites.

Run `node --test tests/tab_discovery.test.cjs tests/browser_open_tab_discovery.test.cjs tests/browser_automation.test.cjs`
to validate matching, duplicate selection, revocation, stale tabs, in-place
read-only extraction and fail-closed navigation handling.
