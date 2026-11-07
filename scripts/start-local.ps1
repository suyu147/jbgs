﻿﻿﻿$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $packageRoot 'backend'
$frontend = Join-Path $packageRoot 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    # 未使用 setup-local 的 venv 时，回读 .env.local 里指定的解释器；再退回 PATH 中的 python
    $envFile = Join-Path $backend '.env.local'
    $configured = (Select-String -Path $envFile -Pattern '^PYTHON_EXECUTABLE=(.+)$' -ErrorAction SilentlyContinue | Select-Object -First 1).Matches.Groups[1].Value
    $python = if ($configured) { $configured.Trim() } else { (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
}
$vite = Join-Path $frontend 'node_modules\vite\bin\vite.js'
$viteArgument = '"' + $vite + '"'
$logs = Join-Path $packageRoot '应用数据\logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
if (-not (Test-Path $python)) { throw '后端虚拟环境不存在，请先运行 scripts\setup-local.ps1。' }
if (-not (Test-Path $vite)) { throw '前端依赖不存在，请先运行 scripts\setup-local.ps1。' }
if (-not (Test-Path (Join-Path $frontend 'dist\index.html'))) { throw '前端构建文件不存在，请先运行 scripts\setup-local.ps1。' }
if (-not (Test-Path (Join-Path $backend '.env.local'))) { throw 'backend\.env.local 不存在，请先运行 scripts\setup-local.ps1。' }

Push-Location $backend
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'MySQL 数据库迁移失败，请检查 3306 端口和 backend\.env.local。' }
} finally {
    Pop-Location
}

if (-not (Get-NetTCPConnection -State Listen -LocalPort 8010 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','--app-dir',$backend,'app.main:app','--host','127.0.0.1','--port','8010') -WorkingDirectory $backend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'backend.out.log') -RedirectStandardError (Join-Path $logs 'backend.err.log') | Out-Null
}
if (-not (Get-NetTCPConnection -State Listen -LocalPort 5175 -ErrorAction SilentlyContinue)) {
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    Start-Process -FilePath $node -ArgumentList @($viteArgument,'preview','--host','127.0.0.1','--port','5175','--strictPort') -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'frontend.out.log') -RedirectStandardError (Join-Path $logs 'frontend.err.log') | Out-Null
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/health' -TimeoutSec 2
        if ($health.data.status -eq 'healthy') { break }
    } catch { }
    Start-Sleep -Seconds 2
}
& (Join-Path $PSScriptRoot 'check-local.ps1')
if ($LASTEXITCODE -ne 0) { throw '服务检查未通过，请查看应用数据\logs。' }

$seedScript = Join-Path $PSScriptRoot 'seed-enterprise-demo.ps1'
if (Test-Path -LiteralPath $seedScript) {
    try { & $seedScript }
    catch { Write-Warning "企业示例简历初始化未完成：$($_.Exception.Message)" }
}
