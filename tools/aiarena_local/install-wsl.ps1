# Run from an elevated PowerShell; never restarts the machine automatically.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$infraRuntime = Join-Path $PSScriptRoot 'runtime'
New-Item -ItemType Directory -Force -Path $infraRuntime | Out-Null
Start-Transcript -Path (Join-Path $infraRuntime 'windows-prerequisites.log') -Append
try {
    $infraFeature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
    if ($infraFeature.State -ne 'Enabled') {
        Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
    }
    winget install --id Microsoft.WSL --exact --source winget --silent --accept-source-agreements --accept-package-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "WSL installer failed: $LASTEXITCODE" }
    wsl --version
    Write-Output 'WSL installed. Enable CPU virtualization in BIOS/UEFI if disabled, then restart Windows.'
} finally {
    Stop-Transcript
}
