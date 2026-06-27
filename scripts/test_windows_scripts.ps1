param(
    [string]$ProjectDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectDir) {
    $ProjectDir = $PSScriptRoot | Split-Path -Parent
}
$ProjectDir = [System.IO.Path]::GetFullPath($ProjectDir)
$TestRoot = Join-Path $ProjectDir ".test-windows-scripts"

function Assert-Equal {
    param(
        [string]$Name,
        $Expected,
        $Actual
    )

    if ($Expected -ne $Actual) {
        throw "$Name failed. Expected: <$Expected>. Actual: <$Actual>."
    }
    Write-Host "  [PASS] $Name" -ForegroundColor Green
}

function Assert-Match {
    param(
        [string]$Name,
        [string]$Actual,
        [string]$Pattern
    )

    if ($Actual -notmatch [regex]::Escape($Pattern)) {
        throw "$Name failed. Expected pattern: <$Pattern>. Actual: <$Actual>."
    }
    Write-Host "  [PASS] $Name" -ForegroundColor Green
}

if (Test-Path $TestRoot) {
    Remove-Item $TestRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $TestRoot | Out-Null

$uvTestProjectDir = Join-Path $TestRoot "uv-project"
$uvRuntimeDir = Join-Path $uvTestProjectDir "runtime"
New-Item -ItemType Directory -Force -Path $uvRuntimeDir | Out-Null
$uvRuntimeFile = Join-Path $uvRuntimeDir "uv.exe"
if (-not (Test-Path $uvRuntimeFile -PathType Leaf)) {
    Set-Content -Path $uvRuntimeFile -Value "test uv" -Encoding UTF8
}

. "$PSScriptRoot\windows-common.ps1"

Assert-Equal `
    "env parsing trims quotes" `
    "F:/quant/tdx/PYPlugins/user" `
    (Get-EnvValue "TDX_SDK_PATH=`"F:/quant/tdx/PYPlugins/user`"" "TDX_SDK_PATH")

$windowsEnvExample = Get-Content (Join-Path $ProjectDir ".env.windows.example") -Raw
$deployWindows = Get-Content (Join-Path $ProjectDir "scripts\deploy_windows.ps1") -Raw
$runtimeChecks = Get-Content (Join-Path $ProjectDir "scripts\run-runtime-checks.ps1") -Raw
$tdxWinswInstall = Get-Content (Join-Path $ProjectDir "scripts\winsw\install-tdx-datasource.ps1") -Raw
Assert-Match "default TDX SDK path" $windowsEnvExample "TDX_SDK_PATH=F:/quant/tdx/PYPlugins/user"
Assert-Match "default QMT path" $windowsEnvExample "QMT_PATH=F:/quant/qmt"
Assert-Match "TDX comment points SDK path to user directory" $windowsEnvExample "TDX_SDK_PATH points to the user directory that contains tqcenter.py."
Assert-Match "TDX comment keeps DLL in parent directory" $windowsEnvExample "TPythClient.dll stays one level above TDX_SDK_PATH."
Assert-Match "default uv python package index" $windowsEnvExample "UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
Assert-Match "default uv python version" $windowsEnvExample "UV_PYTHON=3.12"
Assert-Match "deploy script checks python launcher" $deployWindows "Get-Command py"
Assert-Match "deploy script lets uv handle missing python" $deployWindows "uv sync will create/find Python 3.12"
Assert-Match "deploy script configures uv default index" $deployWindows "--default-index"
Assert-Match "deploy script defaults to Tsinghua python package index" $deployWindows "https://pypi.tuna.tsinghua.edu.cn/simple"
Assert-Match "deploy script pins uv sync python" $deployWindows "--python"
Assert-Match "deploy script defaults to Python 3.12" $deployWindows 'if (-not $uvPython) { $uvPython = "3.12" }'
Assert-Match "deploy script syncs from frozen lockfile" $deployWindows "--frozen"
Assert-Match "deploy script no longer supports service-only step" $deployWindows "Use: install, test"
Assert-Match "deploy script documents no service registration" $deployWindows "不再注册 Windows 服务"
if ($deployWindows -match [regex]::Escape('--locked')) {
    throw "deploy script must use --frozen, not --locked, during appliance installs."
}
Write-Host "  [PASS] deploy script avoids lockfile freshness checks" -ForegroundColor Green
Assert-Match "deploy script logs uv sync output" $deployWindows "uv-sync.log"
Assert-Match "deploy script prints uv sync failure tail" $deployWindows "Recent uv sync output"
if ($deployWindows -match [regex]::Escape('Step 5/5')) {
    throw "deploy script must not include a service registration step."
}
Write-Host "  [PASS] deploy script has no service registration step" -ForegroundColor Green
if ($deployWindows -match [regex]::Escape('nssm status MistTDX / MistQMT')) {
    throw "deploy script must not print NSSM commands in appliance install completion guidance."
}
Write-Host "  [PASS] deploy script avoids NSSM completion guidance" -ForegroundColor Green
if ($deployWindows -match [regex]::Escape('2>$null | Out-Null')) {
    throw "deploy script must not hide uv sync stderr/stdout."
}
Write-Host "  [PASS] deploy script keeps uv sync output visible" -ForegroundColor Green
Assert-Match "TDX WinSW installer accepts started-successfully output" $tdxWinswInstall "started successfully"
Assert-Match "TDX WinSW installer clears native exit code after success" $tdxWinswInstall '$global:LASTEXITCODE = 0'
Assert-Match "TDX WinSW installer resolves packaged uv" $tdxWinswInstall "Resolve-UvExe"
Assert-Match "TDX WinSW installer default executable can be resolved" $tdxWinswInstall 'if (-not $Executable)'
if ($tdxWinswInstall -match [regex]::Escape('("refresh")')) {
    throw "TDX WinSW installer must not call refresh; older bundled WinSW builds do not support it."
}
Write-Host "  [PASS] TDX WinSW installer avoids unsupported refresh command" -ForegroundColor Green
Assert-Match "runtime checks run script self-test" $runtimeChecks "scripts\test_windows_scripts.ps1"
Assert-Match "runtime checks can require source self-test" $runtimeChecks "RequireScriptSelfTest"
Assert-Match "runtime checks knows source-only env example" $runtimeChecks ".env.windows.example"
Assert-Match "runtime checks run SDK preflight" $runtimeChecks "scripts\preflight-sdk.ps1"
Assert-Match "runtime checks can run datasource deploy install" $runtimeChecks "-Only install"
Assert-Match "runtime checks can run datasource deploy test" $runtimeChecks "-Only test"
Assert-Match "runtime checks run WinSW service probe" $runtimeChecks "scripts\winsw\test-tdx-datasource.ps1"
Assert-Match "runtime checks checks TDX service status" $runtimeChecks "mist-tdx-datasource"
Assert-Match "runtime checks points to TDX service logs" $runtimeChecks "logs\mist-tdx-datasource"
Assert-Match "runtime checks run appliance health check" $runtimeChecks "health-check.ps1"
Assert-Match "runtime checks query normalized bars" $runtimeChecks "/v1/bars/query"
Assert-Match "runtime checks query normalized snapshots" $runtimeChecks "/v1/snapshots/query"
Assert-Match "runtime checks query sectors" $runtimeChecks "/v1/sectors/query"
Assert-Match "runtime checks verify raw TDX market data" $runtimeChecks "get_market_data"
Assert-Match "runtime checks verify raw TDX snapshot" $runtimeChecks "get_market_snapshot"
Assert-Match "runtime checks support optional live bar wait" $runtimeChecks "RequireLiveBar"
Assert-Match "runtime checks unsubscribe after websocket smoke" $runtimeChecks '"type" = "unsubscribe"'

Assert-Equal `
    "blank env returns empty string" `
    "" `
    (Get-EnvValue "APP_ENV=production" "QMT_SDK_PATH")

Assert-Equal `
    "uv fallback resolves packaged runtime" `
    (Resolve-FullPath (Join-Path $uvTestProjectDir "runtime\uv.exe")) `
    (Resolve-UvExe -ProjectDir $uvTestProjectDir -PreferPathLookup:$false)
if (Test-Path $TestRoot) {
    Remove-Item $TestRoot -Recurse -Force
}

Write-Host "`nWindows script tests passed." -ForegroundColor Green
