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

$nssmDir = Join-Path $ProjectDir "..\nssm"
New-Item -ItemType Directory -Force -Path $nssmDir | Out-Null
$nssmFile = Join-Path $nssmDir "nssm.exe"
if (-not (Test-Path $nssmFile -PathType Leaf)) {
    Set-Content -Path $nssmFile -Value "test nssm" -Encoding UTF8
}
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
Assert-Match "deploy script logs uv sync output" $deployWindows "uv-sync.log"
Assert-Match "deploy script prints uv sync failure tail" $deployWindows "Recent uv sync output"
if ($deployWindows -match [regex]::Escape('2>$null | Out-Null')) {
    throw "deploy script must not hide uv sync stderr/stdout."
}
Write-Host "  [PASS] deploy script keeps uv sync output visible" -ForegroundColor Green

Assert-Equal `
    "blank env returns empty string" `
    "" `
    (Get-EnvValue "APP_ENV=production" "QMT_SDK_PATH")

Assert-Equal `
    "nssm fallback resolves packaged path" `
    (Resolve-FullPath (Join-Path $ProjectDir "..\nssm\nssm.exe")) `
    (Resolve-NssmExe -ProjectDir $ProjectDir -PreferPathLookup:$false)
Assert-Equal `
    "uv fallback resolves packaged runtime" `
    (Resolve-FullPath (Join-Path $uvTestProjectDir "runtime\uv.exe")) `
    (Resolve-UvExe -ProjectDir $uvTestProjectDir -PreferPathLookup:$false)

. "$PSScriptRoot\service-common.ps1"

$tdxDefinition = New-DatasourceServiceDefinition `
    -Instance tdx `
    -ProjectDir $ProjectDir `
    -LogsDir (Join-Path $ProjectDir "logs")

Assert-Equal "tdx service name" "MistTDX" $tdxDefinition.ServiceName
Assert-Match "tdx runner args" $tdxDefinition.Parameters "service-runner.ps1"
Assert-Match "tdx runner instance" $tdxDefinition.Parameters "-Instance tdx"
Assert-Equal `
    "tdx stdout log" `
    (Join-Path $ProjectDir "logs\tdx-stdout.log") `
    $tdxDefinition.Stdout

. "$PSScriptRoot\service-runner.ps1" -LoadOnly

$statePath = Join-Path $TestRoot "service-runner-tdx-state.json"
Add-CrashRecord `
    -StateFile $statePath `
    -Now ([datetime]"2026-06-22T10:00:00Z") `
    -WindowMinutes 10
Add-CrashRecord `
    -StateFile $statePath `
    -Now ([datetime]"2026-06-22T10:01:00Z") `
    -WindowMinutes 10
Assert-Equal `
    "crash count is retained" `
    2 `
    (Get-CrashCount -StateFile $statePath -Now ([datetime]"2026-06-22T10:02:00Z") -WindowMinutes 10)
Clear-CrashState -StateFile $statePath
Assert-Equal `
    "crash state clears" `
    0 `
    (Get-CrashCount -StateFile $statePath -Now ([datetime]"2026-06-22T10:03:00Z") -WindowMinutes 10)

if (Test-Path $TestRoot) {
    Remove-Item $TestRoot -Recurse -Force
}

Write-Host "`nWindows script tests passed." -ForegroundColor Green
