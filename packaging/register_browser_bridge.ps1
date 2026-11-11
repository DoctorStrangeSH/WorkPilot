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
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$manifestJson = $manifest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8NoBom)

$configJson = @{ extension_id = $ExtensionId } | ConvertTo-Json
[System.IO.File]::WriteAllText($configPath, $configJson, $utf8NoBom)

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
