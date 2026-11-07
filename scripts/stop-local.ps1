$ErrorActionPreference = 'Continue'
$packageRoot = Split-Path -Parent $PSScriptRoot
$backendPattern = [regex]::Escape((Join-Path $packageRoot 'backend'))
$frontendPattern = [regex]::Escape((Join-Path $packageRoot 'frontend'))
foreach ($port in 8010, 5175) {
    $connections = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
        $parent = if ($process.ParentProcessId) { Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)" } else { $null }
        $command = [string]$process.CommandLine
        $parentCommand = [string]$parent.CommandLine
        $allowed = ($port -eq 8010 -and (($command -match 'uvicorn.*app\.main:app' -and ($command -match $backendPattern -or $parentCommand -match $backendPattern)) -or ($parentCommand -match 'uvicorn.*app\.main:app' -and $parentCommand -match $backendPattern))) -or ($port -eq 5175 -and $command -match 'vite' -and $command -match $frontendPattern)
        if ($allowed) {
            Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
            if ($process.ParentProcessId) { Stop-Process -Id $process.ParentProcessId -Force -ErrorAction SilentlyContinue }
            Write-Host "已停止端口 $port。"
        } else {
            Write-Warning "端口 $port 由其它程序占用，未停止。"
        }
    }
}
Write-Host '本项目的前端和后端已停止；MySQL 与 Neo4j 保持不变。'
