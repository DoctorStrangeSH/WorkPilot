$ErrorActionPreference = "Stop"
$hostName = "com.malenia.browser"
$registryPaths = @(
    "HKCU:\Software\Yandex\YandexBrowser\NativeMessagingHosts\$hostName",
    "HKCU:\Software\Chromium\NativeMessagingHosts\$hostName"
)

foreach ($registryPath in $registryPaths) {
    if (Test-Path $registryPath) {
        Remove-Item -LiteralPath $registryPath -Recurse -Force
    }
}

$root = Join-Path $env:LOCALAPPDATA "Malenia"
Remove-Item -LiteralPath (Join-Path $root "browser_bridge.json") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $root "browser-bridge") -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Malenia Browser Bridge registration removed. Existing Malenia task data was kept."
