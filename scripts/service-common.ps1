# Shared NSSM service helpers for mist-datasource.

$commonScript = Join-Path $PSScriptRoot "windows-common.ps1"
if (Test-Path $commonScript -PathType Leaf) {
    . $commonScript
}

function New-DatasourceServiceDefinition {
    param(
        [ValidateSet("tdx", "qmt")]
        [string]$Instance,
        [string]$ProjectDir,
        [string]$LogsDir
    )

    $project = Resolve-FullPath $ProjectDir
    $logs = Resolve-FullPath $LogsDir
    $serviceName = if ($Instance -eq "tdx") { "MistTDX" } else { "MistQMT" }
    $displayName = if ($Instance -eq "tdx") { "Mist TDX DataSource" } else { "Mist QMT DataSource" }
    $description = if ($Instance -eq "tdx") {
        "TongDaXin datasource HTTP/WS service (port 9001)"
    } else {
        "QMT datasource HTTP/WS service (port 9002)"
    }
    $port = if ($Instance -eq "tdx") { 9001 } else { 9002 }

    @{
        Instance = $Instance
        ServiceName = $serviceName
        Application = "powershell.exe"
        Parameters = "-NoProfile -ExecutionPolicy Bypass -File `"scripts\service-runner.ps1`" -Instance $Instance"
        AppDirectory = $project
        DisplayName = $displayName
        Description = $description
        Port = $port
        Stdout = Join-Path $logs "$Instance-stdout.log"
        Stderr = Join-Path $logs "$Instance-stderr.log"
        AppThrottle = "60000"
        AppRestartDelay = "30000"
        SentinelExitCode = "88"
    }
}

function Invoke-Nssm {
    param(
        [string]$NssmExe,
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $NssmExe @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEAP
    }

    if (($exitCode -ne 0) -and (-not $AllowFailure)) {
        throw "nssm $($Arguments -join ' ') failed with exit code $exitCode. $output"
    }

    return @{
        ExitCode = $exitCode
        Output = "$output".Trim()
    }
}

function Test-NssmServiceExists {
    param(
        [string]$NssmExe,
        [string]$ServiceName
    )

    $result = Invoke-Nssm -NssmExe $NssmExe -Arguments @("status", $ServiceName) -AllowFailure
    return ($result.ExitCode -eq 0 -and $result.Output -match "SERVICE_")
}

function Get-NssmValue {
    param(
        [string]$NssmExe,
        [string]$ServiceName,
        [string]$Name
    )

    $result = Invoke-Nssm -NssmExe $NssmExe -Arguments @("get", $ServiceName, $Name) -AllowFailure
    if ($result.ExitCode -ne 0) { return "" }
    return $result.Output
}

function Test-DatasourceDirectoryMarkers {
    param([string]$Path)

    if (-not $Path) { return $false }
    if (-not (Test-Path $Path -PathType Container)) { return $false }

    $hasProject = Test-Path (Join-Path $Path "pyproject.toml") -PathType Leaf
    $hasTdx = Test-Path (Join-Path $Path "tdx") -PathType Container
    $hasQmt = Test-Path (Join-Path $Path "qmt") -PathType Container
    return ($hasProject -and $hasTdx -and $hasQmt)
}

function Test-DatasourceServiceOwnedByProject {
    param(
        [string]$NssmExe,
        [string]$ServiceName,
        [string]$ProjectDir
    )

    if (-not (Test-NssmServiceExists -NssmExe $NssmExe -ServiceName $ServiceName)) {
        return $true
    }

    $currentProject = (Resolve-FullPath $ProjectDir).ToLowerInvariant()
    $appDirectory = Get-NssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Name "AppDirectory"
    $application = Get-NssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Name "Application"
    $parameters = Get-NssmValue -NssmExe $NssmExe -ServiceName $ServiceName -Name "AppParameters"
    $combined = "$application $parameters"

    if ($appDirectory) {
        $resolvedAppDir = Resolve-FullPath $appDirectory
        if ($resolvedAppDir.ToLowerInvariant() -eq $currentProject) { return $true }
        if (Test-DatasourceDirectoryMarkers -Path $resolvedAppDir) { return $true }
    }

    if ($combined -match "service-runner\.ps1") { return $true }
    if ($combined -match "tdx\.main:app") { return $true }
    if ($combined -match "qmt\.main:app") { return $true }

    return $false
}

function Set-NssmValue {
    param(
        [string]$NssmExe,
        [string]$ServiceName,
        [string]$Name,
        [string[]]$Value
    )

    Invoke-Nssm -NssmExe $NssmExe -Arguments (@("set", $ServiceName, $Name) + $Value) | Out-Null
}

function Ensure-DatasourceNssmService {
    param(
        [string]$NssmExe,
        [hashtable]$Definition
    )

    $serviceName = $Definition.ServiceName
    if (-not (Test-NssmServiceExists -NssmExe $NssmExe -ServiceName $serviceName)) {
        Invoke-Nssm `
            -NssmExe $NssmExe `
            -Arguments @("install", $serviceName, $Definition.Application, $Definition.Parameters) `
            | Out-Null
    } elseif (-not (Test-DatasourceServiceOwnedByProject `
        -NssmExe $NssmExe `
        -ServiceName $serviceName `
        -ProjectDir $Definition.AppDirectory)) {
        throw "$serviceName already exists but does not look like a Mist datasource service. Remove or rename it before installing."
    } else {
        Write-Warn "$serviceName already exists; updating configuration"
    }

    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "Application" -Value $Definition.Application
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppParameters" -Value $Definition.Parameters
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppDirectory" -Value $Definition.AppDirectory
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "DisplayName" -Value $Definition.DisplayName
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "Description" -Value $Definition.Description
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "Start" -Value "SERVICE_AUTO_START"
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppStdout" -Value $Definition.Stdout
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppStderr" -Value $Definition.Stderr
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppRotateFiles" -Value "1"
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppRotateBytes" -Value "10485760"
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppThrottle" -Value $Definition.AppThrottle
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppRestartDelay" -Value $Definition.AppRestartDelay
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppExit" -Value @("Default", "Restart")
    Set-NssmValue -NssmExe $NssmExe -ServiceName $serviceName -Name "AppExit" -Value @($Definition.SentinelExitCode, "Exit")

    Write-Ok "$serviceName service configured"
}

function Start-DatasourceNssmService {
    param(
        [string]$NssmExe,
        [string]$ServiceName
    )

    $result = Invoke-Nssm -NssmExe $NssmExe -Arguments @("start", $ServiceName) -AllowFailure
    if ($result.ExitCode -eq 0) {
        Write-Ok "$ServiceName start requested"
        return
    }
    if ($result.Output -match "SERVICE_RUNNING") {
        Write-Warn "$ServiceName is already running"
        return
    }
    throw "Unable to start $ServiceName. $($result.Output)"
}
