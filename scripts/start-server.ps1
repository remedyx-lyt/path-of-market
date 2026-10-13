[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskServerRoot = Join-Path $taskProjectRoot 'apps\server'
$taskWrapper = Join-Path $taskServerRoot 'mvnw.cmd'
$taskJar = Join-Path $taskServerRoot 'target\path-of-market-server.jar'

# Wrapper 自动下载固定版本 Maven；这里只需要本机有 JDK。
$taskJavaHome = $env:JAVA_HOME
if ([string]::IsNullOrWhiteSpace($taskJavaHome)) {
    $taskJavacCommand = Get-Command javac -ErrorAction Stop
    $taskJavaHome = Split-Path -Parent (Split-Path -Parent $taskJavacCommand.Source)
}
$taskJava = Join-Path $taskJavaHome 'bin\java.exe'
$taskJavac = Join-Path $taskJavaHome 'bin\javac.exe'
if (-not (Test-Path -LiteralPath $taskJava) -or -not (Test-Path -LiteralPath $taskJavac)) {
    throw '请安装 JDK 21 或更高版本，并检查 JAVA_HOME 是否指向 JDK 目录。'
}
# 只设置当前脚本进程的环境，不修改系统配置。
$env:JAVA_HOME = $taskJavaHome

Push-Location -LiteralPath $taskServerRoot
try {
    Write-Host '构建 Java 主后端；首次运行需要联网下载 Maven 和项目依赖。'
    & $taskWrapper --batch-mode --no-transfer-progress package
    if ($LASTEXITCODE -ne 0) {
        throw 'Java 构建失败，请检查上面的日志、JDK 版本和网络。'
    }

    Write-Host "Java 健康检查：http://127.0.0.1:$Port/api/health"
    Write-Host '按 Ctrl+C 停止服务。'
    & $taskJava '-Dfile.encoding=UTF-8' -jar $taskJar "--server.port=$Port"
    $taskServerExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($taskServerExitCode -ne 0) {
    throw "Java 主后端退出，代码：$taskServerExitCode。请检查启动日志和端口。"
}
