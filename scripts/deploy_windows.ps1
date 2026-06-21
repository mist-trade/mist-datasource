# mist-datasource Windows 部署脚本
# 用法: 以管理员身份打开 PowerShell, 然后:
#   cd D:\mist-datasource
#   .\scripts\deploy_windows.ps1
#
# 也可只运行特定步骤:
#   .\scripts\deploy_windows.ps1 -SkipService      # 只测试, 不注册服务
#   .\scripts\deploy_windows.ps1 -Only install     # 只运行 install 步骤
#   .\scripts\deploy_windows.ps1 -Only test        # 只运行 test 步骤
#   .\scripts\deploy_windows.ps1 -Only service     # 只注册服务

param(
    [switch]$SkipService,
    [string]$Only = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot | Split-Path -Parent
$LogsDir = Join-Path $ProjectDir "logs"

function Write-Step($msg) { Write-Host "`n===== $msg =====" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

function Get-EnvValue($content, $name) {
    $pattern = "(?m)^\s*$([regex]::Escape($name))\s*=\s*(.*?)\s*(?:#.*)?$"
    $match = [regex]::Match($content, $pattern)
    if (-not $match.Success) { return "" }
    return $match.Groups[1].Value.Trim().Trim('"').Trim("'")
}

function Resolve-NssmExe {
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        (Join-Path $ProjectDir "..\nssm\nssm.exe"),
        (Join-Path $ProjectDir "nssm\nssm.exe")
    )
    foreach ($candidate in $candidates) {
        $resolved = [System.IO.Path]::GetFullPath($candidate)
        if (Test-Path $resolved -PathType Leaf) { return $resolved }
    }
    return $null
}

# ---- 前置检查 ----
if ($Only -and $Only -notin @("install", "test", "service")) {
    Write-Fail "Unknown step: $Only. Use: install, test, service"
    exit 1
}

# ============================================
# Step 1: 环境检查
# ============================================
if (-not $Only -or $Only -eq "install") {
    Write-Step "Step 1/5: 环境检查"

    # 检查 Python
    $pythonExe = $null
    try { $pythonExe = (Get-Command python -ErrorAction Stop).Source } catch {}
    if (-not $pythonExe) {
        try { $pythonExe = (Get-Command python3 -ErrorAction Stop).Source } catch {}
    }
    if (-not $pythonExe) {
        Write-Fail "Python 未安装。请安装 Python 3.12+ 并加入 PATH"
        exit 1
    }
    $pyVer = & $pythonExe --version 2>&1
    Write-Ok "Python: $pyVer ($pythonExe)"

    # 检查 uv
    $uvExe = $null
    try { $uvExe = (Get-Command uv -ErrorAction Stop).Source } catch {}
    if (-not $uvExe) {
        Write-Fail "uv 未安装。运行: powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`""
        exit 1
    }
    $uvVer = & $uvExe --version 2>&1
    Write-Ok "uv: $uvVer ($uvExe)"

    # 检查 .env
    $envFile = Join-Path $ProjectDir ".env"
    if (-not (Test-Path $envFile)) {
        Write-Host "  .env 不存在, 从 .env.example 复制..." -ForegroundColor Yellow
        Copy-Item (Join-Path $ProjectDir ".env.example") $envFile
        Write-Host "  请编辑 .env 填写配置后重新运行此脚本" -ForegroundColor Yellow
        Write-Host "  必填项: APP_ENV=production, TDX_SDK_PATH=..." -ForegroundColor Yellow
        notepad $envFile
        exit 0
    }
    Write-Ok ".env 已存在"

    # 检查 .env 中的关键配置
    $envContent = Get-Content $envFile -Raw
    $appEnv = Get-EnvValue $envContent "APP_ENV"
    if ($appEnv -eq "production") {
        Write-Ok "APP_ENV=production (生产模式)"

        $preflight = Join-Path $PSScriptRoot "preflight-sdk.ps1"
        if (Test-Path $preflight -PathType Leaf) {
            & $preflight -EnvFile $envFile
        } else {
            Write-Warn "preflight-sdk.ps1 未找到, 跳过 SDK 布局检查"
        }
    } else {
        Write-Host "  [INFO] APP_ENV=$appEnv (开发模式, 使用 mock adapter)" -ForegroundColor Yellow
    }

    # 检查 NSSM (仅注册服务时需要)
    if ((-not $SkipService) -and (-not $Only -or $Only -eq "service")) {
        $nssmExe = Resolve-NssmExe
        if (-not $nssmExe) {
            Write-Fail "NSSM 未安装。请下载 nssm.cc 并加入 PATH"
            Write-Host "  下载地址: https://nssm.cc/download" -ForegroundColor Yellow
            Write-Host "  或用 -SkipService 跳过服务注册" -ForegroundColor Yellow
            exit 1
        }
        Write-Ok "NSSM: $nssmExe"
    }
}

# ============================================
# Step 2: 安装依赖
# ============================================
if (-not $Only -or $Only -eq "install") {
    Write-Step "Step 2/5: 安装依赖 (uv sync)"

    Push-Location $ProjectDir
    try {
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        # 所有依赖都在主依赖列表中, 不需要 extra 参数
        $lockFile = Join-Path $ProjectDir "uv.lock"
        $syncArgs = if (Test-Path $lockFile -PathType Leaf) { @("sync", "--locked") } else { @("sync") }
        & uv @syncArgs 2>$null | Out-Null
        $syncExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEAP
        if ($syncExit -ne 0) { throw "uv sync failed (exit code $syncExit)" }
        Write-Ok "uv sync 完成"

        # 检查 venv 是否创建
        $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
        if (-not (Test-Path $venvPython)) {
            Write-Fail ".venv 未创建, uv sync 可能失败了"
            exit 1
        }
        Write-Ok "venv Python: $venvPython"

        # 验证关键包
        & $venvPython -c "import fastapi; print(f'  fastapi {fastapi.__version__}')" 2>&1
        & $venvPython -c "import uvicorn; print(f'  uvicorn {uvicorn.__version__}')" 2>&1
    }
    finally {
        Pop-Location
    }
}

# ============================================
# Step 3: 测试启动
# ============================================
if (-not $Only -or $Only -eq "test") {
    Write-Step "Step 3/5: 测试 TDX 实例启动"

    $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

    # 创建日志目录
    if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir | Out-Null }

    # 读取 .env (确保 $envContent 可用)
    if (-not $envContent) { $envContent = Get-Content (Join-Path $ProjectDir ".env") -Raw }

    # 启动 TDX 实例
    $tdxTestLog = Join-Path $LogsDir "deploy-test-tdx.log"
    $tdxTestErr = Join-Path $LogsDir "deploy-test-tdx-err.log"
    Write-Host "  启动 TDX 实例 (临时, 仅测试)..."
    $proc = Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "uvicorn", "tdx.main:app", "--host", "127.0.0.1", "--port", "9001" `
        -WorkingDirectory $ProjectDir `
        -RedirectStandardOutput $tdxTestLog `
        -RedirectStandardError $tdxTestErr `
        -PassThru -NoNewWindow

    # 等待启动, 最多重试 5 次 (SDK 加载 DLL 可能较慢)
    $tdxOk = $false
    Start-Sleep -Seconds 3
    if ($proc.HasExited) {
        Write-Fail "TDX 实例启动后立即退出 (exit code: $($proc.ExitCode))"
        Get-Content $tdxTestErr -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
    } else {
        for ($i = 1; $i -le 5; $i++) {
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:9001/health" -TimeoutSec 5 -UseBasicParsing
                $body = $resp.Content | ConvertFrom-Json
                Write-Ok "TDX health: status=$($body.status), adapter=$($body.adapter)"
                $tdxOk = $true
                break
            } catch {
                if ($i -lt 5) {
                    Write-Host "  等待 TDX 启动... ($i/5)" -ForegroundColor Yellow
                    Start-Sleep -Seconds 3
                } else {
                    Write-Fail "TDX health 接口无响应 (已重试 5 次)"
                    Get-Content $tdxTestErr -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
                    Get-Content $tdxTestLog -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
                }
            }
        }
        if (-not $proc.HasExited) {
            $proc.Kill()
            $proc.WaitForExit(5000)
        }
    }

    if (-not $tdxOk) {
        Write-Host "`n  TDX 测试失败! 请检查上面的错误信息。" -ForegroundColor Red
        Write-Host "  常见问题:" -ForegroundColor Yellow
        Write-Host "    1. APP_ENV=development -> 检查 mock adapter 是否正常" -ForegroundColor Yellow
        Write-Host "    2. APP_ENV=production -> 检查 TDX_SDK_PATH 是否正确, 通达信终端是否已登录" -ForegroundColor Yellow
        Write-Host "    3. 端口 9001 被占用 -> 关闭占用进程" -ForegroundColor Yellow
        if (-not $Only) {
            Write-Host "`n  是否继续注册服务? (Y/N)" -ForegroundColor Yellow
            $cont = Read-Host
            if ($cont -ne "Y") { exit 1 }
        }
    }

    # 测试 QMT 实例 (仅在配置了 QMT_SDK_PATH 时)
    Write-Step "Step 4/5: 测试 QMT 实例启动"

    $qmtSdk = Get-EnvValue $envContent "QMT_SDK_PATH"
    if (-not $qmtSdk -or $qmtSdk -eq "") {
        Write-Host "  跳过 QMT 测试 (QMT_SDK_PATH 未配置)" -ForegroundColor Yellow
    } else {
        $qmtTestLog = Join-Path $LogsDir "deploy-test-qmt.log"
        $qmtTestErr = Join-Path $LogsDir "deploy-test-qmt-err.log"
        Write-Host "  启动 QMT 实例 (临时, 仅测试)..."
        $qmtProc = Start-Process -FilePath $venvPython `
            -ArgumentList "-m", "uvicorn", "qmt.main:app", "--host", "127.0.0.1", "--port", "9002" `
            -WorkingDirectory $ProjectDir `
            -RedirectStandardOutput $qmtTestLog `
            -RedirectStandardError $qmtTestErr `
            -PassThru -NoNewWindow

        Start-Sleep -Seconds 3

        if ($qmtProc.HasExited) {
            Write-Fail "QMT 实例启动后立即退出 (exit code: $($qmtProc.ExitCode))"
            Get-Content $qmtTestErr -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
        } else {
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:9002/health" -TimeoutSec 5 -UseBasicParsing
                $body = $resp.Content | ConvertFrom-Json
                Write-Ok "QMT health: status=$($body.status), adapter=$($body.adapter)"
            } catch {
                Write-Fail "QMT health 接口无响应: $_"
                Get-Content $qmtTestErr -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
            }
            $qmtProc.Kill()
            $qmtProc.WaitForExit(5000)
        }
    }
}

# ============================================
# Step 5: 注册 NSSM 服务
# ============================================
if ((-not $SkipService) -and (-not $Only -or $Only -eq "service")) {
    Write-Step "Step 5/5: 注册 NSSM 服务"

    $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    $envFile = Join-Path $ProjectDir ".env"
    if (-not (Test-Path $envFile -PathType Leaf)) {
        Write-Fail ".env 不存在, 无法注册服务"
        exit 1
    }
    $envContent = Get-Content $envFile -Raw
    $qmtSdk = Get-EnvValue $envContent "QMT_SDK_PATH"
    $qmtEnabled = $qmtSdk -and $qmtSdk -ne ""
    $nssmExe = Resolve-NssmExe
    if (-not $nssmExe) {
        Write-Fail "NSSM 未安装, 且未在部署包中找到 nssm\nssm.exe"
        Write-Host "  可将 nssm.exe 放到部署包的 nssm 目录, 或加入 PATH" -ForegroundColor Yellow
        exit 1
    }
    Write-Ok "NSSM: $nssmExe"

    # --- TDX 服务 ---
    $tdxService = "MistTDX"
    $prevEAP2 = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $existing = & $nssmExe status $tdxService 2>&1
    $ErrorActionPreference = $prevEAP2
    if ($existing -match "SERVICE_RUNNING|SERVICE_STOPPED") {
        Write-Host "  $tdxService 已存在 (状态: $existing), 跳过注册" -ForegroundColor Yellow
    } else {
        & $nssmExe install $tdxService $venvPython "-m uvicorn tdx.main:app --host 127.0.0.1 --port 9001"
        & $nssmExe set $tdxService AppDirectory $ProjectDir
        & $nssmExe set $tdxService DisplayName "Mist TDX DataSource"
        & $nssmExe set $tdxService Description "通达信数据源 HTTP/WS 服务 (port 9001)"
        & $nssmExe set $tdxService Start SERVICE_AUTO_START
        & $nssmExe set $tdxService AppStdout (Join-Path $LogsDir "tdx-stdout.log")
        & $nssmExe set $tdxService AppStderr (Join-Path $LogsDir "tdx-stderr.log")
        & $nssmExe set $tdxService AppRotateFiles 1
        & $nssmExe set $tdxService AppRotateBytes 10485760
        Write-Ok "$tdxService 服务已注册"
    }

    # --- QMT 服务 ---
    $qmtService = "MistQMT"
    if (-not $qmtEnabled) {
        Write-Warn "QMT_SDK_PATH 未配置, 跳过 MistQMT 服务注册"
    } else {
        $prevEAP3 = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $existing = & $nssmExe status $qmtService 2>&1
        $ErrorActionPreference = $prevEAP3
        if ($existing -match "SERVICE_RUNNING|SERVICE_STOPPED") {
            Write-Host "  $qmtService 已存在 (状态: $existing), 跳过注册" -ForegroundColor Yellow
        } else {
            & $nssmExe install $qmtService $venvPython "-m uvicorn qmt.main:app --host 127.0.0.1 --port 9002"
            & $nssmExe set $qmtService AppDirectory $ProjectDir
            & $nssmExe set $qmtService DisplayName "Mist QMT DataSource"
            & $nssmExe set $qmtService Description "QMT 数据源 HTTP/WS 服务 (port 9002)"
            & $nssmExe set $qmtService Start SERVICE_AUTO_START
            & $nssmExe set $qmtService AppStdout (Join-Path $LogsDir "qmt-stdout.log")
            & $nssmExe set $qmtService AppStderr (Join-Path $LogsDir "qmt-stderr.log")
            & $nssmExe set $qmtService AppRotateFiles 1
            & $nssmExe set $qmtService AppRotateBytes 10485760
            Write-Ok "$qmtService 服务已注册"
        }
    }

    # 启动服务
    Write-Host "`n  启动服务..." -ForegroundColor Cyan
    & $nssmExe start $tdxService
    if ($qmtEnabled) { & $nssmExe start $qmtService }

    Start-Sleep -Seconds 3

    # 最终验证
    Write-Host "`n  最终验证:" -ForegroundColor Cyan
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:9001/health" -TimeoutSec 5 -UseBasicParsing
        $body = $resp.Content | ConvertFrom-Json
        Write-Ok "TDX: status=$($body.status), adapter=$($body.adapter)"
    } catch {
        Write-Fail "TDX 服务启动失败"
    }
    if ($qmtEnabled) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:9002/health" -TimeoutSec 5 -UseBasicParsing
            $body = $resp.Content | ConvertFrom-Json
            Write-Ok "QMT: status=$($body.status), adapter=$($body.adapter)"
        } catch {
            Write-Fail "QMT 服务启动失败"
        }
    } else {
        Write-Warn "QMT 未配置, 已跳过最终验证"
    }
}

Write-Host "`n===== 部署完成 =====" -ForegroundColor Green
Write-Host "  日志目录: $LogsDir"
Write-Host "  管理命令:"
Write-Host "    nssm status MistTDX / MistQMT          # 查看状态"
Write-Host "    nssm restart MistTDX / MistQMT          # 重启服务"
Write-Host "    nssm stop MistTDX / MistQMT             # 停止服务"
Write-Host "    nssm remove MistTDX / MistQMT           # 删除服务"
