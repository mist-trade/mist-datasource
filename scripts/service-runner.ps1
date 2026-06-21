param(
    [string]$Instance = "",
    [switch]$LoadOnly,
    [int]$StableRunSeconds = 60,
    [int]$CrashWindowMinutes = 10,
    [int]$MaxCrashes = 5,
    [int]$SentinelExitCode = 88
)

$ErrorActionPreference = "Stop"

function Get-CrashRecords {
    param(
        [string]$StateFile,
        [datetime]$Now,
        [int]$WindowMinutes
    )

    if (-not (Test-Path $StateFile -PathType Leaf)) { return @() }

    try {
        $state = Get-Content $StateFile -Raw | ConvertFrom-Json
    } catch {
        return @()
    }

    if (-not $state.crashes) { return @() }

    $cutoff = $Now.ToUniversalTime().AddMinutes(-1 * $WindowMinutes)
    $records = @()
    foreach ($value in @($state.crashes)) {
        try {
            $timestamp = ([datetime]$value).ToUniversalTime()
            if ($timestamp -ge $cutoff) {
                $records += $timestamp.ToString("o")
            }
        } catch {
        }
    }

    return $records
}

function Save-CrashRecords {
    param(
        [string]$StateFile,
        [string[]]$Records
    )

    $parent = Split-Path -Parent $StateFile
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    @{ crashes = @($Records) } |
        ConvertTo-Json -Depth 4 |
        Set-Content -Path $StateFile -Encoding UTF8
}

function Add-CrashRecord {
    param(
        [string]$StateFile,
        [datetime]$Now = (Get-Date),
        [int]$WindowMinutes = 10
    )

    $records = @(Get-CrashRecords -StateFile $StateFile -Now $Now -WindowMinutes $WindowMinutes)
    $records += $Now.ToUniversalTime().ToString("o")
    Save-CrashRecords -StateFile $StateFile -Records $records
}

function Get-CrashCount {
    param(
        [string]$StateFile,
        [datetime]$Now = (Get-Date),
        [int]$WindowMinutes = 10
    )

    return @(Get-CrashRecords -StateFile $StateFile -Now $Now -WindowMinutes $WindowMinutes).Count
}

function Clear-CrashState {
    param([string]$StateFile)

    if (Test-Path $StateFile -PathType Leaf) {
        Remove-Item $StateFile -Force
    }
}

function Get-InstanceConfig {
    param([string]$Instance)

    if ($Instance -eq "tdx") {
        return @{
            Module = "tdx.main:app"
            Port = "9001"
        }
    }
    if ($Instance -eq "qmt") {
        return @{
            Module = "qmt.main:app"
            Port = "9002"
        }
    }

    throw "Unknown datasource instance '$Instance'. Use 'tdx' or 'qmt'."
}

if ($LoadOnly) {
    return
}

try {
    $config = Get-InstanceConfig -Instance $Instance
    $projectDir = $PSScriptRoot | Split-Path -Parent
    $logsDir = Join-Path $projectDir "logs"
    New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

    $stateFile = Join-Path $logsDir "service-runner-$Instance-state.json"
    $currentCrashCount = Get-CrashCount `
        -StateFile $stateFile `
        -Now (Get-Date) `
        -WindowMinutes $CrashWindowMinutes

    if ($currentCrashCount -ge $MaxCrashes) {
        Write-Host "Crash-loop protection is active for $Instance. Remove $stateFile after fixing the issue." -ForegroundColor Red
        exit $SentinelExitCode
    }

    $venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython -PathType Leaf)) {
        Write-Host "Missing venv Python: $venvPython" -ForegroundColor Red
        Add-CrashRecord -StateFile $stateFile -Now (Get-Date) -WindowMinutes $CrashWindowMinutes
        exit 1
    }

    $startedAt = Get-Date
    Write-Host "Starting $Instance datasource on 127.0.0.1:$($config.Port)"
    & $venvPython -m uvicorn $config.Module --host 127.0.0.1 --port $config.Port
    $exitCode = $LASTEXITCODE
    $duration = ((Get-Date) - $startedAt).TotalSeconds

    if ($duration -ge $StableRunSeconds) {
        Clear-CrashState -StateFile $stateFile
    } else {
        Add-CrashRecord -StateFile $stateFile -Now (Get-Date) -WindowMinutes $CrashWindowMinutes
        $newCrashCount = Get-CrashCount `
            -StateFile $stateFile `
            -Now (Get-Date) `
            -WindowMinutes $CrashWindowMinutes
        if ($newCrashCount -ge $MaxCrashes) {
            Write-Host "Crash-loop protection stopped $Instance after $newCrashCount early exits." -ForegroundColor Red
            exit $SentinelExitCode
        }
    }

    if ($exitCode -eq 0 -and $duration -lt $StableRunSeconds) {
        exit 1
    }
    exit $exitCode
} catch {
    Write-Host "service-runner failed: $_" -ForegroundColor Red
    exit 1
}
