# Shared Windows deployment helpers for mist-datasource.

function Write-Step($msg) { Write-Host "`n===== $msg =====" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

function Resolve-FullPath {
    param([string]$Path)

    return [System.IO.Path]::GetFullPath($Path)
}

function Get-EnvValue {
    param(
        [string]$Content,
        [string]$Name
    )

    $pattern = "(?m)^\s*$([regex]::Escape($Name))\s*=\s*(.*?)\s*(?:#.*)?$"
    $match = [regex]::Match($Content, $pattern)
    if (-not $match.Success) { return "" }
    return $match.Groups[1].Value.Trim().Trim('"').Trim("'")
}

function Resolve-NssmExe {
    param(
        [string]$ProjectDir,
        [bool]$PreferPathLookup = $true
    )

    if (-not $ProjectDir) {
        $ProjectDir = $PSScriptRoot | Split-Path -Parent
    }

    if ($PreferPathLookup) {
        $cmd = Get-Command nssm -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }

    $candidates = @(
        (Join-Path $ProjectDir "..\nssm\nssm.exe"),
        (Join-Path $ProjectDir "nssm\nssm.exe")
    )
    foreach ($candidate in $candidates) {
        $resolved = Resolve-FullPath $candidate
        if (Test-Path $resolved -PathType Leaf) { return $resolved }
    }

    return $null
}

function Resolve-UvExe {
    param(
        [string]$ProjectDir,
        [bool]$PreferPathLookup = $true
    )

    if (-not $ProjectDir) {
        $ProjectDir = $PSScriptRoot | Split-Path -Parent
    }

    if ($PreferPathLookup) {
        $cmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }

    $candidates = @(
        (Join-Path $ProjectDir "runtime\uv.exe"),
        (Join-Path $ProjectDir "..\runtime\uv.exe")
    )
    foreach ($candidate in $candidates) {
        $resolved = Resolve-FullPath $candidate
        if (Test-Path $resolved -PathType Leaf) { return $resolved }
    }

    return $null
}

function Resolve-WinSWExe {
    param(
        [string]$ProjectDir,
        [string]$WinSWExe = "",
        [bool]$PreferPathLookup = $true
    )

    if (-not $ProjectDir) {
        $ProjectDir = $PSScriptRoot | Split-Path -Parent
    }

    if ($WinSWExe) {
        $resolved = Resolve-FullPath $WinSWExe
        if (Test-Path $resolved -PathType Leaf) { return $resolved }
        return $null
    }

    if ($PreferPathLookup) {
        foreach ($name in @("winsw", "WinSW", "winsw-x64", "WinSW-x64")) {
            $cmd = Get-Command $name -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        }
    }

    $candidates = @(
        (Join-Path $ProjectDir "winsw\winsw.exe"),
        (Join-Path $ProjectDir "winsw\WinSW.exe"),
        (Join-Path $ProjectDir "tools\winsw\winsw.exe"),
        (Join-Path $ProjectDir "runtime\winsw.exe"),
        (Join-Path $ProjectDir "..\winsw\winsw.exe")
    )
    foreach ($candidate in $candidates) {
        $resolved = Resolve-FullPath $candidate
        if (Test-Path $resolved -PathType Leaf) { return $resolved }
    }

    return $null
}

function ConvertTo-XmlEscapedValue {
    param([AllowNull()][object]$Value)

    return [System.Security.SecurityElement]::Escape([string]$Value)
}

function Wait-HttpHealth {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Attempts = 5,
        [int]$DelaySeconds = 3,
        [int]$TimeoutSeconds = 5
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSeconds -UseBasicParsing
            $body = $resp.Content | ConvertFrom-Json
            Write-Ok "$Name health: status=$($body.status), adapter=$($body.adapter)"
            return $true
        } catch {
            if ($i -lt $Attempts) {
                Write-Host "  Waiting for $Name... ($i/$Attempts)" -ForegroundColor Yellow
                Start-Sleep -Seconds $DelaySeconds
            } else {
                Write-Fail "$Name health endpoint did not respond: $_"
                return $false
            }
        }
    }

    return $false
}

function Stop-ProcessTreeBestEffort {
    param([System.Diagnostics.Process]$Process)

    if (-not $Process) { return }
    if ($Process.HasExited) { return }

    try {
        if ([System.Environment]::OSVersion.Platform -eq "Win32NT") {
            & taskkill /PID $Process.Id /T /F | Out-Null
        } else {
            $Process.Kill()
        }
        $Process.WaitForExit(5000) | Out-Null
    } catch {
        Write-Warn "Unable to stop process $($Process.Id): $_"
    }
}
