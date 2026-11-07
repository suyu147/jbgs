param(
    [Parameter(Mandatory=$true)][string]$Neo4jHome,
    [switch]$ReplaceExisting
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$dumpDir = Join-Path $packageRoot 'database\neo4j'
$dumpFile = Join-Path $dumpDir 'neo4j.dump'
$hashFile = Join-Path $dumpDir 'neo4j.dump.sha256.txt'
$admin = Join-Path $Neo4jHome 'bin\neo4j-admin.bat'
if (-not (Test-Path $admin)) { throw "Neo4jHome 无效：找不到 $admin" }
if (-not (Test-Path $dumpFile)) { throw '找不到 database\neo4j\neo4j.dump' }
if (-not (Test-Path $hashFile)) { throw '找不到 database\neo4j\neo4j.dump.sha256.txt' }
if (-not $ReplaceExisting) {
    throw '这是覆盖现有 neo4j 数据库的操作。确认数据库已停止后，重新执行并追加 -ReplaceExisting。'
}
foreach ($port in 7474, 7687) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Neo4j 端口 $port 仍在监听，请先在 Neo4j Desktop 停止数据库。"
    }
}
$expectedHash = (Get-Content -LiteralPath $hashFile -Raw).Trim().Split(' ')[0].ToUpperInvariant()
$actualHash = (Get-FileHash -LiteralPath $dumpFile -Algorithm SHA256).Hash.ToUpperInvariant()
if ($actualHash -ne $expectedHash) {
    throw "Neo4j dump SHA-256 不一致。期望 $expectedHash，实际 $actualHash。"
}
& $admin database load neo4j --from-path=$dumpDir --overwrite-destination=true
if ($LASTEXITCODE -ne 0) { throw "Neo4j dump 恢复失败，退出码 $LASTEXITCODE" }
& $admin database check neo4j
if ($LASTEXITCODE -ne 0) { throw "Neo4j 离线一致性检查失败，退出码 $LASTEXITCODE" }
Write-Host 'Neo4j 图谱恢复和离线一致性检查完成。'
Write-Host '请回到 Neo4j Desktop 启动数据库，再运行 scripts\check-local.ps1 验证 114257 个快照和 67 个时间周期。'
