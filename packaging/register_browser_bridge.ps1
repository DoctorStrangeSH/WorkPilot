[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId,

    [Parameter(Mandatory = $false)]
    [string]$NativeHostPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hostName = "com.workpilot.browser"
$localRoot = Join-Path $env:LOCALAPPDATA "WorkPilot"
$bridgeDir = Join-Path $localRoot "browser-bridge"
$manifestPath = Join-Path $bridgeDir "$hostName.json"
$configPath = Join-Path $localRoot "browser_bridge.json"
$hostRelativePath = "resources\workpilot-native-host\workpilot-native-host.exe"

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
        # Ignore malformed optional discovery paths; explicit paths are validated separately.
    }
}

function Find-InstalledNativeHost {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $installRoots = New-Object 'System.Collections.Generic.List[string]'

    # If WorkPilot is running, its executable directory is the Tauri resource root.
    $processes = Get-Process -Name "WorkPilot" -ErrorAction SilentlyContinue
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

    # Tauri's per-user NSIS installer records its installation in the user's
    # uninstall registry. Prefer these concrete paths over guessed directories.
    $uninstallRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($uninstallRoot in $uninstallRoots) {
        if (-not (Test-Path -LiteralPath $uninstallRoot)) { continue }

        foreach ($key in (Get-ChildItem -LiteralPath $uninstallRoot -ErrorAction SilentlyContinue)) {
            try {
                $entry = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction Stop
                if ([string]$entry.DisplayName -notmatch '^WorkPilot(?:\s|$)') { continue }

                if ($entry.InstallLocation) {
                    Add-UniquePath -List $installRoots -Path ([string]$entry.InstallLocation)
                }

                if ($entry.DisplayIcon) {
                    $iconPath = [string]$entry.DisplayIcon
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

    # Tauri current-user NSIS installs live below LocalAppData. These are
    # fallback candidates only; a host is accepted only if the exact bundled
    # relative path exists.
    foreach ($fallbackRoot in @(
        (Join-Path $env:LOCALAPPDATA "Programs\WorkPilot"),
        (Join-Path $env:LOCALAPPDATA "WorkPilot")
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
Не удалось автоматически найти Native Messaging host.
Проверь, что WorkPilot 0.2 установлен. Если приложение установлено в нестандартную папку,
повтори команду с -NativeHostPath "полный\путь\к\workpilot-native-host.exe".
Ожидаемая структура ресурсов: <папка WorkPilot>\resources\workpilot-native-host\workpilot-native-host.exe
"@
    }

    if ($candidates.Count -gt 1) {
        throw ("Найдено несколько копий Native Messaging host. Укажи нужную явно через -NativeHostPath: " +
            ($candidates -join "; "))
    }

    return $candidates[0]
}

if ([string]::IsNullOrWhiteSpace($NativeHostPath)) {
    $resolvedHostPath = Find-InstalledNativeHost
}
else {
    if (-not (Test-Path -LiteralPath $NativeHostPath -PathType Leaf)) {
        throw "Файл Native Messaging host не найден: $NativeHostPath"
    }
    $resolvedHostPath = (Resolve-Path -LiteralPath $NativeHostPath).Path
}

if ([System.IO.Path]::GetFileName($resolvedHostPath) -ne "workpilot-native-host.exe") {
    throw "Ожидался файл workpilot-native-host.exe, получен: $resolvedHostPath"
}

# PyInstaller onedir requires the adjacent runtime directory to stay with the EXE.
$hostDirectory = Split-Path -Parent $resolvedHostPath
$internalDirectory = Join-Path $hostDirectory "_internal"
if (-not (Test-Path -LiteralPath $internalDirectory -PathType Container)) {
    throw "Рядом с Native Messaging host не найдена папка _internal: $internalDirectory"
}

New-Item -ItemType Directory -Force -Path $bridgeDir | Out-Null

$manifest = @{
    name = $hostName
    description = "WorkPilot user-approved browser tab bridge"
    path = $resolvedHostPath
    type = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$manifestJson = ConvertTo-Json -InputObject $manifest -Depth 5
$configJson = ConvertTo-Json -InputObject @{ extension_id = $ExtensionId }

[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8NoBom)
[System.IO.File]::WriteAllText($configPath, $configJson, $utf8NoBom)

# Register per-user only; no administrator privileges or machine-wide changes.
# Chromium is the documented fallback registry namespace for Chromium-based browsers.
$registryPaths = @(
    "HKCU:\Software\Yandex\YandexBrowser\NativeMessagingHosts\$hostName",
    "HKCU:\Software\Chromium\NativeMessagingHosts\$hostName"
)

foreach ($registryPath in $registryPaths) {
    New-Item -Path $registryPath -Force | Out-Null
    Set-Item -LiteralPath $registryPath -Value $manifestPath
}

Write-Host ""
Write-Host "WorkPilot Browser Bridge зарегистрирован." -ForegroundColor Green
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
Write-Host "Закрой Яндекс Браузер полностью и запусти его снова."
Write-Host "Затем открой WorkPilot Browser Bridge и нажми «Поделиться вкладкой»."
