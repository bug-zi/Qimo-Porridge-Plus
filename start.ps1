# 期末粥++ 本地启动/停止：后端 uvicorn:8000 + 前端 Vite:5173
# 入口：启动项目.bat（启动）/ 停止项目.bat（停止，传 -Stop）
# 服务经 WMI 启动为无窗口后台进程，与终端/IDE 完全解耦（关闭终端不影响服务），日志写入 logs\
param([switch]$Stop)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$Host.UI.RawUI.WindowTitle = '期末粥++ 启动器'

function Test-PortListening([int]$port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# 脱离控制台后台启动：cmd /c <命令>，CreateNoWindow 不弹窗，输出重定向到日志文件
function Start-Detached([string]$command, [string]$workDir) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = "/c $command"
    $psi.WorkingDirectory = $workDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    [void][System.Diagnostics.Process]::Start($psi)
    return $true
}

if ($Stop) {
    $stopped = $false
    foreach ($port in 8000, 5173) {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($null -eq $proc) { continue }
            if ($proc.ProcessName -notin 'python', 'node') {
                Write-Host "[跳过] 端口 $port 被 $($proc.ProcessName)（PID $($proc.Id)）占用，非本项目进程，未终止。" -ForegroundColor Yellow
                continue
            }
            Stop-Process -Id $proc.Id -Force
            Write-Host "已停止端口 $port 上的 $($proc.ProcessName)（PID $($proc.Id)）。" -ForegroundColor Green
            $stopped = $true
        }
    }
    if (-not $stopped) { Write-Host '当前没有在运行的本项目服务。' }
    exit 0
}

Write-Host '================================================'
Write-Host '  期末粥++ 本地启动（后台模式，无窗口）'
Write-Host '  后端  http://127.0.0.1:8000/docs'
Write-Host '  前端  http://localhost:5173'
Write-Host '================================================'
Write-Host ''

if (-not (Test-Path "$root\backend\.venv\Scripts\python.exe")) {
    Write-Host '[错误] 未找到 backend\.venv 虚拟环境，请先完成首次安装：' -ForegroundColor Red
    Write-Host '    cd backend'
    Write-Host '    python -m venv .venv'
    Write-Host '    .venv\Scripts\python.exe -m pip install -r requirements.txt'
    exit 1
}

if (-not (Test-Path "$root\backend\.env")) {
    Write-Host '[错误] 未找到 backend\.env（模型密钥与 JWT 配置），后端无法正常工作。' -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null

$backendRunning = Test-PortListening 8000
$frontendRunning = Test-PortListening 5173

if ($backendRunning) {
    Write-Host '[提示] 端口 8000 已有服务在监听，跳过后端启动（如需重启请先运行 停止项目.bat）。' -ForegroundColor Yellow
} else {
    Write-Host '正在后台启动后端...'
    Start-Detached '.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > ..\logs\backend.log 2>&1' "$root\backend" | Out-Null

    Write-Host '等待后端就绪...'
    $ready = $false
    for ($i = 1; $i -le 15; $i++) {
        Start-Sleep -Seconds 2
        try {
            Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3 | Out-Null
            $ready = $true
            break
        } catch { }
    }
    if ($ready) {
        Write-Host '后端已就绪。' -ForegroundColor Green
    } else {
        Write-Host '[警告] 后端约 30 秒仍未就绪，请查看 logs\backend.log 中的报错信息。' -ForegroundColor Yellow
    }
}

if ($frontendRunning) {
    Write-Host '[提示] 端口 5173 已有服务在监听，跳过前端启动（如需重启请先运行 停止项目.bat）。' -ForegroundColor Yellow
} else {
    if (-not (Test-Path "$root\web\node_modules")) {
        Write-Host '[提示] 未找到前端依赖，先执行 npm install（首次较慢）...'
        Push-Location "$root\web"
        npm install
        $npmExit = $LASTEXITCODE
        Pop-Location
        if ($npmExit -ne 0) {
            Write-Host '[错误] npm install 失败，请确认已安装 Node.js。' -ForegroundColor Red
            exit 1
        }
    }

    Write-Host '正在后台启动前端...'
    Start-Detached 'npm run dev > ..\logs\frontend.log 2>&1' "$root\web" | Out-Null
    Start-Sleep -Seconds 3
}

Start-Process 'http://localhost:5173'

Write-Host ''
Write-Host '================================================'
Write-Host '  启动完成！服务在后台运行，不依赖任何终端窗口'
Write-Host '  前端  http://localhost:5173'
Write-Host '  后端  http://127.0.0.1:8000/docs'
Write-Host '  日志  logs\backend.log ／ logs\frontend.log'
Write-Host '  停止  运行 停止项目.bat'
Write-Host '================================================'
Start-Sleep -Seconds 5
exit 0
