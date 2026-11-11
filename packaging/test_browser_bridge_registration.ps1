[CmdletBinding()]
param([string]$NativeHostPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSEdition -ne "Desktop" -or $PSVersionTable.PSVersion.Major -ne 5) {
    throw "Run this test using Windows PowerShell 5.1."
}
# Remap HKCU only inside this test process. Never touch real bridge keys.
$id = [guid]::NewGuid().ToString("N")
$registryRoot = "Microsoft.PowerShell.Core\Registry::HKEY_CURRENT_USER\Software\WorkPilotRegistrationTest-$id"
$testRoot = Join-Path $env:TEMP "WorkPilotRegistrationTest-$id"
$originalLocalAppData = $env:LOCALAPPDATA
$originalHkcuRoot = (Get-PSDrive HKCU).Root
$remapped = $false
try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    New-Item -Path $registryRoot -Force | Out-Null
    Remove-PSDrive HKCU
    New-PSDrive -Name HKCU -PSProvider Registry -Root $registryRoot | Out-Null
    $remapped = $true
    $env:LOCALAPPDATA = $testRoot
    if ([string]::IsNullOrWhiteSpace($NativeHostPath)) {
        $fixture = Join-Path $testRoot "fixture"
        New-Item -ItemType Directory -Path (Join-Path $fixture "_internal") -Force | Out-Null
        $NativeHostPath = Join-Path $fixture "workpilot-native-host.exe"
        [IO.File]::WriteAllBytes($NativeHostPath, [byte[]]@())
    }
    $NativeHostPath = (Resolve-Path -LiteralPath $NativeHostPath).Path
    $extensionId = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    $registration = Join-Path $PSScriptRoot "register_browser_bridge.ps1"
    # A rejected host must fail before writing any registration.
    $rejected = $false
    try { & $registration -ExtensionId $extensionId -NativeHostPath (Join-Path $testRoot "missing.exe") }
    catch { $rejected = $true }
    if (-not $rejected -or (Test-Path (Join-Path $testRoot "WorkPilot"))) {
        throw "Invalid host was not rejected before writes."
    }
    # Second registration must be safe and produce the same configuration.
    1..2 | ForEach-Object { & $registration -ExtensionId $extensionId -NativeHostPath $NativeHostPath }
    $manifestPath = Join-Path $testRoot "WorkPilot\browser-bridge\com.workpilot.browser.json"
    $configPath = Join-Path $testRoot "WorkPilot\browser_bridge.json"
    $manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $manifestPath | ConvertFrom-Json
    $config = Get-Content -Raw -Encoding UTF8 -LiteralPath $configPath | ConvertFrom-Json
    if ($manifest.name -ne "com.workpilot.browser" -or $manifest.type -ne "stdio" -or
        $manifest.path -ne $NativeHostPath -or $manifest.allowed_origins.Count -ne 1 -or
        $manifest.allowed_origins[0] -ne "chrome-extension://$extensionId/" -or $config.extension_id -ne $extensionId) {
        throw "Registration JSON does not match the requested host and origin."
    }
    foreach ($vendor in @("Yandex\YandexBrowser", "Chromium")) {
        $key = "HKCU:\Software\$vendor\NativeMessagingHosts\com.workpilot.browser"
        if ((Get-Item -LiteralPath $key).GetValue("") -ne $manifestPath) { throw "Registry value mismatch: $key" }
    }
    foreach ($file in @($manifestPath, $configPath)) {
        $bytes = [IO.File]::ReadAllBytes($file)
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) {
            throw "Generated JSON has a UTF-8 BOM."
        }
    }
    Write-Host "PASS: Windows PowerShell 5.1 registration, repeat registration, JSON, HKCU values and invalid-host rejection."
}
finally {
    $env:LOCALAPPDATA = $originalLocalAppData
    if ($remapped) {
        Remove-PSDrive HKCU
        New-PSDrive -Name HKCU -PSProvider Registry -Root $originalHkcuRoot | Out-Null
    }
    # Cleanup is limited to the exact GUID-named roots created above.
    if ($registryRoot -notmatch 'HKEY_CURRENT_USER\\Software\\WorkPilotRegistrationTest-[a-f0-9]{32}$') { throw "Unsafe registry cleanup path." }
    if ((Split-Path -Leaf $testRoot) -ne "WorkPilotRegistrationTest-$id" -or
        (Split-Path -Parent $testRoot) -ne $env:TEMP) { throw "Unsafe fixture cleanup path." }
    if (Test-Path -LiteralPath $registryRoot) { Remove-Item -LiteralPath $registryRoot -Recurse -Force }
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
