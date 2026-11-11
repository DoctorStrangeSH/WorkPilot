# WorkPilot Browser Bridge extension preview

This is a developer-preview Manifest V3 extension for Yandex Browser builds that support Chromium extensions and Native Messaging.

## Permissions

- `activeTab`: temporary access to the tab after the user opens the extension and clicks Share.
- `nativeMessaging`: connect to the explicitly registered WorkPilot native host.

There are no `tabs`, `history`, `cookies`, `scripting`, or broad host permissions. No content script is installed.

## Install for local testing

1. Open `browser://extensions` in Yandex Browser.
2. Enable Developer mode.
3. Choose **Load unpacked** and select this `browser-extension` folder.
4. Copy the extension ID shown by the browser.
5. Open PowerShell (ordinary user permissions are enough). The registration script auto-detects the installed host using the running WorkPilot process, the per-user uninstall registry, and the bundled Tauri resource layout. It also accepts an explicit executable path if auto-detection is ambiguous.
6. From a local clone of this repository, run:

   ```powershell
   .\packaging\register_browser_bridge.ps1 -ExtensionId YOUR_32_CHARACTER_EXTENSION_ID
   ```

   Or download the verified script pinned to the ASCII fix commit (paste the entire block):

   ```powershell
   & {
       $ErrorActionPreference = "Stop"
       $sha = "c7c5f48a4a206048a9aef65efeacce24face79c9"
       $expected = "de7350d5df7d50b7192a030fa79da443b1bf82b269529a4a6525d602eb87f470"
       $fresh = Join-Path $env:TEMP ("workpilot-register-" + [guid]::NewGuid() + ".ps1")
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

   The block creates a unique file, stops on download/ASCII/hash/syntax failure, and only then executes that file. Never rerun the previous `$script` temp file. The commit URL avoids the mutable branch cache; the SHA256 above covers the exact 7433 downloaded bytes.

   If the host is installed in a non-standard location, add `-NativeHostPath "C:\full\path\to\workpilot-native-host.exe"`.
7. Close all Yandex Browser windows (including background processes) and restart the browser.
8. Navigate to a normal HTTP(S) page, open the WorkPilot extension popup and click **Поделиться вкладкой**. Then start/refresh WorkPilot and check the Browser page.

The registration script is intentionally ASCII-only so it also parses correctly in Windows PowerShell 5.1 (`powershell.exe`), which otherwise may misread UTF-8 files without a BOM. The script writes only to the current user's `%LOCALAPPDATA%\WorkPilot` folder and `HKCU` registry keys; it does not require administrator rights. It verifies the host EXE and adjacent PyInstaller `_internal` folder before registering.

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

The extension sends only the active tab's title and URL path after an explicit click. Query parameters and fragments are removed both in the extension and in the native host. The host rejects non-HTTP(S) URLs and URLs containing credentials. The app stores at most the latest 100 shared tab records locally.

This preview does not read cookies, passwords, browser history, page DOM, form fields, local storage, or browser profile files. It does not execute scripts, click page controls, or navigate tabs.

Target browser reported by the initial tester: Yandex Browser 26.10.3.771 (64-bit). Yandex's public documentation confirms Chrome/Opera extension catalogue compatibility and documents the `NativeMessagingUserLevelHosts` policy (default: Not Configured, which permits user-level hosts). It does not specify a stable-consumer-build registry lookup contract. The setup script registers both a Yandex-specific per-user key and the Chromium per-user fallback; actual discovery and tab sharing still need to be confirmed on the target machine. See the official Yandex policy and extension docs linked below.
