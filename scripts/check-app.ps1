[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'app-common.ps1')
$taskFailures = @()
foreach ($taskService in $taskAppServices) {
    if (Test-AppServiceReady $taskService) {
        Write-Host "PASS: $($taskService.Name) $($taskService.Health)"
    }
    else {
        $taskFailures += $taskService.Name
        Write-Host "FAIL: $($taskService.Name) $($taskService.Health)"
    }
}

# 必须从网页同源代理发出请求，才能覆盖网页 -> Java -> Python 整条链路。
try {
    $taskPayload = @{
        target = '启动检查公司'; question = '如何研究研发投入的变化？'
        userStyle = '关注长期增长与风险验证'; omens = @('opportunity', 'abyssal_echoes')
    }
    $taskBody = [System.Text.Encoding]::UTF8.GetBytes(($taskPayload | ConvertTo-Json -Depth 5))
    $taskResponse = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/api/research/mock' -Method Post `
        -ContentType 'application/json; charset=utf-8' -Body $taskBody -TimeoutSec 20
    # Windows PowerShell 5.1 对没有 charset 的 JSON 默认解码不一致，按接口 UTF-8 读取原始字节。
    $taskReport = [System.Text.Encoding]::UTF8.GetString($taskResponse.RawContentStream.ToArray()) | ConvertFrom-Json
    if ($taskReport.mode -ne 'mock' -or $taskReport.isMock -ne $true -or
        $taskReport.target -ne $taskPayload.target -or $taskReport.question -ne $taskPayload.question -or
        $taskReport.userStyle -ne $taskPayload.userStyle -or
        (@($taskReport.omens) -join ',') -ne ($taskPayload.omens -join ',') -or
        [string]::IsNullOrWhiteSpace($taskReport.title) -or
        @($taskReport.sections).Count -ne 3 -or
        $null -eq $taskReport.sources -or @($taskReport.sources).Count -ne 0 -or
        $null -eq $taskReport.toolCalls -or @($taskReport.toolCalls).Count -ne 0) {
        throw '返回内容不符合当前演示报告约定。'
    }
    Write-Host 'PASS: 网页 -> Java -> Python -> 演示报告，中文与研究参数正确'
}
catch {
    $taskFailures += 'research'
    Write-Host "FAIL: 完整研究链路。$($_.Exception.Message)"
}
if ($taskFailures.Count -gt 0) {
    throw "应用检查失败：$($taskFailures -join ', ')。请运行 start-app.ps1 或查看 .runtime/logs；排查说明见 docs/sixth-step.md。"
}
Write-Host 'PASS: 全部 4 项应用检查通过。当前仍为演示模式。'
