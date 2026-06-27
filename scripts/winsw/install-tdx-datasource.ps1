[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectDir = "",
    [string]$ServiceDir = "",
    [string]$WinSWExe = "",
    [string]$Executable = "",
    [string]$Arguments = "run uvicorn tdx.main:app --host %DATASOURCE_HOST% --port %DATASOURCE_PORT%",
    [string]$TdxHttpUrl = "http://127.0.0.1:17709/",
    [string]$TdxSdkPath = "",
    [string]$DatasourceHost = "127.0.0.1",
    [int]$DatasourcePort = 9001,
    [string]$TdxMinutePeriod = "1m",
    [int]$TdxCollectDelaySeconds = 2,
    [int]$TdxRetryDelaySeconds = 8,
    [int]$TdxReconcileIntervalSeconds = 60,
    [int]$TdxMaxSubscriptions = 100,
    [int]$TdxWsQueueMaxSize = 1000,
    [switch]$DisableLegacyMistTDX
)

$ErrorActionPreference = "Stop"
$ServiceName = "mist-tdx-datasource"
$ScriptDir = $PSScriptRoot
$CommonScript = Join-Path (Split-Path -Parent $ScriptDir) "windows-common.ps1"
. $CommonScript

function Get-ConfiguredValue {
    param(
        [string]$Content,
        [string]$Name,
        [object]$Default
    )

    $fromFile = ""
    if ($Content) {
        $fromFile = Get-EnvValue -Content $Content -Name $Name
    }
    if ($fromFile) { return $fromFile }

    $fromEnv = [System.Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }

    return $Default
}

function Get-WindowsServiceController {
    param([string]$Name)

    if ([System.Environment]::OSVersion.Platform -ne "Win32NT") {
        return $null
    }

    return Get-Service -Name $Name -ErrorAction SilentlyContinue
}

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

