param(
    [switch]$InstallOcr,
    [switch]$SkipMysqlImport,
    [string]$MySqlBin = '',
    [string]$PersonalUsername = 'demo_user',
    [string]$PersonalPassword = 'Career2026',
    [string]$AdminUsername = 'demo_admin',
    [string]$AdminPassword = 'Admin2026',
    [string]$EnterpriseUsername = 'demo_enterprise',
    [string]$EnterprisePassword = 'Enterprise2026'
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $packageRoot 'backend'
$frontend = Join-Path $packageRoot 'frontend'
$envFile = Join-Path $backend '.env.local'
$firstSetup = -not (Test-Path -LiteralPath $envFile)

function Read-SecretText([string]$Prompt) {
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Require-Command([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) { throw "找不到 $Name，请先安装并加入 PATH。" }
    return $command.Source
}

$python = Require-Command 'python'
& $python --version
$node = Require-Command 'node'
& $node --version
$packageManager = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $packageManager) { $packageManager = Get-Command npm -ErrorAction SilentlyContinue }
if (-not $packageManager) { throw '找不到 pnpm 或 npm。请先安装 Node.js，并执行 corepack enable。' }

$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    & $python -m venv (Join-Path $backend '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败。' }
}
& $venvPython -m pip install -r (Join-Path $backend 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '安装后端依赖失败。' }
if ($InstallOcr) {
    & $venvPython -m pip install -r (Join-Path $backend 'requirements-ocr.txt')
    if ($LASTEXITCODE -ne 0) { throw '安装 OCR 依赖失败。' }
}

if ($packageManager.Name -match '^pnpm') {
    Push-Location $frontend
    try { & $packageManager.Source install --frozen-lockfile }
    finally { Pop-Location }
} else {
    Push-Location $frontend
    try { & $packageManager.Source install }
    finally { Pop-Location }
}
if ($LASTEXITCODE -ne 0) { throw '安装前端依赖失败。' }
Push-Location $frontend
try {
    & $packageManager.Source run build
    if ($LASTEXITCODE -ne 0) { throw '前端生产构建失败。' }
} finally { Pop-Location }

if (-not (Test-Path $envFile)) {
    $neo4jPassword = Read-SecretText 'Neo4j 数据库密码'
    $mysqlAppPassword = Read-SecretText 'MySQL 应用账户密码'
    if ([string]::IsNullOrWhiteSpace($neo4jPassword) -or [string]::IsNullOrWhiteSpace($mysqlAppPassword)) {
        throw '密码不能为空。'
    }
    $authSecret = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
    $envText = @"
APP_HOST=127.0.0.1
APP_PORT=8010
FRONTEND_ORIGIN=http://127.0.0.1:5175
NEO4J_URL=http://127.0.0.1:7474
NEO4J_DATABASE=neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=$neo4jPassword
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=career_insight
MYSQL_USER=career_insight_app
MYSQL_PASSWORD=$mysqlAppPassword
AGENT_PROVIDER=rules
AGENT_BASE_URL=https://api.coze.cn
AGENT_CHAT_PATH=/v3/chat
AGENT_API_KEY=
AGENT_USER_ID=
AGENT_CAREER_PLANNING_BOT_ID=
AGENT_ABILITY_ANALYSIS_BOT_ID=
AGENT_TIMEOUT_SECONDS=60
AUTH_SECRET=$authSecret
AUTH_TOKEN_HOURS=12
PERSONAL_USERNAME=$PersonalUsername
PERSONAL_PASSWORD=$PersonalPassword
ADMIN_USERNAME=$AdminUsername
ADMIN_PASSWORD=$AdminPassword
ENTERPRISE_USERNAME=$EnterpriseUsername
ENTERPRISE_PASSWORD=$EnterprisePassword
"@
    [IO.File]::WriteAllText($envFile, $envText.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Copy-Item -LiteralPath (Join-Path $frontend '.env.example') -Destination (Join-Path $frontend '.env.local') -Force
    Write-Host "已生成 $envFile。"
} else {
    Write-Host "$envFile 已存在，保留现有配置。"
}

if (-not $SkipMysqlImport -and $firstSetup) {
    $rootPassword = Read-SecretText 'MySQL root 密码（仅本次导入使用）'
    & (Join-Path $PSScriptRoot 'import-mysql.ps1') -RootPassword $rootPassword -MySqlBin $MySqlBin
    $env:MYSQL_ROOT_PASSWORD = $rootPassword
    try {
        Push-Location $backend
        & $venvPython scripts\init_mysql.py
        if ($LASTEXITCODE -ne 0) { throw '应用数据库账户和 Alembic 初始化失败。' }
    } finally {
        Pop-Location
        Remove-Item Env:MYSQL_ROOT_PASSWORD -ErrorAction SilentlyContinue
    }
} else {
    Write-Host '已保留现有 MySQL 数据；全新数据库可显式运行 scripts\import-mysql.ps1。'
}

Write-Host ''
Write-Host '首次配置完成。下一步：在 Neo4j Desktop 停止数据库，运行 restore-neo4j.ps1，再启动 Neo4j，然后运行 start-local.ps1。'
