[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId,

    [Parameter(Mandatory = $false)]
    [string]$NativeHostPath
)

# Keep this script ASCII-only: Windows PowerShell 5.1 reads UTF-8 files
# without a BOM using the active ANSI code page.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hostName = "com.malenia.browser"
# New product namespace; previous registrations are not reused.
$localRoot = Join-Path $env:LOCALAPPDATA "Malenia"
$bridgeDir = Join-Path $localRoot "browser-bridge"
$manifestPath = Join-Path $bridgeDir "$hostName.json"
$configPath = Join-Path $localRoot "browser_bridge.json"
$hostRelativePath = "resources\malenia-native-host\malenia-native-host.exe"

function Add-UniquePath {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    try {
        $fullPath = [System.IO.Path]::GetFullPath($Path)
        if (-not $List.Contains($fullPath)) {
            $List.Add($fullPath)
        }
    }
    catch {
        # Ignore malformed optional discovery paths.
    }
}

function Find-InstalledNativeHost {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $installRoots = New-Object 'System.Collections.Generic.List[string]'

    # If Malenia is running, its executable directory is the resource root.
    $processes = Get-Process -Name "Malenia", "malenia-desktop" -ErrorAction SilentlyContinue
    foreach ($process in $processes) {
        try {
            if ($process.Path) {
                Add-UniquePath -List $installRoots -Path (Split-Path -Parent $process.Path)
            }
        }
        catch {
            # Process path may be unavailable due to permissions.
        }
    }

    # Prefer actual current-user uninstall metadata over guessed directories.
    $uninstallRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($uninstallRoot in $uninstallRoots) {
        if (-not (Test-Path -LiteralPath $uninstallRoot)) { continue }

        foreach ($key in (Get-ChildItem -LiteralPath $uninstallRoot -ErrorAction SilentlyContinue)) {
            try {
                $entry = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction Stop
                $displayNameProperty = $entry.PSObject.Properties["DisplayName"]
                $installLocationProperty = $entry.PSObject.Properties["InstallLocation"]
                $displayIconProperty = $entry.PSObject.Properties["DisplayIcon"]

                $displayName = if ($displayNameProperty) { [string]$displayNameProperty.Value } else { "" }
                if ($displayName -notmatch '^Malenia(?:\s|$)') { continue }

                if ($installLocationProperty -and $installLocationProperty.Value) {
                    Add-UniquePath -List $installRoots -Path ([string]$installLocationProperty.Value)
                }

                if ($displayIconProperty -and $displayIconProperty.Value) {
                    $iconPath = [string]$displayIconProperty.Value
                    if ($iconPath -match '^"([^"]+\.exe)"') {
                        $iconPath = $Matches[1]
                    }
                    else {
                        $iconPath = $iconPath -replace ',\d+$', ''
                        $iconPath = $iconPath.Trim('"')
                    }
                    if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
                        Add-UniquePath -List $installRoots -Path (Split-Path -Parent $iconPath)
                    }
                }
            }
            catch {
                # Ignore unrelated or unreadable uninstall entries.
            }
        }
    }

    # Fallback locations are accepted only if the exact resource file exists.
    foreach ($fallbackRoot in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Malenia"),
        (Join-Path $env:LOCALAPPDATA "Malenia")
    )) {
        if (Test-Path -LiteralPath $fallbackRoot -PathType Container) {
            Add-UniquePath -List $installRoots -Path $fallbackRoot
        }
    }

    foreach ($root in $installRoots) {
        $candidate = Join-Path $root $hostRelativePath
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            Add-UniquePath -List $candidates -Path $candidate
        }
    }

    if ($candidates.Count -eq 0) {
        throw @"
Could not automatically locate the Native Messaging host.
Confirm Malenia 0.3 or newer is installed. For a non-standard install directory, rerun
with -NativeHostPath "C:\full\path\to\malenia-native-host.exe".
Expected layout: <Malenia folder>\resources\malenia-native-host\malenia-native-host.exe
"@
    }

    if ($candidates.Count -gt 1) {
        throw ("Multiple Native Messaging hosts were found. Specify -NativeHostPath: " +
            ($candidates -join "; "))
    }

    return $candidates[0]
}

if ([string]::IsNullOrWhiteSpace($NativeHostPath)) {
    $resolvedHostPath = Find-InstalledNativeHost
}
else {
    if (-not (Test-Path -LiteralPath $NativeHostPath -PathType Leaf)) {
        throw "Native Messaging host file not found: $NativeHostPath"
    }
    $resolvedHostPath = (Resolve-Path -LiteralPath $NativeHostPath).Path
}

if ([System.IO.Path]::GetFileName($resolvedHostPath) -ne "malenia-native-host.exe") {
    throw "Expected malenia-native-host.exe, got: $resolvedHostPath"
}

# PyInstaller onedir requires the adjacent runtime directory.
$hostDirectory = Split-Path -Parent $resolvedHostPath
$internalDirectory = Join-Path $hostDirectory "_internal"
if (-not (Test-Path -LiteralPath $internalDirectory -PathType Container)) {
    throw "PyInstaller _internal folder is missing beside the Native Messaging host: $internalDirectory"
}

New-Item -ItemType Directory -Force -Path $bridgeDir | Out-Null

$manifest = @{
    name = $hostName
    description = "Malenia user-approved browser tab bridge"
    path = $resolvedHostPath
    type = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$manifestJson = ConvertTo-Json -InputObject $manifest -Depth 5
$configJson = ConvertTo-Json -InputObject @{ extension_id = $ExtensionId }

[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8NoBom)
[System.IO.File]::WriteAllText($configPath, $configJson, $utf8NoBom)

# Register current-user locations only; no administrator rights are needed.
$registryPaths = @(
    "HKCU:\Software\Yandex\YandexBrowser\NativeMessagingHosts\$hostName",
    "HKCU:\Software\Chromium\NativeMessagingHosts\$hostName"
)

foreach ($registryPath in $registryPaths) {
    New-Item -Path $registryPath -Force | Out-Null
    Set-Item -LiteralPath $registryPath -Value $manifestPath
}

Write-Host ""
Write-Host "Malenia Browser Bridge registered." -ForegroundColor Green
Write-Host "Extension ID : $ExtensionId"
Write-Host "Native host  : $resolvedHostPath"
Write-Host "Manifest     : $manifestPath"
Write-Host "Config       : $configPath"
Write-Host ""
foreach ($registryPath in $registryPaths) {
    $registeredManifest = (Get-Item -LiteralPath $registryPath).GetValue("")
    Write-Host "$registryPath -> $registeredManifest"
}
Write-Host ""
Write-Host "Close all Yandex Browser windows and restart the browser."
Write-Host "Then open the Malenia Browser Bridge popup and click Share tab."
