[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8080'
)

$ErrorActionPreference = 'Stop'
$taskBaseUrl = $BaseUrl.TrimEnd('/')
$taskHealthUrl = "$taskBaseUrl/api/health"

$taskResponse = Invoke-WebRequest -UseBasicParsing -Uri $taskHealthUrl -TimeoutSec 10
if ($taskResponse.StatusCode -ne 200 -or $taskResponse.Headers['Content-Type'] -notmatch 'application/json') {
    throw '健康检查必须返回 HTTP 200 和 JSON。'
}
$taskHealth = $taskResponse.Content | ConvertFrom-Json
if ($taskHealth.status -ne 'ok' -or $taskHealth.service -ne 'server') {
    throw '健康检查内容与 Java 主后端约定不符。'
}
Write-Host 'PASS: GET /api/health returns 200 and server JSON'

# 同时检查实际 HTTP 路由与方法边界。
$taskCases = @(
    @{ Method = 'GET'; Path = '/api/not-found'; Expected = 404 },
    @{ Method = 'POST'; Path = '/api/health'; Expected = 405 }
)
foreach ($taskCase in $taskCases) {
    $taskStatus = $null
    try {
        $taskResult = Invoke-WebRequest -UseBasicParsing -Method $taskCase.Method -Uri ($taskBaseUrl + $taskCase.Path) -TimeoutSec 10
        $taskStatus = [int]$taskResult.StatusCode
    }
    catch {
        if ($null -eq $_.Exception.Response) { throw }
        $taskStatus = [int]$_.Exception.Response.StatusCode
    }
    if ($taskStatus -ne $taskCase.Expected) {
        throw "Unexpected status for $($taskCase.Method) $($taskCase.Path): $taskStatus"
    }
    Write-Host "PASS: $($taskCase.Method) $($taskCase.Path) returns $taskStatus"
}

Write-Host 'PASS: all 3 HTTP checks completed'
