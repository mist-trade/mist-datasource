[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectDir = "",
    [string]$ServiceDir = ""
)

$ErrorActionPreference = "Stop"
$ServiceName = "mist-tdx-datasource"
$ScriptDir = $PSScriptRoot
$CommonScript = Join-Path (Split-Path -Parent $ScriptDir) "windows-common.ps1"
. $CommonScript

function Invoke-WinSWCommand {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Exe @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if (($exitCode -ne 0) -and (-not $AllowFailure)) {
        throw "WinSW $($Arguments -join ' ') failed with exit code $exitCode. $output"
    }

    return @{
        ExitCode = $exitCode
        Output = "$output".Trim()
    }
}

if (-not $ProjectDir) {
    $ProjectDir = Resolve-FullPath (Join-Path $ScriptDir "..\..")
}
else {
    $ProjectDir = Resolve-FullPath $ProjectDir
}

if (-not $ServiceDir) {
    $ServiceDir = Join-Path $ProjectDir "services\mist-tdx-datasource"
}
$ServiceDir = Resolve-FullPath $ServiceDir
$ServiceExe = Join-Path $ServiceDir "$ServiceName.exe"

if (-not (Test-Path $ServiceExe -PathType Leaf)) {
    if ($WhatIfPreference) {
        Write-Warn "Service executable not found at $ServiceExe. A real uninstall needs the rendered WinSW service exe."
    }
    else {
        Write-Fail "Service executable not found: $ServiceExe"
        exit 1
    }
}

Write-Step "Stop $ServiceName"
if ((Test-Path $ServiceExe -PathType Leaf) -and $PSCmdlet.ShouldProcess($ServiceName, "Stop WinSW service")) {
    $StopResult = Invoke-WinSWCommand -Exe $ServiceExe -Arguments @("stop") -AllowFailure
    if ($StopResult.ExitCode -eq 0) {
        Write-Ok "$ServiceName stop requested"
    }
    else {
        Write-Warn "$ServiceName stop returned exit code $($StopResult.ExitCode): $($StopResult.Output)"
    }
}

Write-Step "Uninstall $ServiceName"
if ((Test-Path $ServiceExe -PathType Leaf) -and $PSCmdlet.ShouldProcess($ServiceName, "Uninstall WinSW service")) {
    $UninstallResult = Invoke-WinSWCommand -Exe $ServiceExe -Arguments @("uninstall") -AllowFailure
    if ($UninstallResult.ExitCode -eq 0) {
        Write-Ok "$ServiceName service uninstalled"
    }
    else {
        Write-Warn "$ServiceName uninstall returned exit code $($UninstallResult.ExitCode): $($UninstallResult.Output)"
    }
}

Write-Warn "TDX client files and SDK files were not removed."
