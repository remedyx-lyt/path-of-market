[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$InstallDependencies
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskAgentRoot = Join-Path $taskProjectRoot 'apps\agent'
$taskVenvRoot = Join-Path $taskAgentRoot '.venv'
$taskPython = Join-Path $taskVenvRoot 'Scripts\python.exe'
$taskRequirements = Join-Path $taskAgentRoot 'requirements.txt'
$taskNeedsInstall = $InstallDependencies.IsPresent

# 使用独立虚拟环境，不要求先手动激活。
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskBootstrapPython = Get-Command python -ErrorAction Stop
    & $taskBootstrapPython.Source -m venv $taskVenvRoot
    if ($LASTEXITCODE -ne 0) {
        throw '创建 Python 虚拟环境失败，请检查本机 Python 安装。'
    }
    $taskNeedsInstall = $true
}

try {
    & $taskPython -c 'import fastapi, pydantic, uvicorn, pypdf, pypdfium2, PIL' 2>$null
    if ($LASTEXITCODE -ne 0) { $taskNeedsInstall = $true }
}
catch {
    $taskNeedsInstall = $true
}

if ($taskNeedsInstall) {
    & $taskPython -m pip install -r $taskRequirements
    if ($LASTEXITCODE -ne 0) {
        throw '依赖安装失败，请检查网络和 requirements.txt。'
    }
}

$taskUvicornArgs = @(
    '-m', 'uvicorn', 'app.main:app',
    '--host', '127.0.0.1', '--port', $Port.ToString()
)
if ($Reload.IsPresent) { $taskUvicornArgs += '--reload' }

Write-Host "研究服务：http://127.0.0.1:$Port/docs"
Write-Host '按 Ctrl+C 停止服务。'
Push-Location -LiteralPath $taskAgentRoot
try {
    & $taskPython @taskUvicornArgs
    $taskServerExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($taskServerExitCode -ne 0) {
    throw "研究服务退出，代码：$taskServerExitCode。请检查启动日志和端口。"
}
