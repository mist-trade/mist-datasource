param(
    [string]$DatasourceDir = "",
    [string]$ApplianceRoot = "",
    [string]$EnvFile = "",
    [string]$BaseUrl = "http://127.0.0.1:9001",
    [string]$WsUrl = "",
    [string]$ClientId = "runtime-smoke",
    [string]$Symbol = "688318.SH",
    [string]$RawSymbol = "",
    [string]$Sector = "880081.SH",
    [string]$Period = "1d",
    [int]$Count = 2,
    [int]$TimeoutSeconds = 20,
    [int]$LiveBarTimeoutSeconds = 60,
    [string]$TdxServiceName = "mist-tdx-datasource",
    [switch]$RunDatasourceInstall,
    [switch]$RunDatasourceStartupTest,
    [switch]$SkipScriptSelfTest,
    [switch]$RequireScriptSelfTest,
    [switch]$SkipSdkPreflight,
    [switch]$SkipWinSWProbe,
    [switch]$SkipApplianceHealth,
    [switch]$SkipMySQL,
    [switch]$SkipSmoke,
    [switch]$SkipWebSocket,
    [switch]$RequireLiveBar,
    [switch]$AllowWebSocketSubscriptionChange,
    [switch]$AllowTdxHttpUnavailable
)

# Optional deployment-side runtime checks:
#   .\scripts\run-runtime-checks.ps1 -RunDatasourceInstall      # calls deploy_windows.ps1 -Only install
#   .\scripts\run-runtime-checks.ps1 -RunDatasourceStartupTest  # calls deploy_windows.ps1 -Only test

$ErrorActionPreference = "Stop"

if (-not $DatasourceDir) {
    $DatasourceDir = $PSScriptRoot | Split-Path -Parent
}
$DatasourceDir = [System.IO.Path]::GetFullPath($DatasourceDir)

if (-not $ApplianceRoot) {
    $candidateRoot = Split-Path $DatasourceDir -Parent
    if (Test-Path (Join-Path $candidateRoot "health-check.ps1") -PathType Leaf) {
        $ApplianceRoot = $candidateRoot
    }
}
if ($ApplianceRoot) {
    $ApplianceRoot = [System.IO.Path]::GetFullPath($ApplianceRoot)
}

if (-not $EnvFile) {
    $EnvFile = Join-Path $DatasourceDir ".env"
}

$BaseUrl = $BaseUrl.TrimEnd("/")
if (-not $WsUrl) {
    $httpBase = $BaseUrl -replace "^http://", "ws://" -replace "^https://", "wss://"
    $WsUrl = "$httpBase/ws/quote/$ClientId"
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "===== $Message =====" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
}

function ConvertTo-TdxNativeSymbol {
    param([string]$Symbol)

    $normalized = $Symbol.Trim().ToUpperInvariant()
    if ($normalized -match "^(?<code>\d{6})\.(?<market>SH|SZ)$") {
        return "$($Matches.market)$($Matches.code)"
    }
    return $normalized
}

function Get-CurrentPowerShellExe {
    $path = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    if ($path -and (Test-Path $path -PathType Leaf)) {
        return $path
    }
    return "pwsh"
}

function Invoke-RuntimeStep {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Step $Name
    try {
        & $Action
        Write-Ok "$Name passed"
    }
    catch {
        Write-Fail "$Name failed: $_"
        throw
    }
}

function Invoke-ChildScript {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @(),
        [switch]$Required
    )

    if (-not (Test-Path $ScriptPath -PathType Leaf)) {
        if ($Required) {
            throw "Required script not found: $ScriptPath"
        }
        Write-Warn "Script not found, skipped: $ScriptPath"
        return
    }

    $shell = Get-CurrentPowerShellExe
    Write-Host "  $shell -NoProfile -File $ScriptPath $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $shell -NoProfile -File $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ScriptPath failed with exit code $LASTEXITCODE"
    }
}

function Get-MissingSourceSelfTestFiles {
    param(
        [string]$RootDir,
        [string]$SelfTestPath
    )

    $requiredFiles = @(
        (Join-Path $RootDir ".env.windows.example"),
        $SelfTestPath
    )
    $missing = @()
    foreach ($file in $requiredFiles) {
        if (-not (Test-Path $file -PathType Leaf)) {
            $missing += $file
        }
    }
    return $missing
}

function Get-TdxServiceLogPath {
    if ($ApplianceRoot) {
        return Join-Path $ApplianceRoot "datasource\logs\mist-tdx-datasource"
    }
    return Join-Path $DatasourceDir "logs\mist-tdx-datasource"
}

