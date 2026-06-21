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

. "$PSScriptRoot\windows-common.ps1"
. "$PSScriptRoot\service-common.ps1"

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
        $tdxOk = Wait-HttpHealth `
            -Name "TDX" `
            -Url "http://127.0.0.1:9001/health" `
            -Attempts 5 `
            -DelaySeconds 3 `
            -TimeoutSeconds 5
        if (-not $tdxOk) {
            Get-Content $tdxTestErr -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
            Get-Content $tdxTestLog -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
        }
        if (-not $proc.HasExited) {
            Stop-ProcessTreeBestEffort -Process $proc
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
            $qmtOk = Wait-HttpHealth `
                -Name "QMT" `
                -Url "http://127.0.0.1:9002/health" `
                -Attempts 5 `
                -DelaySeconds 3 `
                -TimeoutSeconds 5
            if (-not $qmtOk) {
                Get-Content $qmtTestErr -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
            }
            Stop-ProcessTreeBestEffort -Process $qmtProc
        }
    }
}

# ============================================
# Step 5: 注册 NSSM 服务
# ============================================
if ((-not $SkipService) -and (-not $Only -or $Only -eq "service")) {
    Write-Step "Step 5/5: 注册 NSSM 服务"

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
    $tdxDefinition = New-DatasourceServiceDefinition `
        -Instance tdx `
        -ProjectDir $ProjectDir `
        -LogsDir $LogsDir
    Ensure-DatasourceNssmService -NssmExe $nssmExe -Definition $tdxDefinition

    # --- QMT 服务 ---
    if (-not $qmtEnabled) {
        Write-Warn "QMT_SDK_PATH 未配置, 跳过 MistQMT 服务注册"
    } else {
        $qmtDefinition = New-DatasourceServiceDefinition `
            -Instance qmt `
            -ProjectDir $ProjectDir `
            -LogsDir $LogsDir
        Ensure-DatasourceNssmService -NssmExe $nssmExe -Definition $qmtDefinition
    }

    # 启动服务
    Write-Host "`n  启动服务..." -ForegroundColor Cyan
    Start-DatasourceNssmService -NssmExe $nssmExe -ServiceName $tdxDefinition.ServiceName
    if ($qmtEnabled) {
        Start-DatasourceNssmService -NssmExe $nssmExe -ServiceName $qmtDefinition.ServiceName
    }

    Start-Sleep -Seconds 3

    # 最终验证
    Write-Host "`n  最终验证:" -ForegroundColor Cyan
    Wait-HttpHealth -Name "TDX" -Url "http://127.0.0.1:9001/health" -Attempts 1 -TimeoutSeconds 5 | Out-Null
    if ($qmtEnabled) {
        Wait-HttpHealth -Name "QMT" -Url "http://127.0.0.1:9002/health" -Attempts 1 -TimeoutSeconds 5 | Out-Null
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
Write-Host "    Remove-Item logs\service-runner-tdx-state.json  # 修复问题后重置 TDX 熔断状态"
