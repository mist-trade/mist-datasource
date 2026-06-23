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

. "$PSScriptRoot\windows-common.ps1"

Assert-Equal `
    "env parsing trims quotes" `
    "F:/quant/tdx/PYPlugins/user" `
    (Get-EnvValue "TDX_SDK_PATH=`"F:/quant/tdx/PYPlugins/user`"" "TDX_SDK_PATH")

$windowsEnvExample = Get-Content (Join-Path $ProjectDir ".env.windows.example") -Raw
Assert-Match "default TDX SDK path" $windowsEnvExample "TDX_SDK_PATH=F:/quant/tdx/PYPlugins/user"
Assert-Match "default QMT path" $windowsEnvExample "QMT_PATH=F:/quant/qmt"
Assert-Match "TDX comment points SDK path to user directory" $windowsEnvExample "TDX_SDK_PATH points to the user directory that contains tqcenter.py."
Assert-Match "TDX comment keeps DLL in parent directory" $windowsEnvExample "TPythClient.dll stays one level above TDX_SDK_PATH."

Assert-Equal `
    "blank env returns empty string" `
    "" `
    (Get-EnvValue "APP_ENV=production" "QMT_SDK_PATH")

Assert-Equal `
    "nssm fallback resolves packaged path" `
    (Resolve-FullPath (Join-Path $ProjectDir "..\nssm\nssm.exe")) `
    (Resolve-NssmExe -ProjectDir $ProjectDir -PreferPathLookup:$false)

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

Write-Host "`nWindows script tests passed." -ForegroundColor Green
