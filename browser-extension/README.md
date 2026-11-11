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
5. Locate `workpilot-native-host.exe` inside the installed WorkPilot resources directory.
6. In PowerShell, run the registration script from the repository:

   ```powershell
   .\packaging\register_browser_bridge.ps1 -ExtensionId YOUR_32_CHARACTER_EXTENSION_ID -NativeHostPath "C:\path\to\workpilot-native-host.exe"
   ```

7. Restart Yandex Browser and open the extension popup.
8. Navigate to a normal HTTP(S) page and click **Поделиться вкладкой**.

To unregister the native host:

```powershell
.\packaging\unregister_browser_bridge.ps1
```

## Data policy

The extension sends only the active tab's title and URL path after an explicit click. Query parameters and fragments are removed both in the extension and in the native host. The host rejects non-HTTP(S) URLs and URLs containing credentials. The app stores at most the latest 100 shared tab records locally.

This preview does not read cookies, passwords, browser history, page DOM, form fields, local storage, or browser profile files. It does not execute scripts, click page controls, or navigate tabs.

Native Messaging support and registry discovery must still be verified against the user's exact Yandex Browser build. Yandex documents Chromium extension compatibility and Native Messaging management policies, but this repository does not assume every consumer build/channel behaves identically.
