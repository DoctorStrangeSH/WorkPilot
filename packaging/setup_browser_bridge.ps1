[CmdletBinding()]
param([string]$ExtensionId, [string]$NativeHostPath, [switch]$ValidateOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Keep source ASCII; decode localized labels at runtime on PowerShell 5.1.
function U {
    param([string]$Text)
    [regex]::Replace($Text, '\\u([0-9a-fA-F]{4})', {
        param($match)
        [string][char][Convert]::ToInt32($match.Groups[1].Value, 16)
    })
}
function Get-VerifiedRegistration {
    $path = Join-Path $PSScriptRoot 'register_browser_bridge.ps1'
    $bytes = [IO.File]::ReadAllBytes($path)
    if ($bytes.Length -eq 0 -or @($bytes | Where-Object { $_ -gt 127 }).Count -gt 0) {
        throw 'Registration script is empty or non-ASCII. Nothing executed.'
    }
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    # Exact known LF and CRLF byte representations of the same pinned source.
    if ($hash -notin @('f80ece220c84267ba9f0bb5ebdbaa47e8e43046cb674a552983187a2275a7392',
                      '4ab34717c8f21093bd23a600d58f7ffe7fac8751bafb0b751c4d922faea6c1dc')) {
        throw 'Registration script SHA256 mismatch. Nothing executed.'
    }
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw 'Registration script syntax error. Nothing executed.' }
    return $path
}
function Register-Bridge {
    param([string]$Id, [string]$HostFile)
    $clean = $Id.Trim()
    if ($clean -cnotmatch '^[a-p]{32}$') { throw (U 'ID \u0434\u043e\u043b\u0436\u0435\u043d \u0441\u043e\u0434\u0435\u0440\u0436\u0430\u0442\u044c 32 \u0441\u0442\u0440\u043e\u0447\u043d\u044b\u0435 \u0431\u0443\u043a\u0432\u044b \u043e\u0442 a \u0434\u043e p.') }
    $registration = Get-VerifiedRegistration
    if ([string]::IsNullOrWhiteSpace($HostFile)) { & $registration -ExtensionId $clean }
    else { & $registration -ExtensionId $clean -NativeHostPath $HostFile.Trim() }
}
$null = Get-VerifiedRegistration
if ($ValidateOnly) { Write-Output 'PASS: ASCII, SHA256 and PowerShell parser checks.'; return }
if (-not [string]::IsNullOrWhiteSpace($ExtensionId)) {
    Register-Bridge -Id $ExtensionId -HostFile $NativeHostPath
    return
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = U 'Malenia - \u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430'
$form.Size = New-Object Drawing.Size(620, 390)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$info = New-Object Windows.Forms.Label
$info.Text = U '\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u0435 Malenia \u0438 \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u0435 \u0440\u0430\u0441\u043f\u0430\u043a\u043e\u0432\u0430\u043d\u043d\u043e\u0435 \u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u0438\u0435. \u041e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443 \u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u0438\u0439 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430, \u0432\u043a\u043b\u044e\u0447\u0438\u0442\u0435 \u0440\u0435\u0436\u0438\u043c \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a\u0430 \u0438 \u0441\u043a\u043e\u043f\u0438\u0440\u0443\u0439\u0442\u0435 ID Malenia Browser Bridge.'
$info.Location = New-Object Drawing.Point(20, 20)
$info.Size = New-Object Drawing.Size(565, 65)
$form.Controls.Add($info)
$label = New-Object Windows.Forms.Label
$label.Text = U 'ID \u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u0438\u044f (32 \u0431\u0443\u043a\u0432\u044b):'
$label.Location = New-Object Drawing.Point(20, 90)
$label.AutoSize = $true
$form.Controls.Add($label)
$idBox = New-Object Windows.Forms.TextBox
$idBox.Location = New-Object Drawing.Point(20, 115)
$idBox.Size = New-Object Drawing.Size(560, 25)
$form.Controls.Add($idBox)
$hostLabel = New-Object Windows.Forms.Label
$hostLabel.Text = U '\u041f\u0443\u0442\u044c \u043a malenia-native-host.exe (\u043e\u0431\u044b\u0447\u043d\u043e \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u044f\u0435\u0442\u0441\u044f \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438):'
$hostLabel.Location = New-Object Drawing.Point(20, 155)
$hostLabel.AutoSize = $true
$form.Controls.Add($hostLabel)
$hostBox = New-Object Windows.Forms.TextBox
$hostBox.Location = New-Object Drawing.Point(20, 180)
$hostBox.Size = New-Object Drawing.Size(460, 25)
$hostBox.Text = $NativeHostPath
$form.Controls.Add($hostBox)
$browse = New-Object Windows.Forms.Button
$browse.Text = U '\u041e\u0431\u0437\u043e\u0440...'
$browse.Location = New-Object Drawing.Point(490, 178)
$browse.Size = New-Object Drawing.Size(90, 28)
$browse.Add_Click({
    $dialog = New-Object Windows.Forms.OpenFileDialog
    try {
        $dialog.Filter = 'Malenia Native Host|malenia-native-host.exe'
        if ($dialog.ShowDialog() -eq 'OK') { $hostBox.Text = $dialog.FileName }
    } finally { $dialog.Dispose() }
})
$form.Controls.Add($browse)
$note = New-Object Windows.Forms.Label
$note.Text = U '\u041d\u0430 \u043a\u0430\u0436\u0434\u043e\u043c \u043a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440\u0435 \u0432\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u0435\u0433\u043e ID. \u041f\u0440\u043e\u0444\u0438\u043b\u044c, cookies, \u043f\u0430\u0440\u043e\u043b\u0438 \u0438 \u0438\u0441\u0442\u043e\u0440\u0438\u044f \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430 \u043d\u0435 \u0447\u0438\u0442\u0430\u044e\u0442\u0441\u044f.'
$note.Location = New-Object Drawing.Point(20, 225)
$note.Size = New-Object Drawing.Size(560, 40)
$form.Controls.Add($note)
$apply = New-Object Windows.Forms.Button
$apply.Text = U '\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c'
$apply.Location = New-Object Drawing.Point(430, 280)
$apply.Size = New-Object Drawing.Size(150, 35)
$apply.Add_Click({
    $apply.Enabled = $false
    try {
        Register-Bridge -Id $idBox.Text -HostFile $hostBox.Text
        [Windows.Forms.MessageBox]::Show((U '\u041c\u043e\u0441\u0442 \u0437\u0430\u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0438\u0440\u043e\u0432\u0430\u043d. \u041f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 \u0431\u0440\u0430\u0443\u0437\u0435\u0440 \u0438 \u043d\u0430\u0436\u043c\u0438\u0442\u0435 \u0432 \u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u0438\u0438 \xab\u041f\u043e\u0434\u0435\u043b\u0438\u0442\u044c\u0441\u044f \u0432\u043a\u043b\u0430\u0434\u043a\u043e\u0439\xbb.'), 'Malenia') | Out-Null
        $form.Close()
    } catch { [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Malenia', 'OK', 'Error') | Out-Null }
    finally { $apply.Enabled = $true }
})
$form.Controls.Add($apply)
$form.AcceptButton = $apply
try { $null = $form.ShowDialog() } finally { $form.Dispose() }
