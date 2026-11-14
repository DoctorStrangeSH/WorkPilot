$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$setup = Join-Path $PSScriptRoot 'setup_browser_bridge.ps1'
. $setup -ValidateOnly
$label = U '\u041c\u0430\u043b\u0435\u043d\u0438\u044f'
if ($label.Length -ne 7 -or [int][char]$label[0] -ne 0x041c) { throw 'Localization decoding failed.' }
foreach ($invalidId in @(('x' * 32), ('A' * 32), 'abc', (('a' * 32) + ';echo nope'))) {
    $rejected = $false
    try { & $setup -ExtensionId $invalidId } catch { $rejected = $true }
    if (-not $rejected) { throw 'Invalid ID was accepted.' }
}
$fixtureId = [guid]::NewGuid().ToString('N')
$fixtureRoot = Join-Path $env:TEMP "MaleniaSetupTest-$fixtureId"
try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
    Copy-Item -LiteralPath $setup -Destination $fixtureRoot
    $fixtureSetup = Join-Path $fixtureRoot 'setup_browser_bridge.ps1'
    $fixtureRegistration = Join-Path $fixtureRoot 'register_browser_bridge.ps1'
    foreach ($mode in @(0, 1)) {
        $content = if ($mode -eq 0) { [byte[]]@(35, 255) } else { [Text.Encoding]::ASCII.GetBytes("throw 'TAMPERED_SCRIPT_EXECUTED'") }
        [IO.File]::WriteAllBytes($fixtureRegistration, $content)
        $rejected = $false
        try { & $fixtureSetup -ValidateOnly }
        catch {
            if ($_.Exception.Message -eq 'TAMPERED_SCRIPT_EXECUTED') { throw 'Tampered source executed.' }
            $rejected = $true
        }
        if (-not $rejected) { throw 'Tampered registration was accepted.' }
    }
    Write-Output 'PASS: ID validation, localization, non-ASCII and tampered-source rejection.'
}
finally {
    if ((Split-Path -Leaf $fixtureRoot) -ne "MaleniaSetupTest-$fixtureId" -or
        (Split-Path -Parent $fixtureRoot) -ne $env:TEMP) { throw 'Unsafe fixture cleanup.' }
    if (Test-Path -LiteralPath $fixtureRoot) { Remove-Item -LiteralPath $fixtureRoot -Recurse -Force }
}
