[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'app-common.ps1')

$taskOperationLock = Enter-AppOperation
try {
    $taskState = Get-AppState
    if (-not $taskState) {
        Write-Host '没有统一脚本的启动记录。单独启动的服务请在原终端按 Ctrl+C 停止。'
        return
    }
    Stop-AppServices @($taskState.services)
    Remove-Item -LiteralPath $taskAppStatePath
    Write-Host '本次统一启动的服务已停止，日志保留在 .runtime/logs。'
}
finally { $taskOperationLock.Dispose() }
