param(
    [string]$RootPassword = '',
    [string]$MySqlBin = ''
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$mysqlDir = Join-Path $packageRoot 'database\mysql'

function Read-SecretText([string]$Prompt) {
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

if ([string]::IsNullOrWhiteSpace($RootPassword)) { $RootPassword = Read-SecretText 'MySQL root 密码' }
if ([string]::IsNullOrWhiteSpace($MySqlBin)) {
    $candidate = Get-Command mysql.exe -ErrorAction SilentlyContinue
    if ($candidate) { $MySqlBin = Split-Path -Parent $candidate.Source }
    else {
        $known = @('C:\Program Files\MySQL\MySQL Server 8.0\bin', 'E:\mysql-8\bin')
        $MySqlBin = $known | Where-Object { Test-Path (Join-Path $_ 'mysql.exe') } | Select-Object -First 1
    }
}
if ([string]::IsNullOrWhiteSpace($MySqlBin) -or -not (Test-Path (Join-Path $MySqlBin 'mysql.exe'))) {
    throw '找不到 mysql.exe。请使用 -MySqlBin 指定 MySQL 的 bin 目录。'
}
if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 3306 -InformationLevel Quiet)) {
    throw 'MySQL 3306 未监听，请先启动 MySQL 服务。'
}

$env:MYSQL_PWD = $RootPassword
try {
    $sqlFiles = Get-ChildItem -LiteralPath $mysqlDir -Filter '*.sql' | Sort-Object Name
    if (-not $sqlFiles) { throw 'database\mysql 中没有可导入的 SQL 文件。' }
    foreach ($sqlFile in $sqlFiles) {
        Write-Host "正在导入 $($sqlFile.Name)..."
        $process = Start-Process -FilePath (Join-Path $MySqlBin 'mysql.exe') `
            -ArgumentList @('-uroot','--protocol=tcp','--default-character-set=utf8mb4') `
            -RedirectStandardInput $sqlFile.FullName -NoNewWindow -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "导入 $($sqlFile.Name) 失败，退出码 $($process.ExitCode)" }
    }
} finally {
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
}
Write-Host 'MySQL 结构和共享数据导入完成。'
