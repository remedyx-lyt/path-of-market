[CmdletBinding()]
param(
    [ValidateRange(10, 3600)]
    [int]$StartupTimeoutSec = 600,
    [switch]$InstallDependencies
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'app-common.ps1')

$taskOperationLock = Enter-AppOperation
try {
    $taskExisting = Get-AppState
    if ($taskExisting) {
        $taskLive = @($taskExisting.services | Where-Object { Get-AppManagedProcess $_ })
        if ($taskLive.Count -eq 3) {
            Write-Host '三个服务已由统一脚本启动，检查当前链路。'
            & (Join-Path $PSScriptRoot 'check-app.ps1')
            return
        }
        if ($taskLive.Count -gt 0) {
            throw '上次启动的服务只有部分仍在运行。请先运行 scripts/stop-app.ps1，再重新启动。'
        }
        Remove-Item -LiteralPath $taskAppStatePath
    }

    # 不接管其他终端或其他应用的端口；有冲突时在创建进程前退出。
    foreach ($taskService in $taskAppServices) {
        if (Get-NetTCPConnection -State Listen -LocalPort $taskService.Port -ErrorAction SilentlyContinue) {
            throw "端口 $($taskService.Port) 已被占用。请先停止之前单独启动的服务或排查占用程序；没有结束任何已有进程。"
        }
    }
    foreach ($taskCommand in @('python', 'npm.cmd', 'javac')) {
        if (-not (Get-Command $taskCommand -ErrorAction SilentlyContinue)) {
            throw "找不到 $taskCommand。请按 docs/sixth-step.md 检查 Python、Node.js 和 JDK 安装及 PATH。"
        }
    }

    $taskLogRoot = Join-Path $taskRuntimeRoot 'logs'
    New-Item -ItemType Directory -Path $taskLogRoot -Force | Out-Null
    $taskPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $taskStarted = @()
    $taskCompleted = $false
    try {
        foreach ($taskService in $taskAppServices) {
            $taskScript = Join-Path $PSScriptRoot $taskService.Script
            $taskArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$taskScript`""
            if ($InstallDependencies -and $taskService.Name -ne 'server') {
                $taskArguments += ' -InstallDependencies'
            }
            # 明确地址与默认等待上限，避免父终端旧环境变量造成三个服务互相连错。
            if ($taskService.Name -eq 'server') {
                $taskArguments += ' -AgentBaseUrl http://127.0.0.1:8000 -AgentTimeoutMs 10000'
            }
            $taskPreviousJavaUrl = $env:JAVA_SERVER_URL
            try {
                if ($taskService.Name -eq 'web') { $env:JAVA_SERVER_URL = 'http://127.0.0.1:8080' }
                $taskProcess = Start-Process -FilePath $taskPowerShell -ArgumentList $taskArguments -WindowStyle Hidden -PassThru `
                    -WorkingDirectory $taskAppRoot `
                    -RedirectStandardOutput (Join-Path $taskLogRoot "$($taskService.Name).out.log") `
                    -RedirectStandardError (Join-Path $taskLogRoot "$($taskService.Name).err.log")
            }
            finally { $env:JAVA_SERVER_URL = $taskPreviousJavaUrl }
            $taskStarted += @{
                name = $taskService.Name; processId = $taskProcess.Id
                startedAtUtc = $taskProcess.StartTime.ToUniversalTime().ToString('o')
                executablePath = $taskPowerShell; scriptPath = $taskScript
            }
            Save-AppState $taskStarted
            Write-Host "正在启动 $($taskService.Name)（端口 $($taskService.Port)），日志：.runtime/logs/$($taskService.Name).*"
        }
        $taskDeadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSec)
        $taskLastProgress = [DateTime]::MinValue
        while ([DateTime]::UtcNow -lt $taskDeadline) {
            $taskWaiting = @()
            foreach ($taskService in $taskAppServices) {
                $taskEntry = $taskStarted | Where-Object { $_.name -eq $taskService.Name }
                if (-not (Get-AppManagedProcess $taskEntry)) {
                    throw "$($taskService.Name) 启动进程已退出，请查看 .runtime/logs/$($taskService.Name).err.log 和 .out.log。"
                }
                if (-not (Test-AppServiceReady $taskService)) { $taskWaiting += $taskService.Name }
            }
            if ($taskWaiting.Count -eq 0) {
                & (Join-Path $PSScriptRoot 'check-app.ps1')
                $taskCompleted = $true
                break
            }
            if (([DateTime]::UtcNow - $taskLastProgress).TotalSeconds -ge 10) {
                Write-Host "等待服务就绪：$($taskWaiting -join ', ')。首次安装或 Java 构建需要联网，可查看日志。"
                $taskLastProgress = [DateTime]::UtcNow
            }
            Start-Sleep -Seconds 1
        }
        if (-not $taskCompleted) { throw "启动超过 $StartupTimeoutSec 秒，请查看 .runtime/logs。可用 -StartupTimeoutSec 延长等待。" }
        Write-Host '整套应用已启动：http://127.0.0.1:5173/'
        Write-Host '可关闭本终端；服务在后台运行。停止请执行 scripts/stop-app.ps1。电脑重启后需重新启动。'
    }
    finally {
        if (-not $taskCompleted) {
            Write-Host '启动未完成，清理本次创建的服务；错误日志保留。'
            Stop-AppServices $taskStarted
            if (Test-Path -LiteralPath $taskAppStatePath) { Remove-Item -LiteralPath $taskAppStatePath }
        }
    }
}
finally { $taskOperationLock.Dispose() }
