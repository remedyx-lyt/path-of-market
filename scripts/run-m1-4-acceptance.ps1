# M1-4 一键验收：离线检查（不调用模型）→ 网页构建 → 重启三服务 → 真实模型验收（A/B/C 三个案例，会产生模型费用）。
# 任何一步失败立即停止，不会在离线检查失败时花钱。全部输出写入 .runtime\m1-4-acceptance.log（UTF-8），供核对。
# 用法：双击项目根目录的 run-m1-4-acceptance.cmd，或 powershell -ExecutionPolicy Bypass -File scripts\run-m1-4-acceptance.ps1 [-Cases A] [-SkipLive]
param([string]$Cases = 'A,B,C', [switch]$SkipLive)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force -Path '.runtime' | Out-Null
$log = Join-Path $root '.runtime\m1-4-acceptance.log'
Set-Content -LiteralPath $log -Value ("M1-4 验收开始 " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -Encoding UTF8
$python = Join-Path $root 'apps\agent\.venv\Scripts\python.exe'

function Write-Log([string]$text) {
    Write-Host $text
    Add-Content -LiteralPath $log -Value $text -Encoding UTF8
}

function Invoke-Step([string]$name, [string]$file, [string[]]$arguments, [string]$workdir = $root) {
    Write-Log ""
    Write-Log "=== $name"
    Push-Location -LiteralPath $workdir
    & $file @arguments 2>&1 | ForEach-Object { Write-Log ("" + $_) }
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) {
        Write-Log "=== 失败：$name（退出码 $code）。后续步骤未执行。"
        Write-Log "RESULT: FAILED at $name"
        exit 1
    }
    Write-Log "=== 通过：$name"
}

Write-Log "=== 仓库状态（只读）"
& git status --short 2>&1 | ForEach-Object { Write-Log ("" + $_) }
& git log --oneline -5 2>&1 | ForEach-Object { Write-Log ("" + $_) }

if (-not (Test-Path -LiteralPath $python)) {
    Write-Log "RESULT: FAILED（找不到 $python，请先运行一次 scripts\start-agent.ps1 创建虚拟环境）"
    exit 1
}
Invoke-Step '1. 新增离线测试（apps/agent/tests）' $python @('-m', 'unittest', 'discover', '-s', 'apps\agent\tests', '-t', 'apps\agent\tests')
Invoke-Step '2. 原有检查：研究循环' $python @('scripts\check-agent-loop.py')
Invoke-Step '3. 原有检查：财务研究' $python @('scripts\check-financial-research.py')
Invoke-Step '4. 原有检查：图表与方法' $python @('scripts\check-report-figures.py')
Invoke-Step '5. 原有检查：工具（含 FastAPI HTTP）' $python @('scripts\check-tools.py')
Invoke-Step '6. 网页类型检查与构建' 'npm.cmd' @('run', 'build') (Join-Path $root 'apps\web')
Invoke-Step '7. 停止三服务' 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts\stop-app.ps1')
Invoke-Step '8. 启动三服务（加载新代码）' 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts\start-app.ps1')
Invoke-Step '9. 三服务基础链路检查（演示接口，不调用模型）' 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts\check-app.ps1')
if ($SkipLive) {
    Write-Log "RESULT: OFFLINE PASSED（按 -SkipLive 跳过真实模型验收）"
    exit 0
}
Invoke-Step "10. 真实模型验收（案例 $Cases，会产生模型费用）" $python @('scripts\check-omens-live.py', '--live', '--cases', $Cases)
Write-Log "RESULT: ALL PASSED"
exit 0