function Set-TemplateValues {
    param(
        [string]$Template,
        [hashtable]$Values
    )

    $result = $Template
    foreach ($key in $Values.Keys) {
        $result = $result.Replace($key, [string]$Values[$key])
    }
    return $result
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
$LogsDir = Resolve-FullPath (Join-Path $ProjectDir "logs\mist-tdx-datasource")
$TemplateFile = Join-Path $ScriptDir "mist-tdx-datasource.xml"
$ServiceExe = Join-Path $ServiceDir "$ServiceName.exe"
$ServiceXml = Join-Path $ServiceDir "$ServiceName.xml"

if (-not (Test-Path $TemplateFile -PathType Leaf)) {
    Write-Fail "Missing WinSW XML template: $TemplateFile"
    exit 1
}

$EnvFile = Join-Path $ProjectDir ".env"
$EnvContent = ""
if (Test-Path $EnvFile -PathType Leaf) {
    $EnvContent = Get-Content $EnvFile -Raw
}

if (-not $Executable) {
    $Executable = Resolve-UvExe -ProjectDir $ProjectDir -PreferPathLookup:$false
    if (-not $Executable) {
        $Executable = Resolve-UvExe -ProjectDir $ProjectDir -PreferPathLookup:$true
    }
    if (-not $Executable) {
        if ($WhatIfPreference) {
            Write-Warn "uv executable was not found. A real install requires runtime\uv.exe or uv on PATH."
        }
        else {
            Write-Fail "uv executable not found. Place uv.exe under runtime\ or pass -Executable."
            exit 1
        }
    }
}
if ($Executable) {
    Write-Ok "Datasource executable: $Executable"
}

if (-not $PSBoundParameters.ContainsKey("TdxHttpUrl")) {
    $TdxHttpUrl = Get-ConfiguredValue -Content $EnvContent -Name "TDX_HTTP_URL" -Default $TdxHttpUrl
}
if (-not $PSBoundParameters.ContainsKey("TdxSdkPath")) {
    $TdxSdkPath = Get-ConfiguredValue -Content $EnvContent -Name "TDX_SDK_PATH" -Default $TdxSdkPath
}
if (-not $PSBoundParameters.ContainsKey("DatasourceHost")) {
    $DatasourceHost = Get-ConfiguredValue -Content $EnvContent -Name "DATASOURCE_HOST" -Default ""
    if (-not $DatasourceHost) {
        $DatasourceHost = Get-ConfiguredValue -Content $EnvContent -Name "TDX_HOST" -Default "127.0.0.1"
    }
}
if (-not $PSBoundParameters.ContainsKey("DatasourcePort")) {
    $DatasourcePort = [int](Get-ConfiguredValue -Content $EnvContent -Name "DATASOURCE_PORT" -Default (
        Get-ConfiguredValue -Content $EnvContent -Name "TDX_PORT" -Default 9001
    ))
}
if (-not $PSBoundParameters.ContainsKey("TdxMinutePeriod")) {
    $TdxMinutePeriod = Get-ConfiguredValue -Content $EnvContent -Name "TDX_MINUTE_PERIOD" -Default $TdxMinutePeriod
}
if (-not $PSBoundParameters.ContainsKey("TdxCollectDelaySeconds")) {
    $TdxCollectDelaySeconds = [int](Get-ConfiguredValue -Content $EnvContent -Name "TDX_COLLECT_DELAY_SECONDS" -Default $TdxCollectDelaySeconds)
}
if (-not $PSBoundParameters.ContainsKey("TdxRetryDelaySeconds")) {
    $TdxRetryDelaySeconds = [int](Get-ConfiguredValue -Content $EnvContent -Name "TDX_RETRY_DELAY_SECONDS" -Default $TdxRetryDelaySeconds)
}
if (-not $PSBoundParameters.ContainsKey("TdxReconcileIntervalSeconds")) {
    $TdxReconcileIntervalSeconds = [int](Get-ConfiguredValue -Content $EnvContent -Name "TDX_RECONCILE_INTERVAL_SECONDS" -Default $TdxReconcileIntervalSeconds)
}
if (-not $PSBoundParameters.ContainsKey("TdxMaxSubscriptions")) {
    $TdxMaxSubscriptions = [int](Get-ConfiguredValue -Content $EnvContent -Name "TDX_MAX_SUBSCRIPTIONS" -Default $TdxMaxSubscriptions)
}
if (-not $PSBoundParameters.ContainsKey("TdxWsQueueMaxSize")) {
    $TdxWsQueueMaxSize = [int](Get-ConfiguredValue -Content $EnvContent -Name "TDX_WS_QUEUE_MAX_SIZE" -Default $TdxWsQueueMaxSize)
}

$ResolvedWinSWExe = Resolve-WinSWExe -ProjectDir $ProjectDir -WinSWExe $WinSWExe
if (-not $ResolvedWinSWExe) {
    if ($WhatIfPreference) {
        Write-Warn "WinSW executable was not found. A real install requires -WinSWExe or a bundled winsw.exe."
    }
    else {
        Write-Fail "WinSW executable not found. Pass -WinSWExe or place winsw.exe under winsw\, tools\winsw\, or runtime\."
        exit 1
    }
}
else {
    Write-Ok "WinSW: $ResolvedWinSWExe"
}

$ExistingService = Get-WindowsServiceController -Name $ServiceName
$ServiceExists = $null -ne $ExistingService

if ($ServiceExists) {
    Write-Step "Stop existing $ServiceName before updating service files"
    if ($ExistingService.Status -eq "Stopped") {
        Write-Ok "$ServiceName is already stopped"
    }
    elseif ($PSCmdlet.ShouldProcess($ServiceName, "Stop service before replacing WinSW executable")) {
        Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        $ExistingService.WaitForStatus(
            [System.ServiceProcess.ServiceControllerStatus]::Stopped,
            [TimeSpan]::FromSeconds(30)
        )
        Write-Ok "$ServiceName stopped for update"
    }
}

Write-Step "Prepare WinSW service files"
if ($PSCmdlet.ShouldProcess($ServiceDir, "Create service directory")) {
    New-Item -ItemType Directory -Force -Path $ServiceDir | Out-Null
}
if ($PSCmdlet.ShouldProcess($LogsDir, "Create log directory")) {
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
}
if ($ResolvedWinSWExe -and $PSCmdlet.ShouldProcess($ServiceExe, "Copy WinSW executable")) {
    Copy-Item -Path $ResolvedWinSWExe -Destination $ServiceExe -Force
}

$Template = Get-Content $TemplateFile -Raw
$RenderedXml = Set-TemplateValues `
    -Template $Template `
    -Values @{
        "{{PROJECT_DIR}}" = ConvertTo-XmlEscapedValue $ProjectDir
        "{{DATASOURCE_EXECUTABLE}}" = ConvertTo-XmlEscapedValue $Executable
        "{{DATASOURCE_ARGUMENTS}}" = ConvertTo-XmlEscapedValue $Arguments
        "{{TDX_HTTP_URL}}" = ConvertTo-XmlEscapedValue $TdxHttpUrl
        "{{TDX_SDK_PATH}}" = ConvertTo-XmlEscapedValue $TdxSdkPath
        "{{DATASOURCE_HOST}}" = ConvertTo-XmlEscapedValue $DatasourceHost
        "{{DATASOURCE_PORT}}" = ConvertTo-XmlEscapedValue $DatasourcePort
        "{{TDX_MINUTE_PERIOD}}" = ConvertTo-XmlEscapedValue $TdxMinutePeriod
        "{{TDX_COLLECT_DELAY_SECONDS}}" = ConvertTo-XmlEscapedValue $TdxCollectDelaySeconds
        "{{TDX_RETRY_DELAY_SECONDS}}" = ConvertTo-XmlEscapedValue $TdxRetryDelaySeconds
        "{{TDX_RECONCILE_INTERVAL_SECONDS}}" = ConvertTo-XmlEscapedValue $TdxReconcileIntervalSeconds
        "{{TDX_MAX_SUBSCRIPTIONS}}" = ConvertTo-XmlEscapedValue $TdxMaxSubscriptions
        "{{TDX_WS_QUEUE_MAX_SIZE}}" = ConvertTo-XmlEscapedValue $TdxWsQueueMaxSize
        "{{LOG_DIR}}" = ConvertTo-XmlEscapedValue $LogsDir
    }

if ($PSCmdlet.ShouldProcess($ServiceXml, "Render WinSW XML")) {
    $RenderedXml | Set-Content -Path $ServiceXml -Encoding UTF8
}

if ($DisableLegacyMistTDX) {
    Write-Step "Disable legacy MistTDX service"
    if ($PSCmdlet.ShouldProcess("MistTDX", "Stop and disable legacy service")) {
        $LegacyService = Get-Service -Name "MistTDX" -ErrorAction SilentlyContinue
        if ($LegacyService) {
            if ($LegacyService.Status -ne "Stopped") {
                Stop-Service -Name "MistTDX" -Force -ErrorAction Stop
            }
            Set-Service -Name "MistTDX" -StartupType Disabled
            Write-Ok "MistTDX stopped and disabled"
        }
        else {
            Write-Warn "Legacy MistTDX service was not found"
        }
    }
}
else {
    Write-Warn "Legacy MistTDX unchanged. Pass -DisableLegacyMistTDX to stop and disable it."
}

Write-Step "Install or update $ServiceName"
if ($ServiceExists) {
    if ($PSCmdlet.ShouldProcess($ServiceName, "Reinstall WinSW service definition")) {
        Invoke-WinSWCommand -Exe $ServiceExe -Arguments @("uninstall") -AllowFailure | Out-Null
        Invoke-WinSWCommand -Exe $ServiceExe -Arguments @("install") | Out-Null
        Write-Ok "$ServiceName service reinstalled"
    }
}
else {
    if ($PSCmdlet.ShouldProcess($ServiceName, "Install WinSW service")) {
        Invoke-WinSWCommand -Exe $ServiceExe -Arguments @("install") | Out-Null
        Write-Ok "$ServiceName service installed"
    }
}

Write-Step "Start $ServiceName"
if ($PSCmdlet.ShouldProcess($ServiceName, "Start service")) {
    $StartResult = Invoke-WinSWCommand -Exe $ServiceExe -Arguments @("start") -AllowFailure
    if ($StartResult.ExitCode -eq 0) {
        Write-Ok "$ServiceName start requested"
    }
    elseif ($StartResult.Output -match "already|running|SERVICE_RUNNING|started successfully") {
        Write-Warn "$ServiceName start returned exit code $($StartResult.ExitCode), but WinSW output indicates the service is running"
    }
    else {
        throw "Unable to start $ServiceName. $($StartResult.Output)"
    }
}

Write-Ok "WinSW service files: $ServiceDir"
$global:LASTEXITCODE = 0
