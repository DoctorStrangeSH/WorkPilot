param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$NativeHostPath
)

$ErrorActionPreference = "Stop"
$hostName = "com.workpilot.browser"
$root = Join-Path $env:LOCALAPPDATA "WorkPilot"
$bridgeDir = Join-Path $root "browser-bridge"
$manifestPath = Join-Path $bridgeDir "$hostName.json"
$configPath = Join-Path $root "browser_bridge.json"

New-Item -ItemType Directory -Force -Path $bridgeDir | Out-Null
$resolvedHostPath = (Resolve-Path -LiteralPath $NativeHostPath).Path

$manifest = @{
    name = $hostName
    description = "WorkPilot user-approved browser tab bridge"
    path = $resolvedHostPath
    type = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

@{ extension_id = $ExtensionId } |
    ConvertTo-Json |
    Set-Content -LiteralPath $configPath -Encoding UTF8

# Yandex Browser is Chromium-based. Register the Yandex-specific location and
# Chromium fallback for builds that use the upstream Chromium lookup path.
$registryPaths = @(
    "HKCU:\Software\Yandex\YandexBrowser\NativeMessagingHosts\$hostName",
    "HKCU:\Software\Chromium\NativeMessagingHosts\$hostName"
)
foreach ($registryPath in $registryPaths) {
    New-Item -Path $registryPath -Force | Out-Null
    Set-Item -Path $registryPath -Value $manifestPath
}

Write-Host "WorkPilot Browser Bridge registered for extension $ExtensionId."
Write-Host "Native host manifest: $manifestPath"
Write-Host "Restart Yandex Browser before testing the extension."