function Get-WindowsServiceState {
    param([string]$Name)

    if ([System.Environment]::OSVersion.Platform -ne "Win32NT") {
        return [pscustomobject]@{
            IsWindows = $false
            Exists = $false
            Status = "not-windows"
            Name = $Name
        }
    }

    $service = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $service) {
        return [pscustomobject]@{
            IsWindows = $true
            Exists = $false
            Status = "missing"
            Name = $Name
        }
    }

    return [pscustomobject]@{
        IsWindows = $true
        Exists = $true
        Status = [string]$service.Status
        Name = $Name
    }
}

function Write-TdxRuntimeDiagnostics {
    param([object]$ServiceState)

    $logPath = Get-TdxServiceLogPath
    if ($ServiceState.IsWindows) {
        if (-not $ServiceState.Exists) {
            Write-Warn "Windows service '$($ServiceState.Name)' was not found."
            Write-Warn "Install it with scripts\winsw\install-tdx-datasource.ps1 after TDX is logged in."
        }
        elseif ($ServiceState.Status -ne "Running") {
            Write-Warn "Windows service '$($ServiceState.Name)' status is $($ServiceState.Status), not Running."
            Write-Warn "Start it with: Start-Service -Name $($ServiceState.Name)"
        }
        else {
            Write-Warn "Windows service '$($ServiceState.Name)' is Running but $BaseUrl/health did not respond."
        }
    }
    else {
        Write-Warn "Skipping Windows service status check on this platform."
    }

    Write-Warn "Check TDX terminal login/connection and clear conflicting strategy entries before restarting."
    Write-Warn "Check datasource logs under: $logPath"
}

function Invoke-TdxHealthRequest {
    try {
        return Invoke-RestMethod -Method Get -Uri "$BaseUrl/health" -TimeoutSec $TimeoutSeconds
    }
    catch {
        $serviceState = Get-WindowsServiceState -Name $TdxServiceName
        Write-TdxRuntimeDiagnostics -ServiceState $serviceState
        throw "TDX datasource HTTP is not reachable at $BaseUrl/health. Original error: $_"
    }
}

function Assert-PropertyExists {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object -or -not ($Object.PSObject.Properties.Name -contains $Name)) {
        throw "Expected property '$Name' was not present."
    }
}

function Get-ObjectProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($property) {
        return $property.Value
    }
    return $null
}

function Get-NativeProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $expected = $Name.Replace("_", "").ToLowerInvariant()
    foreach ($property in $Object.PSObject.Properties) {
        $token = $property.Name.Replace("_", "").ToLowerInvariant()
        if ($token -eq $expected) {
            return $property.Value
        }
    }
    return $null
}

function Assert-EnvelopeOk {
    param(
        [object]$Envelope,
        [string]$Name
    )

    Assert-PropertyExists -Object $Envelope -Name "ok"
    if ($Envelope.ok -ne $true) {
        $errorText = ""
        if ($Envelope.PSObject.Properties.Name -contains "error") {
            $errorText = $Envelope.error | ConvertTo-Json -Compress -Depth 8
        }
        throw "$Name returned ok=false. $errorText"
    }
}

function Assert-ArrayNotEmpty {
    param(
        [object]$Value,
        [string]$Name
    )

    if ($null -eq $Value -or $Value.Count -lt 1) {
        throw "$Name must be a non-empty array."
    }
}

function Assert-NumericProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    Assert-PropertyExists -Object $Object -Name $Name
    $number = 0.0
    if (-not [double]::TryParse([string](Get-ObjectProperty -Object $Object -Name $Name), [ref]$number)) {
        throw "Expected property '$Name' to be numeric."
    }
}

function Get-RawMarketDataContainers {
    param(
        [object]$Result,
        [string]$Symbol
    )

    $fields = @("Open", "High", "Low", "Close", "Volume", "Amount")
    $containers = @()
    if ($null -ne $Result) {
        $containers += $Result
    }

    $value = Get-NativeProperty -Object $Result -Name "Value"
    if ($null -ne $value) {
        $containers += $value
    }

    # Raw get_market_data direct result shapes vary by TDX bridge version:
    # some wrap rows under Value, some under the symbol, and some return field tables directly.
    foreach ($container in @($containers)) {
        $symbolData = Get-ObjectProperty -Object $container -Name $Symbol
        if ($null -ne $symbolData) {
            $containers += $symbolData
            continue
        }

        if ($null -ne $container -and $container.PSObject.Properties.Count -gt 0) {
            $firstProperty = $container.PSObject.Properties[0]
            if ($fields -notcontains $firstProperty.Name) {
                $containers += $firstProperty.Value
            }
        }
    }

    return $containers
}

