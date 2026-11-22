# 供整套应用的启动、停止和检查脚本共用，不直接执行。
$taskAppRoot = Split-Path -Parent $PSScriptRoot
$taskRuntimeRoot = Join-Path $taskAppRoot '.runtime'
$taskAppStatePath = Join-Path $taskRuntimeRoot 'app-state.json'
$taskAppServices = @(
    @{ Name = 'server'; Port = 8080; Alternate = 8081; Script = 'start-agent.ps1'; Health = 'http://127.0.0.1:8080/api/health' },
    @{ Name = 'web'; Port = 5173; Alternate = 4173; Script = 'start-web.ps1'; Health = 'http://127.0.0.1:5173/' }
)

function Set-AppPort {
    param($Service, [int]$Port)
    $taskUri = [UriBuilder]$Service.Health
    $taskUri.Port = $Port
    $Service.Port = $Port
    $Service.Health = $taskUri.Uri.AbsoluteUri
}

function Find-AppPort {
    param([int]$Preferred, [int]$Alternate)
    # Windows 保留端口没有监听进程。优先选择固定备用端口，使网页地址在重启后保持稳定。
    foreach ($taskCandidate in @($Preferred, $Alternate, 0)) {
        $taskProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $taskCandidate)
        try {
            $taskProbe.Start()
            return $taskProbe.LocalEndpoint.Port
        }
        catch [Net.Sockets.SocketException] {
            if ($taskCandidate -eq 0 -or
                ($taskCandidate -eq $Preferred -and $_.Exception.SocketErrorCode -ne 'AccessDenied') -or
                $_.Exception.SocketErrorCode -notin @('AccessDenied', 'AddressAlreadyInUse')) { throw }
        }
        finally { $taskProbe.Stop() }
    }
}

function Enter-AppOperation {
    New-Item -ItemType Directory -Path $taskRuntimeRoot -Force | Out-Null
    try {
        # 文件可以保留；独占句柄随进程结束释放，避免同时启动/停止覆盖记录。
        return [System.IO.File]::Open((Join-Path $taskRuntimeRoot 'app-operation.lock'),
            [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    }
    catch {
        throw '无法取得运行锁：可能有另一条启动或停止命令正在执行，也请检查 .runtime 的写入权限。'
    }
}

function Get-AppState {
    if (-not (Test-Path -LiteralPath $taskAppStatePath)) { return $null }
    $taskState = Get-Content -LiteralPath $taskAppStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($taskState.version -notin @(1, 2) -or $taskState.projectRoot -ne $taskAppRoot) {
        throw '启动记录与当前项目不符，请先检查 .runtime/app-state.json。'
    }
    $taskSpecs = $taskAppServices
    if ($taskState.version -eq 1) {
        $taskSpecs = @(@{ Name = 'agent'; Script = 'start-agent.ps1' },
            @{ Name = 'server'; Script = 'start-server.ps1' }, @{ Name = 'web'; Script = 'start-web.ps1' })
    }
    $taskSeenNames = @()
    foreach ($taskEntry in @($taskState.services)) {
        $taskSpec = $taskSpecs | Where-Object { $_.Name -eq $taskEntry.name }
        if (-not $taskSpec -or $taskSeenNames -contains $taskEntry.name -or
            $taskEntry.scriptPath -ne (Join-Path $PSScriptRoot $taskSpec.Script) -or
            $taskEntry.processId -le 0) {
            throw '启动记录中的服务不符合约定，请检查 .runtime/app-state.json。'
        }
        if ($taskState.version -eq 2 -and $taskEntry.port) {
            if ($taskEntry.port -lt 1 -or $taskEntry.port -gt 65535) { throw '启动记录端口无效。' }
        }
        $taskSeenNames += $taskEntry.name
    }
    return $taskState
}

function Save-AppState {
    param([object[]]$Services)
    $taskState = @{ version = 2; projectRoot = $taskAppRoot; services = @($Services) }
    $taskTempState = Join-Path $taskRuntimeRoot 'app-state.tmp'
    $taskState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $taskTempState -Encoding UTF8
    Move-Item -LiteralPath $taskTempState -Destination $taskAppStatePath -Force
}

function Get-AppManagedProcess {
    param($Entry)
    $taskProcess = Get-Process -Id $Entry.processId -ErrorAction SilentlyContinue
    if (-not $taskProcess) { return $null }
    $taskCim = Get-CimInstance Win32_Process -Filter "ProcessId = $($Entry.processId)"
    # PID 会复用：必须同时核对创建时间、可执行文件和启动脚本。
    if (-not $taskProcess.StartTime -or $taskProcess.StartTime.ToUniversalTime().ToString('o') -ne $Entry.startedAtUtc -or
        $taskProcess.Path -ne $Entry.executablePath -or -not $taskCim.CommandLine -or
        $taskCim.CommandLine.IndexOf($Entry.scriptPath, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        return $null
    }
    return $taskProcess
}

function Stop-AppServices {
    param([object[]]$Services)
    foreach ($taskEntry in @($Services)) {
        if (-not (Get-AppManagedProcess $taskEntry)) { continue }
        $taskSnapshot = @(Get-CimInstance Win32_Process)
        $taskTree = New-Object System.Collections.Generic.List[object]
        $taskRootProcess = $taskSnapshot | Where-Object { $_.ProcessId -eq $taskEntry.processId }
        if (-not $taskRootProcess) { continue }
        $taskTree.Add($taskRootProcess)
        for ($taskIndex = 0; $taskIndex -lt $taskTree.Count; $taskIndex++) {
            $taskParent = $taskTree[$taskIndex]
            foreach ($taskChild in $taskSnapshot) {
                if ($taskChild.ParentProcessId -eq $taskParent.ProcessId -and
                    $taskChild.CreationDate -ge $taskParent.CreationDate) {
                    $taskTree.Add($taskChild)
                }
            }
        }
        # 先结束已核对的子进程，再结束脚本；不按 java/node/python 名称批量结束。
        for ($taskIndex = $taskTree.Count - 1; $taskIndex -ge 0; $taskIndex--) {
            $taskCandidate = $taskTree[$taskIndex]
            $taskCurrent = Get-CimInstance Win32_Process -Filter "ProcessId = $($taskCandidate.ProcessId)"
            if ($taskCurrent -and $taskCurrent.CreationDate -eq $taskCandidate.CreationDate) {
                $taskProcess = Get-Process -Id $taskCurrent.ProcessId -ErrorAction SilentlyContinue
                if ($taskProcess) { $taskProcess | Stop-Process -Force -ErrorAction Stop }
            }
        }
        Write-Host "已停止：$($taskEntry.name)"
    }
}

function Test-AppServiceReady {
    param($Service)
    try {
        if ($Service.Name -eq 'web') {
            $taskPage = Invoke-WebRequest -UseBasicParsing -Uri $Service.Health -TimeoutSec 2
            return ($taskPage.StatusCode -eq 200 -and $taskPage.Content -match 'id="root"')
        }
        $taskHealth = Invoke-RestMethod -Uri $Service.Health -TimeoutSec 2
        return ($taskHealth.status -eq 'ok' -and $taskHealth.service -eq $Service.Name)
    }
    catch { return $false }
}
