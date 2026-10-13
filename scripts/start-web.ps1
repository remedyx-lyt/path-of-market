[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 5173,
    [switch]$InstallDependencies
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskWebRoot = Join-Path $taskProjectRoot 'apps\web'
$taskViteCommand = Join-Path $taskWebRoot 'node_modules\.bin\vite.cmd'
$taskNpmCommand = Get-Command npm.cmd -ErrorAction Stop

Push-Location -LiteralPath $taskWebRoot
try {
    if ($InstallDependencies.IsPresent -or -not (Test-Path -LiteralPath $taskViteCommand)) {
        Write-Host '按 package-lock.json 安装网页依赖；首次运行需要联网。'
        & $taskNpmCommand.Source ci --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) {
            throw '网页依赖安装失败，请检查 Node.js 版本、网络和安装日志。'
        }
    }
    Write-Host "深研室：http://127.0.0.1:$Port"
    Write-Host '按 Ctrl+C 停止网页服务。'
    & $taskNpmCommand.Source run dev -- --host 127.0.0.1 --port $Port --strictPort
    $taskWebExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($taskWebExitCode -ne 0) {
    throw "网页服务退出，代码：$taskWebExitCode。请检查启动日志和端口。"
}