function Invoke-JsonPost {
    param(
        [string]$Uri,
        [hashtable]$Payload
    )

    $body = $Payload | ConvertTo-Json -Depth 12 -Compress
    return Invoke-RestMethod `
        -Method Post `
        -Uri $Uri `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec $TimeoutSeconds
}

function Assert-RawMarketDataResult {
    param(
        [object]$Result,
        [string]$Symbol
    )

    $containers = @(Get-RawMarketDataContainers -Result $Result -Symbol $Symbol)

    foreach ($field in @("Open", "High", "Low", "Close", "Volume", "Amount")) {
        $series = $null
        foreach ($container in $containers) {
            $candidate = Get-NativeProperty -Object $container -Name $field
            if ($null -ne $candidate) {
                $series = $candidate
                break
            }
        }
        if ($null -eq $series) {
            throw "Raw get_market_data result is missing field $field. Accepted shapes: Value wrapper, symbol wrapper, or Raw get_market_data direct result."
        }
        Assert-ArrayNotEmpty -Value $series -Name "Raw get_market_data field $field"
    }
}

function Assert-RawSnapshotResult {
    param([object]$Result)

    foreach ($field in @("Now", "LastClose", "Open", "Max", "Min", "Volume", "Amount", "ErrorId")) {
        $value = Get-NativeProperty -Object $Result -Name $field
        if ($null -eq $value) {
            throw "Raw get_market_snapshot result is missing $field."
        }
    }
}

function Test-HealthEndpoint {
    $health = Invoke-TdxHealthRequest
    foreach ($key in @("status", "instance", "adapter", "tdxHttpReachable", "tqInitialized", "collectorState")) {
        Assert-PropertyExists -Object $health -Name $key
    }
    if ($health.tqInitialized -ne $true) {
        throw "TDX service is not initialized."
    }
    if (($health.tdxHttpReachable -ne $true) -and (-not $AllowTdxHttpUnavailable)) {
        throw "TDX native HTTP is not reachable. Pass -AllowTdxHttpUnavailable to downgrade this check."
    }
}

function Test-BasicTdxSmoke {
    Test-HealthEndpoint

    $rawBars = Invoke-JsonPost `
        -Uri "$BaseUrl/v1/raw/tdx/call" `
        -Payload @{
            method = "get_market_data"
            params = @{
                stock_list = @($RawSymbol)
                period = $Period
                count = $Count
                dividend_type = "none"
            }
        }
    Assert-EnvelopeOk -Envelope $rawBars -Name "raw get_market_data"
    Assert-RawMarketDataResult -Result $rawBars.data.result -Symbol $RawSymbol

    $bars = Invoke-JsonPost `
        -Uri "$BaseUrl/v1/bars/query" `
        -Payload @{ symbols = @($Symbol); period = $Period; count = $Count }
    Assert-EnvelopeOk -Envelope $bars -Name "normalized bars query"
    Assert-ArrayNotEmpty -Value $bars.data.bars -Name "normalized bars"
    foreach ($field in @("open", "high", "low", "close", "volume", "amount")) {
        Assert-NumericProperty -Object $bars.data.bars[0] -Name $field
    }

    $rawSnapshot = Invoke-JsonPost `
        -Uri "$BaseUrl/v1/raw/tdx/call" `
        -Payload @{
            method = "get_market_snapshot"
            params = @{
                stock_code = $RawSymbol
                field_list = @()
            }
        }
    Assert-EnvelopeOk -Envelope $rawSnapshot -Name "raw get_market_snapshot"
    Assert-RawSnapshotResult -Result $rawSnapshot.data.result

    $snapshots = Invoke-JsonPost `
        -Uri "$BaseUrl/v1/snapshots/query" `
        -Payload @{ symbols = @($Symbol) }
    Assert-EnvelopeOk -Envelope $snapshots -Name "normalized snapshots query"
    Assert-ArrayNotEmpty -Value $snapshots.data.snapshots -Name "normalized snapshots"
    foreach ($field in @("last", "open", "high", "low", "lastClose", "volume", "amount", "asOf")) {
        Assert-PropertyExists -Object $snapshots.data.snapshots[0] -Name $field
    }

    $sectors = Invoke-JsonPost `
        -Uri "$BaseUrl/v1/sectors/query" `
        -Payload @{ sector = $Sector }
    Assert-EnvelopeOk -Envelope $sectors -Name "sector query"
    Assert-ArrayNotEmpty -Value $sectors.data.symbols -Name "sector symbols"
}

function Receive-WebSocketText {
    param(
        [System.Net.WebSockets.ClientWebSocket]$Socket,
        [int]$TimeoutSeconds = 15
    )

    $cts = [System.Threading.CancellationTokenSource]::new()
    $cts.CancelAfter([TimeSpan]::FromSeconds($TimeoutSeconds))
    $buffer = [byte[]]::new(4096)
    $builder = [System.Text.StringBuilder]::new()

    try {
        do {
            $segment = [System.ArraySegment[byte]]::new($buffer)
            $result = $Socket.ReceiveAsync($segment, $cts.Token).GetAwaiter().GetResult()
            if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                throw "WebSocket closed before the expected message was received."
            }
            if ($result.Count -gt 0) {
                [void]$builder.Append([System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count))
            }
        } while (-not $result.EndOfMessage)
    }
    finally {
        $cts.Dispose()
    }

    return $builder.ToString()
}

function Send-WebSocketJson {
    param(
        [System.Net.WebSockets.ClientWebSocket]$Socket,
        [hashtable]$Payload
    )

    $json = $Payload | ConvertTo-Json -Depth 12 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $segment = [System.ArraySegment[byte]]::new($bytes)
    [void]$Socket.SendAsync(
        $segment,
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        [System.Threading.CancellationToken]::None
    ).GetAwaiter().GetResult()
}

function Test-WebSocketSmoke {
    $socket = [System.Net.WebSockets.ClientWebSocket]::new()
    try {
        $connectCts = [System.Threading.CancellationTokenSource]::new()
        $connectCts.CancelAfter([TimeSpan]::FromSeconds($TimeoutSeconds))
        [void]$socket.ConnectAsync([Uri]$WsUrl, $connectCts.Token).GetAwaiter().GetResult()
        $connectCts.Dispose()

        $ready = Receive-WebSocketText -Socket $socket -TimeoutSeconds $TimeoutSeconds | ConvertFrom-Json
        if ($ready.type -ne "ready") {
            throw "Expected WebSocket ready message, got: $($ready | ConvertTo-Json -Compress -Depth 8)"
        }

        Send-WebSocketJson -Socket $socket -Payload @{
            "type" = "ping"
        }

        $pong = Receive-WebSocketText -Socket $socket -TimeoutSeconds $TimeoutSeconds | ConvertFrom-Json
        if ($pong.type -ne "pong") {
            throw "Expected WebSocket pong message, got: $($pong | ConvertTo-Json -Compress -Depth 8)"
        }

        if ($RequireLiveBar) {
            if (-not $AllowWebSocketSubscriptionChange) {
                throw "RequireLiveBar needs -AllowWebSocketSubscriptionChange because it changes TDX subscriptions. Do not use it while Mist backend owns the TDX subscription leader."
            }

            Send-WebSocketJson -Socket $socket -Payload @{
                "type" = "sync_subscriptions"
                "symbols" = @($Symbol)
            }

            $subscribed = Receive-WebSocketText -Socket $socket -TimeoutSeconds $TimeoutSeconds | ConvertFrom-Json
            if ($subscribed.type -ne "subscribed") {
                throw "Expected WebSocket subscribed message, got: $($subscribed | ConvertTo-Json -Compress -Depth 8)"
            }

            $deadline = (Get-Date).AddSeconds($LiveBarTimeoutSeconds)
            $barSeen = $false
            while ((Get-Date) -lt $deadline) {
                $remaining = [Math]::Max(1, [int]($deadline - (Get-Date)).TotalSeconds)
                $message = Receive-WebSocketText -Socket $socket -TimeoutSeconds $remaining | ConvertFrom-Json
                if ($message.type -eq "bar") {
                    $barSeen = $true
                    break
                }
            }
            if (-not $barSeen) {
                throw "No live bar event arrived within $LiveBarTimeoutSeconds seconds."
            }

            Send-WebSocketJson -Socket $socket -Payload @{
                "type" = "unsubscribe"
                "stocks" = @($Symbol)
            }

            $unsubscribed = Receive-WebSocketText -Socket $socket -TimeoutSeconds $TimeoutSeconds | ConvertFrom-Json
            if ($unsubscribed.type -ne "unsubscribed") {
                throw "Expected WebSocket unsubscribed message, got: $($unsubscribed | ConvertTo-Json -Compress -Depth 8)"
            }
        }
    }
    finally {
        if ($socket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            [void]$socket.CloseAsync(
                [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
                "runtime checks complete",
                [System.Threading.CancellationToken]::None
            ).GetAwaiter().GetResult()
        }
        $socket.Dispose()
    }
}

if (-not $RawSymbol) {
    $RawSymbol = ConvertTo-TdxNativeSymbol -Symbol $Symbol
}

Write-Host "Mist datasource runtime checks" -ForegroundColor Cyan
Write-Host "  DatasourceDir: $DatasourceDir"
Write-Host "  ApplianceRoot: $ApplianceRoot"
Write-Host "  BaseUrl:       $BaseUrl"
Write-Host "  WsUrl:         $WsUrl"
Write-Host "  Symbol:        $Symbol"
Write-Host "  RawSymbol:     $RawSymbol"
Write-Host "  Sector:        $Sector"

$selfTestScript = Join-Path $DatasourceDir "scripts\test_windows_scripts.ps1"
$preflightScript = Join-Path $DatasourceDir "scripts\preflight-sdk.ps1"
$deployScript = Join-Path $DatasourceDir "scripts\deploy_windows.ps1"
$winswProbeScript = Join-Path $DatasourceDir "scripts\winsw\test-tdx-datasource.ps1"
$applianceHealthScript = if ($ApplianceRoot) { Join-Path $ApplianceRoot "health-check.ps1" } else { "" }

try {
    if (-not $SkipScriptSelfTest) {
        $missingSourceSelfTestFiles = @(Get-MissingSourceSelfTestFiles -RootDir $DatasourceDir -SelfTestPath $selfTestScript)
        if ($missingSourceSelfTestFiles.Count -eq 0) {
            Invoke-RuntimeStep "Datasource script self-test" {
                Invoke-ChildScript -ScriptPath $selfTestScript -Required
            }
        }
        elseif ($RequireScriptSelfTest) {
            throw "Datasource script self-test requires source-tree files that are missing from this runtime package: $($missingSourceSelfTestFiles -join ', ')"
        }
        else {
            Write-Step "Datasource script self-test"
            Write-Warn "Skipped source-tree self-test because this runtime package is missing: $($missingSourceSelfTestFiles -join ', ')"
            Write-Warn "Pass -RequireScriptSelfTest to fail instead."
        }
    }

    if (-not $SkipSdkPreflight) {
        Invoke-RuntimeStep "Datasource SDK preflight" {
            Invoke-ChildScript -ScriptPath $preflightScript -Arguments @("-EnvFile", $EnvFile) -Required
        }
    }

    if ($RunDatasourceInstall) {
        Invoke-RuntimeStep "Datasource install check" {
            Invoke-ChildScript -ScriptPath $deployScript -Arguments @("-Only", "install") -Required
        }
    }

    if ($RunDatasourceStartupTest) {
        Invoke-RuntimeStep "Datasource temporary startup check" {
            Invoke-ChildScript -ScriptPath $deployScript -Arguments @("-Only", "test") -Required
        }
    }

    if (-not $SkipWinSWProbe) {
        Invoke-RuntimeStep "TDX WinSW runtime probe" {
            [void](Invoke-TdxHealthRequest)
            Invoke-ChildScript `
                -ScriptPath $winswProbeScript `
                -Arguments @("-BaseUrl", $BaseUrl, "-WsUrl", $WsUrl, "-Symbol", $Symbol) `
                -Required
        }
    }

    if (-not $SkipApplianceHealth) {
        Invoke-RuntimeStep "Appliance health check" {
            if (-not $applianceHealthScript) {
                Write-Warn "Appliance root was not resolved; appliance health check skipped."
                return
            }
            $healthArgs = @()
            if (-not $SkipMySQL) {
                $healthArgs += "-IncludeMySQL"
            }
            Invoke-ChildScript -ScriptPath $applianceHealthScript -Arguments $healthArgs
        }
    }

    if (-not $SkipSmoke) {
        Invoke-RuntimeStep "TDX basic HTTP smoke" {
            Test-BasicTdxSmoke
        }
    }

    if (-not $SkipWebSocket) {
        Invoke-RuntimeStep "TDX WebSocket smoke" {
            Test-WebSocketSmoke
        }
    }
}
catch {
    Write-Fail "Runtime checks failed."
    exit 1
}

Write-Host ""
Write-Host "All selected runtime checks passed." -ForegroundColor Green
